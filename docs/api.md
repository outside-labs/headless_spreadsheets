# Public API

## Cell, Limits and failures

`Cell(value=None, formula=None, number_format=None)` is an immutable snapshot.
Its `data_type` is `blank`, `boolean`, `integer`, `number`, `text`, `decimal`,
`date` or `datetime`; its `cache_status` is `value`, `missing` or `stale`.
Unsupported objects and nonfinite numbers raise `SpreadsheetError`. Formulas
must start with `=` and contain an expression but are otherwise preserved
verbatim. They are never executed. Supply a new `Cell` through an explicit edit
to change formula/value/format metadata together.

`Limits(max_rows=100_000, max_columns=1_024, max_cells=1_000_000,
max_input_bytes=16_000_000, max_sheets=256)` provides finite positive guardrails.
Pass `limits=` to construction or input readers. Table row limits count data
rows; sheet limits count every grid row. Workbook cell limits are aggregate.
Zero-column rows and empty sheets still count toward row/sheet limits. A table
converted to a sheet needs room for an additional header row.

`SpreadsheetError` derives from `ValueError`. `AddressError`, `ShapeError` and
`FormatError` specialize address, schema/shape and serialized-input failures.
Unknown named columns use `KeyError`; filesystem errors propagate as `OSError`.
User callbacks propagate their own exceptions. Failed explicit edits leave the
table/grid intact, except for changes a user callback itself performs.

## Table construction and access

```python
from headless_spreadsheets import Cell, Limits, Table

table = Table(["item", "total"], [["Book", Cell(36, formula="=12*3")]])
table = Table.from_records([{"item": "Book", "total": 36}])
table = Table.from_records([], columns=["item", "total"])
```

Column labels are unique nonempty strings and rows must be rectangular.
`from_records` uses first-seen key order and fills absent keys with blank cells.
Explicit `columns=` preserves the supplied order and rejects undeclared keys.
Python values and `Cell` objects can be mixed in rows/records. Inputs are
validated and copied; subsequent edits to input lists/dictionaries do not affect
the table.

| Access | Result |
| --- | --- |
| `table.columns` | Immutable tuple of names |
| `table.shape` | `(data_rows, columns)` |
| `len(table)` | Number of data rows |
| `for row in table` / `table.rows` | Live read-only `Row` mappings |
| `row["total"]` / `row.cell("total")` | Scalar / immutable cell snapshot |
| `row.index` | Zero-based original data row index |
| `table["total"]` | Read-only `Column` sequence |
| `table["total"][1:]` / `.cells` | Tuple of scalars / cell snapshots |
| `table.cell("B2")` | A1 cell, including header at row 1 |
| `table.to_records()` | Independent list of scalar dictionaries |

`table.set("B2", value)` replaces one data cell. Headers cannot be edited through
cell addresses. `set_formula("B2", "=12*3", cached_value=36)` is explicit formula
storage. `add_column(name)` appends blanks; `add_column(name, iterable)` requires
exactly one cell per row; `add_column(name, callable)` computes values from each
read-only row. These Python callbacks produce literal values unless they return
`Cell` objects with formula text. They are not translated to spreadsheet formulas.

## Selection and sorting

```python
view = table.where(total__gte=30)
view = table.where(lambda row: row["item"].startswith("B"), total__lt=100)
view = view.sort_by("total", "item", reverse=True, nulls="last").select("item")
```

Named conditions use `column=value` or `column__operator=value`. Operators are
`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `contains`, and `is_none`. A complete
existing column label takes precedence over splitting its suffix. Conditions
and an optional callable are combined with AND. Ordered comparisons involving
blank do not match. `is_none` requires a Boolean. `in` requires a reusable
sequence, set or mapping, so membership does not consume a generator across
rows. Invalid comparisons raise a clear error; no implicit type coercion occurs.

`sort_by` uses stable Python comparisons, supports multiple columns and one
`reverse` direction, and handles blank placement independently. Mixed values
that Python cannot order raise an error. Views retain fixed row/column
membership in the selected order, even when later source edits change values;
filters and sorts do not rerun. Existing views do not gain newly added columns.

`TableView` offers reading, `where`, `sort_by`, `select`, CSV and presentation.
`source_address("A2")` maps a local cell back to the original table. Stored
formula references remain original; a view is not a relocated formula document.
`to_table()` copies only values, dropping formula/format metadata, for an
independent editable snapshot. Serialize the original table as JSON to retain
formula coordinates and metadata.

## Sheets and workbooks

```python
from headless_spreadsheets import Sheet, Workbook

sheet = Sheet([[2, 4]], name="Inputs")
sheet.set_formula("B1", "=A1*2", cached_value=4)
book = Workbook([sheet, Sheet(name="Empty", width=3)])
assert book["Inputs"].cell("B1").value == 4
```

`Sheet` has no implicit header. `rows` returns immutable rows of cell snapshots;
`shape`, `cell`, `set` and `set_formula` describe the fixed grid. A1 addresses are
case-insensitive and must be within the existing shape. Names are immutable
nonempty strings. `column_name(index)` and `split_address(text)` convert
zero-based coordinates and A1 names.

`table.to_sheet(name="Sales")` copies its headers and data without relocating
formula coordinates. `Workbook.add_sheet(sheet)` retains that sheet object,
requires a unique name and preserves insertion order. Iteration yields sheets;
`sheet_names` returns names. There is no row/column insertion, deletion, reference
rewriting, named range, calculation scheduler or thread-safety guarantee in
v0.1. Coordinate/name validation is local; Excel naming/dimension rules belong
to the later XLSX adapter.

## Serialization and rendering

See [interchange contracts](formats.md) and [presentation](presentation.md) for
complete fidelity and escaping rules. Tables, sheets and workbooks support
native JSON. Tables/views support CSV/TSV and presentation. `TableDocument` is a
display-only immutable snapshot; it is separate from live data. No asynchronous
or cloud API is part of this release.
