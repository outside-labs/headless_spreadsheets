"""Bounded UTF-8 reads and atomic text replacement."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import FormatError

if TYPE_CHECKING:
    from .core import Limits

type FilePath = str | os.PathLike[str]


def check_text(text: str, limits: Limits) -> None:
    if not isinstance(text, str):
        raise FormatError("Expected serialized text, not a path or bytes.")
    try:
        if len(text) > limits.max_input_bytes or len(text.encode("utf-8")) > limits.max_input_bytes:
            raise FormatError("Serialized input exceeds the configured byte limit.")
    except UnicodeError as error:
        raise FormatError("Serialized text must be valid UTF-8.") from error


def read_text(path: FilePath, limits: Limits) -> str:
    path = Path(path)
    if path.stat().st_size > limits.max_input_bytes:
        raise FormatError("Input file exceeds the configured byte limit.")
    with path.open("rb") as stream:
        raw = stream.read(limits.max_input_bytes + 1)
    if len(raw) > limits.max_input_bytes:
        raise FormatError("Input file exceeds the configured byte limit.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError as error:
        raise FormatError("Input file must be UTF-8 text.") from error


def write_text(text: str, path: FilePath | None) -> str:
    if path is None:
        return text
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return text
