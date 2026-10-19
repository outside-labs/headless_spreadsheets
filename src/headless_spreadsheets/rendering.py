"""Immutable presentation documents and safe table-only renderers."""

from __future__ import annotations

import html
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .core import DEFAULT_LIMITS
from .errors import SpreadsheetError
from .serialization import scalar_text

if TYPE_CHECKING:
    from .table import _Tabular

type Alignment = Literal["left", "right", "center"]


def _newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _markdown(text: str) -> str:
    text = html.escape(_newlines(text), quote=False)
    return "".join("\\" + character if character in "\\`*_[]|~" else character for character in text).replace("\n", "<br>")


def _html(text: str) -> str:
    return html.escape(_newlines(text), quote=True).replace("\n", "<br>")


def _terminal(text: str) -> str:
    result = []
    for character in text:
        if character in {"\n", "\r", "\t"}:
            result.append({"\n": r"\n", "\r": r"\r", "\t": r"\t"}[character])
        elif unicodedata.category(character).startswith("C"):
            number = ord(character)
            result.append(f"\\x{number:02x}" if number < 256 else f"\\u{number:04x}")
        else:
            result.append(character)
    return "".join(result)


def _width(text: str) -> int:
    return sum(0 if unicodedata.combining(character) else 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1 for character in text)


def _truncate(text: str, maximum: int) -> str:
    if _width(text) <= maximum:
        return text
    result = []
    width = 0
    for character in text:
        size = _width(character)
        if width + size > maximum - 1:
            break
        result.append(character)
        width += size
    return "".join(result) + "…"


@dataclass(frozen=True, slots=True)
class TableDocument:
    """Display text detached from live cells; this is not a spreadsheet model.

    Construct from tuples or use ``table.to_document()``. Number formats and
    formulas are not interpreted. Rendering methods return text only.
    """

    headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    alignments: tuple[Alignment, ...] = ()

    def __post_init__(self) -> None:
        if type(self.headers) is not tuple or type(self.rows) is not tuple or type(self.alignments) is not tuple:
            raise SpreadsheetError("A table document must use immutable tuples.")
        if not self.alignments:
            object.__setattr__(self, "alignments", ("left",) * len(self.headers))
        if len(self.alignments) != len(self.headers) or any(value not in {"left", "right", "center"} for value in self.alignments):
            raise SpreadsheetError("Each document column needs a left, right or center alignment.")
        if not all(isinstance(value, str) for value in self.headers):
            raise SpreadsheetError("Document headers must be strings.")
        for row in self.rows:
            if type(row) is not tuple or len(row) != len(self.headers) or not all(isinstance(value, str) for value in row):
                raise SpreadsheetError("Document rows must be tuples of text matching the headers.")

    @classmethod
    def from_table(cls, table: _Tabular, *, formulas: bool = False) -> TableDocument:
        if type(formulas) is not bool:
            raise SpreadsheetError("Formula display must be Boolean.")
        rows = []
        numeric = [False] * len(table.columns)
        other = [False] * len(table.columns)
        for row in table:
            values = []
            for position, name in enumerate(table.columns):
                cell = row.cell(name)
                formula = cell.formula if formulas else None
                values.append(formula if formula is not None else scalar_text(cell.value))
                if formula is not None or (cell.value is not None and cell.data_type not in {"integer", "number", "decimal"}):
                    other[position] = True
                elif cell.value is not None:
                    numeric[position] = True
            rows.append(tuple(values))
        alignments = tuple("right" if number and not text else "left" for number, text in zip(numeric, other, strict=True))
        return cls(table.columns, tuple(rows), alignments)

    def to_markdown(self) -> str:
        if not self.headers:
            return ""
        def row(values):
            return "| " + " | ".join(_markdown(value) for value in values) + " |"
        markers = {"left": ":---", "right": "---:", "center": ":---:"}
        lines = [row(self.headers), "| " + " | ".join(markers[value] for value in self.alignments) + " |"]
        lines.extend(row(values) for values in self.rows)
        return "\n".join(lines) + "\n"

    def to_html(self) -> str:
        if not self.headers:
            return ""
        def row(values, header=False):
            tag = "th" if header else "td"
            scope = ' scope="col"' if header else ""
            cells = [f'<{tag}{scope} style="text-align: {alignment};">{_html(value)}</{tag}>' for value, alignment in zip(values, self.alignments, strict=True)]
            return "<tr>" + "".join(cells) + "</tr>\n"
        return "<table>\n<thead>\n" + row(self.headers, True) + "</thead>\n<tbody>\n" + "".join(row(values) for values in self.rows) + "</tbody>\n</table>\n"

    def to_ansi(self, *, max_width: int = 32, color: bool = False) -> str:
        """Render one physical line per row using approximate Unicode cell widths."""
        if type(max_width) is not int or not 1 <= max_width <= DEFAULT_LIMITS.max_input_bytes:
            raise SpreadsheetError("max_width must be a positive integer within the text size limit.")
        if type(color) is not bool:
            raise SpreadsheetError("Terminal color must be Boolean.")
        if not self.headers:
            return ""
        all_rows = [tuple(_terminal(value) for value in row) for row in (self.headers, *self.rows)]
        widths = [min(max_width, max(_width(row[index]) for row in all_rows)) for index in range(len(self.headers))]
        border = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

        def row(values):
            fields = []
            for text, width, alignment in zip(values, widths, self.alignments, strict=True):
                text = _truncate(text, width)
                extra = width - _width(text)
                left = extra if alignment == "right" else extra // 2 if alignment == "center" else 0
                fields.append(" " * left + text + " " * (extra - left))
            return "| " + " | ".join(fields) + " |"

        header = row(all_rows[0])
        if color:
            header = "\x1b[1;36m" + header + "\x1b[0m"
        return "\n".join([border, header, border, *(row(values) for values in all_rows[1:]), border]) + "\n"

    def render(self, format: str, **options) -> str:
        methods = {"markdown": self.to_markdown, "html": self.to_html, "ansi": self.to_ansi}
        if format not in methods:
            raise SpreadsheetError("Expected format='markdown', 'html' or 'ansi'.")
        return methods[format](**options)
