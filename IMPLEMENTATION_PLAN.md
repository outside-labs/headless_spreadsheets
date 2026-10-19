# Headless Spreadsheets — implementation plan

## Purpose and adopted decisions

Build a spreadsheet-native table engine for ordinary Python applications. Cells
retain literal values, formula text, cached results and presentation hints as
separate information. Tables support familiar named-column operations without
requiring a workbook. The engine is independent of a browser, terminal or cloud
service and does not attempt pandas-scale numerical performance.

The initial distribution is `headless-spreadsheets`, imported as
`headless_spreadsheets`, requiring Python 3.14+. It uses the existing uv build
scaffold, the Python standard library and **zero runtime dependencies**. No custom
C/Rust extensions, external services or cloud credentials are required. The source
repository is public at `outside-labs/headless_spreadsheets`, under the MIT
license. PyPI publication is explicitly selected for v0.1.0, using
`.github/workflows/release.yaml` and the GitHub environment `pypi`.

The source brief is `headless_spreadsheets GIST01.md` in this directory. That brief
contains proposed interfaces and a staged roadmap, not implemented capabilities.
This plan adopts its v0.1 table foundation and preserves explicit boundaries for
the later formula engine, XLSX, Google Sheets and advanced operations.

## v0.1.0 acceptance contract

1. Typed, validated immutable `Cell` snapshots support blank, Boolean, integer,
   finite float, text, `Decimal`, `date` and `datetime` values. Optional formula
   text and a number-format hint are independent fields. Formula syntax is
   preserved without evaluation. Cached formula results are reported as stale or
   missing; the library never claims a locally verified result.
2. `Sheet` is an editable rectangular grid with A1 addresses. `Workbook` keeps
   named sheets in insertion order. Invalid addresses, dimensions, duplicate
   names, unsupported values and excessive input fail explicitly.
3. Standalone `Table` objects use unique named columns and records. Read-only
   `Row` and `Column` interfaces expose ordinary Python values while retaining
   access to cell metadata. Explicit edits replace cells atomically.
4. Filtering, stable sorting and column selection return read-only views with
   fixed source row/column membership and live cell values. They do not move
   source cells or rewrite formulas. Materializing a view creates a values-only
   table, preventing accidental relocation of opaque formulas.
5. CSV/TSV import and export use the standard library, preserve quoted/multiline
   text, enforce a rectangular header schema and default to literal text on
   import and cached/literal values on export. Dangerous spreadsheet text is
   prefixed on export by default. Formula interpretation/export must be explicit.
6. Versioned native JSON round-trips tables, sheets and workbooks, including
   typed values, formulas, cached results and number-format hints. The reader
   rejects duplicate keys, unsupported versions, unknown fields, invalid types,
   nonfinite numbers and dimensions beyond configured bounds.
7. Markdown, HTML and ANSI terminal table output is available as text and through
   explicit UTF-8 file destinations. HTML escapes data, Markdown escapes markup
   and pipes, and terminal output neutralizes input control sequences. Optional
   ANSI color is generated only by the renderer. Unicode width handling is
   documented as a standard-library approximation.
8. Examples execute successfully; API contracts and limitations are documented.
   Unit and adversarial tests pass on Linux, macOS and Windows with Python 3.14.
   Wheel and source installs work outside the checkout without runtime packages.
9. Distribution checks validate exact archive allowlists, source bytes, metadata,
   MIT license, `py.typed`, empty runtime requirements and source rebuild parity.
   A tag matching the project version must be on main before publication.
10. Publish v0.1.0 through PyPI Trusted Publishing. Verify published wheel/source
    hashes against the exact verified workflow artifacts and exercise a fresh
    uncached registry install. Preserve the tag and uploaded files once released.

## Object and API design

### Cells and scalar types

`Cell(value=None, formula=None, number_format=None)` is an immutable snapshot.
`cell.data_type` describes the cached/literal scalar. `cell.cache_status` is
`value` for literals, `missing` for formulas without a result, and `stale` for
formulas with a supplied result. Formulas must begin with `=` and contain an
expression, but remain opaque strings. A literal string beginning with `=` stays
literal unless explicitly passed as a formula. No `eval`, dynamic import or code
execution is used. Formatting hints are stored without executing format strings.

Finite scalar values are validated on entry. Containers and arbitrary objects
are not cells. Native JSON uses tagged values to distinguish blanks, dates,
datetimes, decimals, booleans, integers, numbers and text. Datetime ISO offsets
round-trip; named timezone identity and the `fold` flag are outside v0.1 fidelity.

### Sheets and workbooks

`Sheet(rows, name="Sheet1")` accepts rectangular rows and uses A1 coordinates.
`sheet.cell("B2")`, `sheet.set("B2", value)` and
`sheet.set_formula("B2", "=A2*2", cached_value=...)` expose reading and editing.
Addresses are case-insensitive, one-based and bounded by the actual grid.
Structural insertion/deletion, reference rewriting, merged cells, named ranges
and styles are deferred.

`Workbook` supports `add_sheet`, name lookup and ordered iteration. Sheet names
are unique and immutable. Workbooks have no calculation scheduler in v0.1.

### Tables and views

```python
from headless_spreadsheets import Cell, Table

sales = Table.from_records([
    {"item": "Book", "price": 12, "quantity": 3},
    {"item": "Pen", "price": 2, "quantity": 10},
])
sales.add_column("total", lambda row: row["price"] * row["quantity"])
sales.set_formula("D2", "=B2*C2", cached_value=36)
selected = sales.where(total__gte=30).sort_by("item").select("item", "total")
print(selected.to_markdown())
```

Table address row 1 is the immutable header; data starts at row 2. Record columns
use first-seen key order, absent values become blank and explicit columns reject
unknown keys. Column labels must be nonempty unique strings. Empty tables and
header-only tables have defined shapes.

`where` combines a Python predicate with named conditions using AND. Operators
are equality/inequality, ordered comparisons, membership, containment and blank
checks. Blank ordered comparisons do not match. Invalid column/operator/value
combinations raise useful errors rather than guessing a conversion.

`sort_by` is stable and supports multiple columns, reverse ordering and explicit
blank placement. Incomparable mixed values raise an error. Source cell addresses
remain fixed. Views retain their initial row membership after edits; predicates
are not rerun automatically. `to_table()` deliberately materializes only values;
native formula-preserving serialization belongs to the original table/grid.

### Input bounds and failures

`Limits` defaults to 100,000 rows, 1,024 columns, 1,000,000 cells, 256 sheets and
16 MB of encoded input. Construction checks generators incrementally rather than first
materializing unbounded input. File readers check size and cap reads. Native
JSON parsing catches malformed/deep input as a format error. These bounds are
application guardrails, not a hard memory or CPU sandbox. Applications may
supply lower or higher finite positive limits. Workbooks enforce aggregate cell
limits when assembled/loaded/serialized.

Use a small documented exception hierarchy rooted in `SpreadsheetError`, with
specific address, shape and format failures. Failed edits and calculated column
construction must leave the original object intact.

## Serialization and presentation

| Format | v0.1 read | v0.1 write | Fidelity |
| --- | --- | --- | --- |
| Native JSON schema v1 | Yes | Yes | Typed cells, formulas, cache, format hint, sheet names |
| CSV / TSV | Yes | Yes | Text input; values output; explicit formula mode |
| Markdown table | Deferred | Yes | Displayed values or explicit formula text |
| HTML table | Deferred | Yes | Escaped displayed values or formula text |
| ANSI/plain terminal | Deferred | Yes | Display only, bounded cell width |
| XLSX | v0.3 | v0.3 | Contract and corpus required |
| Google Sheets | v0.4 | v0.4 | Separate authentication/transport adapter |

Text methods return strings and optionally write a supplied path. `from_csv` and
`from_json` accept text; `read_csv` and `read_json` accept paths, avoiding guesses
about whether a string is a filename. UTF-8 writes use replacement through a
temporary file in the destination directory. CSV does not preserve Python types,
blank-versus-empty text, formula metadata or formatting. Text injection escaping
also intentionally changes some strings; native JSON is the faithful interchange.

Renderers use a small immutable table document separate from live spreadsheet
objects. They do not interpret user HTML, Markdown links or terminal escapes.
Number-format hints do not imply a locale/Excel formatting implementation.

## Typed Markdown extraction

Inspection of Pretty Notebook at `32c0bda4ba2a74ea60f9df99eb33155074d02713`
confirmed generic-looking `Table`, `TableRow`, `TableCell`, source spans and
alignment support in `src/pretty_notebook/markdown/nodes.py`, with parser/dialect
and notebook-aware renderer integration across adjacent modules. Copying the
whole parser would import a much larger contract and maintenance surface.

For v0.1, use a native table serializer and keep the document boundary explicit.
Track **MD-01** as a later cross-repository extraction task: identify the generic
node/parser/renderer surface; preserve source spans, bounded parsing and existing
conformance fixtures; keep wiki links, routes, publication and notebook metadata
in Pretty Notebook; create an independent package only after its distribution,
license and public API are selected; then add an optional adapter here. There
must be no new mandatory runtime dependency or duplicate notebook parser.
Spreadsheet `Table` and document `Table` must remain separate models.

## Delivery queue and PR boundaries

GitHub issues and Project status are the live queue; this document records the
adopted architecture and acceptance gates. Start with the scaffold, plan, MIT
license and CI on main, then deliver five focused dependent PRs:

| Task | Scope | Dependency | Validation |
| --- | --- | --- | --- |
| CORE-01 | Cells, scalar validation, limits, A1 grid, workbook | Scaffold | Types, formulas, addresses, bounds, mutation atomicity |
| TABLE-01 | Records, rows/columns, live views, filtering, sorting, column edits | CORE-01 | Empty/ragged input, stable selection, formula locations, failed edits |
| IO-01 | CSV/TSV and strict versioned JSON, bounded atomic file I/O | TABLE-01 | Typed round trips, malformed schemas, duplicate keys, safe CSV |
| RENDER-01 | Markdown/HTML/ANSI table output, document boundary, examples | IO-01 | Escaping, controls, Unicode, widths, file output, executable examples |
| REL-01 | Complete docs, artifact checks, release.yaml, pypi, publication | RENDER-01 | Platform CI, installed suites, archive/source parity, fresh PyPI install |

Each task has its own `type/TASK-ID-short-name` branch, tests, Conventional Commit
and issue-linked PR. Push ready work, start CI, then begin the next task. Stack
dependent PRs against their parent so each diff stays focused. Squash merge
passing parents oldest first, retaining parent branches while open dependents
target them. Fetch main, reconcile each child without rewriting shared history,
retarget, verify the focused diff and run fresh checks. Remove completed branches
only after checking for open dependents. Verify the final main tree and CI.

Do not include the private gist, local path references, tool transcripts or local
working notes in distributions. A concise implementation checkpoint belongs in
the conversation while a batch is unfinished; commits, PRs and issues retain the
completed history.

## Test and packaging strategy

Use `unittest` from the standard library and no test runtime dependencies. Tests
exercise observable contracts, adversarial input and integration paths. The
smallest affected module runs during implementation; the complete relevant
suite runs before a PR is ready. CI covers Python 3.14 on Linux, macOS and Windows.

Artifact verification must build wheel/source, reject unexpected files and
links, compare package files to reviewed source, validate metadata and empty
runtime requirements, rebuild the source archive into an identical wheel and
install both artifacts in independent environments outside the checkout. Run
the installed public API suite and examples there, with no editable import path.
The release job reuses checks and publishes only these verified artifacts.

## Release operation

1. Confirm all five task scopes and docs agree, final-main CI passes and the
   source tree is clean. Ensure the version is 0.1.0 in metadata/public API.
2. Configure `pypi` with custom tag deployment policy allowing `v0.1.0`. Check
   PyPI's pending publisher identity matches `outside-labs`, repository
   `headless_spreadsheets`, workflow `release.yaml` and environment `pypi`.
3. Push immutable `v0.1.0` at the verified main SHA. `release.yaml` reuses the
   platform checks, verifies tag/version and main ancestry, builds/inspects/tests
   distributions and uploads the exact pair as a workflow artifact.
4. A separate minimal job obtains OIDC permission inside `pypi` and publishes
   with the PyPA action. No long-lived PyPI token is required or printed.
5. Download the exact build artifact and compare SHA256 values with PyPI JSON
   and downloaded registry files. Install uncached from PyPI in a new environment
   and run the tests/examples. Create the matching GitHub release with verified
   wheel/source assets and concise capability/limitation notes.
6. Close release issue, record immutable receipts and mark Project scope Done.

If Trusted Publishing rejects the identity, diagnose the exact publisher
configuration and preserve the verified artifacts/tag. Stop only if an account
setting requires user access, reporting the precise needed change. Do not change
the name, replace an uploaded file or silently substitute a token.

## Later milestones and decision gates

### v0.2 — formula engine (FORM-01)

Tokenize and parse to typed expressions; never use Python `eval`. Support
arithmetic, comparison, A1/absolute references, ranges and selected functions
(`SUM`, `AVERAGE`, `MIN`, `MAX`, `COUNT`, `IF`, `AND`, `OR`, `ROUND`). Define
spreadsheet error values, blank/text coercion, lazy IF branches, circular
references and function registration. Add dependency tracking, dirty-cell
invalidation and incremental recalculation before concurrency. Preserve unknown
formulas verbatim with explicit stale caches. Add `F.col` only with an explicit
coordinate translation and copy/sort policy. Acceptance requires fixture parity
for the declared Excel/Sheets subset and resource limits on expressions/ranges.

### v0.3 — XLSX (XLSX-01)

Use `zipfile` and XML with bounded archive expansion, member/path validation and
strict relationships. Specify supported shared/inline strings, formula/cache
pairs, style/date serials including 1900/1904 systems, multiple sheets and
recalculation hints. Define rejection/preservation of shared/array formulas,
external links and unsupported features. Test a real Excel/LibreOffice corpus
without promising full file preservation. Legacy XLS, macros and rendering
fidelity remain outside scope.

### v0.4 — Google Sheets (GOOGLE-01)

Separate service JSON mapping from HTTP/authentication. Preserve user-entered,
effective and formatted values without treating cached data as freshly computed.
Select credential ownership, token refresh, request quotas, retries, partial
failure and write confirmation contracts before an authenticated connector.
Provide transport injection and async-friendly I/O only where useful. No cloud
credential workflow is needed for local use.

### v0.5 — advanced table operations (OPS-01)

Group/aggregate, joins, named ranges, type inference, streaming and dataclass
adapters require individually selected semantics for missing values, collisions,
ordering, formulas and resource bounds. Benchmark ordinary workloads before
claiming speed gains. Async does not accelerate CPU calculations by itself;
incremental recomputation is the first optimization.

### Later — reversible edits (HISTORY-01)

Explore cell-level change records, undo/redo and diff with explicit transaction,
identity, persistence and retention contracts. This is an independent feature,
not implied by immutable cell snapshots or table views in v0.1.

## Primary references

- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [uv with GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)
- [Python CSV documentation](https://docs.python.org/3.14/library/csv.html)
- [Pretty Notebook typed Markdown](https://github.com/outside-labs/pretty-notebook/tree/main/src/pretty_notebook/markdown)
