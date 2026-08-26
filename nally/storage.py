"""Object Storage — S3-compatible (Backblaze B2 / Cloudflare R2) with local fallback.

Uploads files to B2/R2 when configured, falls back to local data/ directory.
Generates pre-signed URLs for private buckets.

Env vars:
    S3_ENDPOINT         — S3-compatible endpoint (e.g. s3.us-east-005.backblazeb2.com)
    S3_ACCESS_KEY_ID    — Access key ID
    S3_SECRET_ACCESS_KEY — Secret access key
    S3_BUCKET_NAME      — Bucket name
    S3_PUBLIC_URL       — Custom public domain (optional, skips pre-signed URLs)
    S3_URL_EXPIRY       — Pre-signed URL lifetime in seconds (default: 86400 = 24h)
"""

import os
from pathlib import Path
from typing import Optional

from .utils.logger import logger

# ── Config ──────────────────────────────────────────────────

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
S3_PUBLIC_URL = os.getenv("S3_PUBLIC_URL", "")
S3_URL_EXPIRY = int(os.getenv("S3_URL_EXPIRY", "86400"))

_ENDPOINT_URL = f"https://{S3_ENDPOINT}" if S3_ENDPOINT and not S3_ENDPOINT.startswith("http") else S3_ENDPOINT


def _is_s3_configured() -> bool:
    return bool(S3_ENDPOINT and S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY and S3_BUCKET_NAME)


class ObjectStorage:
    """Unified storage: S3-compatible (B2/R2) when configured, local data/ fallback.

    Usage:
        storage = ObjectStorage()
        url = storage.upload(image_bytes, "generated/img_123.png")
        # url is a pre-signed URL, public URL, or relative local path
    """

    def __init__(self, local_dir: Optional[Path] = None):
        self._local_dir = local_dir or Path("data")
        self._local_dir.mkdir(parents=True, exist_ok=True)
        self._s3_client = None

    def _get_s3_client(self):
        """Lazy-init boto3 S3 client."""
        if self._s3_client is not None:
            return self._s3_client
        if not _is_s3_configured():
            return None
        try:
            import boto3

            self._s3_client = boto3.client(
                "s3",
                endpoint_url=_ENDPOINT_URL,
                aws_access_key_id=S3_ACCESS_KEY_ID,
                aws_secret_access_key=S3_SECRET_ACCESS_KEY,
                region_name="us-east-1",
            )
            logger.info(f"S3 storage initialized: bucket={S3_BUCKET_NAME} endpoint={S3_ENDPOINT}")
            return self._s3_client
        except ImportError:
            logger.warning("boto3 not installed — S3 storage unavailable, using local fallback")
            return None
        except Exception as e:
            logger.error(f"S3 client init failed: {e}")
            return None

    def upload(
        self,
        data: bytes,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes and return a URL.

        Returns pre-signed URL (private bucket), public URL, or local path.
        """
        client = self._get_s3_client()
        if client:
            return self._upload_s3(client, data, key, content_type)
        return self._upload_local(data, key)

    def upload_file(
        self,
        local_path: Path,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a local file and return a URL."""
        data = local_path.read_bytes()
        return self.upload(data, key, content_type)

    def _upload_s3(self, client, data: bytes, key: str, content_type: str) -> str:
        try:
            client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            url = self._get_url(client, key)
            logger.debug(f"S3 uploaded: {key} -> {url[:80]}")
            return url
        except Exception as e:
            logger.error(f"S3 upload failed ({key}): {e} — falling back to local")
            return self._upload_local(data, key)

    def _get_url(self, client, key: str) -> str:
        """Get URL for an object — public URL if configured, else pre-signed."""
        if S3_PUBLIC_URL:
            return f"{S3_PUBLIC_URL.rstrip('/')}/{key}"
        # Pre-signed URL for private buckets
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET_NAME, "Key": key},
                ExpiresIn=S3_URL_EXPIRY,
            )
            return url
        except Exception as e:
            logger.warning(f"Failed to generate pre-signed URL for {key}: {e}")
            return f"s3://{S3_BUCKET_NAME}/{key}"

    def _upload_local(self, data: bytes, key: str) -> str:
        path = self._local_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"/data/{key}"

    def get_url(self, key: str) -> str:
        """Get the URL for an existing object key."""
        client = self._get_s3_client()
        if client:
            return self._get_url(client, key)
        return f"/data/{key}"

    def delete(self, key: str) -> bool:
        """Delete an object. Returns True on success."""
        client = self._get_s3_client()
        if client:
            try:
                client.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
                return True
            except Exception as e:
                logger.error(f"S3 delete failed ({key}): {e}")
        path = self._local_dir / key
        if path.exists():
            path.unlink()
            return True
        return False

    @property
    def backend(self) -> str:
        return "s3" if _is_s3_configured() and self._get_s3_client() else "local"


# ── Module-level singleton ──────────────────────────────────

storage = ObjectStorage()
