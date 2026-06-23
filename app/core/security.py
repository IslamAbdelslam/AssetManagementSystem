"""Input sanitization and validation utilities."""
from __future__ import annotations

import json
import re


_NULL_BYTE_RE = re.compile(r"\x00")
_MAX_METADATA_SIZE = 64 * 1024  # 64KB
_MAX_METADATA_DEPTH = 5


def sanitize_string(value: str, max_length: int = 512) -> str:
    """Normalize: strip whitespace, lowercase, reject null bytes, enforce max length."""
    value = _NULL_BYTE_RE.sub("", value).strip().lower()
    if len(value) > max_length:
        raise ValueError(f"Value exceeds maximum length of {max_length} characters.")
    return value


def validate_metadata(value: dict) -> dict:
    """Enforce max size (64KB) and max nesting depth (5)."""
    serialized = json.dumps(value)
    if len(serialized.encode()) > _MAX_METADATA_SIZE:
        raise ValueError("Metadata exceeds maximum size of 64KB.")
    if _get_depth(value) > _MAX_METADATA_DEPTH:
        raise ValueError(f"Metadata nesting exceeds maximum depth of {_MAX_METADATA_DEPTH}.")
    return value


def validate_tags(tags: list[str]) -> list[str]:
    """Max 20 tags, each max 64 chars, sanitized."""
    if len(tags) > 20:
        raise ValueError("Maximum 20 tags per asset.")
    return [
        _NULL_BYTE_RE.sub("", t).strip()[:64]
        for t in tags
        if t.strip()
    ]


def _get_depth(obj: object, current: int = 0) -> int:
    if current > _MAX_METADATA_DEPTH:
        return current
    if isinstance(obj, dict):
        if not obj:
            return current
        return max(_get_depth(v, current + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return current
        return max(_get_depth(item, current + 1) for item in obj)
    return current
