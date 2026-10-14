"""Block schema: every type validates, and messy LLM output is repaired rather
than rejected (app/schemas/blocks.py)."""

from app.schemas.blocks import (
    BoardBlock,
    ChartBlock,
    ComparisonBlock,
    MatrixBlock,
    TableBlock,
    TextBlock,
    parse_block,
    parse_blocks,
)
from tests.test_export import ALL_BLOCKS


def test_every_block_type_validates_as_itself():
    parsed = parse_blocks(ALL_BLOCKS)
    assert [b.type for b in parsed] == [b["type"] for b in ALL_BLOCKS]


def test_chart_series_are_trimmed_and_padded_to_the_categories():
    block = parse_block({
        "type": "chart", "chart_type": "line", "categories": ["a", "b", "c"],
        "series": [{"name": "long", "data": [1, 2, 3, 4]}, {"name": "short", "data": [1]}],
    })
    assert isinstance(block, ChartBlock)
    assert block.series[0].data == [1, 2, 3]
    assert block.series[1].data == [1, None, None]


def test_unknown_and_aliased_chart_types_are_normalized():
    assert parse_block({"type": "chart", "chart_type": "combo", "categories": ["a"],
                        "series": [{"name": "s", "data": [1]}]}).chart_type == "bar"
    assert parse_block({"type": "chart", "chart_type": "Donut", "categories": ["a"],
                        "series": [{"name": "s", "data": [1]}]}).chart_type == "pie"


def test_pie_keeps_a_single_series():
    block = parse_block({"type": "chart", "chart_type": "pie", "categories": ["a", "b"],
                         "series": [{"name": "x", "data": [1, 2]}, {"name": "y", "data": [3, 4]}]})
    assert len(block.series) == 1


def test_table_rows_are_padded_and_cells_stringified():
    block = parse_block({"type": "table", "columns": ["a", "b", "c"], "rows": [[1, None], [1, 2, 3, 4]]})
    assert isinstance(block, TableBlock)
    assert block.rows == [["1", "", ""], ["1", "2", "3"]]


def test_comparison_scores_are_shaped_and_clamped():
    block = parse_block({"type": "comparison", "options": ["A", "B"], "criteria": ["x", "y"],
                         "scores": [[12, -3, 5]]})
    assert isinstance(block, ComparisonBlock)
    assert block.scores == [[10.0, 0.0], [None, None]]


def test_matrix_points_are_clamped_to_0_10():
    block = parse_block({"type": "matrix", "x_axis": "x", "y_axis": "y",
                         "points": [{"label": "p", "x": 14, "y": -2}]})
    assert isinstance(block, MatrixBlock)
    assert (block.points[0].x, block.points[0].y) == (10.0, 0.0)


def test_board_columns_count_is_clamped():
    block = parse_block({"type": "board", "columns_count": "9", "cells": [{"title": "S"}]})
    assert isinstance(block, BoardBlock)
    assert block.columns_count == 4


def test_invalid_block_becomes_text_keeping_its_content():
    block = parse_block({"type": "chart", "title": "Broken", "categories": [], "series": []})
    assert isinstance(block, TextBlock)
    assert block.title == "Broken"


def test_unknown_type_and_plain_strings_become_text():
    assert isinstance(parse_block({"type": "poem", "content": "roses"}), TextBlock)
    assert parse_block({"type": "poem", "content": "roses"}).markdown == "roses"
    assert parse_block("just text").markdown == "just text"


def test_stat_values_are_stringified():
    block = parse_block({"type": "stats", "items": [{"label": "n", "value": 1200}]})
    assert block.items[0].value == "1200"
