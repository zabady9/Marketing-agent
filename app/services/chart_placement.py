"""Chart placement resolver for report-level visualization.

Determines after which paragraph in the synthesis markdown each generated
chart should be anchored. Used only in report mode (SWOT, PESTEL, feasibility,
market_research, general_analysis) where the full synthesis text is available
before charts are attached.

Strategy: map each chart's title tokens against section headings in the markdown.
The chart is placed immediately after the paragraph that contains the most
overlapping terms. Ties are broken by order of appearance. Unmatched charts
are placed at the end.
"""
from __future__ import annotations

import re

from app.agents.visual_schema import VisualBlock


def _heading_paragraphs(markdown: str) -> list[tuple[str, int]]:
    """Return [(section_heading_lower, paragraph_index)] for each heading found."""
    result = []
    # Split by double newlines to get paragraphs, then find headings
    paras = re.split(r"\n{2,}", markdown)
    for idx, para in enumerate(paras):
        heading_match = re.match(r"^#{1,4}\s+(.+)", para.strip())
        if heading_match:
            result.append((heading_match.group(1).lower(), idx))
    return result


def _tokenize(text: str) -> frozenset[str]:
    _STOP = {"a", "an", "the", "of", "in", "by", "for", "and", "or", "vs", "chart"}
    return frozenset(
        t for t in re.findall(r"[a-z0-9]+", text.lower())
        if t not in _STOP and len(t) > 1
    )


def resolve_placement(
    synthesis_markdown: str,
    visuals: list[VisualBlock],
) -> list[tuple[VisualBlock, int]]:
    """Assign each visual to the paragraph index it should follow.

    Parameters
    ----------
    synthesis_markdown:
        Full synthesis text from the Chief of Staff / generator.
    visuals:
        Validated VisualBlock list to place.

    Returns
    -------
    List of (visual, paragraph_index) pairs, sorted by paragraph_index so that
    the caller can insert charts in reading order. Unmatched visuals appear at
    the end (paragraph index = number of paragraphs).
    """
    paras = re.split(r"\n{2,}", synthesis_markdown)
    n_paras = len(paras)
    headings = _heading_paragraphs(synthesis_markdown)

    placed: list[tuple[VisualBlock, int]] = []
    used_indices: list[int] = []

    for visual in visuals:
        title_tokens = _tokenize(visual.title)
        best_para = n_paras  # default: end of document
        best_score = -1

        for heading, para_idx in headings:
            heading_tokens = _tokenize(heading)
            overlap = len(title_tokens & heading_tokens)
            if overlap > best_score and para_idx not in used_indices:
                best_score = overlap
                best_para = para_idx + 1  # place after the heading paragraph

        # If no heading matched, find the paragraph with the most title token overlap
        if best_score <= 0:
            for para_idx, para_text in enumerate(paras):
                para_tokens = _tokenize(para_text)
                overlap = len(title_tokens & para_tokens)
                if overlap > best_score and para_idx not in used_indices:
                    best_score = overlap
                    best_para = para_idx + 1

        used_indices.append(best_para)
        placed.append((visual, best_para))

    # Sort by paragraph index so caller inserts in document order
    placed.sort(key=lambda x: x[1])
    return placed
