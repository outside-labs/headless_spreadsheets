"""Spreadsheet-native tables and portable interchange for ordinary Python."""

from .core import Cell, CellInput, DataType, Limits, Scalar, Sheet, Workbook, column_name, split_address
from .errors import AddressError, FormatError, ShapeError, SpreadsheetError
from .table import Column, Row, Table, TableView

__version__ = "0.1.0"

__all__ = [
    "AddressError", "Cell", "CellInput", "DataType", "FormatError", "Limits",
    "Scalar", "ShapeError", "Sheet", "SpreadsheetError", "Workbook",
    "Column", "Row", "Table", "TableView", "column_name", "split_address",
]
