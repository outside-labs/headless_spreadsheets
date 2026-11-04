# Registered Backpack sources

The unreleased optional `headless_spreadsheets.backpack` module consumes public
`ApplicationModel` and `AsyncApplicationStore` interfaces. The qualified storage
source is Backpack `9a691aa551bf7fb42134168452bbdb2e1d454928`:

```sh
uv pip install 'backpack-store @ git+https://github.com/wispsy/backpack.git@9a691aa551bf7fb42134168452bbdb2e1d454928'
```

The caller opens storage, registers the complete dataclass model and codec,
initializes its namespace and supplies the trusted handle. Construction and
import do none of those things. Declare the registered domain key and stable
dataclass field IDs; SQL column names and displayed positions are independent.

```python
from dataclasses import dataclass
from backpack_store import ApplicationStore, DataclassCodec
from headless_spreadsheets import SourceColumn
from headless_spreadsheets.backpack import BackpackSource

@dataclass
class Item:
    key: str
    title: str
    private: str = "retained"

with ApplicationStore.open("items.sqlite") as storage:
    model = storage.register(
        DataclassCodec(Item, type_key="example.item"), namespace="items",
        table="app_items", primary_key="key",
        columns={"key": "key", "title": "title", "private": "private"},
    )
    storage.initialize("items")
    source = BackpackSource(
        model, model_type=Item, key_field="key", table_id="items",
        schema_version="1", columns=[
            SourceColumn("key", "Key", "text", False),
            SourceColumn("title", "Title", "text", False,
                         searchable=True, writable=True),
        ],
    )
    # Seed explicitly once through model.create(Item("a", "Alpha")), if needed.
    page = source.query(order=[("title", False)],
                        search={"fields": ["title"], "term": "Alpha"})
    if page.rows:
        row = page.rows[0]
        committed = source.edit(row.key, "title", "Revised",
                                expected_revision=row.revision)
    source.close()  # Releases the binding; storage remains caller-owned.
```

`query` uses registered dataset sorting, literal search and keyset pagination;
it never sorts only the loaded page. Cursors bind the table/schema, projection,
sort and search. Concurrent writes may move rows between pages; refresh is
explicit. Snapshots contain detached cells and durable keys/revisions. Their
`source_addresses` are field IDs, not A1 coordinates. `get(key)` provides a fresh
authoritative row for reconciliation.

`edit` accepts an exact Unicode string, Boolean, portable integer, finite float
or an explicitly nullable field's `None`. Booleans and integers are distinct;
floats require actual floats. Undeclared fields, immutable keys, read-only
columns, rich cells/formulas, Decimal, date, datetime and nested values are
refused before mutation. A string beginning with `=` remains literal text.
The checked public whole-row transform reconstructs and validates the complete
dataclass, then the registered codec/storage validates and commits it atomically.
Unrelated fields remain present. Failed writes preserve the revision; successful
writes increment it once. Storage errors retain their public classes, including
`RevisionConflictError`. No automatic retry, merge or conversion occurs.

For async use, configure `AsyncApplicationStore.open` with a synchronous callback
that registers/initializes the model and returns `BackpackSource` on its owning
worker. Borrow it with `AsyncBackpackSource(backend)`; an explicit synchronous
`select` callback can extract the source from composite worker state. Await
`query`, `get` and `edit`. `aclose` releases the binding only; the caller must
await `backend.aclose()` to drain accepted work and close the owned connection.
Callbacks execute under Backpack's redacted exception boundary.

A dispatched cancellation does not mean rollback: `DispatchedCancellation`
retains an operation receipt. Await `error.receipt.wait()` or perform a fresh
`get` before deciding whether to retry. A revision belongs to the whole row, so
simultaneous edits of different cells in the same row can conflict. Other rows
have independent revisions. Native in-memory `Table`/`TableSource` behavior,
including formula metadata and Decimal/date/datetime fidelity, is unchanged.
