"""Explicit optional binding to caller-registered Backpack application models.

Importing this module requires Backpack. Neither construction nor close opens,
initializes or closes storage. Async bindings use its public owned worker API.
"""

import base64
from dataclasses import fields, is_dataclass, replace
import hashlib
import json
import math
import re
import types
from typing import Union, get_args, get_origin, get_type_hints

from backpack_store import Order, TextSearch

from .core import Cell
from .errors import SpreadsheetError
from .sources import ID, SourceColumn, SourceRow, TableSnapshot

KINDS = {str: "text", bool: "boolean", int: "integer", float: "number"}


class BackpackSource:
    """A trusted registered handle with explicit model/field capabilities.

    Column IDs are dataclass field IDs, independent of physical SQL names.
    Persisted source addresses use those IDs, never synthetic A1 positions.
    Storage errors, including stale revisions, retain their public classes.
    """

    def __init__(self, model, *, model_type, key_field, table_id, schema_version, columns, max_work=1000000):
        if (not isinstance(model_type, type) or not is_dataclass(model_type)
                or any(type(v) is not str or not ID.fullmatch(v) for v in (table_id, schema_version))
                or type(max_work) is not int or not 1 <= max_work <= 1000000
                or type(columns) not in (tuple, list) or not 1 <= len(columns) <= 64
                or any(not isinstance(c, SourceColumn) for c in columns)
                or len({c.id for c in columns}) != len(columns)):
            raise SpreadsheetError("Declare a bounded registered scalar source.")
        hints = get_type_hints(model_type)
        self._types = {}
        for field in fields(model_type):
            annotation = hints[field.name]
            args = get_args(annotation) if get_origin(annotation) in (Union, types.UnionType) else (annotation,)
            scalar = tuple(arg for arg in args if arg is not type(None))
            if not field.init or len(scalar) != 1 or scalar[0] not in KINDS:
                raise SpreadsheetError("Persisted sources require flat portable scalar fields.")
            self._types[field.name] = scalar[0], type(None) in args
        if type(key_field) is not str or self._types.get(key_field) != (str, False):
            raise SpreadsheetError("Declare the registered non-null text key field.")
        for column in columns:
            declared = self._types.get(column.id)
            if (declared is None or column.type != KINDS[declared[0]] or column.nullable != declared[1]
                    or column.id == key_field and column.writable):
                raise SpreadsheetError("Columns must match registered fields; keys are immutable.")
        if any(not callable(getattr(model, name, None)) for name in ("find", "get", "update")):
            raise SpreadsheetError("Select a registered application model handle.")
        self._model, self._model_type, self._key_field = model, model_type, key_field
        self.table_id, self.schema_version, self.columns = table_id, schema_version, tuple(columns)
        self._by_id = {c.id: c for c in columns}
        self._max_work = max_work

    def close(self):
        """Release this binding. The caller retains ownership of the connection."""
        self._model = None

    def _live(self):
        if self._model is None:
            raise SpreadsheetError("Source is closed.")
        return self._model

    def _check(self, field, value):
        scalar, nullable = self._types[field]
        if value is None and nullable:
            return
        if (type(value) is not scalar or scalar is int and abs(value) > 9007199254740991
                or scalar is float and not math.isfinite(value)):
            raise SpreadsheetError("Value does not match the persisted scalar profile.")
        if scalar is str:
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise SpreadsheetError("Persisted text requires valid Unicode.") from None

    def _row(self, row, selected):
        return SourceRow(row.key, row.revision, tuple(Cell(getattr(row.value, name)) for name in selected), tuple(selected))

    def query(self, *, columns=None, order=(), search=None, limit=50, cursor=None, generation=0):
        model = self._live()
        if (type(limit) is not int or not 1 <= limit <= 1000
                or type(generation) is not int or not 0 <= generation <= 9007199254740991):
            raise SpreadsheetError("Invalid page limit or generation.")
        if columns is None:
            columns = [c.id for c in self.columns if c.visible]
        if (type(columns) not in (tuple, list) or len(columns) > 64
                or any(type(c) is not str or c not in self._by_id or not self._by_id[c].visible for c in columns)
                or len(set(columns)) != len(columns) or limit * len(columns) > 16000):
            raise SpreadsheetError("Invalid visible projection.")
        if type(order) not in (tuple, list) or len(order) > 3:
            raise SpreadsheetError("Select at most three sort fields.")
        prepared, seen = [], set()
        for item in order:
            if (type(item) not in (tuple, list) or len(item) != 2 or type(item[0]) is not str
                    or item[0] not in self._by_id or not self._by_id[item[0]].sortable
                    or not self._by_id[item[0]].visible or type(item[1]) is not bool or item[0] in seen):
                raise SpreadsheetError("Invalid source sort.")
            prepared.append(Order(*item))
            seen.add(item[0])
        descriptor_search, prepared_search = None, None
        if search is not None:
            if type(search) is not dict or search.keys() != {"fields", "term"}:
                raise SpreadsheetError("Invalid literal search.")
            names, term = search["fields"], search["term"]
            if (type(names) not in (tuple, list) or not 1 <= len(names) <= 8
                    or any(type(n) is not str or n not in self._by_id or not self._by_id[n].searchable for n in names)
                    or len(set(names)) != len(names) or type(term) is not str or len(term) > 256):
                raise SpreadsheetError("Invalid literal search.")
            try:
                term.encode("utf-8")
            except UnicodeError:
                raise SpreadsheetError("Search text requires valid Unicode.") from None
            if term:
                descriptor_search = [sorted(names), term]
                prepared_search = TextSearch(tuple(names), term)
        descriptor = [self.table_id, self.schema_version, list(columns), list(order), descriptor_search]
        fingerprint = hashlib.sha256(json.dumps(descriptor, sort_keys=True).encode()).hexdigest()
        after = None
        if cursor is not None:
            try:
                if type(cursor) is not str or not 1 <= len(cursor) <= 16384:
                    raise ValueError
                data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if type(data) is not list or len(data) != 2 or data[0] != fingerprint or type(data[1]) is not str:
                    raise ValueError
                after = data[1]
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise SpreadsheetError("Cursor does not match source/query.") from None
        page = model.find(order=tuple(prepared), search=prepared_search, limit=limit, cursor=after, max_work=self._max_work)
        continuation = base64.urlsafe_b64encode(json.dumps([fingerprint, page.next_cursor]).encode()).decode() if page.next_cursor else None
        if continuation is not None and len(continuation) > 16384:
            raise SpreadsheetError("Source cursor exceeds the bound.")
        return TableSnapshot(self.table_id, self.schema_version, tuple(self._by_id[n] for n in columns),
                             tuple(self._row(row, columns) for row in page.rows), generation, continuation)

    def get(self, row_key):
        """Fresh authoritative row for explicit uncertain-save reconciliation."""
        row = self._live().get(row_key)
        return self._row(row, [c.id for c in self.columns if c.visible])

    def edit(self, row_key, column_id, value, *, expected_revision):
        model = self._live()
        if (type(row_key) is not str or not ID.fullmatch(row_key)
                or type(expected_revision) is not str or not re.fullmatch(r"[1-9][0-9]{0,18}", expected_revision, re.ASCII)
                or int(expected_revision) > 9223372036854775807):
            raise SpreadsheetError("A durable key and expected row revision are required.")
        column = self._by_id.get(column_id) if type(column_id) is str else None
        if column is None or not column.writable or column_id == self._key_field:
            raise SpreadsheetError("Column is undeclared or read-only.")
        self._check(column_id, value)
        def transform(current):
            proposed = replace(current, **{column_id: value})
            if type(proposed) is not self._model_type or getattr(proposed, self._key_field) != row_key:
                raise SpreadsheetError("The registered model and durable key must be preserved.")
            for name in self._types:
                self._check(name, getattr(proposed, name))
            return proposed
        row = model.update(row_key, expected_revision=expected_revision, transform=transform)
        return self._row(row, [c.id for c in self.columns if c.visible])


class AsyncBackpackSource:
    """Borrow an AsyncApplicationStore configured with a worker-owned source.

    The configuration callback returns BackpackSource (or select extracts it
    from caller state). DispatchedCancellation and its receipt propagate intact;
    await the receipt or get a fresh row before retrying an uncertain write.
    """

    def __init__(self, backend, *, select=lambda state: state):
        self._backend, self._select = backend, select

    async def _run(self, operation):
        if self._backend is None:
            raise SpreadsheetError("Source is closed.")
        return await self._backend.run(lambda state: operation(self._select(state)))

    async def query(self, **query):
        return await self._run(lambda source: source.query(**query))

    async def get(self, row_key):
        return await self._run(lambda source: source.get(row_key))

    async def edit(self, row_key, column_id, value, *, expected_revision):
        return await self._run(lambda source: source.edit(row_key, column_id, value, expected_revision=expected_revision))

    async def aclose(self):
        self._backend = None
