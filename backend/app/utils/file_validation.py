"""Upload validation based on actual file CONTENT (magic bytes), size limits and safe naming."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePath

ALLOWED = {
    "application/pdf": (b"%PDF-", ".pdf"),
    "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
    "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
}
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


class UploadRejected(Exception):
    """Raised for files that must be refused. ``status_code`` maps to the HTTP response."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ValidatedUpload:
    content_type: str
    extension: str
    sha256: str
    size: int
    safe_name: str
    extension_mismatch: bool


def safe_filename(name: str | None) -> str:
    """Basename only, no control chars/path separators, bounded length. For DISPLAY; never used as a path."""
    base = PurePath((name or "upload").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    base = re.sub(r"[^A-Za-z0-9._ \-()]", "_", base).strip(" .") or "upload"
    return base[:120]


def sniff_content_type(data: bytes) -> str | None:
    for ctype, (magic, _) in ALLOWED.items():
        if data.startswith(magic):
            return ctype
    return None


def validate_upload(data: bytes, filename: str | None, max_bytes: int) -> ValidatedUpload:
    if not data:
        raise UploadRejected("The uploaded file is empty.", 400)
    if len(data) > max_bytes:
        raise UploadRejected(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.", 413)
    ctype = sniff_content_type(data)
    if ctype is None:
        raise UploadRejected("Unsupported file type. Only PDF, PNG and JPEG files are accepted "
                             "(type is checked from file content, not the extension).", 415)
    name = safe_filename(filename)
    ext = PurePath(name).suffix.lower()
    expected = ALLOWED[ctype][1]
    mismatch = ext not in ALLOWED_EXTENSIONS or (ext == ".jpeg" and ctype != "image/jpeg") or \
        (ext not in {expected, ".jpeg"})
    return ValidatedUpload(ctype, expected, hashlib.sha256(data).hexdigest(), len(data), name, mismatch)
