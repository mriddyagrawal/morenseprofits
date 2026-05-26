# Heatmap click handling — failure log

Living record of every approach tried for "click a heatmap cell → drill-down opens" on the
**morenseprofits** Streamlit dashboard, in chronological order, with **what failed and why**.

The contract is now: **the selectbox cell-picker is the primary mechanism** (always visible below
the heatmaps). Click events from the heatmap are kept as a possible fast-path but are NOT
load-bearing.

---

## Environment

- **Streamlit** 1.57.0 (`requirements.txt` pins ≥ 1.34.0 for `on_select="rerun"`)
- **Plotly** 6.7
- **Python** 3.11 in `.venv`
- **User browser**: real browser session (Mac, Chrome / Safari)
- **Test browser**: Antigravity-driven headless Chrome (Playwright)

---

## Attempt history

### Attempt 1 — `commit a1db694` — `fix(p7.heatmap.click)`

**Approach:** native `st.plotly_chart` with `on_select="rerun"` + `selection_mode="points"`, plus
layout tweaks `dragmode="select"` + `clickmode="event+select"` on the value-pane figure, plus
`config={"modeBarButtonsToAdd": ["select2d", "lasso2d"], "displaylogo": False}` to surface the
drag-select tools.

**Theory:** Plotly heatmap traces emit `plotly_click` reliably but `plotly_selected` only on box /
lasso drag. Streamlit's `on_select="rerun"` binds to `plotly_selected`. Setting `dragmode=select`
+ `clickmode=event+select` was meant to make a single click register as a 1-cell box-select.

**Result:** **Failed.** User reported clicks did not fire in their real browser. Antigravity
verification (`walkthrough.md`) corroborated: synthetic clicks didn't propagate selection through
the websocket boundary.

**Verdict:** `dragmode=select` / `clickmode=event+select` is necessary but NOT sufficient for
heatmap-trace click → `plotly_selected` round-trip. The Plotly docs are weak on click semantics
specifically for heatmap traces; the empirical answer is "doesn't reliably work."

---

### Attempt 2 — `commit 2459233` — `fix(p7.heatmap.plotly_events)`

**Approach:** swap `st.plotly_chart(on_select=...)` for `streamlit_plotly_events.plotly_events(
click_event=True, select_event=False, hover_event=False)`. The package is a Streamlit custom
component that embeds a static React frontend bound to Plotly's `plotly_click` event directly,
sidestepping Streamlit's selection-mode listener.

**Theory:** `plotly_events` bypasses `plotly_selected` entirely and binds to `plotly_click`, which
heatmap traces DO emit reliably. The library's frontend forwards clicked-point payloads back to
Python as a list of dicts.

**Result:** **Failed catastrophically.** The heatmap rendered **EMPTY**:
- No trace data visible
- Default integer axes (0, 1, 2, 3, …) instead of categorical `T-N` tick labels
- Layout title + axis labels still appeared (proving the figure JSON was read)
- The trace itself was missing or invisible

**Diagnosis:** `streamlit-plotly-events` was last released in **2022** with an embedded React
frontend bundle frozen against an older Plotly version. The static bundle's renderer is
incompatible with Plotly 6.7 / Streamlit 1.57 for heatmap traces specifically. The figure JSON is
serialized correctly but the embedded renderer can't draw it.

**Verdict:** A third-party static-bundle Streamlit component is a hard maintenance trap. The
package is archived; we can't patch its React frontend. Reverting was the only option.

---

### Attempt 3 — `commit 81882c9` — `fix(p7.heatmap.click): revert streamlit-plotly-events`

**Approach:** roll back to `st.plotly_chart(on_select="rerun", selection_mode=("points",))`. Note
the **tuple form** of `selection_mode` per a hint from the user (vs. the string form used in
attempt 1) — both *should* work per the docs but the tuple is the canonical example in Streamlit's
own snippets.

**Theory:** the native API at least RENDERS the heatmap correctly (categorical axes, all cells
visible). If click happens to fire on some browser configurations, we get it for free; if not, we
need a fallback.

**Result:** **Rendering works again.** Heatmap displays correctly with `T-N` tick labels and full
data.

**Click status:** still **does NOT fire** for the user in their real browser (manual test
confirmation). Manual cell-picker selectbox is the actual interaction.

**Verdict:** native API is the only sustainable renderer for this app. Click semantics for
heatmap traces in Plotly + Streamlit are unreliable enough that depending on them is unsafe. Don't
ship features that REQUIRE the click event; treat any-firing as a bonus.

---

## Current state — `commit 357c2c1` onward

**Primary cell-selection mechanism:** two `st.selectbox` widgets ("Entry offset" / "Exit offset")
rendered directly below the dual heatmaps with the prompt **"Pick a cell to drill down:"**. The
picker is always visible (no expander, no "fallback" framing) because that hiding-in-an-expander
behavior was confusing operator-facing — the user had to hunt for the path that actually works.

**Click event is still bound** via `st.plotly_chart(on_select="rerun", selection_mode=("points",))`
on the value pane, in case it fires for some browser configurations. The `_capture_cell_selection`
helper still parses the payload and writes to `mp_heatmap_selected_cell` if a click does land.

**Both paths write to the same session-state key** (`mp_heatmap_selected_cell`). The drill-down
body reads from session state and doesn't care which mechanism populated it.

---

## What we ruled out

| Approach | Why ruled out |
|---|---|
| `st.plotly_chart(on_select="rerun", selection_mode="points")` (string) | Native; doesn't fire on click for our user |
| `selection_mode=("points",)` (tuple form) | Same as above — string vs tuple makes no difference empirically |
| Adding `dragmode="select"` + `clickmode="event+select"` to layout | Necessary but not sufficient for heatmap click → selection |
| Adding `select2d` / `lasso2d` buttons to modebar | Surfaced drag-select as a workaround, but user shouldn't have to discover that |
| `streamlit-plotly-events` (custom-component bridge) | Archived 2022 package; embedded React frontend breaks heatmap rendering on Plotly 6.7 |
| Plain HTML/JS injection via `st.components.v1.html` for custom click handler | Not attempted — would require maintaining our own React component bundle; same maintenance trap as `streamlit-plotly-events` |
| WebSocket-side eavesdropping | Not attempted — Streamlit's transport is private API; would break across versions |

---

## What WOULD be needed if click MUST work in the future

1. **`streamlit-plotly-events` fork**: rebuild the React frontend against current Plotly. ~1-2
   days of frontend work. Maintainable only if someone wants to own it.
2. **Custom Streamlit component from scratch**: same scope as the fork, just without the legacy
   baggage. Same trade-off.
3. **Wait for Streamlit native**: file an issue against [streamlit/streamlit](https://github.com/streamlit/streamlit)
   asking for `click_mode="rerun"` or `selection_mode=("clicks",)` for heatmap traces. Could be a
   year or never.
4. **Replace Plotly with a different chart library** (Altair, Vega, custom D3): Altair's
   selection API on heatmaps works cleanly via `st.altair_chart` and `on_select`. The trade-off is
   re-doing all chart styling + features (hover tooltips, RdYlGn diverging colormap, etc.).
   ~1 week of work to port the value pane.

None of these are blocking for the current dashboard. The selectbox picker delivers the
same drill-down trigger with ~2 extra clicks (open Entry dropdown → pick → open Exit dropdown →
pick). For a research tool used by one operator, that's fine.

---

## Lessons

1. **Visually verify rendering before declaring a click-handler fix done.** Tests passing on the
   API surface (547/547 in attempt 2) didn't catch the blank-chart breakage. Always launch the
   app and look at it.

2. **Headless browser tests don't catch click-semantics regressions reliably.** Synthetic clicks
   via Playwright/Selenium don't propagate the same way real human clicks do through Plotly's
   React event handlers. Antigravity (Attempt 1's walkthrough) reported the bug correctly, but it
   wasn't a synthetic-click-only artifact — the user's real browser had the same problem.

3. **Static React bundles in Streamlit components age badly.** Anything that ships frontend code
   compiled against a specific Plotly version is a future regression waiting to happen.

4. **Don't depend on features the underlying library doesn't reliably support.** Plotly heatmap
   click semantics have been weakly documented and inconsistent for years. Building a UX around
   them is unsafe.

5. **Always provide a primary path that's independent of JS interaction.** A click is a nice-to-
   have; an explicit selectbox / form is a contract.

---

*Last updated:* commits `a1db694` → `2459233` → `81882c9` → `357c2c1`. Future click-related
attempts should append a new section to this file with the same shape (approach, theory, result,
verdict).
