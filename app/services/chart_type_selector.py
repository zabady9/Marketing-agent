"""Rule-based chart type selector.

Deterministically selects the correct VisualType for a given data shape,
using an explicitly ordered if/elif chain. Each rule is placed before the
next for a documented reason — see inline comments.

Never uses an LLM. This is the single highest-leverage addition to prevent
"why did it choose a bar chart here" issues from being implicit in prompts.
"""
from __future__ import annotations

from typing import Literal

from app.agents.visual_schema import VisualType

DataShape = Literal[
    "time_series",       # Values over time (dates/timestamps as x-axis)
    "categorical",       # Values across discrete categories
    "proportional",      # Parts-of-whole (segments sum to 100% / a total)
    "multi_attribute",   # Multiple attributes compared across 2-3 entities (spider/radar)
    "single_metric",     # One KPI vs. a target or maximum
    "entity_comparison", # Named entities compared on a few attributes (mix of text + number)
    "event_sequence",    # Events with dates or milestones (no y-axis value)
    "term_frequency",    # Frequency-weighted terms or keywords
]


def select_chart_type(
    data_shape: DataShape,
    n_series: int,
    n_categories: int,
) -> VisualType:
    """Return the best VisualType for the given data characteristics.

    Parameters
    ----------
    data_shape:
        Semantic shape of the data (see DataShape literal above).
    n_series:
        Number of distinct series/entities (e.g. 2 companies → 2).
    n_categories:
        Number of categories, time points, or attributes (e.g. 5 years → 5).

    Returns
    -------
    One of the 14 supported VisualType values.
    """

    # 1. Event sequence first: "dates" alone does not imply a trend; events have
    #    labels, not values. Must precede time_series checks or milestone data
    #    would be misclassified as line_chart.
    if data_shape == "event_sequence":
        return "timeline"

    # 2. Single KPI before time_series: gauge requires exactly one value + a
    #    target/max. If checked after time_series, a single-point series would
    #    incorrectly become line_chart.
    if data_shape == "single_metric":
        return "gauge"

    # 3. Multi-series time data before single-series: area_chart requires
    #    n_series > 1. Checked before line_chart so "dates + multiple series"
    #    doesn't fall through to line_chart.
    if data_shape == "time_series" and n_series > 1:
        return "area_chart"

    # 4. Single-series time data: the base case after multi-series is handled.
    if data_shape == "time_series":
        return "line_chart"

    # 5. Proportional data: parts-of-whole semantics. Checked before categorical
    #    because proportional is a strict subset (categories summing to a whole).
    #    Cap at 6 segments — beyond that a table reads better.
    if data_shape == "proportional" and n_categories <= 6:
        return "pie_chart"   # Caller may request donut_chart via UI preference

    # 6. Multi-attribute: radar requires 4-7 attributes AND 2-3 entities.
    #    Checked before entity_comparison to avoid sending sparse comparisons
    #    (< 4 attributes) to radar.
    if (
        data_shape == "multi_attribute"
        and 4 <= n_categories <= 7
        and 2 <= n_series <= 3
    ):
        return "radar_chart"

    # 7. Entity comparison with few entities: comparison_grid handles mixed
    #    text/numeric attributes. Checked before table so entity-centric data
    #    with prose values isn't forced into a numeric-only table.
    if data_shape == "entity_comparison" and n_series < 3:
        return "comparison_grid"

    # 8. Dense numeric table: 3+ entities × 3+ metrics (numeric values).
    #    Catches what slipped past comparison_grid.
    if n_series >= 3 and n_categories >= 3:
        return "table"

    # 9. Term frequency: word_cloud is the only type that meaningfully encodes
    #    frequency weight.
    if data_shape == "term_frequency":
        return "word_cloud"

    # 10. Default: any remaining categorical data becomes a bar chart.
    return "bar_chart"
