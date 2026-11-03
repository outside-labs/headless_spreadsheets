"""Bounded read-only sources with stable instance identity and detached cells."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import re

from .core import Cell, column_name
from .errors import SpreadsheetError
from .table import Table, TableView

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class SourceColumn:
    id: str
    label: str
    type: str = "native"
    nullable: bool = True
    visible: bool = True
    sortable: bool = True
    searchable: bool = False
    writable: bool = False

    def __post_init__(self):
        if type(self.id) is not str or not ID.fullmatch(self.id) or type(self.label) is not str:
            raise SpreadsheetError("Invalid source column identity.")
        if self.type not in {"native", "text", "boolean", "integer", "number"}:
            raise SpreadsheetError("Unsupported source column type.")
        if any(type(getattr(self, name)) is not bool for name in ("nullable", "visible", "sortable", "searchable", "writable")):
            raise SpreadsheetError("Capabilities must be exact booleans.")
        if (not self.visible and (self.sortable or self.searchable or self.writable)) or (self.searchable and self.type != "text"):
            raise SpreadsheetError("Invalid source capabilities.")


@dataclass(frozen=True, slots=True)
class SourceRow:
    key: str
    revision: str | None
    cells: tuple[Cell, ...]
    source_addresses: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "cells", tuple(self.cells))
        object.__setattr__(self, "source_addresses", tuple(self.source_addresses))
        if (type(self.key) is not str or not ID.fullmatch(self.key)
                or len(self.cells) != len(self.source_addresses)
                or any(not isinstance(cell, Cell) for cell in self.cells)):
            raise SpreadsheetError("Invalid source row.")
        if self.revision is not None and (type(self.revision) is not str
                or not re.fullmatch(r"[1-9][0-9]{0,18}", self.revision, re.ASCII)
                or int(self.revision) > 9223372036854775807):
            raise SpreadsheetError("Invalid source revision.")


@dataclass(frozen=True, slots=True)
class TableSnapshot:
    table_id: str
    schema_version: str
    columns: tuple[SourceColumn, ...]
    rows: tuple[SourceRow, ...]
    generation: int = 0
    next_cursor: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "rows", tuple(self.rows))
        if (type(self.table_id) is not str or not ID.fullmatch(self.table_id)
                or type(self.schema_version) is not str or not self.schema_version
                or type(self.generation) is not int or self.generation < 0):
            raise SpreadsheetError("Invalid snapshot identity/generation.")
        if (len(self.columns) > 64 or len(self.rows) > 1000 or len(self.columns) * len(self.rows) > 16000
                or any(not isinstance(column, SourceColumn) or not column.visible for column in self.columns)
                or len({column.id for column in self.columns}) != len(self.columns)
                or any(not isinstance(row, SourceRow) or len(row.cells) != len(self.columns) for row in self.rows)
                or len({row.key for row in self.rows}) != len(self.rows)):
            raise SpreadsheetError("Invalid or unbounded snapshot shape.")
        if self.next_cursor is not None and (type(self.next_cursor) is not str or not 1 <= len(self.next_cursor) <= 16384):
            raise SpreadsheetError("Invalid snapshot cursor.")


class TableSource:
    """A caller-owned Table/live-view binding; queries capture immutable cells.

    Keys survive new bindings and views of the same Table, not reconstruction
    or process restart. No writes are exposed. Close releases this binding only.
    """

    def __init__(self, table: Table | TableView, *, columns=None):
        if not isinstance(table, (Table, TableView)):
            raise SpreadsheetError("A source requires Table or TableView.")
        if table.shape[0] > 100000 or table.shape[1] > 128 or table.shape[0] * table.shape[1] > 1000000:
            raise SpreadsheetError("Source exceeds the complete local query budget.")
        if len(set(table._row_positions)) != len(table._row_positions):
            raise SpreadsheetError("A source requires unique row membership.")
        self._table = table
        self.table_id = table._root._source_id
        self.schema_version = str(len(table._root.columns))
        positions = tuple(table._column_positions)
        if columns is None:
            result = []
            for name, position in zip(table.columns, positions, strict=True):
                text = all(table._root._rows[row][position].value is None or type(table._root._rows[row][position].value) is str
                           for row in table._row_positions)
                result.append(SourceColumn(f"c{position + 1}", name, "text" if text else "native", searchable=text))
            columns = tuple(result)
        self.columns = tuple(columns)
        if (len(self.columns) != len(positions) or any(not isinstance(column, SourceColumn) or column.writable for column in self.columns)
                or len({column.id for column in self.columns}) != len(self.columns)):
            raise SpreadsheetError("Declare one distinct source column per selected column.")
        self._positions = dict(zip((column.id for column in self.columns), positions, strict=True))
        self._closed = False

    def close(self):
        self._closed = True
        self._table = None

    def query(self, *, columns=None, order=(), search=None, limit=50, cursor=None, generation=0):
        if self._closed:
            raise SpreadsheetError("Source is closed.")
        if type(limit) is not int or not 1 <= limit <= 1000 or type(generation) is not int or generation < 0:
            raise SpreadsheetError("Invalid page limit or generation.")
        declared = {column.id: column for column in self.columns}
        if columns is not None and (type(columns) not in (tuple, list) or any(type(name) is not str for name in columns)):
            raise SpreadsheetError("Projection requires a sequence of column IDs.")
        selected = tuple(c.id for c in self.columns if c.visible) if columns is None else tuple(columns)
        if (len(selected) > 64 or len(set(selected)) != len(selected)
                or any(name not in declared or not declared[name].visible for name in selected)
                or limit * len(selected) > 16000):
            raise SpreadsheetError("Invalid or unbounded visible projection.")
        if type(order) not in (tuple, list) or len(order) > 3:
            raise SpreadsheetError("Select at most three sort fields.")
        prepared = []
        for item in order:
            if (type(item) not in (tuple, list) or len(item) != 2 or type(item[0]) is not str or item[0] not in declared
                    or not declared[item[0]].visible or not declared[item[0]].sortable
                    or type(item[1]) is not bool or item[0] in [name for name, _ in prepared]):
                raise SpreadsheetError("Invalid source sort.")
            prepared.append(tuple(item))
        term, search_fields = "", ()
        if search is not None:
            if type(search) is not dict or set(search) != {"fields", "term"}:
                raise SpreadsheetError("Invalid literal search.")
            term, search_fields = search["term"], search["fields"]
            if (type(term) is not str or len(term) > 256 or type(search_fields) not in (tuple, list)
                    or not 1 <= len(search_fields) <= 8 or any(type(name) is not str for name in search_fields)
                    or len(set(search_fields)) != len(search_fields)
                    or any(name not in declared or not declared[name].searchable for name in search_fields)):
                raise SpreadsheetError("Invalid literal search.")
            search_fields = tuple(sorted(search_fields)) if term else ()
        table = self._table
        descriptor = [self.table_id, self.schema_version, list(table._row_positions), self._positions,
                      selected, prepared, term, search_fields]
        fingerprint = hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()
        offset = 0
        if cursor is not None:
            try:
                if type(cursor) is not str or not 1 <= len(cursor) <= 16384:
                    raise ValueError
                data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if (type(data) is not list or len(data) != 2 or data[0] != fingerprint
                        or type(data[1]) is not int or not 0 <= data[1] <= 100000):
                    raise ValueError
                offset = data[1]
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise SpreadsheetError("Cursor does not match source/query.") from None
        # Capture the immutable root tuple once, then evaluate a detached page.
        root_rows = table._root._rows
        indices = sorted(table._row_positions) if prepared else list(table._row_positions)
        if term:
            indices = [row for row in indices if any(type(value := root_rows[row][self._positions[name]].value) is str and term in value
                                                     for name in search_fields)]
        try:
            for name, descending in reversed(prepared):
                position = self._positions[name]
                present = [row for row in indices if root_rows[row][position].value is not None]
                missing = [row for row in indices if root_rows[row][position].value is None]
                present.sort(key=lambda row: root_rows[row][position].value, reverse=descending)
                indices = present + missing
        except TypeError:
            raise SpreadsheetError("Source sort values are not comparable.") from None
        positions = [self._positions[name] for name in selected]
        rows = tuple(SourceRow(f"r{row + 1}", None, tuple(root_rows[row][position] for position in positions),
                               tuple(f"{column_name(position)}{row + 2}" for position in positions))
                     for row in indices[offset:offset + limit])
        next_cursor = None
        if offset + limit < len(indices):
            next_cursor = base64.urlsafe_b64encode(json.dumps([fingerprint, offset + limit]).encode()).decode()
        return TableSnapshot(self.table_id, self.schema_version, tuple(declared[name] for name in selected), rows, generation, next_cursor)
