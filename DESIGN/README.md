# DESIGN/

Phase-6 UI design artifacts. Authored by the user (`mriddyagrawal`), referenced
by every Phase-6 implementation commit.

## Contents

- **[DESIGN_SPEC.md](DESIGN_SPEC.md)** — frozen UI architecture + 26-commit
  Phase-6 roadmap. Source of truth for tab structure, sidebar wiring,
  Plotly choices, colormap conventions, headline-stats contracts, and
  thin-data UX patterns. Departures land in §11 change log.

## Mockups

| Image | Tab | Implementing commits (DESIGN_SPEC §4) |
|---|---|---|
| [leaderboard.png](leaderboard.png) | Leaderboard | `feat(p6.2.headline)`, `feat(p6.2.table)`, `feat(p6.2.thin)`, `feat(p6.2.toggle)` |
| [per_stock.png](per_stock.png) | Per-stock | `feat(p6.5.headline)`, `feat(p6.5.dash)` |
| [heatmap.png](heatmap.png) | Heatmap | `feat(p6.3.headline)`, `feat(p6.3.pivot)`, `feat(p6.3.hover)` |
| [trends.png](trends.png) | Trends | `feat(p6.4.headline)`, `feat(p6.4.yoy)`, `feat(p6.4.yoy_n)`, `feat(p6.4.moy)` |

Each Phase-6 implementation commit is cross-checked against the matching
mockup. When a commit's visual output diverges from the mockup AND that
divergence is intentional (e.g., a polished spacing decision, a clearer
label), the commit body notes it explicitly. Otherwise the implementation
should match.

## Cross-cutting elements visible in every mockup

- **Top bar**: project name, sweep selector + run_id, last-updated timestamp,
  cache-fetch status — implemented in `app.py`'s header.
- **Caveats row** (three cards: MULTIPLE COMPARISONS, SURVIVORSHIP RISK,
  MARGIN TIER-B ASYMMETRY) — implemented in `src/web/caveats.py`. Per
  DESIGN_SPEC §1.4, the cards collapse to a slim banner on dismiss.
- **Sidebar** (strategies multiselect, symbols multiselect, MIN N slider,
  regime radio) — implemented in `app.py` per SPECS §11.4 state contract
  (keys prefixed `mp_`).
- **Dark theme + Plotly diverging RdYlGn colormap with `zmid=0`** — pinned
  in DESIGN_SPEC §2.3; never sequential green (a first-negative-cell on a
  later sweep would otherwise render mid-green and mislead).

## Notes on the mockups themselves

DESIGN_SPEC §11 (the design's own change log) calls out two mockup bugs
the implementation must NOT inherit:

1. The Leaderboard mockup labels a `₹25.76 L` value as "AVG ROI" — rupees
   mislabeled as a percentage. DESIGN_SPEC §2.5's naming rule
   (one-line subtitle naming the denominator) prevents code from
   inheriting this.
2. The Heatmap mockup shows `AVG ROI +264.1 %/yr` alongside `BEST CELL
   +82.3 %/yr` — best can't be lower than average; mathematically
   impossible. Numbers in production come from the aggregator output;
   the implementation will produce internally consistent values.
