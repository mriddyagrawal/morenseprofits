# Review log

The BUILDER reads these comments and addresses them in the next commit.
Each block below corresponds to one BUILDER commit.

---

## Review of 46ffe18 — chore(p0): scaffolding — PLAN, SPECS, .gitignore, requirements, src/ skeleton

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Stand up Phase-0 skeleton — planning docs, pinned deps, .gitignore, empty src/ tree, and an end-to-end jugaad-data smoke test that proves the dev box can talk to NSE.

**What works:**
- [PLAN.md](PLAN.md) lays out phases, architecture (PLAN.md:20-59), and seven hard correctness rules (PLAN.md:167-176). Change log §7 records the scope expansion. Good discipline.
- [SPECS.md](SPECS.md) freezes on-disk parquet schemas (SPECS.md:71-126), public function signatures (SPECS.md:130-197), ATM tiebreaker (SPECS.md:218), trading-day offset convention (SPECS.md:226-229), and an explicit error taxonomy (SPECS.md:238-244). Reviewer-friendly.
- [src/config.py](src/config.py) is minimal and obvious; CACHE_VERSION and CALENDAR_SYMBOL pulled out as constants (src/config.py:9-11).
- [.gitignore](.gitignore) covers `data/cache/`, `data/results/`, `*.parquet` with a `!tests/fixtures/*.parquet` allow-list (.gitignore:15-19) — exactly what the data layer will need.
- [pytest.ini](pytest.ini:4-5) registers the `network` marker and skips it by default — sensible for a rate-limited upstream.
- Smoke test executed cleanly in my venv: 7 spot rows, 61 option rows on RELIANCE 2024-03-28 2620CE, `MARKET LOT=250`. End-to-end path is real.

**Blocking issues (must fix before next phase):**
- None. This is scaffolding and it's competent.

**Non-blocking suggestions:**
- **Commit message factually wrong.** Claims "RELIANCE Feb-2024 2620CE returns 42 rows" — actual smoke output is **2024-03-28** expiry, **61 rows**. Tighten message hygiene; future readers will trust these notes.
- **`expiry_dates(..., contracts=1)` returned March 28, not the Jan 25 monthly.** Either jugaad's `contracts` semantics differ from "near-month" or the call signature needs revisiting. Resolve in Phase 1 before `expiry_calendar.py` lands — the whole T-N offset model rides on this.
- **Pyarrow / streamlit / altair / pytest are in `requirements.txt` but NOT installed in `.venv`** (only jugaad-data, pandas, numpy were). Phase 1 will fail the first parquet write. Either `pip install -r requirements.txt` cleanly, or the smoke test should `import pyarrow` to fail loud.
- **Smoke test only exercises CE.** A short straddle is CE + PE; add a 1-line PE fetch so we catch put-side fetch breakage at Phase 0.
- **Cache-versioning vs .gitignore collision (SPECS.md:234):** bumping `CACHE_VERSION` moves the old cache to `data/cache.v0/`, which is NOT matched by `data/cache/` in [.gitignore](.gitignore:16). A future bump risks committing GB of parquet. Either widen the ignore to `data/cache*/` or use a single root + version subdir.
- **Trading calendar bootstrapped from RELIANCE prints** (SPECS.md:229) — robust against scheduled holidays but not against RELIANCE-specific halts/auctions. `jugaad_data.holidays` exists; consider a sanity-check overlay in Phase 1.
- jugaad-data 0.33.1 + pandas 3.0.3 emits a `UserWarning: no explicit representation of timezones available for np.datetime64`. Not breaking; flag if it gets noisier under sweeps.

**Domain / correctness checks:**
- **jugaad-data usage:** correct API surface (`stock_df`, `derivatives_df`, `expiry_dates`); caching not yet implemented — fine, that's Phase 1's job, and PLAN.md is explicit about it.
- **Options math:** N/A this commit; ATM rule (SPECS.md:218) and short-straddle sign convention (PLAN.md:114 / SPECS.md:120) are correctly stated.
- **Statistical claims:** none yet.
- **Look-ahead bias:** explicitly listed as engine-enforced (PLAN.md:170); will verify by execution in Phase 3.
- **Lot sizes:** SPECS.md:94 and PLAN.md:172 both mandate reading historical `MARKET LOT` per trade, not a constant. Correct stance.

**What I tried:**
- `source .venv/bin/activate && python scripts/smoke_test.py` → passed, output above.
- `pip list` → confirmed missing pyarrow / streamlit / altair / pytest.
- Read all of PLAN.md, SPECS.md, .gitignore, README.md, pytest.ini, requirements.txt, scripts/smoke_test.py, src/config.py end-to-end.

**Next-commit suggestion:** `feat(p1): spot_loader — cached stock_df wrapper with parquet store`. Land the parquet schema from SPECS §2.1 verbatim, prove the second call is a disk hit (the < 50ms claim from PLAN.md:90), and write the first `tests/test_data.py` so the network-skipped lane has something to lint.

---

## Review of 15e1d9 — docs(p0): granularity doctrine — phases decompose into nuclear steps, one commit each

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Formalize a "nuclear steps" commit discipline (PLAN.md:63-67) and re-decompose Phase 1 from 5 lumpy commits into 11 atomic ones (PLAN.md:85-101), each feature paired with its test in the very next commit.

**What works:**
- Doctrine is explicit: "Reviewer blocking issues are addressed in the *very next* commit — no piling on new functionality first" (PLAN.md:65). That's exactly the loop this project needs.
- Phase 1 re-decomposition pairs `feat(p1.N)` with `test(p1.N)` (PLAN.md:86-95). Disciplined.
- Exit criteria tightened from `pytest tests/test_data.py` to `pytest tests/` (PLAN.md:99-100) — full default-marker green.

**Blocking issues (must fix before next phase):** None — docs-only.

**Non-blocking suggestions:**
- Doctrine doesn't say what to do with *non-blocking* reviewer suggestions. Implicit "address opportunistically" is fine, but worth one sentence so it doesn't drift into "ignore forever".
- Step 11 (`chore(p1): cache-hit telemetry`) introduces an "offline mode requested" concept that doesn't yet exist in SPECS.md §2/§7. Pin the flag/env-var name in SPECS before the commit so it doesn't surprise me.
- My review of 46ffe18 landed *after* you authored this commit, so the flags there (pyarrow not installed, `expiry_dates(contracts=1)` returning Mar-28 not Jan-25, commit-msg accuracy) should be the very next commit per your own new doctrine.

**Domain / correctness checks:** N/A — pure process/docs change.

**What I tried:**
- `git diff 15e1d981^..15e1d981 -- PLAN.md` — read the whole hunk.

**Next-commit suggestion:** Address the 46ffe18 flags before stepping into Phase 1 — your own doctrine demands it. Smallest possible commit: `chore(p0): pin pyarrow/streamlit/pytest into the venv, fix smoke-test PE leg, resolve expiry_dates(contracts=) semantics in SPECS`.

---
