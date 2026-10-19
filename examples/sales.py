"""A standalone table, formula-preserving storage and three display formats."""

from headless_spreadsheets import Table


def main() -> None:
    sales = Table.from_records([
        {"item": "Book", "price": 12, "quantity": 3},
        {"item": "Pen", "price": 2, "quantity": 10},
        {"item": "Bag", "price": 25, "quantity": 2},
    ])
    sales.add_column("total", lambda row: row["price"] * row["quantity"])
    sales.set_formula("D2", "=B2*C2", cached_value=36)
    restored = Table.from_json(sales.to_json())
    assert restored.cell("D2").formula == "=B2*C2"
    assert restored.cell("D2").cache_status == "stale"
    selected = restored.where(total__gte=30).sort_by("total", reverse=True).select("item", "total")
    assert selected["item"][:] == ("Bag", "Book")
    assert selected.source_address("B3") == "D2"
    assert selected.to_table().cell("B3").formula is None
    for format in ("markdown", "html", "ansi"):
        print(selected.render(format))


if __name__ == "__main__":
    main()
