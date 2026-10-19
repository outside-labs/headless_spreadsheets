"""Strict native JSON schema v1 and deliberately text-oriented CSV interchange."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .core import DEFAULT_LIMITS, Cell, Limits, Scalar, Sheet, Workbook
from .errors import FormatError, SpreadsheetError
from .file_io import check_text
from .table import Table, TableView, _Tabular

_FORMAT = "headless-spreadsheets"
_VERSION = 1


def scalar_text(value: Scalar) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _value_data(cell: Cell) -> dict[str, Any]:
    value = cell.value
    if cell.data_type in {"date", "datetime"}:
        value = value.isoformat()
    elif cell.data_type == "decimal":
        value = str(value)
    return {"type": cell.data_type, "value": value}


def _cell_data(cell: Cell) -> dict[str, Any]:
    return {
        "value": _value_data(cell), "formula": cell.formula,
        "number_format": cell.number_format, "cache_status": cell.cache_status,
    }


def _sheet_data(sheet: Sheet) -> dict[str, Any]:
    return {"name": sheet.name, "width": sheet.shape[1], "rows": [[_cell_data(cell) for cell in row] for row in sheet.rows]}


def dumps(document: Table | Sheet | Workbook, *, indent: int | None = 2) -> str:
    if indent is not None and (type(indent) is not int or not 0 <= indent <= 8):
        raise FormatError("JSON indent must be None or an integer from 0 to 8.")
    if isinstance(document, Table):
        kind = "table"
        data = {"columns": list(document.columns), "rows": [[_cell_data(cell) for cell in row] for row in document._rows]}
    elif isinstance(document, Sheet):
        kind, data = "sheet", _sheet_data(document)
    elif isinstance(document, Workbook):
        # Recheck aggregate bounds before producing a persistent representation.
        Workbook(document, limits=document._limits)
        kind, data = "workbook", {"sheets": [_sheet_data(sheet) for sheet in document]}
    else:
        raise FormatError("Native JSON requires an original Table, Sheet or Workbook.")
    try:
        text = json.dumps(
            {"format": _FORMAT, "schema_version": _VERSION, "kind": kind, "data": data},
            ensure_ascii=False, allow_nan=False, indent=indent,
        ) + "\n"
    except (ValueError, OverflowError) as error:
        raise FormatError("A cell cannot be represented in native JSON.") from error
    check_text(text, document._limits)
    return text


def _fields(value: Any, expected: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise FormatError(f"Expected exactly these object fields: {', '.join(sorted(expected))}.")
    return value


def _decode_value(value: Any) -> Scalar:
    data = _fields(value, {"type", "value"})
    kind, scalar = data["type"], data["value"]
    basic = {"blank": type(None), "boolean": bool, "integer": int, "number": float, "text": str}
    if not isinstance(kind, str):
        raise FormatError("A value type must be a string.")
    if kind in basic and type(scalar) is basic[kind]:
        return scalar
    if type(scalar) is str:
        if kind == "decimal":
            return Decimal(scalar)
        if kind == "date":
            return date.fromisoformat(scalar)
        if kind == "datetime":
            return datetime.fromisoformat(scalar)
    raise FormatError(f"Invalid scalar for native type {kind!r}.")


def _decode_cell(value: Any) -> Cell:
    data = _fields(value, {"value", "formula", "number_format", "cache_status"})
    cell = Cell(_decode_value(data["value"]), formula=data["formula"], number_format=data["number_format"])
    if data["cache_status"] != cell.cache_status:
        raise FormatError("A formula cache cannot be marked fresh or contradict its value.")
    return cell


def _decode_rows(rows: Any, width: int, limits: Limits) -> list[list[Cell]]:
    if type(rows) is not list or type(width) is not int or width < 0:
        raise FormatError("Expected rows and a nonnegative integer width.")
    limits.check(len(rows), width)
    result = []
    for row in rows:
        if type(row) is not list or len(row) != width:
            raise FormatError("Native rows must match the declared width.")
        result.append([_decode_cell(cell) for cell in row])
    return result


def _decode_sheet(data: Any, limits: Limits) -> Sheet:
    data = _fields(data, {"name", "width", "rows"})
    return Sheet(_decode_rows(data["rows"], data["width"], limits), name=data["name"], width=data["width"], limits=limits)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise FormatError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise FormatError("Native JSON numbers must be finite.")


def loads(text: str, *, limits: Limits | None = None) -> Table | Sheet | Workbook:
    selected = DEFAULT_LIMITS if limits is None else limits
    check_text(text, selected)
    try:
        document = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
        document = _fields(document, {"format", "schema_version", "kind", "data"})
        if document["format"] != _FORMAT or type(document["schema_version"]) is not int or document["schema_version"] != _VERSION:
            raise FormatError("Unsupported native JSON format or schema version.")
        data = document["data"]
        if document["kind"] == "table":
            data = _fields(data, {"columns", "rows"})
            if type(data["columns"]) is not list:
                raise FormatError("Expected a list of column labels.")
            rows = _decode_rows(data["rows"], len(data["columns"]), selected)
            return Table(data["columns"], rows, limits=selected)
        if document["kind"] == "sheet":
            return _decode_sheet(data, selected)
        if document["kind"] == "workbook":
            data = _fields(data, {"sheets"})
            if type(data["sheets"]) is not list or len(data["sheets"]) > selected.max_sheets:
                raise FormatError("Expected a bounded list of sheets.")
            return Workbook((_decode_sheet(sheet, selected) for sheet in data["sheets"]), limits=selected)
        raise FormatError("Unknown native JSON document kind.")
    except FormatError:
        raise
    except (ValueError, TypeError, ArithmeticError, RecursionError) as error:
        raise FormatError(f"Invalid native JSON: {error}") from error


def _delimiter(delimiter: str) -> None:
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n\0"':
        raise FormatError("A delimiter must be one character other than a newline, NUL or quote.")


def _csv_text(text: str, escape_formulas: bool) -> str:
    if escape_formulas and text and (
        text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n"))
    ):
        return "'" + text
    return text


def to_csv(
    table: _Tabular, *, delimiter: str = ",", formulas: bool = False, escape_formulas: bool = True,
) -> str:
    _delimiter(delimiter)
    if type(formulas) is not bool or type(escape_formulas) is not bool:
        raise FormatError("CSV formula options must be Boolean.")
    if formulas and isinstance(table, TableView):
        raise FormatError("Formula CSV export requires the original table so coordinates stay in place.")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow([_csv_text(name, escape_formulas) for name in table.columns])
    for row in table:
        fields = []
        for name in table.columns:
            cell = row.cell(name)
            if formulas and cell.formula is not None:
                fields.append(cell.formula)
            else:
                value = scalar_text(cell.value)
                fields.append(_csv_text(value, escape_formulas) if type(cell.value) is str else value)
        writer.writerow(fields)
    return stream.getvalue()


def from_csv(
    text: str, *, delimiter: str = ",", formulas: bool = False, limits: Limits | None = None,
) -> Table:
    selected = DEFAULT_LIMITS if limits is None else limits
    check_text(text, selected)
    _delimiter(delimiter)
    if type(formulas) is not bool:
        raise FormatError("CSV formula interpretation must be Boolean.")
    try:
        reader = csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline=""), delimiter=delimiter, strict=True)
        columns = next(reader, [])
        def rows():
            for row in reader:
                if len(row) != len(columns):
                    raise FormatError("CSV rows must match the header width.")
                yield [Cell(formula=value) if formulas and value.startswith("=") else Cell(value) for value in row]
        return Table(columns, rows(), limits=selected)
    except FormatError:
        raise
    except (csv.Error, SpreadsheetError) as error:
        raise FormatError(f"Invalid CSV: {error}") from error
