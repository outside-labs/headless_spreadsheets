"""Errors raised by the public spreadsheet interfaces."""


class SpreadsheetError(ValueError):
    """Base class for invalid spreadsheet data or operations."""


class AddressError(SpreadsheetError):
    """An A1 address is malformed or outside the existing grid."""


class ShapeError(SpreadsheetError):
    """A grid is ragged, has invalid labels or exceeds its limits."""


class FormatError(SpreadsheetError):
    """Serialized spreadsheet data does not satisfy the format contract."""
