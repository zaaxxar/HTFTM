"""MinIO (S3-compatible) blob storage for recorded audio (design §2).

Audio files live here; Postgres holds only the bucket + object key (golden rule #3).
The S3 API keeps a later cloud migration rewrite-free (NFR-6). The `minio` client is
synchronous — callers run these via `asyncio.to_thread` so the event loop isn't blocked.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from minio import Minio

logger = logging.getLogger("relay.storage")


class ObjectStore:
    def __init__(self, endpoint: str, access_key: str, secret_key: str) -> None:
        parsed = urlparse(endpoint)
        host = parsed.netloc or parsed.path  # tolerate "minio:9000" without scheme
        self._client = Minio(
            host,
            access_key=access_key,
            secret_key=secret_key,
            secure=(parsed.scheme == "https"),
        )

    def ensure_bucket(self, bucket: str) -> None:
        """Create the bucket if it doesn't exist (idempotent)."""
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)
            logger.info("created bucket %s", bucket)

    def upload_file(self, bucket: str, key: str, path: str, content_type: str) -> None:
        self.ensure_bucket(bucket)
        self._client.fput_object(bucket, key, path, content_type=content_type)
        logger.info("uploaded s3://%s/%s", bucket, key)
