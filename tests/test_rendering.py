"""Display output escapes content and never relocates or executes formulas."""

import dataclasses
import runpy
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from headless_spreadsheets import Cell, SpreadsheetError, Table, TableDocument


class RenderingTests(unittest.TestCase):
    def test_markdown_escapes_markup_pipes_html_and_multiline_text(self):
        table = Table(["name|x", "value"], [['<script>& [click](x) `a` *b* \\ |\nnext', 2]])
        text = table.to_markdown()
        self.assertIn(r"name\|x", text)
        self.assertIn("&lt;script&gt;&amp;", text)
        self.assertIn(r"\[click\](x)", text)
        self.assertIn(r"\`a\` \*b\* \\ \|<br>next", text)
        self.assertIn("| :--- | ---: |", text)
        self.assertNotIn("<script>", text)

    def test_html_is_escaped_and_has_semantic_headers(self):
        table = Table(['<img src=x onerror="bad()">'], [["<script>alert(1)</script>\n&\"'"]])
        text = table.to_html()
        self.assertIn('<th scope="col"', text)
        self.assertIn("&lt;img", text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;<br>&amp;&quot;&#x27;", text)
        self.assertNotIn("<img", text)
        self.assertNotIn("<script", text)

    def test_plain_terminal_sanitizes_input_escape_control_and_bidi_sequences(self):
        text = Table(["x"], [["\x1b[2J\x9b31m\n\t\r\u202eend"]]).to_ansi(max_width=100)
        for character in ("\x1b", "\x9b", "\u202e", "\t", "\r"):
            self.assertNotIn(character, text)
        self.assertIn(r"\x1b[2J\x9b31m\n\t\r\u202eend", text)

    def test_exact_plain_layout_unicode_truncation_and_generated_color(self):
        plain = TableDocument(("x", "n"), (("雪abc", "2"),), ("left", "right")).to_ansi(max_width=3)
        self.assertEqual(plain, "+-----+---+\n| x   | n |\n+-----+---+\n| 雪… | 2 |\n+-----+---+\n")
        colored = Table(["x"], [["\x1b[2J"]]).to_ansi(color=True)
        self.assertEqual(colored.count("\x1b"), 2)
        self.assertIn("\x1b[1;36m", colored)
        self.assertIn("\x1b[0m", colored)
        self.assertIn(r"\x1b[2J", colored)
        self.assertIn("…", Table(["x"], [["雪"]]).to_ansi(max_width=1))

    def test_formula_display_is_explicit_and_document_is_an_immutable_snapshot(self):
        table = Table(["total"], [[Cell(36, formula="=B2*C2", number_format="0.00")]])
        document = table.to_document()
        self.assertIn("36", document.to_markdown())
        self.assertNotIn("=B2", document.to_markdown())
        self.assertIn(r"=B2\*C2", table.to_markdown(formulas=True))
        table.set("A2", 99)
        self.assertEqual(document.rows, (("36",),))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            document.headers = ("new",)

    def test_empty_header_only_and_view_output(self):
        for format in ("markdown", "html", "ansi"):
            self.assertEqual(Table().render(format), "")
            self.assertIn("name", Table(["name"]).render(format))
            self.assertIn("Book", Table(["name", "n"], [["Book", 1]]).select("name").render(format))

    def test_invalid_presentation_options_are_explicit(self):
        table = Table(["x"], [[1]])
        for width in (0, -1, True, 1.5):
            with self.assertRaises(SpreadsheetError):
                table.to_ansi(max_width=width)
        with self.assertRaises(SpreadsheetError):
            table.render("xlsx")
        with self.assertRaises(SpreadsheetError):
            table.to_markdown(formulas=1)
        with self.assertRaises(SpreadsheetError):
            TableDocument(("a",), (("a", "b"),))
        with self.assertRaises(SpreadsheetError):
            TableDocument(["a"])

    def test_all_presentation_destinations_are_utf8(self):
        with tempfile.TemporaryDirectory() as directory:
            table = Table(["name"], [["雪"]])
            for format in ("markdown", "html", "ansi"):
                path = Path(directory) / format
                result = getattr(table, "to_" + format)(path)
                self.assertEqual(path.read_bytes().decode("utf-8"), result)

    def test_sales_example_executes(self):
        output = StringIO()
        with redirect_stdout(output):
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "sales.py"), run_name="__main__")
        self.assertIn("Bag", output.getvalue())
        self.assertIn("<table>", output.getvalue())
