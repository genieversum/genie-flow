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
    type: file
    config:
      database_path: ./permanent/db
      blob_path: ./permanent/blob
      compress: false
      blob_directory_depth: 2
```

Here a permanent store of type "file" has been configured. This means that a permanently
stored version of the session will be created. In this case using "files".

To date, the options for `type` are:

`none`
: no permanent storage is configured and expired sessions are lost indefinitely

`file`
: sessions are permanently stored in tar files and an index or sessions is kept in an
  SQLite database. See [File Permanent Store](#File-Permanent-Store) below for details.


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

## File Permanent Store
Permanently store GenieModel objects in tar files and keep an index of persisted
records in an SQLite database.

### tar files
The tar files consist of one or more files (members), containing the serialization of
components of a GenieModel.

The member "_" contains the serialization of the GenieModel itself.
For every key in the secondary store of a GenieModel, a member of the tar file is
created that has the name of the key and content being the serialized data of the
secondary store value.

Using the example configuration above, this will create a directory tree of two levels and 
store files at the lowest level of that tree. These files will be named `<session_id>.tar`.
The directory tree is constructed by the last (highest level) and penultimate bytes (second 
level) of the session_id. So a file `019be56e-ad36-f9b5-a63a-557a98e8f71d.tar` will be stored 
as `./permanent/blob/1d/f7/019be56e-ad36-f9b5-a63a-557a98e8f71d.tar`

### database index
For every tar file, a record is created in the database `permanent_store.db` which will
be stored as `./permanent/db/permanent_store.db`.

This database contains the table `sessions`, which is defined as:
```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    email_address TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```
This index is used to be able to retrieve sessions belonging to a specific user, identified
by their email address.

### access to the central blob store
Storing these files is done by the Celery worker that picks up the periodic tasks called
"genie_flow.scheduler.permanent_persistence". Retrieval of permanently stored objects is
conducted by the API process.

This means that access to the blob files and database needs to be provided to these
processes. Either because they all run on the same machine and storage is configured to be
on a local disk on that machine - or a network share of these files is mounted onto the
worker and API processes.

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

> For production deployments, it is recommended to run a separate permanent storage worker
> that listens on a dedicated permanent storage queue

### network filesystem limitation
The `FileStorageManager` implementation uses SQLite with Write-Ahead Logging (WAL mode) for
the session index, which enables efficient concurrent access from multiple readers and a 
single writer. However, **WAL mode requires all processes to share memory-mapped files and
is therefore incompatible with network filesystems** (NFS, SMB, CIFS, etc.). This means 
`FileStorageManager` can only be used when all processes (API processes and workers) run on 
the same physical machine with local access to the database file. For distributed deployments
where processes run on multiple machines, and storage must be accessed over a network 
filesystem, use `PostgresStorageManager` instead, which stores the session index in PostgreSQL
while keeping tar files on shared storage.

**NB: The PostgresStorageManager is @TODO**