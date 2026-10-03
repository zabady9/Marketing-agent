"""Where user-uploaded chat attachments live — one small interface over two
backends, picked by settings.upload_storage:

- "local" (dev): files land under settings.upload_local_dir, uploaded by the
  browser through this backend's own PUT .../attachments/{id}/content route.
- "gcs" (production): files land in settings.upload_bucket, uploaded by the
  browser *directly* to GCS through a V4 signed PUT URL. This is the only way
  to accept files bigger than Cloud Run's 32MB request-body cap. Signing
  works without a service account key file through IAM signBlob, which needs
  the runtime SA to hold roles/iam.serviceAccountTokenCreator on itself (it
  already does, for mcp-office-docs — see CLAUDE.md). The bucket also needs
  a CORS rule allowing PUT from the frontend's origin.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings

_SIGNED_URL_TTL = timedelta(hours=1)


def _gcs_bucket():
    from google.cloud import storage

    return storage.Client().bucket(get_settings().upload_bucket)


def object_path(project_id: str, attachment_id: str, safe_filename: str) -> str:
    """The storage_path for a new attachment — a GCS object name, or a path
    under upload_local_dir. Always derived from server-side ids plus an
    already-sanitized filename, never from a raw client-supplied path."""
    relative = f"{project_id}/{attachment_id}/{safe_filename}"
    settings = get_settings()
    if settings.upload_storage == "gcs":
        return relative
    return str(Path(settings.upload_local_dir) / relative)


def create_upload_target(storage_path: str, content_type: str, local_upload_url: str) -> dict:
    """Where the browser should PUT the file's bytes. local_upload_url is the
    backend's own PUT .../content route, used only in local mode."""
    settings = get_settings()
    if settings.upload_storage != "gcs":
        return {"url": local_upload_url, "method": "PUT", "headers": {"Content-Type": content_type}}

    import google.auth
    from google.auth.transport import requests as google_requests

    credentials, _ = google.auth.default()
    credentials.refresh(google_requests.Request())
    url = _gcs_bucket().blob(storage_path).generate_signed_url(
        version="v4",
        expiration=_SIGNED_URL_TTL,
        method="PUT",
        content_type=content_type,
        service_account_email=credentials.service_account_email,
        access_token=credentials.token,
    )
    return {"url": url, "method": "PUT", "headers": {"Content-Type": content_type}}


def stat(storage_path: str) -> int | None:
    """The stored file's size in bytes, or None if nothing was uploaded."""
    if get_settings().upload_storage == "gcs":
        blob = _gcs_bucket().get_blob(storage_path)
        return None if blob is None else blob.size
    try:
        return os.path.getsize(storage_path)
    except OSError:
        return None


def open_read(storage_path: str) -> BinaryIO:
    """A streaming, seekable reader. GCS's BlobReader fetches in chunks, so
    a 2GB file is never held in memory at once."""
    if get_settings().upload_storage == "gcs":
        return _gcs_bucket().blob(storage_path).open("rb")
    return open(storage_path, "rb")


def delete(storage_path: str) -> None:
    if get_settings().upload_storage == "gcs":
        blob = _gcs_bucket().blob(storage_path)
        if blob.exists():
            blob.delete()
        return
    try:
        os.remove(storage_path)
    except FileNotFoundError:
        pass
