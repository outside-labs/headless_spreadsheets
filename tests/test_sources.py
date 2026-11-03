from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
import unittest

from headless_spreadsheets import Cell, SourceColumn, SpreadsheetError, Table, TableSource, TableView


class SourceTests(unittest.TestCase):
    def test_sorted_projected_view_keeps_identity_and_formula_metadata(self):
        formula = Cell(Decimal("2.50"), formula="=B2*2", number_format="0.00")
        table = Table(["name", "amount", "date"], [["Zulu", formula, date(2026, 1, 1)], ["Alpha", 2, None], ["Alpha", 2, None]])
        source = TableSource(table)
        original = source.query()
        sorted_page = source.query(columns=["c2", "c1"], order=[("c1", False)], generation=7)
        self.assertEqual([row.key for row in sorted_page.rows], ["r2", "r3", "r1"])
        self.assertEqual(sorted_page.generation, 7)
        self.assertEqual(sorted_page.rows[-1].cells[0], formula)
        self.assertEqual(sorted_page.rows[-1].source_addresses, ("B2", "A2"))
        view = table.sort_by("name").select("amount", "name")
        other = TableSource(view).query()
        self.assertEqual(other.table_id, original.table_id)
        self.assertEqual([column.id for column in other.columns], ["c2", "c1"])
        self.assertEqual(other.rows[-1].key, original.rows[0].key)
        self.assertIsNone(other.rows[0].revision)
        self.assertNotEqual(TableSource(Table(table.columns)).table_id, source.table_id)

    def test_snapshot_is_detached_while_existing_view_stays_live(self):
        table = Table(["label"], [["Alpha"], ["Zulu"]])
        view = table.where(label="Alpha")
        source = TableSource(view)
        captured = source.query()
        table.set("A2", "Changed")
        self.assertEqual(view.cell("A2").value, "Changed")
        self.assertEqual(captured.rows[0].cells[0].value, "Alpha")
        self.assertEqual(source.query().rows[0].cells[0].value, "Changed")
        with self.assertRaises(FrozenInstanceError):
            captured.rows[0].cells[0].value = "No"
        source.close()
        source.close()
        with self.assertRaises(SpreadsheetError):
            source.query()
        table.set("A2", "Caller still owns table")

    def test_search_is_literal_and_unicode_without_normalization(self):
        table = Table(["label"], [[s] for s in ["100%_\\' OR 1=1", "café", "cafe\u0301", "CAFÉ", "a\x00b", None]])
        source = TableSource(table)
        for term, expected in [("%_\\'", ["r1"]), ("café", ["r2"]), ("CAFÉ", ["r4"]), ("\x00", ["r5"]), ("", [f"r{i}" for i in range(1, 7)])]:
            page = source.query(search={"fields": ["c1"], "term": term})
            self.assertEqual([row.key for row in page.rows], expected)

    def test_null_last_ties_pagination_and_changed_query(self):
        source = TableSource(Table(["value"], [[2], [None], [1], [2]]))
        first = source.query(order=[("c1", True)], limit=1)
        second = source.query(order=[("c1", True)], limit=3, cursor=first.next_cursor)
        self.assertEqual([r.key for r in first.rows + second.rows], ["r1", "r4", "r3", "r2"])
        self.assertIsNone(second.next_cursor)
        with self.assertRaises(SpreadsheetError):
            source.query(order=[("c1", False)], cursor=first.next_cursor)

    def test_invalid_capabilities_and_bounds(self):
        for kwargs in [dict(writable=True), dict(searchable=True), dict(visible=False), dict(sortable=1)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(SpreadsheetError):
                SourceColumn("c", "Label", **kwargs)
        source = TableSource(Table(["label"], [["A"]]))
        for query in [dict(columns=["c1", "c1"]), dict(order=[("c1", 1)]), dict(limit=True), dict(generation=-1),
                      dict(search={"fields": ["c1"], "term": "x" * 257}), dict(search={"fields": ["missing"], "term": ""}),
                      dict(cursor="!"), dict(order=[("c1", False)] * 4)]:
            with self.subTest(query=query), self.assertRaises(SpreadsheetError):
                source.query(**query)
        hidden = TableSource(Table(["hidden"], [["private"]]), columns=[SourceColumn("secret", "Same label", visible=False, sortable=False)])
        self.assertEqual(hidden.query().rows[0].cells, ())
        with self.assertRaises(SpreadsheetError):
            hidden.query(columns=["secret"])
        with self.assertRaises(SpreadsheetError):
            TableSource(TableView(Table(["x"], [[1]]), [0, 0], [0]))
