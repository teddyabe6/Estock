"""File storage behind an interface (PRD 18).

Local disk is the default and the only thing tests need.  An S3-compatible
backend can be added by implementing :class:`StorageBackend` and selecting it
with ``STORAGE_BACKEND``; nothing else in the codebase changes.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings
from app.core.errors import ValidationError

#: Spreadsheet and image types accepted for upload (PRD 20).
ALLOWED_IMPORT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "application/csv",
    "text/plain",
}
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
#: Leading characters that spreadsheet software treats as a formula (PRD 20).
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    cleaned = _SAFE_NAME.sub("_", name).strip("._") or "file"
    return cleaned[:150]


def escape_for_spreadsheet(value: str | None) -> str | None:
    """Neutralise formula injection in exported cells (PRD 20)."""
    if value is None:
        return None
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


class StorageBackend(ABC):
    @abstractmethod
    def save(self, tenant_id: uuid.UUID, filename: str, content: bytes) -> str:
        """Persist the bytes and return the storage key."""

    @abstractmethod
    def load(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def url_for(self, key: str) -> str | None:
        """A directly servable URL, or ``None`` when the app must stream it."""


class LocalDiskStorage(StorageBackend):
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.storage_local_root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root)):
            raise ValidationError("Invalid storage key")
        return path

    def save(self, tenant_id: uuid.UUID, filename: str, content: bytes) -> str:
        key = f"{tenant_id}/{uuid.uuid4().hex}-{safe_filename(filename)}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    def load(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def url_for(self, key: str) -> str | None:
        return None


_BACKENDS: dict[str, type[StorageBackend]] = {"local": LocalDiskStorage}


def get_storage() -> StorageBackend:
    backend = _BACKENDS.get(settings.storage_backend)
    if backend is None:
        raise ValidationError(f"Unknown storage backend '{settings.storage_backend}'")
    return backend()


def validate_upload(
    *, filename: str, content_type: str, content: bytes, allowed_types: set[str]
) -> str:
    """Check type and size, and return the content checksum (PRD 20)."""
    if len(content) > settings.max_upload_bytes:
        raise ValidationError(
            f"File is larger than the {settings.max_upload_bytes // (1024 * 1024)}MB limit"
        )
    if not content:
        raise ValidationError("The uploaded file is empty")
    if content_type not in allowed_types:
        raise ValidationError(
            f"'{content_type}' files are not accepted here",
            details={"allowed": sorted(allowed_types)},
        )
    return hashlib.sha256(content).hexdigest()
