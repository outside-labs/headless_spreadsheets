"""Cells preserve expressions; grids validate shape before accepting edits."""

import dataclasses
import itertools
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from headless_spreadsheets import (
    AddressError, Cell, Limits, ShapeError, Sheet, SpreadsheetError, Workbook,
    column_name, split_address,
)


class CellTests(unittest.TestCase):
    def test_scalar_types_remain_distinct(self):
        cases = [
            (None, "blank"), (False, "boolean"), (0, "integer"), (1.5, "number"),
            ("=SUM(A1:A2)", "text"), (Decimal("1.20"), "decimal"),
            (date(2026, 10, 19), "date"), (datetime.now(timezone.utc), "datetime"),
        ]
        for value, kind in cases:
            with self.subTest(kind=kind):
                cell = Cell(value)
                self.assertIs(cell.value, value)
                self.assertEqual(cell.data_type, kind)
                self.assertEqual(cell.cache_status, "value")
                self.assertIsNone(cell.formula)

    def test_formulas_are_opaque_and_results_unverified(self):
        cell = Cell(36, formula="=UNSUPPORTED(A1)", number_format="0.00")
        self.assertEqual(cell.formula, "=UNSUPPORTED(A1)")
        self.assertEqual(cell.cache_status, "stale")
        self.assertEqual(cell.number_format, "0.00")
        self.assertEqual(Cell(formula="=SUM(A1:A2)").cache_status, "missing")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cell.value = 10

    def test_invalid_values_and_formulas_are_rejected(self):
        for value in ([], {}, object(), float("nan"), float("inf"), Decimal("NaN")):
            with self.subTest(value=type(value).__name__), self.assertRaises(SpreadsheetError):
                Cell(value)
        for formula in ("", "A1", "=  ", 1):
            with self.subTest(formula=formula), self.assertRaises(SpreadsheetError):
                Cell(formula=formula)
        with self.assertRaises(SpreadsheetError):
            Cell(number_format=7)


class GridTests(unittest.TestCase):
    def test_a1_coordinates_and_bounds(self):
        sheet = Sheet([range(28), range(28)])
        self.assertEqual(sheet.cell("ab2").value, 27)
        for index in (0, 25, 26, 27, 701, 702, 16383):
            self.assertEqual(split_address(column_name(index) + "9"), (8, index))
        for address in ("A0", "A01", "$A$1", " A1", "A1:B2", "1A", "Ａ1", "A3", "AC1", 1):
            with self.subTest(address=address), self.assertRaises(AddressError):
                sheet.cell(address)

    def test_empty_shapes_and_rectangular_rows(self):
        self.assertEqual(Sheet().shape, (0, 0))
        self.assertEqual(Sheet(width=3).shape, (0, 3))
        self.assertEqual(Sheet([[], []]).shape, (2, 0))
        for rows in ([[1], [1, 2]], ["abc"], [[1], []]):
            with self.subTest(rows=rows), self.assertRaises(ShapeError):
                Sheet(rows)
        with self.assertRaises(ShapeError):
            Sheet([[1]], width=2)

    def test_mutation_is_explicit_and_invalid_edits_are_atomic(self):
        sheet = Sheet([[2, Cell(4, formula="=A1*2")]])
        snapshot = sheet.cell("A1")
        sheet.set("A1", 5)
        self.assertEqual(snapshot.value, 2)
        self.assertEqual(sheet.cell("A1").value, 5)
        self.assertEqual(sheet.cell("B1").value, 4)
        self.assertEqual(sheet.cell("B1").cache_status, "stale")
        before = sheet.rows
        with self.assertRaises(SpreadsheetError):
            sheet.set("A1", [])
        self.assertEqual(sheet.rows, before)
        sheet.set_formula("B1", "=A1*3")
        self.assertIsNone(sheet.cell("B1").value)

    def test_iterators_are_bounded_during_construction(self):
        limits = Limits(max_rows=2, max_columns=2, max_cells=3)
        for rows in ([[1, 2], [3, 4]], itertools.repeat([1]), [itertools.repeat(1)]):
            with self.subTest(rows=type(rows).__name__), self.assertRaises(ShapeError):
                Sheet(rows, limits=limits)
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ShapeError):
                Limits(max_rows=value)


class WorkbookTests(unittest.TestCase):
    def test_order_names_and_live_sheets(self):
        first = Sheet([[1]], name="Sales")
        book = Workbook([first, Sheet(name="Totals")])
        self.assertEqual(book.sheet_names, ("Sales", "Totals"))
        self.assertEqual([sheet.name for sheet in book], ["Sales", "Totals"])
        first.set("A1", 2)
        self.assertEqual(book["Sales"].cell("A1").value, 2)
        with self.assertRaises(ShapeError):
            book.add_sheet(Sheet(name="Sales"))
        self.assertEqual(len(book), 2)

    def test_aggregate_cells_and_even_empty_sheets_are_bounded(self):
        book = Workbook([Sheet([[1, 2]])], limits=Limits(max_cells=3))
        with self.assertRaises(ShapeError):
            book.add_sheet(Sheet([[3, 4]], name="Other"))
        self.assertEqual(len(book), 1)
        with self.assertRaises(ShapeError):
            Workbook((Sheet(name=str(i)) for i in itertools.count()), limits=Limits(max_sheets=2))
