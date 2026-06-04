"""NSE Corporate Events loader — earnings-filter source.

PORTFOLIO_MEMOIR.md §17. The operator-delivered CSV
``CF-Event-equities-{from}-to-{to}.csv`` at the repo root lists every
board meeting NSE-listed companies filed under Reg 29(1)(a) for the
covered window (memoir §17.2 schema: SYMBOL / COMPANY / PURPOSE /
DETAILS / DATE, DD-Mon-YYYY).

The DATE column is the BOARD-MEETING date (= results-announcement
day for the rows we keep). The Reg 29(1)(a) notice itself is filed
5-14 days BEFORE the meeting; the memoir §17.7 acknowledges using
the meeting date directly is a 5-14 day lookahead vs strictly-public
knowledge, which is acceptable per the operator's intent
(avoid the earnings event, not model exact lead-time).

Public API:

  ``load_events(csv_path=None, *, force_refresh=False) -> pd.DataFrame``
      Cache-first loader. Reads CSV, filters to ``PURPOSE`` containing
      "Financial Results" per §17.5, normalizes whitespace + dates,
      writes ``data/cache/events.parquet`` for re-use, returns the
      DataFrame. Auto-rebuilds if the CSV mtime is newer than the
      cached parquet.

  ``has_earnings_in_window(events_df, symbol, entry_date, exit_date)
                            -> bool``
      §17.5 / F10 filter: True if any Financial Results event for
      ``symbol`` falls in ``[entry_date, exit_date + 1 day]``. The
      +1 day buffer catches the case where exit is the day before
      announcement (vol still elevated, gap risk present).

Cache schema (canonical):
    SYMBOL  StringDtype  — NSE trading symbol (stripped, uppercase
                            preserved from source)
    PURPOSE StringDtype  — the raw "PURPOSE" CSV column (stripped;
                            may be multi-category, slash-separated)
    DATE    datetime64[us] — board-meeting date

The cache holds ONLY rows whose PURPOSE contains "Financial Results"
(per §17.5). Other PURPOSE rows — Dividend, Fund Raising, etc. — are
dropped at parse time so downstream consumers can't accidentally
filter on a wider event set without re-reading the raw CSV.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.data import cache

_REPO = Path(__file__).resolve().parent.parent.parent

# Canonical output schema. Pin here so a future contributor adding
# columns to the parquet has to update one tuple, not seven assertions.
EVENTS_COLUMNS: tuple[str, ...] = ("SYMBOL", "PURPOSE", "DATE")


def _default_csv_path() -> Path:
    """Find the operator-delivered CSV at the repo root.

    Matches ``CF-Event-equities-*.csv``. If multiple files match
    (different export windows), returns the lexicographically last
    one — the operator can pass an explicit ``csv_path`` to override.
    """
    matches = sorted(_REPO.glob("CF-Event-equities-*.csv"))
    if not matches:
        raise FileNotFoundError(
            f"no CF-Event-equities-*.csv at repo root ({_REPO}). "
            f"Export from NSE Corporate Events feed per "
            f"PORTFOLIO_MEMOIR.md §17.1, or pass ``csv_path=`` to "
            f"point at a specific file."
        )
    return matches[-1]


def _empty_frame() -> pd.DataFrame:
    """Empty frame with the canonical schema — returned by
    ``load_events`` when the CSV exists but contains zero Financial
    Results rows (operator triage edge case)."""
    return pd.DataFrame({
        "SYMBOL": pd.Series(dtype="string"),
        "PURPOSE": pd.Series(dtype="string"),
        "DATE": pd.Series(dtype="datetime64[us]"),
    })


def _parse_csv(path: Path) -> pd.DataFrame:
    """Parse the raw CSV into the canonical schema.

    Handles:
      - BOM + trailing-whitespace column names ("SYMBOL " etc.).
      - Free-text NSE date format "DD-Mon-YYYY" with mixed case.
      - Per-cell whitespace around symbol and purpose strings.
      - Multi-category PURPOSE (kept as-is for caller pattern matching).

    Drops any row whose PURPOSE doesn't contain "Financial Results"
    per §17.5, and any row whose DATE failed to parse.
    """
    df = pd.read_csv(path)
    # Strip whitespace + newlines from column NAMES (the CSV header
    # ships with literal newlines inside quoted column labels — see
    # operator's file).
    df.columns = [c.strip() for c in df.columns]
    missing = set(EVENTS_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"events CSV at {path} missing required columns "
            f"{sorted(missing)}; got {list(df.columns)}"
        )
    out = pd.DataFrame({
        "SYMBOL": df["SYMBOL"].astype(str).str.strip().astype("string"),
        "PURPOSE": df["PURPOSE"].astype(str).str.strip().astype("string"),
        "DATE": pd.to_datetime(
            df["DATE"].astype(str).str.strip(),
            format="%d-%b-%Y", errors="coerce",
        ),
    })
    # Per §17.5: keep ONLY Financial Results rows. Dividend, Fund
    # Raising, Stock Split, etc. don't move IV the way earnings do
    # and shouldn't be in the filter set downstream. Multi-category
    # values like "Financial Results/Dividend" survive (the dominant
    # tag is Financial Results) — substring match is intentional.
    out = out[out["PURPOSE"].str.contains("Financial Results", na=False)]
    # Drop rows where the DATE didn't parse (typos in the source).
    out = out.dropna(subset=["DATE"]).copy()
    out["DATE"] = out["DATE"].astype("datetime64[us]")
    return (
        out[list(EVENTS_COLUMNS)]
        .sort_values(["SYMBOL", "DATE"])
        .reset_index(drop=True)
    )


def load_events(
    csv_path: Path | None = None,
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return all Financial Results events from the NSE Corporate
    Events feed, indexed by canonical schema.

    Cache-first behavior:
      - If ``data/cache/events.parquet`` exists AND the source CSV
        is older than the cache → return the cached frame.
      - If the CSV is newer (operator dropped in a fresh export)
        → reparse and rewrite the cache.
      - If the cache exists but the CSV is gone (fresh clone where
        the operator hasn't yet re-downloaded) → return the cached
        frame anyway; better than failing.
      - If neither exists → ``FileNotFoundError``.

    ``force_refresh=True`` always reparses the CSV.

    See module docstring for the cache schema.
    """
    cache_path = cache.events_path()
    try:
        resolved_csv = csv_path or _default_csv_path()
    except FileNotFoundError:
        resolved_csv = None

    use_cache = (
        not force_refresh
        and cache.exists(cache_path)
        and (
            resolved_csv is None
            or resolved_csv.stat().st_mtime <= cache_path.stat().st_mtime
        )
    )
    if use_cache:
        return cache.read(cache_path)

    if resolved_csv is None:
        raise FileNotFoundError(
            f"events cache at {cache_path} not present AND no CSV "
            f"available to build from. Drop a "
            f"CF-Event-equities-*.csv at the repo root."
        )

    df = _parse_csv(resolved_csv)
    if df.empty:
        # Don't write an empty parquet — that would make the cache
        # path exist but carry no information. Caller gets an empty
        # frame with the canonical schema; next call will retry the
        # CSV parse.
        return _empty_frame()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache.write(cache_path, df, overwrite=True)
    return df


def has_earnings_in_window(
    events_df: pd.DataFrame,
    symbol: str,
    entry_date: date,
    exit_date: date,
) -> bool:
    """True if any Financial Results event for ``symbol`` lands in the
    inclusive window ``[entry_date, exit_date + 1 calendar day]``.

    Per PORTFOLIO_MEMOIR.md §21.4 F10 + §17.5:

      - Filter strictly on the SYMBOL exact match (NSE tickers are
        uppercase; we uppercase the input symbol defensively).
      - The +1 calendar day buffer after exit catches the case where
        exit is the day BEFORE the announcement — vol is still
        elevated and gap-overnight risk is present.
      - PURPOSE is re-checked here even though ``load_events``
        already filtered to Financial Results: defense-in-depth in
        case a future caller passes a hand-built frame.

    Returns ``False`` immediately on an empty input frame (cold
    cache → conservative "no filter triggered" rather than raising).
    """
    if events_df.empty:
        return False
    sym = symbol.upper()
    ts_entry = pd.Timestamp(entry_date)
    ts_exit_plus = pd.Timestamp(exit_date) + pd.Timedelta(days=1)
    mask = (
        (events_df["SYMBOL"] == sym)
        & events_df["PURPOSE"].str.contains("Financial Results", na=False)
        & (events_df["DATE"] >= ts_entry)
        & (events_df["DATE"] <= ts_exit_plus)
    )
    return bool(mask.any())
