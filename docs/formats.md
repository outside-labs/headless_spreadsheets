# Interchange contracts

## Native JSON schema 1

Use `Table.to_json()`, `Sheet.to_json()` or `Workbook.to_json()` for typed,
formula-preserving interchange. Their matching `from_json(text)` and
`read_json(path)` methods enforce the expected document kind.

The envelope contains exactly `format`, `schema_version`, `kind` and `data`:

```json
{
  "format": "headless-spreadsheets",
  "schema_version": 1,
  "kind": "table",
  "data": {
    "columns": ["price", "double"],
    "rows": [[
      {"value": {"type": "integer", "value": 3}, "formula": null, "number_format": null, "cache_status": "value"},
      {"value": {"type": "integer", "value": 6}, "formula": "=A2*2", "number_format": "0.00", "cache_status": "stale"}
    ]]
  }
}
```

All fields shown on a cell are required. No additional fields are accepted.
Scalar tags are `blank` (null), `boolean`, `integer`, `number` (JSON floating-point
number), `text`, `decimal` (string), `date` (ISO string) and `datetime` (ISO string).
Types are checked strictly, including the distinction between integers and
booleans. Decimal scale/sign and datetime UTC offsets are retained. Datetime
named timezone identity and the `fold` flag are outside the format's fidelity.
Floats and decimals must be finite.

A sheet's data contains exactly `name`, `width` and `rows`. A workbook's data
contains exactly `sheets`, an ordered list of those sheet objects. Width preserves
an empty sheet's column count. Table headers are unique nonempty strings, stored
separately from data rows. Table A1 row 1 is the header; sheet A1 row 1 is data.

`cache_status` is `value` for a literal, `missing` for a formula whose value is
blank, and `stale` for a supplied formula result. Fresh calculation is unavailable
in v0.1. An opaque formula is never evaluated, translated or rewritten. An
uncalculated formula and a formula with a cached blank share the `missing` status.
Number-format hints are retained but are not executed by the renderers.

Unknown versions/kinds, duplicate keys, unknown fields, malformed types,
nonfinite values, inconsistent cache statuses and ragged/oversized grids raise
`FormatError`. Input is bounded by `Limits` before parsing; Python's JSON parser
still constructs the bounded document in memory. These are application
guardrails, not a CPU/memory isolation boundary.

Views have no native JSON method: serialize the original table to retain source
formula coordinates, or explicitly call `view.to_table()` to copy only values.

## CSV and TSV

```python
table = Table.from_csv('name,amount\r\nBook,12\r\n')
table = Table.read_csv("sales.tsv", delimiter="\t")
text = table.to_csv()
table.to_csv("sales.tsv", delimiter="\t")
```

CSV imports all fields as text, including numbers and strings beginning with
`=`. Quoting, embedded delimiters, Unicode and multiline fields use Python's
standard-library CSV rules. UTF-8 BOMs are accepted. A header is required for
nonempty data and each row must match its width. Empty input is a zero-column
table. CSV field size also follows Python's current `csv.field_size_limit()`;
the library never changes that process-wide setting.

CSV export writes literal/cached values. Blank cells become empty fields, so
blank and empty text cannot be distinguished on return. Dates use ISO text;
other nonblank scalars use their Python string representation. Python types,
formula caches and formatting hints do not round-trip through CSV.

By default text fields and headers beginning with spreadsheet-active content
(`=`, `+`, `-`, `@`, including after whitespace, or leading tab/newline/return)
receive a leading apostrophe. Numeric negative values retain their sign. This
intentionally alters some strings; import does not remove that apostrophe. Use
`escape_formulas=False` only when exact text is required for a trusted consumer.
How a spreadsheet application imports quoted/escaped text is application-specific.

`from_csv(..., formulas=True)` explicitly treats leading `=` fields as formulas,
with missing caches. `to_csv(formulas=True)` explicitly writes stored formula
text; it retains text escaping for literal string cells unless disabled. Formula
export requires the original table. Views cannot emit executable CSV formulas
because selection/sorting would change their coordinates.

## Paths and file replacement

Text parsers never guess whether a string is a path. Use `read_csv`/`read_json`
for paths. Readers cap UTF-8 byte counts using `Limits.max_input_bytes` and reject
invalid UTF-8. Export methods return the generated text even when a destination
is supplied. File writes use UTF-8, flush a temporary file beside the destination
and atomically replace it. Parent directories must already exist. Filesystem
errors propagate, and failed replacement preserves the previous destination.
