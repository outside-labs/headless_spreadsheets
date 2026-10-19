# Table presentation

Tables and views provide `to_markdown()`, `to_html()`, `to_ansi()` and
`render("markdown" | "html" | "ansi")`. Each `to_*` method optionally accepts a
destination path and returns its generated text. The unified `render` method
returns text only.

By default cells display their literal or supplied cached value; a formula with
no result displays blank. Pass `formulas=True` to display preserved expressions.
This is display text, not formula evaluation or reference translation. In v0.1,
supplied formula results are always stale. Number-format hints are retained by
native JSON but are not applied here.

```python
print(sales.to_markdown())
sales.to_html("sales.html")
print(sales.to_ansi(max_width=24, color=True))
print(sales.render("markdown", formulas=True))
```

Columns containing only numbers and blanks align right; other columns align
left. Boolean values are not treated as numbers. Formula display aligns columns
containing formulas left. Zero-column tables render as empty text; header-only
tables retain their headers.

Markdown escapes pipes, backslashes and inline markup, escapes HTML data and
represents line breaks with `<br>`. It emits table syntax, without parsing any
input as Markdown. HTML escapes all cell/header data, emits semantic column
headers and uses fixed alignment styles. Neither format embeds formulas in
hidden metadata or preserves spreadsheet types on import. Markdown/HTML reading
is outside v0.1.

Terminal output uses ASCII borders and one physical line per source row. Input
control characters, ANSI escapes and Unicode control/format characters are
rendered as visible escape text. Optional color adds only a fixed header style
and reset sequence. Newlines and tabs inside cells are displayed as `\n` and
`\t`. Maximum column width includes a truncation ellipsis when needed.

Width handling uses `unicodedata`: combining marks count as zero, East Asian
wide/fullwidth characters as two, and other characters as one. Terminal fonts,
ambiguous widths, variation selectors and emoji grapheme sequences can differ;
this is an approximation without a third-party width library. Unicode format
controls such as zero-width joiners are escaped rather than interpreted.

## Independent document boundary

`table.to_document()` returns an immutable `TableDocument` containing display
strings and alignments. Later source edits do not change it. Its `render` and
`to_*` methods return text. You can also construct one from immutable tuples:

```python
from headless_spreadsheets import TableDocument

report = TableDocument(
    ("item", "total"),
    (("Book", "36"), ("Bag", "50")),
    ("left", "right"),
)
print(report.to_markdown())
```

This document model is separate from live spreadsheet `Table`, `Sheet` and
`Cell`. The later typed Markdown extraction is tracked by MD-01; v0.1 does not
copy Pretty Notebook's parser or require it at runtime.
