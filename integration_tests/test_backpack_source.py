import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from backpack_store import (
    ApplicationStore, AsyncApplicationStore, DataclassCodec, DispatchedCancellation,
    RevisionConflictError, TransactionError,
)
from headless_spreadsheets import Cell, SourceColumn, SpreadsheetError
from headless_spreadsheets.backpack import AsyncBackpackSource, BackpackSource


@dataclass
class Item:
    key: str
    title: str
    done: bool = False
    rank: int | None = None
    score: float = 1.0
    private: str = "untouched"

    def __post_init__(self):
        if self.title == "invalid":
            raise ValueError("private validation detail")


COLUMNS = (
    SourceColumn("key", "Key", "text", False),
    SourceColumn("title", "Title", "text", False, searchable=True, writable=True),
    SourceColumn("done", "Done", "boolean", False, writable=True),
    SourceColumn("rank", "Rank", "integer", True, writable=True),
    SourceColumn("score", "Score", "number", False, writable=True),
)


def register(store):
    model = store.register(DataclassCodec(Item, type_key="test.item"), namespace="items", table="app_items",
                           primary_key="key", columns={name: name for name in Item.__dataclass_fields__})
    store.initialize("items")
    return model


def bind(model):
    return BackpackSource(model, model_type=Item, key_field="key", table_id="items", schema_version="1", columns=COLUMNS)


class BackpackSourceTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "items.sqlite"
        self.store = ApplicationStore.open(self.path)
        self.addCleanup(self.store.close)
        self.model = register(self.store)
        self.model.create(Item("a", "Zulu"))
        self.model.create(Item("b", "Alpha"))
        self.source = bind(self.model)

    def test_sort_search_edit_and_independent_reopen(self):
        page = self.source.query(columns=["title", "key"], order=[("title", False)],
                                 search={"fields": ["title"], "term": "Alpha"}, generation=9)
        row = page.rows[0]
        self.assertEqual((row.key, row.revision, row.source_addresses), ("b", "1", ("title", "key")))
        result = self.source.edit(row.key, "title", "Changed", expected_revision=row.revision)
        self.assertEqual((result.key, result.revision, result.cells[1].value), ("b", "2", "Changed"))
        self.assertEqual(row.cells[0].value, "Alpha")
        self.assertEqual(self.model.get("a").value.title, "Zulu")
        self.assertEqual(self.model.get("b").value.private, "untouched")
        with ApplicationStore.open(self.path) as other:
            rebound = bind(register(other))
            self.assertEqual(rebound.get("b"), result)
        self.source.close()
        with self.assertRaises(SpreadsheetError):
            self.source.query()
        self.assertEqual(self.model.get("b").revision, "2")

    def test_complete_model_validation_and_rollback(self):
        before = self.model.get("b")
        with self.assertRaises(TransactionError) as caught:
            self.source.edit("b", "title", "invalid", expected_revision="1")
        self.assertNotIn("private validation detail", str(caught.exception))
        self.assertEqual(self.model.get("b"), before)
        with self.assertRaises(TransactionError):
            with self.store.unit_of_work():
                self.source.edit("a", "title", "Rolled back", expected_revision="1")
                self.source.edit("b", "title", "invalid", expected_revision="1")
        self.assertEqual(self.model.get("a").revision, "1")

    def test_invalid_and_rich_values_are_refused_before_mutation(self):
        before = self.model.get("a")
        cases = [("key", "new"), ("private", "changed"), ("missing", 1), ("done", 1), ("rank", True),
                 ("rank", 2**53), ("score", 1), ("score", float("inf")), ("title", None), ("title", "\ud800")]
        cases += [("title", value) for value in (Decimal("2"), date.today(), datetime.now(), Cell(1, formula="=1"), [1], {})]
        for column, value in cases:
            with self.subTest(column=column, value=type(value)), self.assertRaises(SpreadsheetError):
                self.source.edit("a", column, value, expected_revision="1")
            self.assertEqual(self.model.get("a"), before)
        self.source.edit("a", "rank", 2, expected_revision="1")
        self.assertEqual(self.source.edit("a", "rank", None, expected_revision="2").revision, "3")

    def test_two_writers_and_different_rows(self):
        barrier = threading.Barrier(2)
        def writer(column, value):
            with ApplicationStore.open(self.path) as store:
                source = bind(register(store))
                barrier.wait(timeout=5)
                try:
                    return source.edit("a", column, value, expected_revision="1").revision
                except RevisionConflictError:
                    return "stale"
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(writer, "title", "Winner")
            second = pool.submit(writer, "done", True)
            self.assertCountEqual([first.result(timeout=10), second.result(timeout=10)], ["2", "stale"])
        self.assertEqual(self.source.edit("b", "done", True, expected_revision="1").revision, "2")
        with self.assertRaises(RevisionConflictError):
            self.source.edit("a", "title", "Lost", expected_revision="1")

    def test_query_cursors_and_capabilities(self):
        first = self.source.query(limit=1, order=[("title", False)])
        next_page = self.source.query(limit=1, order=[("title", False)], cursor=first.next_cursor)
        self.assertEqual([r.key for r in first.rows + next_page.rows], ["b", "a"])
        for query in (dict(columns=["private"]), dict(order=[("private", False)]), dict(limit=True),
                      dict(cursor=first.next_cursor), dict(search={"fields": ["title"], "term": "\ud800"})):
            with self.subTest(query=query), self.assertRaises(SpreadsheetError):
                self.source.query(**query)
        with self.assertRaises(SpreadsheetError):
            BackpackSource(self.model, model_type=Item, key_field="key", table_id="items", schema_version="1",
                           columns=[SourceColumn("key", "Key", "text", False, writable=True)])


class AsyncBackpackTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_worker_cancellation_receipt_and_reconciliation(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "async.sqlite"
            committed, release = threading.Event(), threading.Event()
            class Model:
                def __init__(self, handle):
                    self.handle = handle
                def find(self, **query):
                    return self.handle.find(**query)
                def get(self, key):
                    return self.handle.get(key)
                def update(self, *args, **kwargs):
                    result = self.handle.update(*args, **kwargs)
                    committed.set()
                    if not release.wait(5):
                        raise RuntimeError("test release timed out")
                    return result
            def configure(store):
                model = register(store)
                model.create(Item("a", "Original"))
                return bind(Model(model))
            backend = await AsyncApplicationStore.open(path, configure=configure)
            source = AsyncBackpackSource(backend)
            try:
                task = asyncio.create_task(source.edit("a", "title", "Committed", expected_revision="1"))
                self.assertTrue(await asyncio.to_thread(committed.wait, 5))
                task.cancel()
                with self.assertRaises(DispatchedCancellation) as caught:
                    await task
                release.set()
                result = await caught.exception.receipt.wait()
                self.assertEqual(result.revision, "2")
                self.assertEqual(await source.get("a"), result)
                await source.aclose()
                self.assertEqual(await backend.run(lambda state: state.get("a")), result)
            finally:
                release.set()
                await backend.aclose()
            with ApplicationStore.open(path) as reopened:
                self.assertEqual(bind(register(reopened)).get("a"), result)
