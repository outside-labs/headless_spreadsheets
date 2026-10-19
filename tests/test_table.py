"""Named operations retain source identity, live values and formula locations."""

import itertools
import unittest

from headless_spreadsheets import AddressError, Cell, Limits, ShapeError, SpreadsheetError, Table, TableView


class TableTests(unittest.TestCase):
    def test_records_key_order_missing_values_and_explicit_schema(self):
        table = Table.from_records([{"item": "Book", "price": 12}, {"quantity": 2, "item": "Pen"}])
        self.assertEqual(table.columns, ("item", "price", "quantity"))
        self.assertEqual(table.shape, (2, 3))
        self.assertEqual(table.to_records()[1], {"item": "Pen", "price": None, "quantity": 2})
        self.assertEqual(table.cell("A1").value, "item")
        self.assertEqual(Table.from_records([], columns=["a"]).shape, (0, 1))
        self.assertEqual(Table.from_records([{}, {}]).shape, (2, 0))
        with self.assertRaises(ShapeError):
            Table.from_records([{"b": 1}], columns=["a"])

    def test_rows_columns_and_atomic_explicit_edits(self):
        table = Table.from_records([{"price": 12}, {"price": 2}])
        row = table.rows[0]
        column = table["price"]
        self.assertEqual(dict(row), {"price": 12})
        self.assertEqual(column[:], (12, 2))
        self.assertEqual(column[-1], 2)
        table.set("A2", Cell(20, number_format="0.00"))
        self.assertEqual(row["price"], 20)
        self.assertEqual(column.cells[0].number_format, "0.00")
        table.add_column("double", lambda current: current["price"] * 2)
        self.assertEqual(table["double"][:], (40, 4))
        with self.assertRaises(AddressError):
            table.set("A1", "rename")
        before = table.to_records()
        with self.assertRaises(ShapeError):
            table.add_column("bad", [1])
        with self.assertRaises(SpreadsheetError):
            table.add_column("bad", lambda current: [])
        self.assertEqual(table.to_records(), before)
        table.add_column("blank")
        self.assertEqual(table["blank"][:], (None, None))

    def test_invalid_schema_and_bounded_records(self):
        for columns in (["a", "a"], [" "], [1], "abc"):
            with self.subTest(columns=columns), self.assertRaises(ShapeError):
                Table(columns)
        for records in ([{"": 1}], [{1: "x"}], [[1, 2]]):
            with self.assertRaises(ShapeError):
                Table.from_records(records)
        limits = Limits(max_rows=2, max_cells=3)
        with self.assertRaises(ShapeError):
            Table.from_records(itertools.repeat({}), limits=limits)
        with self.assertRaises(ShapeError):
            Table.from_records([{"a": 1}, {"b": 2}], limits=limits)
        with self.assertRaises(ShapeError):
            Table(["a"], [[1]]).add_column("b", itertools.repeat(1))

    def test_sheet_copy_preserves_formula_positions(self):
        table = Table(["price", "double"], [[3, Cell(6, formula="=A2*2")]])
        sheet = table.to_sheet(name="Sales")
        self.assertEqual(sheet.name, "Sales")
        self.assertEqual(sheet.cell("B2").formula, "=A2*2")
        sheet.set("A2", 4)
        self.assertEqual(table.cell("A2").value, 3)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.table = Table.from_records([
            {"item": "Book", "total": 36, "group": "a"},
            {"item": "Pen", "total": 20, "group": "a"},
            {"item": "Bag", "total": 50, "group": "b"},
            {"item": "Blank", "total": None, "group": "b"},
        ])

    def test_named_and_callable_filters(self):
        self.assertEqual(self.table.where(total__gte=30)["item"][:], ("Book", "Bag"))
        self.assertEqual(self.table.where(lambda row: row["item"].startswith("B"), total__lt=40)["item"][:], ("Book",))
        self.assertEqual(self.table.where(total__is_none=True)["item"][:], ("Blank",))
        self.assertEqual(self.table.where(item__contains="a")["item"][:], ("Bag", "Blank"))
        self.assertEqual(self.table.where(item__in={"Pen", "Book"})["item"][:], ("Book", "Pen"))
        self.assertEqual(len(self.table.where(total=None)), 1)
        self.assertEqual(len(self.table.where(total__ne=None)), 3)

    def test_invalid_filters_are_explicit(self):
        with self.assertRaises(KeyError):
            self.table.where(missing=1)
        for conditions in ({"total__is_none": 1}, {"total__regex": "x"}, {"total__gt": "a"}, {"item__in": iter(["Book"])}):
            with self.subTest(conditions=conditions), self.assertRaises(SpreadsheetError):
                self.table.where(**conditions)
        special = Table.from_records([{"total__gte": 1}])
        self.assertEqual(len(special.where(total__gte=1)), 1)

    def test_stable_multicolumn_sort_and_independent_blank_placement(self):
        ordered = self.table.sort_by("group", "total", reverse=True)
        self.assertEqual(ordered["item"][:], ("Bag", "Blank", "Book", "Pen"))
        self.assertEqual(self.table.sort_by("total", reverse=True)["item"][:], ("Bag", "Book", "Pen", "Blank"))
        self.assertEqual(self.table.sort_by("total", nulls="first")["item"][:], ("Blank", "Pen", "Book", "Bag"))
        self.assertEqual(self.table.sort_by("group")["item"][:], ("Book", "Pen", "Bag", "Blank"))
        with self.assertRaises(SpreadsheetError):
            Table(["mixed"], [[1], ["x"]]).sort_by("mixed")

    def test_views_keep_source_membership_values_and_formulas(self):
        self.table.set_formula("B4", "=SUM(A4:A5)", cached_value=50)
        view = self.table.where(total__gte=30).sort_by("total", reverse=True).select("total", "item")
        self.assertEqual(view.source_address("A2"), "B4")
        self.assertEqual(view.cell("A2").formula, "=SUM(A4:A5)")
        self.assertEqual(self.table.cell("B4").formula, "=SUM(A4:A5)")
        self.table.set("B4", 1)
        self.assertEqual(view["total"][:], (1, 36))
        self.assertEqual([row.index for row in view], [2, 0])
        self.assertFalse(hasattr(view, "set"))
        self.assertEqual(view.select().shape, (2, 0))

    def test_materialized_view_is_independent_and_drops_formula_metadata(self):
        self.table.set_formula("B2", "=2*18", cached_value=36)
        copy = self.table.select("total").to_table()
        self.assertEqual(copy.cell("A2"), Cell(36))
        copy.set("A2", 99)
        self.assertEqual(self.table.cell("B2").value, 36)

    def test_direct_view_construction_validates_source_positions(self):
        for rows, columns in (([-1], [0]), ([4], [0]), ([0], [3]), ([0], [0, 0])):
            with self.assertRaises(ShapeError):
                TableView(self.table, rows, columns)
        bounded = Table(["a"], [[1]], limits=Limits(max_rows=2))
        with self.assertRaises(ShapeError):
            TableView(bounded, itertools.repeat(0), [0])
