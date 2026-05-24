"""Sweep-parquet discovery for the Phase-6 UI.

SPECS §11.2 contract. Pure pandas + pathlib; NO streamlit imports at
module-time per §11.1, so this module is unit-testable in a regular
pytest context without a Streamlit runtime.

Two helpers:
  - ``find_latest_sweep(results_dir)`` returns the newest-mtime
    ``sweep_*.parquet`` (excluding ``*_skipped.parquet``), or ``None``
    when no candidates exist. ``app.py`` renders a "no sweeps yet"
    empty state on ``None``.
  - ``read_sweep_with_skips(parquet_path)`` returns
    ``(results_df, skips_df)``. The companion skips parquet is
    optional; when missing we return the canonical empty skips frame
    (NOT ``None``) so callers can ``.groupby('skip_reason')``
    unconditionally.

The mtime convention is load-bearing per DESIGN_SPEC §1.5 — matches
the operator's "the sweep I just ran" mental model. The "largest by
row count" alternative (used by ``scripts/verify_p5.py``) is rejected
here because a stale-but-big historical sweep would silently outrank
a fresh small one.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import RESULTS_DIR
from src.engine.results import empty_skips_frame, skips_path


def find_latest_sweep(results_dir: Path = RESULTS_DIR) -> Path | None:
    """Return the newest-mtime ``sweep_*.parquet`` under ``results_dir``,
    excluding the companion ``*_skipped.parquet`` files. Returns ``None``
    if no candidates exist (caller renders an empty state).

    Mtime ties (rare; same-second writes) are broken by ``Path.name``
    ascending — deterministic across re-listings even though the OS
    doesn't guarantee a stable order for same-mtime files."""
    if not results_dir.exists():
        return None
    candidates = [
        p for p in results_dir.glob("sweep_*.parquet")
        if "_skipped" not in p.name
    ]
    if not candidates:
        return None
    # Sort by (mtime DESC, name ASC) so the freshest wins; ties broken
    # deterministically by name.
    candidates.sort(key=lambda p: (-p.stat().st_mtime, p.name))
    return candidates[0]


def read_sweep_with_skips(
    parquet_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the sweep results parquet + its companion skips parquet.

    Returns ``(results_df, skips_df)``. ``skips_df`` is the canonical
    empty skips frame if no companion file exists — NOT ``None`` — so
    callers like ``skips_df.groupby('skip_reason')`` work
    unconditionally.

    Raises ``FileNotFoundError`` if the results parquet itself doesn't
    exist (the caller should have checked via ``find_latest_sweep``
    first; this is a defensive raise for direct callers passing a
    stale path)."""
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"sweep parquet not found: {parquet_path}"
        )
    results_df = pd.read_parquet(parquet_path)

    # The companion skips parquet shares the run_id; derive its path
    # from the results path's filename. ``skips_path()`` builds the
    # canonical name; we strip the "sweep_" prefix + ".parquet" suffix
    # to recover the run_id.
    stem = parquet_path.stem  # e.g. "sweep_bde92aef8573"
    if stem.startswith("sweep_"):
        run_id = stem[len("sweep_"):]
    else:
        # Non-canonical filename — caller built the path themselves.
        # Fall back to empty skips; we won't guess the run_id.
        return results_df, empty_skips_frame()

    skips_companion = skips_path(run_id, name="sweep")
    if not skips_companion.exists():
        return results_df, empty_skips_frame()
    return results_df, pd.read_parquet(skips_companion)
