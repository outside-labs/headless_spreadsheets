"""Lazy serialization interfaces shared by the document models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from .errors import FormatError
from .file_io import FilePath, read_text, write_text

if TYPE_CHECKING:
    from .core import Limits


class NativeJSON:
    def to_json(self, path: FilePath | None = None, *, indent: int | None = 2) -> str:
        """Serialize typed cells; optionally replace a UTF-8 destination atomically."""
        from .serialization import dumps
        return write_text(dumps(self, indent=indent), path)

    @classmethod
    def from_json(cls, text: str, *, limits: Limits | None = None) -> Self:
        """Parse native JSON text of this model's kind, rejecting unknown schemas."""
        from .serialization import loads
        result = loads(text, limits=limits)
        if not isinstance(result, cls):
            raise FormatError(f"Expected a serialized {cls.__name__}.")
        return result

    @classmethod
    def read_json(cls, path: FilePath, *, limits: Limits | None = None) -> Self:
        from .core import DEFAULT_LIMITS
        selected = DEFAULT_LIMITS if limits is None else limits
        return cls.from_json(read_text(path, selected), limits=selected)
