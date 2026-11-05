"""Chart suggestion helpers for QueryPilot query results."""
from __future__ import annotations

from typing import Any


def suggest_chart(rows: list[dict[str, Any]]) -> dict[str, str] | None:
    """Suggest a chart from result shape without changing the result data."""
    if len(rows) < 2:
        return None

    columns = list(rows[0].keys())
    numeric_columns = [
        column for column in columns
        if any(_is_number(row.get(column)) for row in rows)
        and all(
            row.get(column) in (None, "") or _is_number(row.get(column))
            for row in rows
        )
    ]
    categorical_columns = [column for column in columns if column not in numeric_columns]

    if not numeric_columns or not categorical_columns:
        return None

    date_columns = [
        column for column in categorical_columns
        if any(token in column.lower() for token in ("date", "month", "year", "week", "period"))
    ]
    preferred_numeric = [
        column for column in numeric_columns
        if any(
            token in column.lower()
            for token in ("revenue", "sales", "amount", "total", "count", "number",
                          "quantity", "average", "payroll", "salary", "deduction",
                          "hours", "percentage", "rate")
        )
    ]
    y_column = preferred_numeric[0] if preferred_numeric else numeric_columns[0]

    if date_columns:
        other_categories = [c for c in categorical_columns if c not in date_columns]
        if len(other_categories) == 1:
            return {
                "type": "grouped_bar",
                "x": date_columns[0],
                "y": y_column,
                "color": other_categories[0],
                "title": f"{_label(y_column)} by {_label(date_columns[0])} and {_label(other_categories[0])}",
            }
        if len(other_categories) == 0:
            return {
                "type": "line",
                "x": date_columns[0],
                "y": y_column,
                "title": f"{_label(y_column)} over time",
            }
        return None

    if len(categorical_columns) == 2:
        cardinalities = {
            column: len({row.get(column) for row in rows})
            for column in categorical_columns
        }
        color_column = min(categorical_columns, key=lambda column: cardinalities[column])
        x_column = next(column for column in categorical_columns if column != color_column)
        if cardinalities[x_column] <= 15 and cardinalities[color_column] <= 8:
            return {
                "type": "grouped_bar",
                "x": x_column,
                "y": y_column,
                "color": color_column,
                "title": f"{_label(y_column)} by {_label(x_column)} and {_label(color_column)}",
            }
        return None

    if len(categorical_columns) == 1:
        x_column = categorical_columns[0]
        if len({row.get(x_column) for row in rows}) <= 20:
            return {
                "type": "bar",
                "x": x_column,
                "y": y_column,
                "title": f"{_label(y_column)} by {_label(x_column)}",
            }
    return None


def _label(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _is_number(value: Any) -> bool:
    if value is None or value == "":
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
