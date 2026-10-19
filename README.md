# Headless Spreadsheets

Spreadsheet-native tables for ordinary Python applications. Pure Python 3.14+,
zero runtime dependencies, MIT licensed.

Keep typed values, formula text and cached results together, work with named
records, and move data between Python, CSV, native JSON and table displays.

```sh
pip install headless-spreadsheets
```

## A table without a workbook

```python
from headless_spreadsheets import Table

sales = Table.from_records([
    {"item": "Book", "price": 12, "quantity": 3},
    {"item": "Pen", "price": 2, "quantity": 10},
    {"item": "Bag", "price": 25, "quantity": 2},
])
sales.add_column("total", lambda row: row["price"] * row["quantity"])

report = sales.where(total__gte=30).sort_by("total", reverse=True)
print(report.select("item", "total").to_markdown())
```

```markdown
| item | total |
| :--- | ---: |
| Bag | 50 |
| Book | 36 |
```

Rows behave like read-only dictionaries; columns behave like read-only
sequences. Filtering, sorting and selection return views with fixed source
membership and live values. They keep the original cells in place.

## Preserve spreadsheet expressions

```python
sales.set_formula("D2", "=B2*C2", cached_value=36)
cell = sales.cell("D2")
assert cell.formula == "=B2*C2"
assert cell.value == 36
assert cell.cache_status == "stale"

restored = Table.from_json(sales.to_json())
assert restored.cell("D2") == cell
```

Table addresses include a header at row 1; data begins at row 2. `Sheet` is a
rectangular grid without an implicit header, and `Workbook` contains named
sheets. Literal strings starting with `=` remain text unless explicitly supplied
as formulas.

**v0.1 preserves formulas and supplied cached results; it does not calculate
them.** Formula caches are always `stale` or `missing`. Unknown formulas stay
inspectable and exportable. Views expose `source_address()` and retain original
formula text; `view.to_table()` deliberately creates an independent values-only
copy. Number-format hints are stored without being applied.

## Interchange and display

```python
sales.to_json("sales.json")             # Types, formulas, cache and hints
sales = Table.read_json("sales.json")
sales.to_csv("sales.csv")               # Values; active text escaped by default
text_table = Table.read_csv("sales.csv") # All imported fields are text
sales.to_csv("sales.tsv", delimiter="\t")

sales.to_markdown("sales.md")
sales.to_html("sales.html")
print(sales.to_ansi(max_width=24, color=True))
print(sales.render("markdown", formulas=True))
```

Each export returns text and optionally writes a UTF-8 file atomically. Text
readers are `from_csv(text)` and `from_json(text)`; path readers are `read_csv`
and `read_json`. CSV loses Python types and blank-versus-empty distinctions.
Explicit CSV formula modes are available. Native JSON is the fidelity format.
HTML/Markdown escape content; terminal output neutralizes input controls.

## Scope

Supported cell values are blank (`None`), Boolean, integer, finite float, text,
`Decimal`, `date` and `datetime`. Configurable `Limits` bound rows, columns,
cells, sheets and serialized input. The core has no custom C/Rust extensions and
requires no third-party packages. It makes no pandas-scale performance claim.

Formula calculation, `F` expressions, XLSX, Google Sheets, Markdown/HTML import,
grouping/joins, async execution and undo/history are later milestones. The native
table writer has no Pretty Notebook dependency; shared typed Markdown extraction
is tracked separately.

- [API and behavior](https://github.com/outside-labs/headless_spreadsheets/blob/main/docs/api.md)
- [Interchange contracts](https://github.com/outside-labs/headless_spreadsheets/blob/main/docs/formats.md)
- [Presentation and Unicode limits](https://github.com/outside-labs/headless_spreadsheets/blob/main/docs/presentation.md)
- [Implementation plan](https://github.com/outside-labs/headless_spreadsheets/blob/main/IMPLEMENTATION_PLAN.md)
- [Project and queue](https://github.com/orgs/outside-labs/projects/16)

## Development

```sh
uv sync --locked
uv run --frozen python -W error::ResourceWarning -m unittest discover -s tests -v
uv run --frozen python examples/sales.py
uv run --frozen python scripts/check_distribution.py
```

CI tests Python 3.14 on Linux, macOS and Windows. Distribution verification
checks exact archive contents, metadata, source bytes, source rebuild parity and
the complete suite in independent wheel/source installations. See
[release procedures](https://github.com/outside-labs/headless_spreadsheets/blob/main/docs/releases.md)
for the tag-driven Trusted Publishing workflow.
