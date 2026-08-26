"""Object Storage — Cloudflare R2 with local fallback.

Uploads files to R2 when configured, falls back to local data/ directory.
Provides public URLs for R2 objects.

Env vars:
    R2_ACCOUNT_ID       — Cloudflare account ID
    R2_ACCESS_KEY_ID    — R2 API token access key
    R2_SECRET_ACCESS_KEY — R2 API token secret
    R2_BUCKET_NAME      — R2 bucket name
    R2_PUBLIC_URL       — Custom domain or r2.dev public URL (optional)
"""

import hashlib
import os
import time
from pathlib import Path
from typing import Optional

from .utils.logger import logger

# ── Config ──────────────────────────────────────────────────

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")

_R2_ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else ""


def _is_r2_configured() -> bool:
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME)


class ObjectStorage:
    """Unified storage: R2 when configured, local data/ fallback.

    Usage:
        storage = ObjectStorage()
        url = storage.upload(image_bytes, "generated/img_123.png")
        # url is an R2 public URL or a relative local path
    """

    def __init__(self, local_dir: Optional[Path] = None):
        self._local_dir = local_dir or Path("data")
        self._local_dir.mkdir(parents=True, exist_ok=True)
        self._r2_client = None

    def _get_r2_client(self):
        """Lazy-init boto3 S3 client for R2."""
        if self._r2_client is not None:
            return self._r2_client
        if not _is_r2_configured():
            return None
        try:
            import boto3

            self._r2_client = boto3.client(
                "s3",
                endpoint_url=_R2_ENDPOINT,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                region_name="auto",
            )
            logger.info(f"R2 storage initialized: bucket={R2_BUCKET_NAME}")
            return self._r2_client
        except ImportError:
            logger.warning("boto3 not installed — R2 storage unavailable, using local fallback")
            return None
        except Exception as e:
            logger.error(f"R2 client init failed: {e}")
            return None

    def upload(
        self,
        data: bytes,
        key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes and return a URL.

        Args:
            data: File content bytes.
            key: Object key (e.g. "generated/img_123.png").
            content_type: MIME type for the object.

        Returns:
            Public URL (R2) or relative local path.
        """
        client = self._get_r2_client()
        if client:
            return self._upload_r2(client, data, key, content_type)
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

    def _upload_r2(self, client, data: bytes, key: str, content_type: str) -> str:
        try:
            client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            if R2_PUBLIC_URL:
                url = f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
            else:
                url = f"https://{R2_BUCKET_NAME}.{R2_ACCOUNT_ID}.r2.dev/{key}"
            logger.debug(f"R2 uploaded: {key} -> {url[:80]}")
            return url
        except Exception as e:
            logger.error(f"R2 upload failed ({key}): {e} — falling back to local")
            return self._upload_local(data, key)

    def _upload_local(self, data: bytes, key: str) -> str:
        path = self._local_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"/data/{key}"

    def get_public_url(self, key: str) -> str:
        """Get the public URL for an object key."""
        if _is_r2_configured():
            if R2_PUBLIC_URL:
                return f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
            return f"https://{R2_BUCKET_NAME}.{R2_ACCOUNT_ID}.r2.dev/{key}"
        return f"/data/{key}"

    def delete(self, key: str) -> bool:
        """Delete an object. Returns True on success."""
        client = self._get_r2_client()
        if client:
            try:
                client.delete_object(Bucket=R2_BUCKET_NAME, Key=key)
                return True
            except Exception as e:
                logger.error(f"R2 delete failed ({key}): {e}")
        # Local fallback — best effort
        path = self._local_dir / key
        if path.exists():
            path.unlink()
            return True
        return False

    @property
    def backend(self) -> str:
        return "r2" if _is_r2_configured() and self._get_r2_client() else "local"


# ── Module-level singleton ──────────────────────────────────

storage = ObjectStorage()
