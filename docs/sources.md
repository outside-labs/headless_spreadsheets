# Read-only tabular sources

`TableSource(table_or_view)` exposes a complete bounded in-memory source.
`query(columns=["c2", "c1"], order=[("c1", False)], limit=50, generation=1)`
returns an immutable `TableSnapshot`: table/schema identity, declared
`SourceColumn` values, `SourceRow` keys, original `Cell` objects and source A1
addresses, request generation and optional continuation. Search accepts
`search={"fields": ["c1"], "term": "literal"}` with the tabular/1 case-sensitive
Unicode substring semantics, no normalization or wildcard syntax. Only declared
text columns may search. Defaults infer text capability from current cells;
applications can supply one explicit SourceColumn per selected source column.

Column IDs derive from original column positions and row keys from original
row positions, scoped by a random Table instance ID. New bindings and
sort/filter/projection views over that same Table retain these identities.
Reconstructed tables and process restarts do not. Revisions are null; this
binding exposes no editing or persistence capability. Durable adapters must
supply durable domain keys and checked row revisions. Duplicate labels in an
explicit column declaration are permitted; IDs must stay distinct. Duplicate
view row membership is refused because it would repeat a row identity.

Existing TableView membership stays fixed and its values stay live. Query
results capture immutable cells, including rich scalar values, formula source
locations, stale/missing caches and formats. Later Table.set operations cannot
change captured snapshots. No to_table conversion is used. Formula text is
opaque and never evaluated or relocated.

Sort nulls last in either direction, with stable original source order
for ties. Mixed incomparable native values fail explicitly. Source queries
admit 100,000 rows/1,000,000 cells and 128 source columns, 64 projected columns,
three sort fields, eight search fields, 256 query code points, 1,000 page rows
and 16,000 page cells. Configure a smaller page when projecting many columns.
There is no remote scan or implicit fetch-all operation. Cursors bind source,
schema, membership, projection and normalized query. Changed queries refuse old
cursors; concurrent value changes provide fresh pages, not frozen multi-page
snapshots. Refresh starts without a cursor. Generation is echoed independently
from schema identity and never claims a row revision.

`close()` refuses subsequent queries and releases this binding's table
reference. The caller retains ownership of the underlying Table. Keep mutations
and queries on the application's chosen thread; this source adds no locking or
background worker. Snapshots remain usable after close. The base package still
has no mandatory runtime dependencies.

Contract: [tabular/1](https://github.com/wispsy/compose_application/blob/d8c4e3a1d4cd1979222c0dddcbf0a14d44ee415c/docs/tabular-v1.md).
