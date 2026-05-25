"""Shared filter helpers for the Phase-6 tabs.

Three tab modules (heatmap, trends, per_stock) all need
``df[(df["strategy"] == X) & (df["symbol"] == Y)]`` — extracting it
here removes duplication AND gives a single place to add ergonomics
later (e.g., regime filter post-classification per §1.2).

Pure pandas; no streamlit imports.
"""
from __future__ import annotations

import pandas as pd


def filter_pair(
    df: pd.DataFrame,
    *,
    strategy: str | None,
    symbol: str | None,
) -> pd.DataFrame:
    """Return the subset of ``df`` matching ``strategy`` and ``symbol``.

    Either may be ``None`` to skip that filter — useful when a tab
    aggregates across one axis but pins the other (e.g., per_stock
    pins symbol but iterates strategies)."""
    out = df
    if strategy is not None:
        out = out[out["strategy"] == strategy]
    if symbol is not None:
        out = out[out["symbol"] == symbol]
    return out
