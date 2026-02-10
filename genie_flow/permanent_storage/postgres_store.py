from pathlib import Path

from genie_flow.permanent_storage.abstract_file_store import AbstractFileStorageManager


class PostgresFileStoreManager(AbstractFileStorageManager):

    def __init__(
        self,
        critical_watermark: int | float,
        max_writes: int,
        blob_path: str | Path | None,
        compress: bool,
        blob_directory_depth: int,
        database_uri: str,
    ):
        super().__init__(
            critical_watermark,
            max_writes,
            blob_path,
            compress,
            blob_directory_depth,
        )
