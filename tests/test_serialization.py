"""Native fidelity, intentionally lossy CSV, bounded reads and atomic writes."""

import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from headless_spreadsheets import Cell, FormatError, Limits, Sheet, Table, Workbook


class NativeJSONTests(unittest.TestCase):
    def test_all_types_formula_cache_and_hints_round_trip(self):
        values = [
            None, "", False, 0, -12345678901234567890, -0.0, 1.25,
            "雪\n|<x>", Decimal("-0.1200"), date(2026, 10, 19),
            datetime(2026, 10, 19, 1, 2, 3, 456, tzinfo=timezone(timedelta(hours=-7))),
        ]
        cells = [Cell(value) for value in values]
        cells.extend([Cell(12, formula="=VENDOR.UNKNOWN(A2)", number_format="0.00"), Cell(formula="=A2")])
        original = Table([f"c{i}" for i in range(len(cells))], [cells])
        restored = Table.from_json(original.to_json())
        for i, expected in enumerate(cells):
            actual = restored.rows[0].cell(f"c{i}")
            self.assertEqual(actual, expected)
            self.assertIs(type(actual.value), type(expected.value))
            if isinstance(expected.value, Decimal):
                self.assertEqual(actual.value.as_tuple(), expected.value.as_tuple())
        self.assertEqual(restored.to_json(), original.to_json())

    def test_workbook_order_sheet_names_and_empty_width_round_trip(self):
        book = Workbook([Sheet([["x", Cell(2, formula="=1+1")]], name="First"), Sheet(name="Empty", width=4)])
        restored = Workbook.from_json(book.to_json())
        self.assertEqual(restored.sheet_names, ("First", "Empty"))
        self.assertEqual(restored["First"].rows, book["First"].rows)
        self.assertEqual(restored["Empty"].shape, (0, 4))
        self.assertEqual(Sheet.from_json(book["First"].to_json()).rows, book["First"].rows)
        with self.assertRaises(FormatError):
            Table.from_json(book.to_json())
        with self.assertRaises(FormatError):
            Workbook.from_json(book.to_json(), limits=Limits(max_cells=1))

    def test_duplicate_unknown_and_malformed_native_json_are_rejected(self):
        baseline = json.loads(Table(["a"], [[1]]).to_json())
        invalid = []
        for key, value in (("schema_version", 2), ("schema_version", True), ("format", "other"), ("kind", "unknown")):
            document = copy.deepcopy(baseline)
            document[key] = value
            invalid.append(json.dumps(document))
        for fields in (
            {"cache_status": "fresh"}, {"formula": "not a formula"}, {"number_format": []},
            {"value": {"type": "integer", "value": True}},
            {"value": {"type": "number", "value": 1}},
            {"value": {"type": "decimal", "value": "NaN"}},
            {"value": {"type": "date", "value": "invalid"}},
            {"value": {"type": [], "value": 1}},
        ):
            document = copy.deepcopy(baseline)
            document["data"]["rows"][0][0].update(fields)
            invalid.append(json.dumps(document))
        document = copy.deepcopy(baseline)
        document["data"]["extra"] = True
        invalid.append(json.dumps(document))
        document = copy.deepcopy(baseline)
        document["data"]["rows"][0].append(document["data"]["rows"][0][0])
        invalid.append(json.dumps(document))
        invalid.extend(['{"x": 1, "x": 2}', '[NaN]', '[Infinity]', '[' * 2000 + ']' * 2000, '', '{}'])
        for text in invalid:
            with self.subTest(text=text[:100]), self.assertRaises(FormatError):
                Table.from_json(text)

    def test_byte_dimension_limits_and_indent_options(self):
        text = Table(["a", "b"], [[1, 2], [3, 4]]).to_json()
        for limits in (Limits(max_rows=1), Limits(max_columns=1), Limits(max_cells=3), Limits(max_input_bytes=20)):
            with self.assertRaises(FormatError):
                Table.from_json(text, limits=limits)
        with self.assertRaises(FormatError):
            Table.from_json("雪" * 10, limits=Limits(max_input_bytes=20))
        for indent in ("  ", True, -1, 9):
            with self.assertRaises(FormatError):
                Table().to_json(indent=indent)
        self.assertEqual(Table.from_json(Table().to_json(indent=None)).shape, (0, 0))


class CSVTests(unittest.TestCase):
    def test_quotes_unicode_newlines_and_tsv_remain_text(self):
        table = Table(["item", "value"], [['雪, "book"\nnext', 12], ["pen", None]])
        text = table.to_csv(escape_formulas=False)
        restored = Table.from_csv(text)
        self.assertEqual(restored.to_records(), [{"item": '雪, "book"\nnext', "value": "12"}, {"item": "pen", "value": ""}])
        self.assertEqual(Table.from_csv(table.to_csv(delimiter="\t"), delimiter="\t").columns, table.columns)
        self.assertEqual(Table.from_csv("\ufeffa,b\r\n1,2\r\n").to_records(), [{"a": "1", "b": "2"}])

    def test_formula_modes_and_active_text_are_explicit(self):
        table = Table(["=header", "formula", "negative"], [["  =1+1", Cell(4, formula="=2+2"), -2]])
        self.assertEqual(Table.from_csv(table.to_csv()).to_records(), [{"'=header": "'  =1+1", "formula": "4", "negative": "-2"}])
        formula_csv = table.to_csv(formulas=True, escape_formulas=False)
        literal = Table.from_csv(formula_csv)
        self.assertEqual(literal.cell("B2"), Cell("=2+2"))
        interpreted = Table.from_csv(formula_csv, formulas=True)
        self.assertEqual(interpreted.cell("B2"), Cell(formula="=2+2"))
        for dangerous in ("=1", "+1", "-1", "@SUM(A1)", "\ttext", "\rtext", "\ntext"):
            result = Table.from_csv(Table(["a"], [[dangerous]]).to_csv()).cell("A2").value
            self.assertEqual(result, "'" + dangerous)
        with self.assertRaises(FormatError):
            table.select("formula").to_csv(formulas=True)

    def test_csv_errors_bounds_and_empty_shapes(self):
        for text in ('a,a\n1,2\n', 'a,b\n1\n', 'a\n"unterminated', 'a\n=\n'):
            with self.subTest(text=text), self.assertRaises(FormatError):
                Table.from_csv(text, formulas=True)
        with self.assertRaises(FormatError):
            Table.from_csv("a\n1\n2\n", limits=Limits(max_rows=1))
        with self.assertRaises(FormatError):
            Table.from_csv("a\n" + "x" * 10, limits=Limits(max_input_bytes=10))
        for delimiter in ("", "ab", "\n", '"'):
            with self.assertRaises(FormatError):
                Table.from_csv("a", delimiter=delimiter)
        self.assertEqual(Table.from_csv("").shape, (0, 0))
        self.assertEqual(Table.from_csv("a,b\r\n").shape, (0, 2))
        self.assertEqual(Table.from_csv(Table([], [[], []]).to_csv()).shape, (2, 0))


class FileTests(unittest.TestCase):
    def test_utf8_destinations_and_explicit_path_readers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = Table(["name"], [["雪"]])
            csv_path, json_path = root / "data.csv", root / "data.json"
            self.assertEqual(table.to_csv(csv_path), csv_path.read_bytes().decode())
            self.assertEqual(table.to_json(json_path), json_path.read_text(encoding="utf-8"))
            self.assertEqual(Table.read_csv(csv_path).to_records(), table.to_records())
            self.assertEqual(Table.read_json(json_path).to_records(), table.to_records())
            with self.assertRaises(FormatError):
                Table.read_json(json_path, limits=Limits(max_input_bytes=10))
            csv_path.write_bytes(b"\xff")
            with self.assertRaises(FormatError):
                Table.read_csv(csv_path)

    def test_failed_atomic_replacement_preserves_destination_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "data.json"
            destination.write_text("original", encoding="utf-8")
            with patch("headless_spreadsheets.file_io.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    Table(["a"], [[1]]).to_json(destination)
            self.assertEqual(destination.read_text(), "original")
            self.assertEqual(list(Path(directory).iterdir()), [destination])
