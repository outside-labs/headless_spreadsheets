"""Named tables and stable, read-only selections over source cells."""

from __future__ import annotations

import operator
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any

from .core import (
    DEFAULT_LIMITS, Cell, CellInput, Limits, Scalar, Sheet, _collect_rows,
    as_cell, column_name, split_address,
)
from .errors import AddressError, ShapeError, SpreadsheetError
from .file_io import FilePath, read_text, write_text
from .formats import NativeJSON


def _columns(names: Iterable[str], limits: Limits) -> tuple[str, ...]:
    if isinstance(names, str):
        raise ShapeError("Column names must be an iterable of labels, not one string.")
    result = []
    seen = set()
    for name in names:
        limits.check(0, len(result) + 1)
        if not isinstance(name, str) or not name.strip():
            raise ShapeError("Column names must be nonempty strings.")
        if name in seen:
            raise ShapeError(f"Duplicate column name: {name!r}")
        result.append(name)
        seen.add(name)
    return tuple(result)


class Row(Mapping[str, Scalar]):
    """A read-only mapping with live values and a zero-based source row index."""

    def __init__(self, table: _Tabular, index: int) -> None:
        self._table = table
        self._index = index

    @property
    def index(self) -> int:
        return self._index

    def cell(self, column: str) -> Cell:
        position = self._table._column_position(column)
        return self._table._root._rows[self._index][position]

    def __getitem__(self, column: str) -> Scalar:
        return self.cell(column).value

    def __iter__(self) -> Iterator[str]:
        return iter(self._table.columns)

    def __len__(self) -> int:
        return len(self._table.columns)


class Column(Sequence[Scalar]):
    """A read-only sequence; ``cells`` exposes immutable metadata snapshots."""

    def __init__(self, table: _Tabular, name: str) -> None:
        self._table = table
        self._name = name
        self._position = table._column_position(name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def cells(self) -> tuple[Cell, ...]:
        return tuple(self._table._root._rows[row][self._position] for row in self._table._row_positions)

    def __len__(self) -> int:
        return len(self._table._row_positions)

    def __getitem__(self, index: int | slice) -> Scalar | tuple[Scalar, ...]:
        if isinstance(index, slice):
            return tuple(cell.value for cell in self.cells[index])
        row = self._table._row_positions[index]
        return self._table._root._rows[row][self._position].value


_COMPARISONS = {
    "eq": operator.eq, "ne": operator.ne, "gt": operator.gt, "gte": operator.ge,
    "lt": operator.lt, "lte": operator.le,
}
_OPERATORS = {*_COMPARISONS, "in", "contains", "is_none"}


class _Tabular:
    @property
    def _root(self) -> Table:
        raise NotImplementedError

    @property
    def _row_positions(self) -> Sequence[int]:
        raise NotImplementedError

    @property
    def _column_positions(self) -> Sequence[int]:
        raise NotImplementedError

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(self._root._columns[column] for column in self._column_positions)

    @property
    def shape(self) -> tuple[int, int]:
        return len(self._row_positions), len(self._column_positions)

    @property
    def rows(self) -> tuple[Row, ...]:
        return tuple(self)

    def __len__(self) -> int:
        return len(self._row_positions)

    def __iter__(self) -> Iterator[Row]:
        return (Row(self, index) for index in self._row_positions)

    def __getitem__(self, name: str) -> Column:
        return Column(self, name)

    def _column_position(self, name: str) -> int:
        try:
            return self._column_lookup[name]
        except KeyError:
            raise KeyError(f"Unknown column: {name!r}") from None

    def _position(self, address: str) -> tuple[int, int]:
        row, column = split_address(address)
        if row > len(self) or column >= len(self.columns):
            raise AddressError(f"Address {address!r} is outside the table (including its header).")
        return row, column

    def cell(self, address: str) -> Cell:
        """Read a cell; header row 1 is followed by data rows starting at 2."""
        row, column = self._position(address)
        if row == 0:
            return Cell(self.columns[column])
        return self._root._rows[self._row_positions[row - 1]][self._column_positions[column]]

    def source_address(self, address: str) -> str:
        """Map a local view address to the original table, including its header."""
        row, column = self._position(address)
        original_row = 1 if row == 0 else self._row_positions[row - 1] + 2
        return f"{column_name(self._column_positions[column])}{original_row}"

    def to_records(self) -> list[dict[str, Scalar]]:
        return [dict(row) for row in self]

    def to_csv(
        self, path: FilePath | None = None, *, delimiter: str = ",", formulas: bool = False,
        escape_formulas: bool = True,
    ) -> str:
        """Export values, escaping spreadsheet-active text unless explicitly disabled."""
        from .serialization import to_csv
        return write_text(to_csv(self, delimiter=delimiter, formulas=formulas, escape_formulas=escape_formulas), path)

    def select(self, *columns: str) -> TableView:
        names = _columns(columns, self._root._limits)
        positions = tuple(self._column_position(name) for name in names)
        return TableView(self._root, self._row_positions, positions)

    def where(self, predicate: Callable[[Row], bool] | None = None, **conditions: Any) -> TableView:
        """Combine a Python predicate and named conditions using AND."""
        if predicate is not None and not callable(predicate):
            raise TypeError("A row predicate must be callable.")
        prepared = []
        for key, expected in conditions.items():
            if key in self.columns:
                name, operation = key, "eq"
            else:
                name, separator, operation = key.rpartition("__")
                if not separator:
                    name, operation = key, "eq"
                if operation not in _OPERATORS:
                    raise SpreadsheetError(f"Unknown filter operator: {operation!r}")
            position = self._column_position(name)
            if operation == "is_none" and type(expected) is not bool:
                raise SpreadsheetError("is_none expects True or False.")
            # Membership uses a stable reusable collection, not a consumed generator.
            if operation == "in" and not isinstance(expected, (Sequence, set, frozenset, Mapping)):
                raise SpreadsheetError("in expects a reusable sequence, set or mapping.")
            prepared.append((position, operation, expected))

        def matches(index: int) -> bool:
            for position, operation, expected in prepared:
                value = self._root._rows[index][position].value
                try:
                    if operation == "is_none":
                        match = (value is None) == expected
                    elif operation == "in":
                        match = value in expected
                    elif operation == "contains":
                        match = value is not None and expected in value
                    elif operation in {"gt", "gte", "lt", "lte"} and (value is None or expected is None):
                        match = False
                    else:
                        match = _COMPARISONS[operation](value, expected)
                except (TypeError, ValueError) as error:
                    raise SpreadsheetError(f"Cannot apply {operation!r} to column {self._root._columns[position]!r}.") from error
                if not match:
                    return False
            return predicate is None or bool(predicate(Row(self, index)))

        return TableView(self._root, (index for index in self._row_positions if matches(index)), self._column_positions)

    def sort_by(self, *columns: str, reverse: bool = False, nulls: str = "last") -> TableView:
        """Stable multi-column ordering; blank placement is independent of reverse."""
        if not columns:
            raise SpreadsheetError("sort_by requires at least one column.")
        if type(reverse) is not bool or nulls not in {"first", "last"}:
            raise SpreadsheetError("Expected a Boolean reverse and nulls='first' or 'last'.")
        positions = [self._column_position(name) for name in columns]
        indices = list(self._row_positions)
        for position in reversed(positions):
            present, missing = [], []
            for index in indices:
                (missing if self._root._rows[index][position].value is None else present).append(index)
            try:
                present.sort(key=lambda index: self._root._rows[index][position].value, reverse=reverse)
            except TypeError as error:
                raise SpreadsheetError(f"Column {self._root._columns[position]!r} contains incomparable values.") from error
            indices = missing + present if nulls == "first" else present + missing
        return TableView(self._root, indices, self._column_positions)

    def to_table(self) -> Table:
        """Materialize displayed values, dropping formulas rather than relocating them."""
        return Table(self.columns, ([row[name] for name in self.columns] for row in self), limits=self._root._limits)


class Table(_Tabular, NativeJSON):
    """A standalone named table with explicit edits and immutable headers."""

    def __init__(
        self, columns: Iterable[str] = (), rows: Iterable[Iterable[CellInput]] = (),
        *, limits: Limits = DEFAULT_LIMITS,
    ) -> None:
        self._limits = limits
        self._columns = _columns(columns, limits)
        self._column_lookup = {name: index for index, name in enumerate(self._columns)}
        self._rows, _ = _collect_rows(rows, width=len(self._columns), limits=limits)

    @classmethod
    def from_records(
        cls, records: Iterable[Mapping[str, CellInput]], *, columns: Iterable[str] | None = None,
        limits: Limits = DEFAULT_LIMITS,
    ) -> Table:
        explicit = columns is not None
        names = list(_columns(columns, limits)) if explicit else []
        known = set(names)
        collected = []
        for record in records:
            limits.check(len(collected) + 1, len(names))
            if not isinstance(record, Mapping):
                raise ShapeError("Each record must be a mapping of column names to cells.")
            current = {}
            for name, value in record.items():
                if not isinstance(name, str) or not name.strip():
                    raise ShapeError("Record keys must be nonempty column names.")
                if name not in known:
                    if explicit:
                        raise ShapeError(f"Record contains undeclared column: {name!r}")
                    limits.check(len(collected) + 1, len(names) + 1)
                    names.append(name)
                    known.add(name)
                current[name] = as_cell(value)
            collected.append(current)
        return cls(names, ([record.get(name) for name in names] for record in collected), limits=limits)

    @classmethod
    def from_csv(
        cls, text: str, *, delimiter: str = ",", formulas: bool = False,
        limits: Limits | None = None,
    ) -> Table:
        """Parse CSV text; fields remain literal strings unless formula mode is explicit."""
        from .serialization import from_csv
        return from_csv(text, delimiter=delimiter, formulas=formulas, limits=limits)

    @classmethod
    def read_csv(
        cls, path: FilePath, *, delimiter: str = ",", formulas: bool = False,
        limits: Limits | None = None,
    ) -> Table:
        selected = DEFAULT_LIMITS if limits is None else limits
        return cls.from_csv(read_text(path, selected), delimiter=delimiter, formulas=formulas, limits=selected)

    @property
    def _root(self) -> Table:
        return self

    @property
    def columns(self) -> tuple[str, ...]:
        return self._columns

    @property
    def _row_positions(self) -> range:
        return range(len(self._rows))

    @property
    def _column_positions(self) -> range:
        return range(len(self._columns))

    def set(self, address: str, value: CellInput) -> None:
        row, column = self._position(address)
        if row == 0:
            raise AddressError("Table headers cannot be edited as cells.")
        cell = as_cell(value)
        index = row - 1
        changed = (*self._rows[index][:column], cell, *self._rows[index][column + 1:])
        self._rows = (*self._rows[:index], changed, *self._rows[index + 1:])

    def set_formula(self, address: str, formula: str, *, cached_value: Scalar = None) -> None:
        self.set(address, Cell(cached_value, formula=formula))

    def add_column(
        self, name: str, values: Iterable[CellInput] | Callable[[Row], CellInput] | None = None,
    ) -> None:
        """Append blanks, an iterable or per-row results after validating every value."""
        names = _columns((*self._columns, name), self._limits)
        self._limits.check(len(self), len(names))
        if values is None:
            cells = [Cell() for _ in self._rows]
        elif callable(values):
            cells = [as_cell(values(row)) for row in self]
        else:
            if isinstance(values, (str, bytes)):
                raise ShapeError("Column values must be a sequence of cells, not text.")
            cells = []
            for value in values:
                if len(cells) >= len(self):
                    raise ShapeError("A new column needs exactly one value per row.")
                cells.append(as_cell(value))
            if len(cells) != len(self):
                raise ShapeError("A new column needs exactly one value per row.")
        changed = tuple((*row, cell) for row, cell in zip(self._rows, cells, strict=True))
        self._rows, self._columns = changed, names
        self._column_lookup = {name: index for index, name in enumerate(names)}

    def to_sheet(self, *, name: str = "Sheet1") -> Sheet:
        return Sheet((self._columns, *self._rows), name=name, width=len(self.columns), limits=self._limits)


class TableView(_Tabular):
    """Fixed source membership with live values; selections never move formulas.

    Create views with ``where``, ``select`` and ``sort_by``. Materialize using
    ``to_table`` when independent values are required.
    """

    def __init__(self, source: Table, rows: Iterable[int], columns: Iterable[int]) -> None:
        if not isinstance(source, Table):
            raise ShapeError("A view requires a source Table.")

        def positions(values, size, maximum):
            result = []
            for value in values:
                if len(result) >= maximum:
                    raise ShapeError("View dimensions exceed the configured limits.")
                if type(value) is not int or not 0 <= value < size:
                    raise ShapeError("View positions must be valid zero-based source indices.")
                result.append(value)
            return tuple(result)

        self._source = source
        self._selected_rows = positions(rows, len(source), source._limits.max_rows)
        self._selected_columns = positions(columns, len(source.columns), source._limits.max_columns)
        source._limits.check(len(self._selected_rows), len(self._selected_columns))
        if len(set(self._selected_columns)) != len(self._selected_columns):
            raise ShapeError("View columns must be unique.")
        self._names = tuple(source.columns[index] for index in self._selected_columns)
        self._column_lookup = dict(zip(self._names, self._selected_columns, strict=True))

    @property
    def columns(self) -> tuple[str, ...]:
        return self._names

    @property
    def _root(self) -> Table:
        return self._source

    @property
    def _row_positions(self) -> tuple[int, ...]:
        return self._selected_rows

    @property
    def _column_positions(self) -> tuple[int, ...]:
        return self._selected_columns
