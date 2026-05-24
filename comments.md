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

## Review of b8de59 — feat(p1.1): data/cache.py — parquet read/write/exists + CACHE_VERSION guard

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the single parquet persistence layer that every data loader will go through — atomic writes, version sentinel, path builders matching SPECS §2.

**What works:**
- Atomic write via tmp + `replace()` ([src/data/cache.py:74-80](src/data/cache.py#L74-L80)) — crash-safe on POSIX.
- Version sentinel raises `CacheVersionMismatch` rather than silently mixing schemas ([src/data/cache.py:30-43](src/data/cache.py#L30-L43)) — exactly the loud-failure stance PLAN.md §4 demands.
- Path builders match SPECS §2 layout verbatim. Verified by exercising:
  ```
  spot/RELIANCE/2024.parquet
  options/RELIANCE/20240328/2620-CE.parquet
  expiries/RELIANCE.parquet
  ```
- Pyarrow now resolved on the venv (24.0.0) — my 46ffe18 flag is unblocked even though it wasn't called out in the commit message.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- **Silent strike collision via banker's rounding** ([src/data/cache.py:51](src/data/cache.py#L51)): `int(round(50.5))` returns 50 (round-half-to-even), so a hypothetical ₹50 strike and ₹50.50 strike would write to the same file. NSE stock options use whole-rupee strikes today, so this won't bite — but a one-line `assert strike == int(strike)` or `int(round(strike * 100)) / 100` filename scheme would make it future-proof. Cheap insurance.
- **`_ensure_root()` runs on every path build** ([src/data/cache.py:46-63](src/data/cache.py#L46-L63)) — touches disk (sentinel read) per call. Across a sweep with 10k path constructions this is O(10k) stat calls. Memoize with a module-level `_root_verified: bool`, or only call `_ensure_root` inside `read`/`write`.
- **SPECS §7 says "never overwrite real historical data unless `--force-refresh`"** — `write()` here unconditionally replaces. Either implement the guard here (refuse to clobber unless an explicit `overwrite=True`) or pin the policy at the loader layer. Either way, write the rule down before the spot loader lands.
- **No `delete()` helper.** Phase 2's universe membership cache invalidation may need it. Defer until needed; just noting.

**Domain / correctness checks:**
- **jugaad-data usage:** N/A this commit.
- **Options math:** N/A.
- **Statistical claims:** N/A.
- **Look-ahead bias:** N/A — pure I/O. (But: parquet schemas freeze field types, so a date-column-as-string slip here would propagate. Next commit's test should pin dtypes.)

**What I tried:**
```python
# imported, built all 3 path types, round-tripped a small df,
# read sentinel ('1'), corrupted sentinel to '99' and confirmed
# CacheVersionMismatch is raised. Strike-rounding edge cases:
#   50.5 -> 50-CE   (banker's rounding, collides with 50)
#   50.7 -> 51-CE
#   51.0 -> 51-CE
```

**Next-commit suggestion:** Per the planned step list this is `test(p1.1)`. Make sure tests pin dtypes (date → datetime64, strike → float64, lot_size → int64) — that's the real value of writing tests next to the helper.

---

## Review of 20279c5 — test(p1.1): cache.py — round-trip, path builders, version sentinel, atomic write

**Verdict:** ⚠️ accept-with-followups

**Phase / commit goal (as I understood it):** Lock in the p1.1 cache helpers with unit tests so future refactors can't silently break the persistence contract.

**What works:**
- 5/5 pass on my machine via `python -m pytest tests/test_cache.py -v` (0.38s).
- `monkeypatch` cleanly redirects `cache.CACHE_DIR` per test ([tests/test_cache.py:12-14](tests/test_cache.py#L12-L14)) — no fixture cross-talk.
- Tests assert symbol normalization (`reliance` → `RELIANCE`) and option_type uppercasing (`ce` → `CE`) ([tests/test_cache.py:27-39](tests/test_cache.py#L27-L39)) — good defensive coverage of the public API surface.
- Sentinel-mismatch path covered ([tests/test_cache.py:50-55](tests/test_cache.py#L50-L55)).
- Pytest now installed (9.0.3) — second 46ffe18 flag implicitly resolved.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions (carry into p1.2):**
- **Round-trip test doesn't pin dtypes.** [tests/test_cache.py:19](tests/test_cache.py#L19) uses `{"x":[1,2,3],"y":["a","b","c"]}` — generic. The parquet schemas in SPECS §2 are precise about `datetime64[ns]`, `float64`, `int64`. Add one test with a SPECS §2.1-shaped frame and assert dtypes survive the round-trip; that's what protects the data layer from silent type drift.
- **"Atomic write" test only checks the happy path.** [tests/test_cache.py:58-64](tests/test_cache.py#L58-L64) confirms no leftover `.tmp` *after a successful write* — which proves the rename completed, not that the write is crash-safe. To actually test the atomicity claim, `monkeypatch` `Path.replace` to raise, then assert the destination file does *not* exist. Currently the test name overpromises.
- **Strike-collision case from b8de59 still untested.** `option_path("X", date(2024,1,1), 50.5, "CE")` and `..., 50, "CE")` resolve to the same file. Either assert/enforce integer strikes or add a test that documents the current behavior so a future change is loud.
- **No test asserts `CacheVersionMismatch.__str__` is informative.** Loud failure is only loud if the message helps the user; one substring check (`"version"` in `str(exc)`) is enough.

**Domain / correctness checks:**
- **Lookahead / financial logic:** N/A — pure I/O tests.
- **Network / caching hygiene:** No network. `@pytest.mark.network` not needed here. Good.

**What I tried:**
- `python -m pytest tests/test_cache.py -v` → 5 passed in 0.38s.
- Confirmed pytest 9.0.3 is now in `.venv`.

**Next-commit suggestion:** `feat(p1.2): data/spot_loader.py`. When you write it, decide the force-refresh policy first (SPECS §7) so `load_spot` knows whether to re-call NSE when a year-parquet exists. The cleanest answer is probably: `force=False` default, never re-fetch a *closed* year; always re-fetch the current year up to today's date.

---
