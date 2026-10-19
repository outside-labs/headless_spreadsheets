"""Typed cells, rectangular grids and ordered workbooks."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from .errors import AddressError, ShapeError, SpreadsheetError
from .formats import NativeJSON

type Scalar = None | bool | int | float | str | Decimal | date | datetime
type CellInput = Scalar | Cell
type DataType = Literal["blank", "boolean", "integer", "number", "text", "decimal", "date", "datetime"]

_TYPES: dict[type, DataType] = {
    type(None): "blank", bool: "boolean", int: "integer", float: "number",
    str: "text", Decimal: "decimal", date: "date", datetime: "datetime",
}


@dataclass(frozen=True, slots=True)
class Cell:
    """A literal or an opaque formula with an unverified cached scalar result.

    A string beginning with '=' is literal unless supplied as ``formula``.
    Formula results are never calculated or marked fresh in this release.
    ``number_format`` is an inert presentation hint.
    """

    value: Scalar = None
    formula: str | None = None
    number_format: str | None = None

    def __post_init__(self) -> None:
        if type(self.value) not in _TYPES:
            raise SpreadsheetError(f"Unsupported cell type: {type(self.value).__name__}")
        if type(self.value) is float and not math.isfinite(self.value):
            raise SpreadsheetError("Cell numbers must be finite.")
        if type(self.value) is Decimal and not self.value.is_finite():
            raise SpreadsheetError("Cell decimals must be finite.")
        if self.formula is not None and (
            not isinstance(self.formula, str)
            or not self.formula.startswith("=")
            or not self.formula[1:].strip()
        ):
            raise SpreadsheetError("A formula must start with '=' and contain an expression.")
        if self.number_format is not None and not isinstance(self.number_format, str):
            raise SpreadsheetError("A number-format hint must be text or None.")

    @property
    def data_type(self) -> DataType:
        return _TYPES[type(self.value)]

    @property
    def cache_status(self) -> Literal["value", "missing", "stale"]:
        if self.formula is None:
            return "value"
        return "missing" if self.value is None else "stale"


def as_cell(value: CellInput) -> Cell:
    return value if isinstance(value, Cell) else Cell(value)


@dataclass(frozen=True, slots=True)
class Limits:
    """Finite application guardrails, not a hard memory or CPU sandbox."""

    max_rows: int = 100_000
    max_columns: int = 1_024
    max_cells: int = 1_000_000
    max_input_bytes: int = 16_000_000
    max_sheets: int = 256

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ShapeError(f"{name} must be a positive integer.")

    def check(self, rows: int, columns: int) -> None:
        if rows > self.max_rows or columns > self.max_columns or rows * columns > self.max_cells:
            raise ShapeError("Grid dimensions exceed the configured limits.")


DEFAULT_LIMITS = Limits()


def column_name(index: int) -> str:
    """Convert a zero-based column index to its A1 name."""
    if type(index) is not int or index < 0:
        raise AddressError("A column index must be a nonnegative integer.")
    result = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def split_address(address: str) -> tuple[int, int]:
    """Return zero-based (row, column) coordinates for an A1 address."""
    if not isinstance(address, str) or len(address) > 64:
        raise AddressError("Expected an A1 cell address.")
    match = re.fullmatch(r"([A-Za-z]+)([1-9][0-9]*)", address)
    if match is None:
        raise AddressError(f"Invalid A1 address: {address!r}")
    column = 0
    for letter in match[1].upper():
        column = column * 26 + ord(letter) - 64
    return int(match[2]) - 1, column - 1


def _collect_rows(
    rows: Iterable[Iterable[CellInput]], *, width: int | None, limits: Limits
) -> tuple[tuple[tuple[Cell, ...], ...], int]:
    if width is not None and (type(width) is not int or width < 0):
        raise ShapeError("Grid width must be a nonnegative integer.")
    limits.check(0, width or 0)
    collected = []
    for row in rows:
        limits.check(len(collected) + 1, width or 0)
        if isinstance(row, (str, bytes)):
            raise ShapeError("A row must be an iterable of cells, not text.")
        cells = []
        for value in row:
            limits.check(len(collected) + 1, len(cells) + 1)
            if width is not None and len(cells) >= width:
                raise ShapeError("Rows must all have the declared width.")
            cells.append(as_cell(value))
        if width is None:
            width = len(cells)
        if len(cells) != width:
            raise ShapeError("Rows must all have the declared width.")
        collected.append(tuple(cells))
    return tuple(collected), width or 0


class Sheet(NativeJSON):
    """An editable rectangular grid; edits never resize or calculate the grid."""

    def __init__(
        self, rows: Iterable[Iterable[CellInput]] = (), *, name: str = "Sheet1",
        width: int | None = None, limits: Limits = DEFAULT_LIMITS,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ShapeError("A sheet name must be nonempty text.")
        self._name = name
        self._limits = limits
        self._rows, self._width = _collect_rows(rows, width=width, limits=limits)

    @property
    def name(self) -> str:
        return self._name

    @property
    def shape(self) -> tuple[int, int]:
        return len(self._rows), self._width

    @property
    def rows(self) -> tuple[tuple[Cell, ...], ...]:
        return self._rows

    def __len__(self) -> int:
        return len(self._rows)

    def _position(self, address: str) -> tuple[int, int]:
        row, column = split_address(address)
        if row >= len(self._rows) or column >= self._width:
            raise AddressError(f"Address {address!r} is outside the existing grid.")
        return row, column

    def cell(self, address: str) -> Cell:
        row, column = self._position(address)
        return self._rows[row][column]

    def set(self, address: str, value: CellInput) -> None:
        row, column = self._position(address)
        cell = as_cell(value)
        changed = (*self._rows[row][:column], cell, *self._rows[row][column + 1:])
        self._rows = (*self._rows[:row], changed, *self._rows[row + 1:])

    def set_formula(self, address: str, formula: str, *, cached_value: Scalar = None) -> None:
        self.set(address, Cell(cached_value, formula=formula))


class Workbook(NativeJSON):
    """Named sheets in insertion order, without a calculation scheduler."""

    def __init__(self, sheets: Iterable[Sheet] = (), *, limits: Limits = DEFAULT_LIMITS) -> None:
        self._limits = limits
        self._sheets: dict[str, Sheet] = {}
        for sheet in sheets:
            self.add_sheet(sheet)

    def add_sheet(self, sheet: Sheet) -> None:
        if not isinstance(sheet, Sheet):
            raise ShapeError("A workbook contains Sheet objects.")
        if sheet.name in self._sheets:
            raise ShapeError(f"Duplicate sheet name: {sheet.name!r}")
        if len(self._sheets) >= self._limits.max_sheets:
            raise ShapeError("Workbook sheet count exceeds the configured limit.")
        self._limits.check(*sheet.shape)
        total = sum(rows * columns for rows, columns in (item.shape for item in self._sheets.values()))
        if total + sheet.shape[0] * sheet.shape[1] > self._limits.max_cells:
            raise ShapeError("Workbook cell count exceeds the configured limit.")
        self._sheets[sheet.name] = sheet

    @property
    def sheet_names(self) -> tuple[str, ...]:
        return tuple(self._sheets)

    def __getitem__(self, name: str) -> Sheet:
        return self._sheets[name]

    def __iter__(self) -> Iterator[Sheet]:
        return iter(self._sheets.values())

    def __len__(self) -> int:
        return len(self._sheets)
