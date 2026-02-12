# Permanent Storage
Active sessions are retained in Redis - the in-memory database - for fast processing across
multiple instances of both the API and the Workers. In the config that goes with your agent
you will specify the expiration of sessions. This is typically a period between 2 minutes
for short-lived processing sessions to a couple of hours for interactive workloads.

When the expiration time is passed, the session is removed from the in-memory database and
references to that expired session will fail with a 404 Not Found status.

Unless a permanent store has been defined. Look at the following snippet from a `config.yaml`
of an agent:
```yaml
persistence:
  permanent_store:
    type: embedded
    config:
      critical_watermark: 120
      max_writes: 32
      file_storage_config:
        file_storage_url: file://./permanent/blobs
        compress: false
        shard_depth: 2
        options: null
      database_config:
        path: ./permanent/db
        retries: 5
```

Here a permanent store of type "embedded" has been configured. This means that a permanently
stored version of the session will be created using an embedded SQLite database for the
session index and tar files for the actual session data.

To date, the options for `type` are:

`none`
: no permanent storage is configured and expired sessions are lost indefinitely

`embedded`
: sessions are permanently stored in tar files and an index of sessions is kept in an
  embedded SQLite database. See [Embedded Storage Manager](#embedded-storage-manager) below for details.

`postgres`
: sessions are permanently stored in tar files and an index of sessions is kept in a
  PostgreSQL database. See [PostgreSQL Storage Manager](#postgresql-storage-manager) below for details.

## Configuration Structure
Permanent storage configuration is organized into three levels:

### 1. General Permanent Storage Configuration
These parameters apply to all storage manager types and control the persistence behavior:

`critical_watermark`
: Time-to-live threshold (in seconds) below which a session is considered critical to persist.
  Sessions with TTL below this value will be prioritized for persistence. (default: 120)

`max_writes`
: Maximum number of sessions to persist in a single batch. This limits the work done in each
  periodic persistence cycle. (default: 32)

### 2. File Storage Configuration
All storage managers use tar files for storing session data. These parameters control how
and where those tar files are stored:

`file_storage_config.file_storage_url`
: URL or path for blob storage. Uses [fsspec](https://filesystem-spec.readthedocs.io/) for
  flexible backend support. Examples: `file://./data` (local), `s3://bucket/path` (S3),
  `gs://bucket/path` (GCS), `az://container/path` (Azure), `sftp://host/path` (SFTP)

`file_storage_config.compress`
: Whether to compress the content within tar files. Set to `true` to save storage space at
  the cost of CPU time. (default: false)

`file_storage_config.shard_depth`
: Depth of the directory tree for organizing tar files. A depth of 2 creates a two-level
  directory structure based on the session ID for better filesystem performance. (default: 2)

`file_storage_config.options`
: Backend-specific storage options as a dictionary. Used for credentials, endpoints, and
  other backend-specific parameters. Set to `null` for local filesystem.

### 3. Storage Manager-Specific Configuration
Each storage manager type has its own configuration section under `database_config`. See the
specific sections below for [Embedded Storage Manager](#embedded-storage-manager) and
[PostgreSQL Storage Manager](#postgresql-storage-manager) configuration details.

## Tar File Structure and Storage
Both storage managers use the same tar file format for storing session data. Understanding
this structure helps with debugging and troubleshooting.

### Flexible Blob Storage with fsspec
Both storage managers use [fsspec](https://filesystem-spec.readthedocs.io/) for
blob storage, which provides a unified interface to many storage backends. This means you
can store tar files on local disk, network filesystems, or cloud object storage without
changing your code.

**Example configurations:**

Local filesystem:
```yaml
file_storage_config:
  file_storage_url: file:///mnt/shared/genie-sessions
  compress: false
  shard_depth: 2
  options: null
```

AWS S3:
```yaml
file_storage_config:
  file_storage_url: s3://my-bucket/genie-sessions
  compress: true
  shard_depth: 2
  options:
    key: ${AWS_ACCESS_KEY}
    secret: ${AWS_SECRET_KEY}
```

Google Cloud Storage:
```yaml
file_storage_config:
  file_storage_url: gs://my-bucket/genie-sessions
  compress: true
  shard_depth: 2
  options:
    token: ${GCS_TOKEN}
```

Azure Blob Storage:
```yaml
file_storage_config:
  file_storage_url: az://my-container/genie-sessions
  compress: true
  shard_depth: 2
  options:
    account_name: ${AZURE_ACCOUNT}
    account_key: ${AZURE_KEY}
```

SFTP:
```yaml
file_storage_config:
  file_storage_url: sftp://storage-host/data/genie-sessions
  compress: false
  shard_depth: 2
  options:
    username: ${SFTP_USER}
    password: ${SFTP_PASSWORD}
```

### Tar File Contents
Each tar file contains one or more members representing the serialized components of a GenieModel:

**Main model member (`_`)**
: Contains the serialization of the GenieModel itself

**Secondary storage members**
: For each key in the secondary store of a GenieModel, a member is created with the name
  of the key and content being the serialized data of that secondary store value

**Manifest member (`MANIFEST.json`)**
: Contains metadata about the tar file including a SHA-256 hash of all content for
  corruption detection

### File Organization and Sharding
Tar files are organized in a sharded directory structure for better filesystem performance.
Using `shard_depth: 2`, a directory tree of two levels is created, with files stored at the
lowest level.

Files are named `<session_id>.tar`. The directory tree is constructed using the last
(highest level) and penultimate bytes (second level) of the session_id in reverse order.
This is because session id's are constructed as `ULID`s meaning that there is very low
entropy in the first bytes.

**Example:** A session with ID `019be56e-ad36-f9b5-a63a-557a98e8f71d` will be stored as:
```
./permanent/blobs/d1/7f/019be56e-ad36-f9b5-a63a-557a98e8f71d.tar
```

This sharding approach distributes files evenly across directories, preventing any single
directory from becoming too large.

### Manifest and Corruption Detection
Each tar file includes a `MANIFEST.json` file containing:
- Timestamp of when the tar was created
- SHA-256 hash of all data members (excluding the manifest itself)
- List of members with their names and sizes

When reading a tar file, the implementation:
1. Reads all members and computes a running SHA-256 hash
2. Reads the manifest
3. Compares the computed hash with the manifest hash
4. If hashes don't match, retries the read (up to 3 attempts with exponential backoff)

This manifest-based approach is particularly important for cloud storage backends like S3,
where atomic file operations are expensive. The hash verification ensures data integrity
even when reads might overlap with writes or experience eventual consistency delays.

### Concurrent Access Pattern
With a single writer and multiple readers, the following scenario is possible:
- A reader opens a tar file and begins streaming its contents
- The writer updates the same tar file with new data
- The reader detects a hash mismatch and automatically retries

This is an acceptable trade-off for archival storage, occurring in approximately 1 in 100,000
reads under heavy load. The retry mechanism ensures readers eventually get consistent data,
though it might be from a slightly older version of the session.


# Keeping Permanent Storage up to date
When a permanent storage manager (other than `none`) is configured, the Genie Flow engine
will keep track of whether sessions have been altered. A set of "dirty" session ids is
maintained (inside the object store Redis database) and a "sweep" is scheduled to persist
any and all dirty sessions.

For this, a [Celery periodic task](https://docs.celeryq.dev/en/main/userguide/periodic-tasks.html)
is required. In the configuration, the periodic of that task is configured in the `config.yaml`
as demonstrated in the following snippet:
```yaml
celery:
  broker: redis://localhost:6379/0
  backend: redis://localhost:6379/0
  redis_socket_timeout: 4.0
  redis_socket_connect_timeout: 4.0
  permanent_persistence_period: 30.0
```

Here the `permanent_persistence_period` specifies the number of seconds between subsequent
sweeps. This setting should be lower than the expiration time specified for the `object_store`,
otherwise session objects might be expired before they are persisted.

There is a fine balance between the number of sessions to persist in one sweep and the
frequency at which these sweeps are conducted.

## periodic tasks
As described in the Celery documentation, the `beat` process schedules periodic tasks. These
tasks are then put onto the workers queue and will be picked up by any of the workers
listening to that queue.

By default, these scheduled tasks will be put onto the default queue called 'celery' which
is the queue that all workers will listen to when not told otherwise.

To dedicate a worker to conduct these periodic tasks, you would need to run that worker
as, for instance: `celery -A celery_app worker -Q permanent_store` which would make that worker
look at tasks on the queue called "permanent_store". In the `config.yaml` file, you would
then add that name to the `celery` config, as follows:
```yaml
celery:
  broker: redis://localhost:6379/0
  backend: redis://localhost:6379/0
  redis_socket_timeout: 4.0
  redis_socket_connect_timeout: 4.0
  permanent_persistence_period: 30.0
  permanent_persistence_queue: permanent_store
```

## Embedded Storage Manager
The `EmbeddedStorageManager` permanently stores GenieModel objects in tar files and keeps 
an index of persisted records in an embedded SQLite database. This is the recommended option
for small to medium deployments where all processes can access a shared local filesystem.

### Installation

To use the embedded storage manager, install genie-flow with the `permanent` extra:

```bash
pip install genie-flow[permanent]
```

This installs the required `fsspec` dependency for flexible blob storage backends.

### Configuration Example
```yaml
persistence:
  permanent_store:
    type: embedded
    config:
      critical_watermark: 120
      max_writes: 32
      file_storage_config:
        file_storage_url: file://./permanent/blobs
        compress: false
        shard_depth: 2
        options: null
      database_config:
        path: ./permanent/db
        retries: 5
```

See [Configuration Structure](#configuration-structure) above for `critical_watermark`, 
`max_writes`, and `file_storage_config` parameter descriptions.

### Database Configuration Parameters

`database_config.path`
: Path to the directory where the SQLite database file will be stored. The database file
  `permanent_store.db` will be created in this directory.

`database_config.retries`
: Maximum number of retry attempts for database operations in case of lock contention. The
  implementation uses exponential backoff between retries. (default: 5)

### database index
For every tar file, a record is created in the database `permanent_store.db` which will
be stored in the configured `database_config.path`.

This database contains the table `sessions`, which is defined as:
```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    email_address TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```
This index is used to retrieve sessions belonging to a specific user, identified
by their email address.

### concurrent access and robustness
The SQLite database implementation is designed to handle multiple concurrent readers 
alongside a single writer process efficiently and reliably.

* [Write-Ahead Logging (WAL mode)](https://www.sqlite.org/wal.html) is enabled, which allows
readers to access the database without blocking the writer, and vice versa.
* Each process maintains its own thread-local database connection to ensure thread safety 
in multi-threaded environments like Celery workers.
* Write operations are wrapped in explicit transactions with immediate lock acquisition
(`BEGIN IMMEDIATE`) and include automatic retry logic with exponential backoff for transient
lock contention.
* Batch writes are used whenever possible to minimize transaction overhead and maximize
throughput.
* After each batch write cycle, a passive checkpoint is performed to keep the WAL size
manageable without blocking concurrent readers.

This architecture ensures that the permanent storage system remains responsive and reliable
even under heavy concurrent read load from multiple Celery Workers while a dedicated worker
process handles all write operations.

### network filesystem limitation
The `EmbeddedStorageManager` uses SQLite with Write-Ahead Logging (WAL mode) for
the session index, which enables efficient concurrent access from multiple readers and a 
single writer. However, **WAL mode requires all processes to share memory-mapped files and
is therefore incompatible with network filesystems** (NFS, SMB, CIFS, etc.). This means 
`EmbeddedStorageManager` can only be used when all processes (API processes and workers) run 
on the same physical machine with local access to the database file. For distributed 
deployments where processes run on multiple machines, use `PostgresFileStoreManager` instead.

### when to use embedded storage
Use the `EmbeddedStorageManager` when:
* All workers and API processes run on a single machine
* You want simple deployment with no external database dependencies
* Your session volume is low to medium (thousands to tens of thousands of sessions)
* You have access to a shared local filesystem for all processes

## PostgreSQL Storage Manager
The `PostgresFileStoreManager` permanently stores GenieModel objects in tar files and keeps
an index of persisted records in a PostgreSQL database. This is the recommended option for
large-scale deployments where processes are distributed across multiple machines.

### Installation

To use the PostgreSQL storage manager, install genie-flow with both the `permanent` and 
`permanent_postgres` extras:

```bash
pip install genie-flow[permanent,permanent_postgres]
```

This installs:
- `fsspec` for flexible blob storage backends
- `psycopg` (with binary drivers) for PostgreSQL connectivity
- `psycopg-pool` for connection pooling

### Configuration Example
```yaml
persistence:
  permanent_store:
    type: postgres
    config:
      critical_watermark: 120
      max_writes: 32
      file_storage_config:
        file_storage_url: s3://my-bucket/genie-sessions
        compress: false
        shard_depth: 2
        options:
          key: ${AWS_ACCESS_KEY}
          secret: ${AWS_SECRET_KEY}
      database_config:
        host: postgres.example.com
        port: 5432
        database: genie_sessions
        user: genie
        password: ${POSTGRES_PASSWORD}
        max_pool_size: 10
        timeout: 30.0
```

See [Configuration Structure](#configuration-structure) above for `critical_watermark`, 
`max_writes`, and `file_storage_config` parameter descriptions.

### Database Configuration Parameters

`database_config.host`
: PostgreSQL server hostname or IP address

`database_config.port`
: PostgreSQL server port (typically 5432)

`database_config.database`
: Name of the database to use for storing the session index

`database_config.user`
: PostgreSQL username for authentication

`database_config.password`
: PostgreSQL password for authentication. It is strongly recommended to use environment
  variables (e.g., `${POSTGRES_PASSWORD}`) rather than hardcoding passwords in configuration files.

`database_config.max_pool_size`
: Maximum number of connections to maintain in the connection pool. Adjust based on the number
  of worker processes and expected concurrent load. (default: 10)

`database_config.timeout`
: Connection timeout in seconds. Operations that take longer than this will fail with a timeout
  error. (default: 30.0)

### database index
The PostgreSQL database contains a `sessions` table:
```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    email_address TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

With indexes on `email_address` and `updated_at` for efficient querying.

### concurrent access
PostgreSQL's MVCC (Multi-Version Concurrency Control) architecture provides true concurrent
access without blocking:
* Multiple readers can query the session index simultaneously
* The single writer process can insert/update records without blocking readers
* Connection pooling ensures efficient resource usage across all processes
* No shared memory requirements - works across network boundaries

### when to use postgresql storage
Use the `PostgresFileStoreManager` when:
* Workers and API processes are distributed across multiple machines
* You need true network-accessible storage for the session index
* You want flexibility in blob storage location (local, NFS, S3, GCS, etc.)
* You require scalability beyond a single machine
* You already have PostgreSQL infrastructure available

## Choosing Between Embedded and PostgreSQL Storage

| Feature               | Embedded Storage               | PostgreSQL Storage              |
|-----------------------|--------------------------------|---------------------------------|
| **Deployment**        | Single machine                 | Multi-machine cluster           |
| **Database**          | SQLite (embedded)              | PostgreSQL (external)           |
| **Blob storage**      | Local filesystem or fsspec     | Any fsspec backend              |
| **Setup complexity**  | Minimal                        | Requires PostgreSQL             |
| **Scalability**       | Low to medium                  | High                            |
| **Concurrent access** | WAL mode (local only)          | MVCC (network-safe)             |
| **Dependencies**      | None (SQLite built-in)         | PostgreSQL + psycopg            |
| **Best for**          | Development, small deployments | Production, distributed systems |