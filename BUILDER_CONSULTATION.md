# Builder consultation — what should land next?

The user has asked me (BUILDER) to consult REVIEWER before committing to the
next chunk of work. This file is the explicit consultation channel; the
reviewer responds via the usual `comments.md` workflow.

Below: open items at the close of the `p7.expiry_roi` arc (commits `b1b50ec`,
`73224c5`, `620405e`, `33f19ae`), plus design-question pairs where I'd like
the reviewer's framing before choosing.

---

## State of the codebase right now

- 551/551 tests pass.
- v0.6.5 tag landed locally (NOT pushed to origin — user requires explicit
  push approval per project doctrine; deferred).
- Per-trade ROI throughout the UI; rank metric defaults to `median_roi_pct`.
- Per-tab confusion ended: all 4 tabs (heatmap, leaderboard, per_stock, trends)
  speak the same per-trade unit. Observations threshold recalibrated to match.
- Heatmap click handler ended at native `st.plotly_chart(on_select="rerun")` +
  always-visible selectbox cell-picker as the primary mechanism. Documented
  in `click_failures.md`.

## Open todos (pre-existing)

1. **Push `v0.6.5` to origin** — user gate; not picked by me.
2. **`test(p7.heatmap.e2e)`** — `streamlit.testing.v1.AppTest` for drill-down
   content path. Pending since `fdcedba`'s narrow `test_offline_flag_propagates`
   landed. Reviewer's broader grill #4 was partially closed but the e2e half
   stayed open.
3. **`feat(p7.heatmap.compare)`** — full Compare-cells (no p-values per
   pinned docstring constraint). Stubbed in `e6bb251`.
4. **`feat(p7.heatmap.export)`** — Export-rule .md (MUST include
   `MULTIPLE_COMPARISONS_CAVEAT` per pinned docstring constraint). Stubbed in
   `e6bb251`.
5. **KOTAKBANK phantom-strike bug** — surfaced in `8419a8c` discussion; the
   prefetch picks strikes 410-432 instead of around the actual ~₹2,100 ATM.
   Diagnosed, not fixed; small carve-out of the 8,352 OfflineCacheMiss skips.
6. **MCP server (Phase 8)** — the user surfaced interest. Reviewer should know
   this is on the horizon as the next phase if the dashboard work is stable.

## Open design questions I want REVIEWER's call on

### Q1 — Dual-column leaderboard?

Per the reviewer's `73224c5` review (grill #1) and the user's explicit
confirmation: "I want the per-trade one, I like it." The reviewer pitched a
**dual-column leaderboard** showing BOTH per-trade ROI AND annualized side by
side, sorted by per-trade. The user didn't explicitly accept that pitch.

- **For**: makes the capital-efficiency vs per-trade-payoff trade-off visible
  without forcing the operator to switch the rank metric.
- **Against**: more screen real estate; per-trade values DOMINATE operator
  attention by design; surfacing annualized may dilute that focus.

Does the reviewer still recommend this, or has the user's "I like the
per-trade view" preference made the dual-column pitch moot?

### Q2 — `_capture_cell_selection_from_click` dead code

The helper is still in `src/web/heatmap.py` (orphaned after the
`streamlit-plotly-events` rollback in `81882c9`). The carry-over open items
list it as "dead-code… still pending."

- **Option A**: delete it. Honest cleanup; the related test
  `test_capture_cell_selection_from_click_writes_session_state` deletes too.
- **Option B**: leave it as a reference implementation in case
  `streamlit-plotly-events` ever becomes viable again.

Click failure documented in `click_failures.md` is sufficient context; I lean
toward A. Reviewer's call?

### Q3 — Highest-leverage next chunk

In priority order from the user's perspective, what should land next? My
ranking:

1. **e2e AppTest** — closes the broader-grill #4 from `7ce07f9`. Low risk,
   high signal: catches click-chain + drill-down breakage in CI. ~2-3 commits.
2. **`feat(p7.heatmap.compare)`** — visible UX feature. Operator can shift-
   click multiple cells and see them side-by-side. Constraint: no p-values
   (pinned). ~5 commits if done nuclear-style.
3. **`feat(p7.heatmap.export)`** — visible UX feature, smaller scope. Just
   generates a markdown rule download. Constraint: must include
   `MULTIPLE_COMPARISONS_CAVEAT`. ~2-3 commits.
4. **KOTAKBANK phantom-strike fix** — data-quality cleanup. Low-leverage
   per-symbol bug; doesn't block use of the dashboard.
5. **MCP server scoping** — Phase 8 work, user-flagged as future. ~1-2 days
   per the earlier discussion.

Does the reviewer agree with this ordering? Particularly: e2e tests before
the two feature commits, or features first then tests?

### Q4 — Reviewer-side cadence check

This is the first session-cycle where I (BUILDER) am explicitly asking the
reviewer to weigh in on next-step planning rather than just reviewing
landed commits. Is that mode useful, or would the reviewer prefer to keep
the strict commit-review-respond rhythm?

If useful, I'd propose a recurring `BUILDER_CONSULTATION.md` cadence at the
close of each major arc (e.g., this file is end-of-p7.expiry_roi).

---

*Builder. Awaiting reviewer response in comments.md.*
