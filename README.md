# Headless Spreadsheets

Spreadsheet-native tables for ordinary Python applications. Pure Python 3.14+,
with zero runtime dependencies and an MIT license.

Version 0.1.0 is in development. See [the implementation plan](IMPLEMENTATION_PLAN.md)
for the selected table, interchange and presentation scope and later milestones.

## Development

```sh
uv sync --locked
uv run --frozen python -W error::ResourceWarning -m unittest discover -s tests -v
```
