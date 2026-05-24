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

## Review of 75f6a21 — chore(p0): address reviewer non-blocking flags before Phase 1.2

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Clear the non-blocking flag backlog from the 46ffe18 + 15e1d9 reviews before opening Phase 1.2 — pyarrow / smoke-test PE leg / `.gitignore` for versioned caches / jugaad `expiry_dates` semantics / offline-mode contract / doctrine extension for non-blocking flags.

**What works:**
- [.gitignore:16](.gitignore#L16) → `data/cache*/` catches the cache-version directory bump. [.gitignore:27](.gitignore#L27) adds `.claude/` so harness state stays untracked.
- Smoke test now exercises **both** CE and PE ([scripts/smoke_test.py:27-41](scripts/smoke_test.py#L27-L41)) and explicitly imports pyarrow ([scripts/smoke_test.py:44](scripts/smoke_test.py#L44)). I ran it: green; 42 rows CE + 42 rows PE for the expiry it picked; `[deps] pyarrow importable` printed.
- [SPECS.md:106](SPECS.md#L106) documents the `expiry_dates(contracts=N)` gotcha — verified against jugaad source: `filter(lambda x: int(x[10])>contracts, cells)` confirms it's a liquidity threshold, not a "next N expiries" knob. Spec note matches reality.
- [SPECS.md:233-235](SPECS.md#L233-L235) pins offline-mode contract: kwarg + `MORENSE_OFFLINE=1` env + telemetry on accidental fetch. Clean.
- [PLAN.md:65](PLAN.md#L65) doctrine extension is exactly what was missing — non-blocking flags get an open-questions entry if they slip past the phase boundary.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- **NEW finding — jugaad `expiry_dates` is non-deterministic across runs.** The function ends with `return list(set(dts))` (jugaad_data/nse.py inside `expiry_dates`). Across runs the same call gave me Mar-28, then Feb-29; the BUILDER's hand-run gave Jan-25. That's set iteration order, not a NSE inconsistency. **Phase 1.3's `monthly_expiries()` must `sorted(...)` the result before caching**, and any expiry-picker (e.g. "first expiry on/after X") must work on the sorted view. Otherwise test_engine determinism (SPECS.md:253) becomes flaky-by-construction.
- The same set-nondeterminism is *why* the 46ffe18 commit-message confusion arose. Worth noting in PLAN.md change log so future-you doesn't re-derive it.
- `data/cache*/` will also match `data/cachezzz/` if someone makes a typo. Probably fine. `data/cache(.*)?/` is the pedantic form — skip unless it bites.
- The smoke test still prints `lots = sorted(set(opt["MARKET LOT"]))` only on the CE branch ([scripts/smoke_test.py:38-40](scripts/smoke_test.py#L38-L40)). Cheap to also assert `lot == 250` so smoke fails loudly if lot size silently drifts.

**Domain / correctness checks:**
- **jugaad-data usage:** verified by reading source — `contracts` is a `>N` filter on the bhavcopy `int(x[10])` column. SPECS now accurately reflects this.
- **Options math:** PE leg now in smoke; sign-convention work still pending in Phase 3.
- **Look-ahead bias:** `MORENSE_OFFLINE=1` and the "warn on network fetch during sweep" telemetry are the right hooks to *enforce* no-lookahead during production runs. Worth keeping in mind when wiring Phase 1.5.
- **Lot size:** smoke confirms `MARKET LOT=250` for RELIANCE 2024 — current NSE spec.

**What I tried:**
- `python scripts/smoke_test.py` → green, both legs, pyarrow OK.
- `inspect.getsource(jugaad_data.nse.expiry_dates)` → confirmed `filter(... > contracts)` and `list(set(dts))` return; the gotcha note in SPECS is correct *and* a determinism hazard.
- Re-read SPECS §2.3 + §6a hunks end-to-end.

**Next-commit suggestion:** `feat(p1.2): data/spot_loader.py` — but bake **two non-negotiables** into the loader from commit 1: (a) sort the returned DataFrame by `date` ascending before write/return, and assert monotonicity (this kills the set-order class of bug at the data layer for *every* loader, not just expiries); (b) pin the force-refresh policy now — closed years are immutable on disk, current year re-fetches the tail. Both decisions are cheaper to make once than to retrofit across 5 loaders.

---

## Review of ab4e423 — fix(p1.1.a): cache.py — strike-int guard, memoized root, overwrite-protect

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Address the three non-blocking flags from the b8de59 review — banker's-rounding strike collision, per-call sentinel I/O, and SPECS §7's "append-mostly" overwrite policy — plus log the `expiry_dates` set-determinism finding in PLAN's change log.

**What works:**
- `StrikeNotIntegerError` via `float(strike) != int(strike)` ([src/data/cache.py:84-88](src/data/cache.py#L84-L88)) — loud, accurate, named. Verified: `50.5` raises, `2620.0` and `2620` both resolve to `2620-CE.parquet`.
- `_root_verified` memoization ([src/data/cache.py:30](src/data/cache.py#L30), [src/data/cache.py:45-55](src/data/cache.py#L45-L55)) — sentinel I/O is O(1)/process. Test helper now calls `_reset_root_memo()` so per-test redirection still works ([tests/test_cache.py:13-15](tests/test_cache.py#L13-L15)).
- `write(..., *, overwrite: bool = False)` + `WouldOverwriteError` ([src/data/cache.py:107-117](src/data/cache.py#L107-L117)) — SPECS §7 is now *enforced*, not aspirational.
- Atomic-write cleanup on failure ([src/data/cache.py:121-126](src/data/cache.py#L121-L126)) — the test name `test_atomic_write_no_tmp_left_behind` no longer overpromises; the property is real.
- [PLAN.md:200](PLAN.md#L200) change log entry for the `list(set(dts))` discovery — explicitly mandates `sorted(...)` at the data-layer boundary "so this class of bug dies once". Good doctrine.
- 5/5 prior tests still green via `python -m pytest tests/test_cache.py -v`.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- **Test-cross-contamination risk via global `_root_verified`.** Forgetting to call `_reset_root_memo()` in a new test fixture would silently re-use the prior process's verification. Promote to an `autouse` pytest fixture in [tests/conftest.py](tests/conftest.py) before more tests land, or stash the state in a small singleton object. Cheap insurance.
- **Strike-int guard is strict about FP.** `float(2620.0000000001) != int(...)` raises. Fine for jugaad-derived strikes (always clean ints), but if any synthesizer ever passes computed strikes (e.g. `spot * 1.05`), the guard will bite. Document the contract (strikes are observed, not computed) or relax to `math.isclose(strike, round(strike))`.
- **Overwrite-protect interacts with the "re-fetch current year's tail" pattern** I suggested in the last review. Phase 1.2's spot_loader will need `overwrite=True` plus a *length check* (refuse to clobber if the new fetch has fewer rows than the on-disk parquet — that would indicate a partial network response, not a real data update).
- The `try/except Exception` in `write()` ([src/data/cache.py:121-126](src/data/cache.py#L121-L126)) is correct here because it re-raises — flagging only because the pattern is rare-enough-to-double-check, not because it's wrong.

**Domain / correctness checks:**
- **jugaad-data usage:** N/A this commit.
- **Options math:** strike-int guard now enforces NSE stock-option strike spec. Good.
- **Look-ahead bias:** N/A.
- **Statistical claims:** N/A.

**What I tried:**
- `python -m pytest tests/test_cache.py -v` → 5 passed, 0.38s.
- `python -c "..."` → confirmed `50.5` raises, `2620.0` and `2620` produce identical paths.
- Read the diff and the full updated [src/data/cache.py](src/data/cache.py) end-to-end.

**Next-commit suggestion:** `test(p1.1.a): cache.py guards — strike-int, overwrite-protect, true atomicity` — and the load-bearing one is the **true atomicity test**: monkeypatch `pd.DataFrame.to_parquet` (or `Path.replace`) to raise mid-write, then assert (1) the final destination file does not exist and (2) no `.tmp` remains. That's the property the commit message claims; until a test pins it, the next refactor can break it silently. Also pin `WouldOverwriteError` on a second `write()` to the same path, and a memoization test (mock `Path.read_text`, assert called once after N path-builds).

---

## Review of 6c94296 — test(p1.1.b): cache.py guards — atomicity, overwrite, strike-int, memo, dtypes

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Lock in the contracts introduced in fix(p1.1.a) with tests for every flag I'd raised — and pin the dtype contract so silent type drift can never sneak in.

**What works:**
- `test_true_atomicity_on_failure` ([tests/test_cache.py:71-85](tests/test_cache.py#L71-L85)) — monkeypatches `pd.DataFrame.to_parquet` to raise, asserts dest does not exist AND no `.tmp` lingers. This is **exactly** the load-bearing property I called out; it's now real.
- `test_overwrite_protect` ([tests/test_cache.py:88-97](tests/test_cache.py#L88-L97)) covers both the raise and the explicit-opt-in path.
- `test_strike_integer_guard` ([tests/test_cache.py:100-112](tests/test_cache.py#L100-L112)) — int + integer-float resolve identically, fractional raises. Good belt-and-suspenders.
- `test_version_mismatch_message_is_informative` ([tests/test_cache.py:115-123](tests/test_cache.py#L115-L123)) — checks the message contains the on-disk version, expected version, and "SPECS" pointer. Loud failure is now also *useful* failure.
- `test_root_verification_memoized` ([tests/test_cache.py:126-148](tests/test_cache.py#L126-L148)) — actually counts `.cache_version` reads after a primer; asserts zero across 100 path builds. The O(1) claim is now property-tested.
- `test_round_trip_pins_dtypes` ([tests/test_cache.py:151-176](tests/test_cache.py#L151-L176)) **surfaced a real silent drift**: pandas 3.0 + pyarrow 24 round-trips `datetime64[ns]` → `datetime64[us]`. The BUILDER caught it via the test (not me), then patched SPECS §2.1 to document the unit-float. That's the test paying for itself on the very first run.
- `tests/conftest.py` autouse fixture ([tests/conftest.py:16-20](tests/conftest.py#L16-L20)) closes the cross-contamination risk I flagged on ab4e423. Belt + suspenders (reset before *and* after each test).
- 11/11 pass via `python -m pytest tests/test_cache.py -v` in 0.08s.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- The SPECS §2.1 relaxation to "datetime64 (any unit)" is correct for storage but means **downstream engine code must NEVER compare dtypes string-equal to `'datetime64[ns]'`**. Worth a SPECS note in §8 (error taxonomy) or wherever the engine contract lives, before Phase 3.
- `test_round_trip_pins_dtypes` covers the **spot** schema fields (date / symbol / open / volume). The options schema (SPECS §2.2 — has `lot_size: int64`, `oi: int64`, `option_type: string`, `expiry: date`) isn't covered. Land a sister test when the options_loader does (Phase 1.4) — `expiry: date` is the worrying one since parquet may turn `date` into `datetime64`.
- The atomicity test uses `RuntimeError("simulated")` and pytest.raises. Good. If you ever add `BaseException`-level cleanup paths (KeyboardInterrupt), they won't be covered — probably fine to defer.

**Domain / correctness checks:**
- **jugaad-data usage:** N/A this commit.
- **Options math:** N/A.
- **Look-ahead bias:** N/A.
- **Statistical claims:** N/A.

**What I tried:**
- `python -m pytest tests/test_cache.py -v` → 11/11 pass, 0.08s.
- Read the full diff for [tests/test_cache.py](tests/test_cache.py), [tests/conftest.py](tests/conftest.py), and the [SPECS.md](SPECS.md) dtype note.

**Next-commit suggestion:** `feat(p1.2): data/spot_loader.py` — bake **three** invariants from commit-one. (1) The previous two I called out: sort by `date` asc + monotonicity assert (PLAN.md change-log mandates it); force-refresh policy where closed years are immutable. (2) **NEW** — commit to **"one parquet per year contains the ENTIRE year, not just the days a caller asked for"**. Sparse year-caches lead to silent gaps when a later sweep widens the request: the union of "Jan 2–Jan 5" + "Jan 2–Dec 31" looks fine but actually missed Jan 6–Jan 31 if the first call cached only its 4 days. Easiest: every miss fetches the whole year (closed years) or the whole-year-up-to-today (current year). (3) Inject `today()` (or `today_fn: Callable[[], date] = date.today`) so tests can freeze time without monkeypatching the stdlib.

---

## Review of 8d34626 — feat(p1.2): data/spot_loader.py — year-keyed cache with 4 frozen invariants

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the first loader. All three of my next-commit invariants implemented + a fourth bug the BUILDER caught during their own verification (jugaad's date column is offset 5h30m from midnight IST).

**What works:**
- All four invariants present and individually verifiable: full-year parquets, closed-year immutability, length-checked current-year refetch, sort+monotonicity assert ([src/data/spot_loader.py:3-19](src/data/spot_loader.py#L3-L19), [src/data/spot_loader.py:64-68](src/data/spot_loader.py#L64-L68)).
- `today_fn` injection ([src/data/spot_loader.py:72-82](src/data/spot_loader.py#L72-L82)) — tests can freeze time; verified by passing `lambda: date(2024,6,1)` and watching the cached parquet stop at 2024-05-31.
- **The date-shift bug is real and the fix works**: confirmed end-to-end. NSE Jan-2 trading row arrives raw at `2024-01-01 18:30:00` (yes, the *previous* calendar date), +5h30m correction lands at `2024-01-02 00:00:00`. Single-day `load_spot("RELIANCE", Jan-2, Jan-2)` returns exactly 1 row, close=2611.7 — the regression a future refactor must never reintroduce.
- Concat-then-filter handles cross-year cleanly ([src/data/spot_loader.py:135-145](src/data/spot_loader.py#L135-L145)). Verified Dec-15-2023 → Jan-15-2024 returns 21 rows, monotonic across the boundary.

**My verification grid (live NSE):**
| check | observed |
|---|---|
| cold fetch Jan 2–5 | 34ms, 4 rows, closes 2611.7 / 2583.3 / 2596.65 / 2607.7 |
| hot read same range | 32.5ms (PLAN target is <50ms ✓) |
| single-day Jan-2 (the bug case) | 1 row, close=2611.7 ✓ |
| cross-year Dec-15-23 → Jan-15-24 | 21 rows, monotonic ✓ |
| full-year invariant | partial query → 249-row 2024.parquet on disk ✓ |
| from_date > to_date | raises `ValueError` ✓ |
| force_refresh | re-fetches & overwrites ✓ |
| today_fn=2024-06-01 | cache ends at 2024-05-31 (≤ frozen today) ✓ |

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- **Subtle dtype inconsistency for `symbol` vs `series`.** Verified: `symbol` is `<StringDtype(na_value=nan)>` (scalar-broadcast default) while `series` is `<StringDtype(na_value=<NA>)>` (explicit `.astype("string")`). Both pass `is_string_dtype`, but `df.dropna(subset=["symbol"])` and `dropna(subset=["series"])` use different missing-value sentinels — corner-case correctness drift waiting to happen. Fix: `df["symbol"] = pd.Series([symbol.upper()] * len(df), dtype="string")` or assign-then-`.astype("string")`.
- **Partial-response guard is length-only** ([src/data/spot_loader.py:108-114](src/data/spot_loader.py#L108-L114)). If NSE returns a same-length-but-different-rows fresh frame (e.g. one date dropped, one added), the length check passes and we silently overwrite. Cheap upgrade: `if not set(cached["date"]).issubset(set(fresh["date"])):` → also refuse.
- **`warnings.simplefilter("ignore", UserWarning)`** ([src/data/spot_loader.py:80](src/data/spot_loader.py#L80)) suppresses ALL UserWarnings during the fetch. Narrow to the known timezone message: `warnings.filterwarnings("ignore", message=".*timezones available.*")`. Otherwise a future jugaad upgrade may emit a meaningful UserWarning we'd swallow.
- **Concat-then-filter cost on multi-year sweeps**: at sweep time (Phase 4) `load_spot` may be called O(stocks × strategies × months) — each call concat'ing all year parquets. Probably fine on a warm cache, but worth a perf check when Phase 4 lands. Don't optimize now.
- **`max_cached >= today` cache-skip path** ([src/data/spot_loader.py:105](src/data/spot_loader.py#L105)) — fine in practice, but if a sweep runs intraday before NSE's EOD bhavcopy is published, the cache will refuse to refetch even though "today's" row doesn't yet exist. The right semantics here is "do not refresh until bhavcopy is available". Possibly out of scope; just flagging.

**Domain / correctness checks:**
- **jugaad-data usage:** correct; series="EQ" pinned; UserWarning rationale documented in the suppress block; **the date-shift fix is the kind of thing PLAN.md §4 hard-rule #2 ("real prices only") implicitly required**. Without this, every backtest's entry/exit-date prices would be off-by-one trading day. This is the most important bug caught so far.
- **Options math:** N/A.
- **Statistical claims:** N/A.
- **Look-ahead bias:** the loader returns historical EOD up to `today_fn()` — caller is still responsible for not querying the future. Engine work in Phase 3 will need to enforce.
- **Schema:** [src/data/spot_loader.py:36-48](src/data/spot_loader.py#L36-L48) rename map matches SPECS §2.1 column order. Good.

**What I tried:**
- 9 end-to-end checks against live NSE (see grid above). All green.
- Re-read [src/data/spot_loader.py](src/data/spot_loader.py) line by line.
- Verified the date-shift arithmetic by sorting raw output and walking through the timestamps before/after `+5h30m`.

**Next-commit suggestion:** `test(p1.2): spot_loader` — and the **load-bearing test is the date-shift regression**. Construct a `pd.DataFrame` matching jugaad's raw shape (DATE column at `YYYY-MM-DD 18:30:00`), monkeypatch `jugaad_data.nse.stock_df` to return it, then call `load_spot(sym, Jan-2, Jan-2)` and assert (a) exactly one row, (b) `date` equals `pd.Timestamp("2024-01-02")`, (c) the close matches the input row. If this test ever turns red, every backtest's entry/exit price is off-by-one. Also pin the four invariants individually (full-year-cache, immutable-closed-year, length-check-refuses-shrink, monotonic-output) and the `today_fn` freeze. Plus a "no-network on second call" test by monkeypatching `stock_df` to raise — proves the cache contract holds.

---

## Review of c77e62f — test(p1.2.a): spot_loader — 9 tests including the date-shift regression

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin every invariant of the spot_loader, with `test_date_shift_regression` as the explicit load-bearing test that prevents off-by-one trading-day price corruption.

**What works:**
- **20/20 pass** in 0.23s via `python -m pytest tests/ -v`.
- `test_date_shift_regression` ([tests/test_spot_loader.py:79-102](tests/test_spot_loader.py#L79-L102)) does exactly what I asked: feeds a `_fake_jugaad` frame with raw `Jan-1 18:30:00` for trading-day Jan-2, asserts single-day filter returns 1 row at `pd.Timestamp("2024-01-02 00:00:00")` with `close=2611.7`. The off-by-one trap is now a permanent tripwire.
- `_fake_jugaad` helper ([tests/test_spot_loader.py:32-58](tests/test_spot_loader.py#L32-L58)) builds the exact 15-column raw shape and **constructs the timestamp via `datetime(...) - pd.Timedelta(hours=5,minutes=30)`** — so the fake faithfully simulates the +5h30m offset the real loader corrects. Reusable for every future spot-related test.
- `test_closed_year_immutable_and_no_network_on_hit` ([tests/test_spot_loader.py:132-150](tests/test_spot_loader.py#L132-L150)) is clever: after the cold fetch, **re-monkeypatches stock_df to RAISE**, then asserts the second query succeeds purely from cache. Catches the class of bug where someone adds an accidental "refresh on every call" path.
- `test_full_year_parquet_invariant` ([tests/test_spot_loader.py:112-115](tests/test_spot_loader.py#L112-L115)) asserts `from_date == Jan 1` and `to_date == Dec 31` inside the factory itself — sparse caches now impossible by test, not just by convention.
- `test_partial_response_refuses_to_shrink_cache` ([tests/test_spot_loader.py:155-186](tests/test_spot_loader.py#L155-L186)) covers both the cache preservation AND the warning emission.
- `test_returned_frame_is_monotonic` shuffles the fake input and verifies the sort survives.
- `test_multi_year_span_fetches_each_year_once` ([tests/test_spot_loader.py:224-234](tests/test_spot_loader.py#L224-L234)) proves the cross-year stitching does N fetches, one per year.
- Conftest autouse memo reset is doing its job — no manual `_reset_root_memo()` calls cluttering tests.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- `_fake_jugaad` builds `DATE` via `pd.to_datetime(utc_naive)` which yields `datetime64[ns]`; real jugaad returns `datetime64[ms]` (I verified earlier). Functionally equivalent for the +5h30m shift, but if Phase 1.4 (options_loader) reuses this helper, the dtype subtlety could mask an unrelated bug. One-line fix: `pd.to_datetime(utc_naive).astype("datetime64[ms]")` to match jugaad exactly.
- `test_partial_response_refuses_to_shrink_cache` doesn't pin **what** the warning's `stacklevel` resolves to, only that the message contains "partial NSE response". Fine — but `stacklevel=3` in the source ([src/data/spot_loader.py:112](src/data/spot_loader.py#L112)) is a hand-tuned magic number; one assertion on `w.filename` ending in `spot_loader.py` or in the caller would lock that down.
- `test_today_fn_clamps_current_year_fetch` ([tests/test_spot_loader.py:205-219](tests/test_spot_loader.py#L205-L219)) asserts `seen_to == [fixed_today]`. Doesn't cover the edge case where `today_fn()` returns a date that's *already in the past* relative to caller's `to_date`. Probably fine; flag if Phase 3 ever calls `load_spot` with a frozen historical today.
- The fixed `today_fn = lambda: date(2026, 5, 24)` is hardcoded in many tests — when the actual `date.today()` passes 2026-05-24 in real time, no failure modes shift, but a `TODAY_AFTER_2024 = date(2030, 1, 1)` module constant would make the intent explicit.

**Domain / correctness checks:**
- **jugaad-data usage:** N/A this commit, but `_fake_jugaad` proves the BUILDER understands the raw shape precisely.
- **Options math:** N/A.
- **Look-ahead bias:** `today_fn` injection means tests can simulate "running on date X" — that's the right primitive for no-lookahead enforcement in Phase 3.
- **Statistical claims:** N/A.

**What I tried:**
- `python -m pytest tests/ -v` → 20/20 in 0.23s.
- Read [tests/test_spot_loader.py](tests/test_spot_loader.py) line by line; verified the `_fake_jugaad` helper matches real jugaad's column set against my own earlier inspect output.

**Next-commit suggestion:** Per the BUILDER's own note this is `fix(p1.2.b)` — bundle (1) the **subset-based partial-response check** (`if not set(cached["date"]).issubset(set(fresh["date"]))`) since that's the only one of the three followups with real correctness teeth, (2) explicit `symbol` dtype cast to `"string"` matching `series`, (3) narrow warning filter `warnings.filterwarnings("ignore", message=".*timezones available.*")`. **Crucial:** add a new `test_partial_response_with_dropped_dates` to `test_spot_loader.py` — feed a "fresh" frame of the SAME length as cached but with one date dropped and one added; assert the cache stays put. The length-only check passes this case silently today; without a test the subset upgrade can regress.

---

## Review of 64227f1 — fix(p1.2.b): subset-based partial check + symbol dtype + narrow warning

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close the three non-blocking flags from the 8d34626 review — and lock in the **subset** (not length) partial-response check with a regression test for the same-length-but-content-shifted case that length-only would pass silently.

**What works:**
- Subset check implemented at [src/data/spot_loader.py:114-127](src/data/spot_loader.py#L114-L127). The warning now identifies the **first 3 missing dates** explicitly — far more actionable than the old "rows fetched vs cache has" count.
- `test_partial_response_with_dropped_dates` ([tests/test_spot_loader.py:191-243](tests/test_spot_loader.py#L191-L243)) is exactly the test I asked for: same-length fresh response, middle date dropped, spurious future date inserted; asserts (a) cache length unchanged, (b) **dropped date still in cache**, (c) **spurious date not in cache**, (d) warning emitted. The four assertions together close every angle.
- Symbol dtype now via `pd.array([symbol.upper()] * len(df), dtype="string")` ([src/data/spot_loader.py:53-58](src/data/spot_loader.py#L53-L58)). `test_symbol_and_series_have_matching_dtype` ([tests/test_spot_loader.py:247-256](tests/test_spot_loader.py#L247-L256)) pins both columns to `pd.StringDtype()`.
- Warning filter narrowed to `message=r".*timezones available.*"` ([src/data/spot_loader.py:87](src/data/spot_loader.py#L87)) — a future jugaad change emitting a meaningful UserWarning will now reach us.
- `_fake_jugaad` DATE dtype cast to `datetime64[ms]` ([tests/test_spot_loader.py:43-45](tests/test_spot_loader.py#L43-L45)) — keeps the fake honest against my non-blocking note that real jugaad returns ms not ns.
- **22/22 pass** in 0.25s via `python -m pytest tests/`.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- The subset check could be a one-liner against pandas `.isin`: `cached["date"].isin(fresh["date"]).all()` — slightly clearer than dual-set construction, and avoids materializing two Python sets per refetch. Cosmetic; skip.
- If `cached` is ever empty (cold-fetch path can't reach this branch, but defensive), `set().issubset(anything) → True` and any fresh response is accepted. Not a real issue today; defer.
- `assert out["symbol"].dtype == pd.StringDtype()` ([tests/test_spot_loader.py:255](tests/test_spot_loader.py#L255)) relies on `StringDtype.__eq__` being version-stable across pandas. Hasn't been an issue for many versions; flag if pandas 3.1 surfaces a `default_na_value` change.

**Domain / correctness checks:**
- **jugaad-data usage:** correct; warning filter narrower is good hygiene for catching future upstream changes.
- **Options math:** N/A.
- **Look-ahead bias:** N/A.
- **Statistical claims:** N/A.
- **Data integrity:** the dropped-date scenario this commit closes was the most realistic real-world failure mode (NSE returns a partial bhavcopy after a midday glitch). Now provably blocked.

**What I tried:**
- `python -m pytest tests/ -v` → 22/22 in 0.25s.
- Read the diff line-by-line; verified the new test's logic against the implementation.

**Next-commit suggestion:** Phase 1.1+1.2 are now well-locked. Next planned is `feat(p1.3): data/expiry_calendar.py`. Three things matter from commit one: **(1) determinism is the load-bearing invariant** — the calendar must return a sorted unique list of `date` (Python `date`, per SPECS §2.3, not `datetime64`); the first test must be "two calls with the same inputs return byte-identical lists" because the whole reason for this module is to escape the `list(set(...))` non-determinism we already logged. **(2) Source the expiries from `bhavcopy_fo`'s `EXPIRY_DT` column for OPTSTK rows of the symbol, NOT a computed "last Thursday of month"** — NSE shifts expiries when the scheduled Thursday is a holiday, and computed last-Thursday will be wrong on those months. Hand-check one known expiry as part of testing: `RELIANCE` January 2024 monthly = `2024-01-25` (last Thursday). **(3) Cache the bhavcopy itself per-date, separate from the per-symbol expiries**: one bhavcopy serves all symbols, so a 5-symbol × 5-year sweep should fetch 60 monthly bhavcopies once, not 300.

---

## Review of 22d3da2 — chore(p1.3.plan): nuclear decomposition + SPECS §2.4 bhavcopy_fo cache

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Decompose the single `feat(p1.3)` step into 7 nuclear commits (cache-helper → bhavcopy-loader → expiry-calendar → live-verify), pin the bhavcopy_fo schema in SPECS §2.4, and propagate the user's pointer to the local jugaad-data clone into a canonical-reference preamble.

**What works:**
- 7-step decomposition ([PLAN.md:90-97](PLAN.md#L90-L97)) is exactly the per-date-bhavcopy / per-symbol-calendar separation I suggested. Each step has a paired test commit; the trailing `chore(p1.3.verify)` lands the live-NSE check the verify-downloads doctrine demands.
- New SPECS §2.4 ([SPECS.md:110-136](SPECS.md#L110-L136)) — 11-column schema with proper dtypes (`instrument`/`symbol`/`option_type` as `string`, `expiry`/`trade_date` as `date`, `contracts`/`oi`/`oi_change` as `int64`, `strike`/OHLC as `float64`). One parquet per date — a 5-symbol × 5-year sweep fetches ~60 bhavcopies, not 300. Exactly the structural decision I flagged.
- Jul-8-2024 UDiff cutover is **named in the SPECS** ([SPECS.md:133-136](SPECS.md#L133-L136)) and the BUILDER commits to verifying with tests on both sides. That's the kind of pre-decision that prevents a half-day debugging session later.
- Canonical-reference preamble ([SPECS.md:5](SPECS.md#L5)) names the local jugaad-data clone and flags the J_CACHE_DIR pitfall — perfectly aligned with what we learned from the docs scan.
- Hand-check `RELIANCE Jan 2024 = 2024-01-25` is baked into the p1.3.2 test description ([PLAN.md:95](PLAN.md#L95)).
- Phase 1.5 now includes `+ jugaad holidays overlay` ([PLAN.md:99](PLAN.md#L99)) — picks up the unanswered 46ffe18 flag about `jugaad_data.holidays`.

**Blocking issues (must fix before next phase):** None — docs-only.

**Non-blocking suggestions:**
- **Step 16 bundles two concerns** (`offline-mode kwarg on every loader + cache-hit telemetry`). Both are useful but logically independent — offline-mode is a behavior contract, telemetry is observability. Per the nuclear-steps doctrine, this should probably be `chore(p1.6): offline-mode kwarg` + `chore(p1.7): cache-hit telemetry`. Defer the call to the BUILDER.
- **§2.4 schema lists `expiry: date` and `trade_date: date`** — but Python `date` isn't a native parquet/pandas type. SPECS §2.1's date drift (`datetime64[ns]` → `datetime64[us]`) already proves this is fiddly. Pin the actual on-disk representation now: e.g. "stored as `datetime64[us]`, exposed to callers as Python `date` via `.dt.date`". Save the BUILDER mid-implementation thrash in p1.3.1.
- **No mention of CACHE_VERSION** in the schema-addition. Adding a new schema family (bhavcopy_fo) shouldn't bump the version (no on-disk structure changed for existing data), but worth a one-line SPECS §7 amendment: "additive schemas do not bump CACHE_VERSION; only schema *changes* do."
- **The Jul-8-2024 verify** is in `p1.3.1` tests per the plan — make sure those tests use a recorded byte-for-byte sample of each format. Live tests are skipped by default per pytest.ini, so the regression value comes from the *recorded* fixtures, not live calls.

**Domain / correctness checks:**
- **jugaad-data usage:** correct. The per-date bhavcopy_fo cache + per-symbol expiry projection is the right separation. Avoids both `expiry_dates`'s non-determinism and the redundant-fetch trap.
- **Options math:** N/A.
- **Look-ahead bias:** N/A. The bhavcopy is dated — engine consumers must filter `trade_date ≤ entry_date` at use time. Worth one line in §2.4 about that contract.
- **Statistical claims:** N/A.

**What I tried:**
- Read the diff in full. Cross-checked the §2.4 columns against `jugaad_data/nse/archives.py:322` (`bhavcopy_fo_raw`) — the BUILDER's schema is a faithful normalized subset.
- Cross-checked the Jul-8-2024 cutover claim against `docs/guides/nse_historical.rst:18-26` in the local jugaad clone — confirmed.

**Next-commit suggestion:** `feat(p1.3.0): cache.bhavcopy_fo_path` is going to be trivial (symmetric with `spot_path`/`option_path`). The interesting decision is **what dtype `trade_date`/`expiry` take on disk** — pin that BEFORE writing the path helper, so p1.3.1's parser doesn't have to revisit. Concretely: store as `datetime64[us]` (matches the spot loader's de-facto post-roundtrip dtype), expose via `.dt.date` in any public API that promises a `date`. Add one line to SPECS §2.4 saying so. Without this, the parser in p1.3.1 will choose silently and we'll catch a third dtype variant in tests.

---

## Review of b0ef46a — chore(p1.3.plan.b): pin bhavcopy date dtype + look-ahead caveat + CACHE_VERSION rule

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close the five non-blocking flags from the 22d3da2 review before p1.3.0 lands, so the p1.3.1 parser inherits unambiguous contracts.

**What works:**
- **Date dtype contract pinned** ([SPECS.md:133-137](SPECS.md#L133-L137)): `datetime64[us]` on disk, `.dt.date` at any API boundary that promises Python `date`. Exactly what I suggested.
- **Look-ahead caveat for bhavcopy** ([SPECS.md:139-141](SPECS.md#L139-L141)): consumers must filter `trade_date ≤ entry_date`. Names Phase 3 as the enforcement point — ties the SPECS contract to PLAN §4.1's hard rule.
- **Format-compat test now explicit about recorded fixtures, not live calls** ([SPECS.md:143-146](SPECS.md#L143-L146)). That's the only way the network-skipped test lane has regression value.
- **CACHE_VERSION additive rule** ([SPECS.md:282](SPECS.md#L282)): adding §2.4 doesn't bump; only existing-schema changes do. Closes the obvious ambiguity from the prior commit.
- **Step 16 split into 16 + 17** ([PLAN.md:101-102](PLAN.md#L101-L102)): offline-mode contract first, telemetry second. Clean ordering.

**Blocking issues (must fix before next phase):** None — docs-only.

**Non-blocking suggestions:**
- **The `datetime64[us]` rule is scoped to §2.4 only.** §2.2 options schema has `expiry: date` and §2.3 expiry calendar has `expiry_date: date` and `month_anchor: date` — same ambiguity, not updated. When p1.3.2 builds the calendar from the bhavcopy, the column passed through will be `datetime64[us]` per §2.4 but the §2.3 spec still says `date`. Either generalize the dtype rule globally or replicate in §2.2/§2.3. Otherwise a future reader will read §2.3 and try to store as Python `date` — won't survive parquet round-trip.
- The look-ahead caveat ([SPECS.md:139](SPECS.md#L139)) is good but only on §2.4. PLAN §4.1's hard rule is also currently spot-centric ("Strategy receives only `market_data[market_data.date <= entry_date]`"). Worth a small refactor of PLAN §4.1 in Phase 3 to cover bhavcopy/expiries explicitly — but that's Phase 3's problem, not this commit's.

**Domain / correctness checks:**
- **Look-ahead bias:** the bhavcopy `trade_date` filter rule is the right primitive — it generalizes to any future point-in-time-correct join.
- **jugaad-data usage:** N/A this commit.
- **Options math / stats:** N/A.

**What I tried:**
- Read the diff in full. Cross-checked §2.4's `datetime64[us]` choice against the spot loader's actual on-disk dtype I observed in 8d34626's verification grid — matches.

**Next-commit suggestion:** `feat(p1.3.0): cache.bhavcopy_fo_path` — the one micro-decision that matters here is **the parameter type**. Take `dt: date`, not `dt: datetime`. A `datetime(2024,1,2,9,30)` would format to `"20240102"` and feel correct, but `datetime(2024,1,2,23,59,59)` interpreted as UTC for a sweep running just before midnight IST could silently round to the wrong day. Pinning to `date` removes the class. Test should pass a `date` and either a `datetime` (assert raises or normalizes — pick one and document) so the contract is enforced from commit one.

---

## Review of 13dacbd — feat(p1.3.0): cache.bhavcopy_fo_path — per-date F&O bhavcopy path helper

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Add the symbol-agnostic per-date bhavcopy path builder, symmetric with `spot_path`/`option_path`/`expiry_path`.

**What works:**
- 13-line implementation ([src/data/cache.py:99-108](src/data/cache.py#L99-L108)). Path layout `data/cache/bhavcopy_fo/{YYYYMMDD}.parquet` matches SPECS §2.4 verbatim.
- `_ensure_root()` reused — picks up the existing memoization and version-sentinel guarantees for free.
- `trade_date: date` signature — duck-typed to also accept `datetime` (subclass of `date`); verified both produce identical paths.
- YYYYMMDD filename sorts lexicographically = chronologically: confirmed `['20240115', '20240215', '20240315', '20241215']` in lex order.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- `datetime` is silently accepted via Python's `date`-subclass relationship. That's defensible — `strftime("%Y%m%d")` on a `datetime` only consumes the date fields and ignores time/tz, so a naive `datetime(2024,1,2,23,59,59)` still produces `20240102`. Worth a one-line docstring note: "accepts either `date` or `datetime`; only the date portion is used" so a future caller doesn't expect tz-aware time normalization.
- No reasonableness check (e.g. `trade_date < today`, or in the NSE history range). That's correctly the loader's responsibility, not the path builder's. Skip.

**Domain / correctness checks:**
- **jugaad-data usage:** N/A this commit.
- **Options math / look-ahead / stats:** N/A.

**What I tried:**
```python
cache.bhavcopy_fo_path(date(2024,1,2))            # → .../bhavcopy_fo/20240102.parquet
cache.bhavcopy_fo_path(datetime(2024,1,2,9,30))   # → same path, time ignored
# sorted across months: chronological ✓
```

**Next-commit suggestion:** Per the plan, `test(p1.3.0)`. Mirror the existing `test_path_builders` shape; mandatory cases: (a) `date(2024,1,2)` resolves to `bhavcopy_fo/20240102.parquet`; (b) a `datetime` with non-midnight time produces the same path as the equivalent `date` (so the duck-typed acceptance is *documented*, not accidental); (c) the parent dir is `bhavcopy_fo`. Then move to `feat(p1.3.1)` where the real work lives — and per b0ef46a's commitment, capture **byte-for-byte recorded fixtures** for one pre-Jul-8-2024 and one ≥Jul-8-2024 bhavcopy NOW so the test can be written against them, not deferred.

---

## Review of 5f9cdeb — test(p1.3.0): cache.bhavcopy_fo_path — path shape + symbol-agnostic API

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Lock in the new path helper with shape + idempotence + structural assertion that the API stays symbol-agnostic.

**What works:**
- `test_bhavcopy_fo_path` ([tests/test_cache.py:46-62](tests/test_cache.py#L46-L62)) covers: filename `YYYYMMDD.parquet`, parent dir `bhavcopy_fo`, idempotent re-builds, distinct dates → distinct paths.
- **`inspect.signature` regression-blocker** ([tests/test_cache.py:60-62](tests/test_cache.py#L60-L62)): asserts the signature is exactly `["trade_date"]`. Structurally pins the "one file per date, no symbol axis" contract — a future drive-by addition of a `symbol` kwarg trips this test rather than silently turning a 60-fetch sweep into a 300-fetch one. Clean.
- Uses `date(2024, 2, 29)` as one of the test dates — happens to cover the leap-day path too.
- 23/23 pass via `python -m pytest tests/` in 0.25s.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- The `datetime` duck-typing I flagged on 13dacbd is still **structurally accepted but not tested or documented**. Add one assertion: `cache.bhavcopy_fo_path(datetime(2024,1,2,9,30)) == cache.bhavcopy_fo_path(date(2024,1,2))`. Either pins it as supported behavior, or — if the BUILDER prefers — replace with an `isinstance(trade_date, datetime)` rejection. Either way, *document it*. Currently a caller passing a tz-aware `datetime` would get an unknown-tz silent truncation.
- The `inspect.signature` assertion would break if a defensive kwarg ever gets added (e.g. `*, _force_root_check: bool = False` for testing). Brittleness is acceptable here given the structural-contract intent; just noting.

**Domain / correctness checks:**
- **jugaad-data usage / options math / look-ahead / stats:** N/A this commit.

**What I tried:**
- `python -m pytest tests/` → 23/23 pass, 0.25s.
- Read the diff in full.

**Next-commit suggestion:** `feat(p1.3.1): data/bhavcopy_fo_loader.py` is where every Phase-1.3 bet pays off — start with **capturing the two recorded fixtures** as the very first sub-step. A small `scripts/capture_bhavcopy_fixtures.py` that fetches one pre-Jul-8-2024 and one ≥Jul-8-2024 bhavcopy via `bhavcopy_fo_raw`, prints byte length + first/last 200 chars to stderr (so we can sanity-check), and saves both to `tests/fixtures/bhavcopy_fo_*.csv`. Write the parser against those fixtures rather than against an assumption about column layout — the two formats almost certainly have different columns, and parser-first-then-debug burns a half-day. **Pin the column-name mapping by NAME** (jugaad's `expiry_dates` accesses column index 10 — that's brittle across formats). The load-bearing test in `test_bhavcopy_fo_loader`: feed each recorded fixture through the loader, assert the SPECS §2.4 schema exactly (column names, dtypes including the `datetime64[us]` rule and `option_type` as pd.StringDtype with `<NA>` for futures rows).

---

## Review of a359b80 — chore(specs): generalize datetime64[us] date-dtype rule across §2

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Promote the §2.4-only date dtype rule to a global §2.0 preamble that applies to every parquet schema (§2.1 spot, §2.2 options, §2.3 expiries, §2.4 bhavcopy, §2.5 results). Closes the b0ef46a flag about §2.2/§2.3 inheriting the same ambiguity silently.

**What works:**
- New §2.0 ([SPECS.md:73-81](SPECS.md#L73-L81)) gives one canonical answer: `datetime64[us]` on disk, `.dt.date` at the boundary, tests assert `is_datetime64_any_dtype`. Per-schema columns now use `date` as shorthand.
- §2.1's verbose unit-float note collapsed to `(see §2.0)` — DRY.
- §2.4's duplicate dtype paragraph removed; it inherits from §2.0 now.
- Net +11/-7: spec got *shorter* AND more rigorous. Rare and good.

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**
- The shorthand `date` in column tables (e.g. `expiry: date` in §2.4) still reads as "Python `date`" to a first-time reader. Adding `(see §2.0)` *inside* every column-table cell would be noisy. Acceptable as-is, but if the test suite ever surfaces a misread, consider renaming the shorthand to e.g. `date†` with the dagger pointing to §2.0.
- §2.0 says "Microsecond precision is far more than daily data needs" — true; just noting the precise units already vary between the parquet engines (some return `ns`). The `is_datetime64_any_dtype` test convention is the right way to absorb that.

**Domain / correctness checks:** N/A — pure docs.

**What I tried:** Read the diff, cross-checked §2.1/§2.4 hunks for consistency post-edit.

**Next-commit suggestion:** Back on track for `feat(p1.3.1): bhavcopy_fo_loader`. The single concrete action that maximizes downstream velocity: **fetch one pre-Jul-8-2024 and one ≥Jul-8-2024 bhavcopy via `bhavcopy_fo_raw` RIGHT NOW** and inspect them side-by-side before writing any parser code. If the column headers are identical across formats (jugaad's transparent handling), the parser is a single code path with one CSV reader. If they differ, you need format detection (header sniff) + two parsers. Either way, knowing this BEFORE writing code beats writing-then-debugging. Save both raw blobs as `tests/fixtures/bhavcopy_fo_pre_udiff.csv` and `tests/fixtures/bhavcopy_fo_udiff.csv` so the parser tests are fixture-driven from commit one (per the recorded-fixtures commitment in b0ef46a). And map by column NAME — jugaad's `expiry_dates` indexes by position 10, which is exactly the kind of fragility the format change might break.

---

## Review of 7d15eac — fix(p1.3.0.a): reject datetime in bhavcopy_fo_path — loud > silent truncation

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close the duck-typed-acceptance flag from the 13dacbd / 5f9cdeb reviews — `datetime` is a subclass of `date` and would silently slip through, so reject it loudly with a TypeError.

**What works:**
- Reasoning in the docstring + commit message is precise and correct ([src/data/cache.py:109-114](src/data/cache.py#L109-L114)): tz-aware datetime is **genuinely ambiguous** about which trade date it names (UTC 23:59 vs IST 23:59 straddle different calendar days); naive datetime is just unnecessary. Either way, force the caller to `.date()` first.
- Error message includes the offending repr AND tells the caller exactly the fix: "Call .date() on it first". Useful failure.
- `test_bhavcopy_fo_path_rejects_datetime` covers naive datetime, tz-aware datetime, **and** confirms the `date` happy path still works ([tests/test_cache.py:46-62](tests/test_cache.py#L46-L62)) — the third assertion is what catches a future over-eager refactor that breaks legitimate `date` callers too.
- `inspect.signature` regression-blocker from 5f9cdeb still passes — adding the isinstance check didn't widen the signature.
- 24/24 pass via `python -m pytest tests/`.

**Blocking issues (must fix before next phase):** None.

**Non-blocking suggestions:**
- **The other path builders are inconsistent.** [src/data/cache.py:50](src/data/cache.py#L50) `option_path(..., expiry: date, ...)` also takes a `date` and would silently accept a datetime. The ambiguity is less severe there (options are tied to a fixed expiry date with no time semantics), but for consistency consider applying the same isinstance check. Or accept that bhavcopy_fo is special because tz-awareness matters and explicitly say so in a comment above the other path builders.
- Imports inside the test body (`from datetime import datetime as _dt`, `from datetime import timezone` at [tests/test_cache.py:51,56](tests/test_cache.py#L51-L56)) work but feel less tidy than top-of-file. Cosmetic.

**Domain / correctness checks:**
- **Look-ahead bias:** the rejection rule encodes the same point-in-time discipline as PLAN §4 hard rules — only `date` makes sense as a trade-date identity. Implicit alignment.
- **Other:** N/A this commit.

**What I tried:**
- `python -m pytest tests/` → 24/24 pass, 0.26s.
- Read the diff; confirmed the docstring + commit message match the implementation.

**Next-commit suggestion:** Stay the course on `feat(p1.3.1): bhavcopy_fo_loader` — the fixture-capture-first guidance from the a359b80 review still applies. One useful add given this commit's "loud over silent" pattern: when the loader detects an unknown format (header doesn't match either pre-Jul-8 or ≥Jul-8 schema), it should raise a `BhavcopyFormatError` (new entry in SPECS §8 error taxonomy) rather than papering over with a permissive parser. Same reasoning as this commit: a future NSE format change should be a loud error, not a silent partial-fill.

---

## Review of 641276e — chore(p1.3.1.discovery): F&O bhavcopy dual-format reality + recorded fixtures

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Honor the "capture fixtures FIRST" directive — go look at real bhavcopies on both sides of 2024-07-08, write down what's actually there, and correct the SPECS where they were wrong.

**What works:**
- **Discovery overturned a prior SPECS claim** — b0ef46a/a359b80 had "jugaad handles both transparently"; that's true for *equity* bhavcopy, NOT F&O. `bhavcopy_fo_raw` raises `BadZipFile` for ≥ Jul-8-2024. SPECS §2.4 now reflects reality.
- Found the correct historical UDiff URL: `https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip`. Verified live against 4 dates (2024-07-08, 2024-07-25, 2024-08-29, 2024-10-25). The `NSEDailyReports` API only exposes today/yesterday — for historical it's direct-URL construction. Worth committing to the SPECS.
- Both schemas documented in SPECS §2.4 ([SPECS.md:147-167](SPECS.md#L147-L167)) — 15 cols legacy with `OPTSTK`/`OPTIDX`/`FUTSTK`/`FUTIDX`, 34 cols UDiff with `STO`/`IDO`/`STF`/`IDF` — including the 1:1 instrument-code mapping.
- Recorded fixtures: 35-row slice each, RELIANCE rows present in both:
  - [tests/fixtures/bhavcopy_fo_legacy_20240125.csv](tests/fixtures/bhavcopy_fo_legacy_20240125.csv) has the Jan-25 hand-check rows (`OPTSTK,RELIANCE,25-Jan-2024,...`).
  - [tests/fixtures/bhavcopy_fo_udiff_20240829.csv](tests/fixtures/bhavcopy_fo_udiff_20240829.csv) has the Aug-29 + Oct-31 expiry rows (`STO,...,RELIANCE,...,2024-08-29,2024-10-31,...`).
- `scripts/capture_bhavcopy_fixtures.py` is the discovery-trail script with all findings in the top-of-file docstring — future-readers don't re-derive.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`XpryDt` vs `FininstrmActlXpryDt` (UDiff) — pick a canonical and document why.** Both fields exist in the UDiff schema. In the captured fixture they agree (Aug-29 trading day → Aug-29 + Oct-31 expiries, same value in both columns). They likely diverge only on **holiday-shifted expiries** (scheduled Thursday is a holiday → contract settles previous trading day). The §2.4 `expiry` column should map to whichever is *actually settled*, since that's what a backtest's exit price ties to. Worth capturing a third fixture from a holiday-affected month (e.g. Diwali week 2024) to disambiguate before p1.3.1 lands.
- **NSE 403s without a browser User-Agent.** The capture script sets `Mozilla/5.0 ... Chrome/...` headers ([scripts/capture_bhavcopy_fixtures.py:53-57](scripts/capture_bhavcopy_fixtures.py#L53-L57)). The production loader's UDiff fetcher will need the same trick. Pin this in SPECS §2.4 or in the loader's docstring — the next-NSE-quirk-of-the-week shouldn't make us re-derive.
- **Trailing commas in legacy CSV** (the `25-JAN-2024,` row endings) produce a phantom "Unnamed: 16" column when pandas-parsed. The parser must drop it explicitly or pass `usecols=`. UDiff's `Rmks,Rsvd1..4` mostly-empty columns are similar.
- **`arc.udiff_start_date`** is referenced in the capture script but the script doesn't pin its current value. If jugaad ships a date constant for the cutover, the loader should *import* it rather than re-hardcode `date(2024, 7, 8)` — keeps us in lockstep with the upstream library's view of the boundary.
- The discovery script is `scripts/capture_bhavcopy_fixtures.py` — correctly outside `tests/`, but it's a one-shot. Add a `# Run once: ` comment near the top so future-me doesn't accidentally re-run and overwrite the committed fixtures.

**Domain / correctness checks:**
- **jugaad-data usage:** revealed `bhavcopy_fo_raw`'s actual coverage limit. That's a real upstream constraint, not our bug. Naming the URL pattern in SPECS is the right escape hatch.
- **Options math:** the captured fixtures contain real RELIANCE Jan-25 + Aug-29 contract rows with non-zero `CLOSE`/`SETTLE_PR` and `MARKET LOT=250` — material for sanity-checking the parser later.
- **Look-ahead bias:** `trade_date` rule from §2.4 still holds; the fetcher should accept the trade date and stamp it onto every row of the normalized output even if upstream doesn't carry it (legacy stores it in `TIMESTAMP`, UDiff stores it in `TradDt`/`BizDt` — both ~= filename date).
- **Statistical claims:** N/A.

**What I tried:**
- Read SPECS diff + the capture script top to bottom.
- `head -5` + `grep RELIANCE` on both fixtures — confirmed the legacy "DD-Mmm-YYYY" + uppercase-codes shape AND the UDiff "ISO-date" + STO-codes shape.
- Cross-checked the UDiff URL format against the script's `UDIFF_URL_TPL` and the 4-date verification in the commit message.

**Next-commit suggestion:** `feat(p1.3.1): bhavcopy_fo_loader.py` — and the cleanest design separates **fetcher** from **parser**: the *fetcher* dispatches by date (`<` vs `≥` the cutover, prefer `jugaad.archives.NSEArchives.udiff_start_date` if it exists; fall back to `date(2024,7,8)`) and returns `(raw_text, format_tag)`. The *parser* takes `(raw_text, format_tag)` and returns the §2.4 DataFrame. Two independently testable layers — fetcher tests can monkeypatch network; parser tests use the recorded fixtures directly. Add `BhavcopyFormatError` to SPECS §8 for the "neither header matches" case. And lock the **stamping** rule in code: the loader writes `trade_date` from the request date passed in (not from upstream's TIMESTAMP/TradDt), and asserts the inferred value from upstream matches — catches mis-dispatched fetches loudly.

---

## Review of 50a2bc9 — chore(p1.3.1.specs): canonical expiry rule + 403-headers + udiff_start_date import + BhavcopyFormatError

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close every non-blocking flag from the 641276e + 7d15eac reviews before p1.3.1 lands.

**What works:**
- **Canonical expiry rule pinned** ([SPECS.md:165-173](SPECS.md#L165-L173)): UDiff `FininstrmActlXpryDt` → our `expiry`. Loader emits `warnings.warn()` on divergence vs `XpryDt`, so holiday shifts surface visibly. Right call — backtest exit prices tie to actual settlement, not scheduled.
- **Browser UA documented as load-bearing** ([SPECS.md:175-178](SPECS.md#L175-L178)) with the explicit "don't strip it to be tidy" warning. Captures the WAF reality of the user-provided endpoint.
- **`udiff_start_date` from upstream** ([SPECS.md:180-183](SPECS.md#L180-L183)) — I verified live: `NSEArchives().udiff_start_date` returns `date(2024, 7, 8)`. Importing it keeps us in lockstep.
- **`BhavcopyFormatError(DataError)`** added to error taxonomy ([SPECS.md:329](SPECS.md#L329)) — same "loud > silent" pattern as 7d15eac.
- "Run once" comment on the capture script ([scripts/capture_bhavcopy_fixtures.py:30-33](scripts/capture_bhavcopy_fixtures.py#L30-L33)) with explicit re-run conditions (NSE format change OR holiday-shifted expiry fixture).

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**
- **Divergence-warning aggregation unspecified.** A bhavcopy can have ~15k OPTSTK rows. If `XpryDt != FininstrmActlXpryDt` on a holiday-shifted batch, you don't want 5000 `warnings.warn()` calls. Pin once-per-file (collect divergent rows, emit one summary) or once-per-(symbol, expiry). Decide in the loader implementation.
- **The `udiff_start_date` phrasing** says "imports `jugaad_data.nse.archives.NSEArchives.udiff_start_date`" — Python can't `from X import Class.attr`. The actual code will need `from jugaad_data.nse.archives import NSEArchives` then `_CUTOVER = NSEArchives.udiff_start_date`. Pedantic; not blocking.
- **Browser UA freshness**: the Chrome major-version (134 in the capture script) will eventually go stale enough for NSE's WAF to reject. Worth a fallback chain or a clear "if you start seeing 403s, bump the UA" inline comment in the loader.
- **No test commitment for `BhavcopyFormatError`** yet. The next p1.3.1 test commit should explicitly pin: "given a CSV with a corrupted/unknown header, the parser raises BhavcopyFormatError, not a silent shape change".

**Domain / correctness checks:**
- **jugaad-data usage:** correct — `udiff_start_date` exists and resolves to the empirically-verified cutover.
- **Options math:** the canonical-expiry choice (`FininstrmActlXpryDt`) is the right one for backtest exit pricing; confirmed by Phase 3's hard rule (exit price = price on actual exit date).
- **Look-ahead bias / stats:** N/A.

**What I tried:**
- `python -c "from jugaad_data.nse.archives import NSEArchives; print(NSEArchives().udiff_start_date)"` → `2024-07-08` (type `date`). Matches.
- Read the SPECS diff + capture-script tweak.

**Next-commit suggestion:** Before writing any parser code in `feat(p1.3.1)`, **pin the column-mapping table in SPECS §2.4** — one table per format, each row `(upstream column) → (§2.4 column) [transform]`. That makes the parser a mechanical translation, not a judgment call mid-implementation. The two non-obvious mappings to spell out: (a) legacy `CLOSE` → `close` and `SETTLE_PR` → `settle_price`, UDiff `ClsPric` → `close` and `SttlmPric` → `settle_price` — verified consistent across both formats (option's daily settle, which on expiry day equals reference value for ITM contracts); (b) UDiff `FinInstrmTp` codes (`STO`/`IDO`/`STF`/`IDF`) map 1:1 to legacy `OPTSTK`/`OPTIDX`/`FUTSTK`/`FUTIDX`, and §2.4 stores the legacy form as the canonical. With that table in SPECS, the parser is ~80 lines and the test suite asserts the table row-for-row.

---

## Review of f5ff10c — feat(p1.3.1): bhavcopy_fo_loader — dual-format dispatch + SPECS §2.4 normalize

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Implement the F&O bhavcopy loader as a fetcher/parser split that dispatches by trade_date (legacy < 2024-07-08 < UDiff) and normalizes both upstream schemas to SPECS §2.4. Cache per-date.

**What works:**
- Fetcher/parser split exactly as suggested ([src/data/bhavcopy_fo_loader.py:73-100](src/data/bhavcopy_fo_loader.py#L73-L100) for fetcher, [src/data/bhavcopy_fo_loader.py:126-229](src/data/bhavcopy_fo_loader.py#L126-L229) for parsers). Parsers are public so fixture-driven tests can drive them with no network mock.
- `_udiff_start_date()` pulls from `NSEArchives.udiff_start_date` ([src/data/bhavcopy_fo_loader.py:77-80](src/data/bhavcopy_fo_loader.py#L77-L80)) — lockstep with upstream.
- `src/data/errors.py` is the right shape for a centralized DataError taxonomy.
- **Trade-date stamp + upstream-match assertion** ([src/data/bhavcopy_fo_loader.py:138-143](src/data/bhavcopy_fo_loader.py#L138-L143) legacy, [src/data/bhavcopy_fo_loader.py:181-185](src/data/bhavcopy_fo_loader.py#L181-L185) udiff) — catches mis-dispatched fetches loudly. Verified: passing `date(2024,1,26)` with the Jan-25 fixture raises a clear `BhavcopyFormatError`.
- **Format-marker sniffing** ([src/data/bhavcopy_fo_loader.py:63-64](src/data/bhavcopy_fo_loader.py#L63-L64)) — subset-based, allows benign upstream column additions without flipping into `BhavcopyFormatError`. Right balance.
- **XpryDt vs FininstrmActlXpryDt divergence warning** is **file-level granularity** ([src/data/bhavcopy_fo_loader.py:188-195](src/data/bhavcopy_fo_loader.py#L188-L195)) with a count and a "likely holiday-shifted" interpretation. Closes the aggregation-level flag I raised on 50a2bc9.
- **TtlTradgVol semantic verified during implementation** ([src/data/bhavcopy_fo_loader.py:207-211](src/data/bhavcopy_fo_loader.py#L207-L211)) — comment shows the BUILDER caught and corrected a "divide by lot" assumption by checking against a known row (RELIANCE 2840CE, 26 contracts × ~3024 notional/contract ≈ 78k, TtlTrfVal=19.6M = underlying notional). That's the verify-as-you-go pattern paying off.
- **End-to-end verification (mine, against fixtures):**
  - Legacy 35-row fixture → 14-col §2.4 frame. All dtypes match (`string`, `datetime64[us]`, `float64`, `int64`).
  - RELIANCE 1900 CE legacy hand-check ✓: `close=804.0, contracts=1, oi=250, oi_change=250, settle_price=2706.25`.
  - UDiff fixture → same 14-col §2.4 frame.
  - RELIANCE 2840 CE UDiff hand-check ✓: `close=201.7, oi=41500, oi_change=-1500, contracts=26`.
  - RELIANCE expiries from Aug-29 UDiff: `['2024-08-29','2024-09-26','2024-10-31']` — material for p1.3.2's calendar build.
  - Corrupt header → `BhavcopyFormatError` listing missing required cols.
  - Off-by-one trade_date → `BhavcopyFormatError`.
  - Parquet round-trip preserves `datetime64[us]`.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`.astype("int64")` on `contracts/oi/oi_change` is brittle to upstream NaN.** Today's fixtures have no blanks but a future upstream row with a missing `CONTRACTS` would `IntCastingNaNError`. Either use `pd.Int64Dtype()` (nullable) or `.fillna(0).astype("int64")` with a warning. SPECS §2.4 says `int64`, so the choice is between strict + brittle vs nullable. Pick deliberately, document in SPECS.
- **Weekend/holiday fetches not translated to `MissingDataError`.** `load_bhavcopy_fo(date(2024,7,7))` (a Sunday) would raise raw `HTTPError` from requests or `BadZipFile` from jugaad. Wrap both in `MissingDataError` so Phase 2/3 callers have one catch.
- **Asymmetric upstream caching**: legacy goes through `NSEArchives().bhavcopy_fo_raw` which hits jugaad's internal pickle cache (`J_CACHE_DIR`); UDiff goes through bare `requests.get` (no upstream cache). Functionally fine because our parquet cache is in front of both — but worth noting for the upcoming cache-hit telemetry chore (p1.7) that a "cold from our cache, warm from jugaad" hit is possible only on the legacy path.
- **Browser UA pinned to Chrome 134** ([src/data/bhavcopy_fo_loader.py:52-55](src/data/bhavcopy_fo_loader.py#L52-L55)) — when NSE bumps WAF strictness this'll start 403ing. Worth a one-line "if you start seeing 403s, bump this" inline comment beyond the existing "Don't strip 'to be tidy'".
- **Divergence-warning code path is reachable but untested** in the recorded fixture (the Aug-29 bhavcopy happens to have 0 divergences). The next test commit MUST include a synthetic fixture with one `XpryDt != FininstrmActlXpryDt` row.
- **Default `cache.write(path, df)` call** in `load_bhavcopy_fo` ([src/data/bhavcopy_fo_loader.py:247](src/data/bhavcopy_fo_loader.py#L247)) uses `overwrite=False`. On a cold call, path doesn't exist, write succeeds. On a re-fetch (force-refresh scenario), it'd `WouldOverwriteError`. Pin a `force_refresh: bool = False` kwarg now to mirror `spot_loader.load_spot` — or commit to the manual `rm` path. Doctrinal call.

**Domain / correctness checks:**
- **jugaad-data usage:** correct on both paths. `NSEArchives.udiff_start_date` accessed at class level.
- **Options math:** `strike: NaN` for futures rows, `option_type: <NA>` for futures rows — both verified in the data; means downstream `df[df["instrument"]=="OPTSTK"]` filters cleanly.
- **Look-ahead bias:** `trade_date` stamped from request, so a bhavcopy can't be backdated by accident; SPECS §2.4's "consumers filter `trade_date ≤ entry_date`" rule still applies at the engine.
- **Statistical claims:** N/A.

**What I tried:**
- Ran `parse_legacy` and `parse_udiff` on the recorded fixtures.
- RELIANCE 1900 CE legacy + RELIANCE 2840 CE UDiff hand-checks against the raw fixture lines.
- Corrupt-header negative test.
- Off-by-one trade_date negative test.
- Parquet round-trip via `to_parquet`/`read_parquet`.

**Next-commit suggestion:** `test(p1.3.1)` — the **load-bearing test pair**: (1) `test_load_bhavcopy_fo_cache_hit` — call `load_bhavcopy_fo` twice with the same `trade_date`; monkeypatch `_fetch_raw` to **raise** on the second call; assert the second call succeeds purely from parquet. Without this, a regression that drops the `cache.exists` short-circuit would silently re-fetch every call (and Phase 2/3 sweeps would melt your laptop). (2) `test_holiday_shifted_expiry_warns` — construct a **synthetic UDiff CSV** with one row where `XpryDt != FininstrmActlXpryDt` (mutate one row of the recorded fixture); assert exactly one `UserWarning` with the divergence count, and assert the output `expiry` column carries `FininstrmActlXpryDt` for that row. The warning path is currently reachable-but-untested. The two together cover the highest-blast-radius behaviors not already verified end-to-end above.

---

## Review of fca735a — test(p1.3.1): bhavcopy_fo_loader — 16 tests including both load-bearing ones

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin every contract introduced by f5ff10c, with the cache-hit and holiday-shift tests as the named load-bearing pair.

**What works:**
- **40/40 pass** in 0.33s.
- Both load-bearing tests present and green ([tests/test_bhavcopy_fo_loader.py:248-300](tests/test_bhavcopy_fo_loader.py#L248-L300) for cache; [tests/test_bhavcopy_fo_loader.py:196-241](tests/test_bhavcopy_fo_loader.py#L196-L241) for divergence) — the synthetic UDiff mutation is the right pattern (only one row diverges, exactly one file-level warning, ActlXpryDt wins).
- `_assert_specs_2_4_schema` ([tests/test_bhavcopy_fo_loader.py:56-66](tests/test_bhavcopy_fo_loader.py#L56-L66)) shared helper used by both parsers + cache round-trip. DRY.
- Hand-check guards the **TtlTradgVol/lot bug the BUILDER caught during implementation** ([tests/test_bhavcopy_fo_loader.py:102-121](tests/test_bhavcopy_fo_loader.py#L102-L121)) — the `contracts == 26` assertion is the regression block.
- `test_udiff_unknown_instrument_code_raises` mutates `,STO,` to `,XYZ,` and asserts `BhavcopyFormatError` — covers future NSE additions like a currency segment.
- Two off-by-one tests (legacy via TIMESTAMP, udiff via TradDt) prove the mis-dispatched-fetch trap holds on both branches.
- Schema dtype assertions check `pd.StringDtype()` and `is_datetime64_any_dtype` (per §2.0 rule) and the float64/int64 pins.
- Cache hit test uses `pd.testing.assert_frame_equal(df1, df2)` — strict comparison between fresh in-memory and parquet round-trip frames. Catches subtle dtype/attribute drift.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Header field-position assertion** in the holiday-shift test ([tests/test_bhavcopy_fo_loader.py:206](tests/test_bhavcopy_fo_loader.py#L206)): `assert xpry_idx == 9 and actl_idx == 10`. Brittle to upstream UDiff column order changes. The assertion serves as a sanity-canary (test fails loud if order changes) so it's defensible — just naming it.
- **`_fetch_raw` dispatch logic isn't unit-tested.** All cache-hit / round-trip tests monkeypatch `_fetch_raw` directly, bypassing the `< udiff_start_date()` branch. A regression that flipped the `<` to `<=` (and thus mis-routed the 2024-07-08 boundary day) would not be caught. One-shot test: monkeypatch `_fetch_legacy` and `_fetch_udiff` to track which was called, hit it with dates straddling the cutover, assert dispatch.
- **`int64` dtype assertion is the brittle path I flagged on f5ff10c.** Today's fixtures have no NaN; if upstream ever drops in a blank `CONTRACTS`, the dtype assertion is fine but the parser fails. Carries until the followup fix.
- **No `force_refresh` test yet** — fine because the feature doesn't exist; just noting it'll need one when added.

**Domain / correctness checks:**
- **jugaad-data usage / options math / look-ahead / stats:** N/A this commit (pure tests).
- **Schema/dtype:** every column in SPECS §2.4 has at least one dtype assertion via `_assert_specs_2_4_schema`. SPECS contract is now structurally enforced.

**What I tried:**
- `python -m pytest tests/ -v` → 40/40 pass, 0.33s.
- Read the whole test file. Cross-checked the mutation logic in the divergence test against the UDiff fixture's column order.

**Next-commit suggestion:** Per the BUILDER's note the **followup fix commit comes next**. The three followups have different urgency — **prioritize `MissingDataError` wrapping for weekend/holiday fetches** because the upcoming `feat(p1.3.2): expiry_calendar` will need to cleanly distinguish "this candidate date had no F&O bhavcopy" from "the fetch crashed". Concretely: `_fetch_legacy` wraps `BadZipFile`/`HTTPError` into `MissingDataError(f"no F&O bhavcopy for {trade_date}")`; same for `_fetch_udiff`'s 404/403 path. Then `feat(p1.3.2)` can `try: load_bhavcopy_fo(d) except MissingDataError: continue` while iterating candidate sample days per month — clean control flow without leaking network internals. `Int64Dtype()` + `force_refresh` can land in the same commit or follow, but the `MissingDataError` wrap is on the p1.3.2 critical path.

---

## Review of bc1add4 — fix(p1.3.1.b): wrap fetch failures as MissingDataError + dispatch test

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the p1.3.2-critical-path piece — wrap "no upstream data" failures as `MissingDataError` while leaving network-level errors untouched. Plus close the dispatch-boundary test gap.

**What works:**
- **Wrap-policy boundary explicitly defined and tested.** [src/data/errors.py:21-30](src/data/errors.py#L21-L30) docstring says "callers iterating candidate dates use this to distinguish 'no data here' from 'the network blew up'"; `test_network_errors_are_not_wrapped` ([tests/test_bhavcopy_fo_loader.py:386-393](tests/test_bhavcopy_fo_loader.py#L386-L393)) pins the boundary by asserting `ConnectionError` propagates unchanged.
- Three concrete wrap sites covered:
  - Legacy `BadZipFile` → `MissingDataError` ([src/data/bhavcopy_fo_loader.py:82-95](src/data/bhavcopy_fo_loader.py#L82-L95)). NSE returns HTML for non-trading days; jugaad surfaces as BadZipFile. Test mocks NSEArchives to raise BadZipFile, asserts wrap.
  - UDiff `HTTPError` (404) → `MissingDataError` with status code in the message. Test fakes a 404 response and asserts `match="no UDiff F&O bhavcopy.*404"`.
  - UDiff `BadZipFile` (200 + HTML body, which NSE actually does in the wild) → `MissingDataError`. Test fakes a 200 with HTML content and asserts wrap. The fact that the BUILDER caught BOTH the 404 and the 200+HTML failure modes is the kind of attention real NSE gives back.
- **Dispatch-boundary test** ([tests/test_bhavcopy_fo_loader.py:309-336](tests/test_bhavcopy_fo_loader.py#L309-L336)) closes the gap from the fca735a review — pins 2024-07-07 → legacy, 2024-07-08 → udiff, 2024-07-09 → udiff. A `<` → `<=` regression would now fire.
- `raise X(...) from e` preserves the original traceback. `e.response.status_code if e.response is not None` is defensive.
- 45/45 pass in 0.35s.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **HTTP 403 currently wraps to `MissingDataError` too** (any `HTTPError` does). Semantically 403 means "data exists, you're rejected" (likely a stale browser UA), not "no data". For p1.3.2's `except MissingDataError: continue` iteration, a 403 would be silently swallowed — every sample-day might 403 and the calendar would build empty without a hint why. Consider distinguishing: `if e.response and e.response.status_code == 403: raise` (let it propagate) or wrap as a separate `BhavcopyAccessDeniedError`. Cheap insurance against the WAF-update-on-friday surprise.
- **`HTTPError` catch is broad.** A future 500/503 from NSE is genuinely "service flaking, retryable", not "no data". Mapping those to `MissingDataError` could turn a transient outage into a silent skip during a calendar build. Either narrow to 404/410 specifically, or keep `requests.HTTPError` propagating for 5xx and wrap only 4xx-with-no-data.
- **Wrap docstring lists `weekend, holiday, post-cutover` as causes** ([src/data/bhavcopy_fo_loader.py:84-86](src/data/bhavcopy_fo_loader.py#L84-L86)) — but "post-cutover" for legacy and "pre-cutover" for udiff are *programmer* errors (mis-dispatch), not data-availability gaps. The fetchers wouldn't be called for those dates by `_fetch_raw`. Worth removing from the docstring causes list to avoid teaching the wrong mental model.
- **`test_legacy_fetch_wraps_badzipfile_as_missing_data` uses `date(2024, 1, 6)` (Saturday)** as the requested date — fine, but the test doesn't actually verify it's a Saturday. The point of the test is the wrap, not the calendar logic. Cosmetic.

**Domain / correctness checks:**
- **jugaad-data usage:** correct — `NSEArchives()` is now monkey-patchable via the `bfo.NSEArchives` reference.
- **Look-ahead bias:** N/A this commit.
- **Options math / stats:** N/A.

**What I tried:**
- `python -m pytest tests/` → 45/45 in 0.35s.
- Read the new tests + the docstrings on `MissingDataError`.

**Next-commit suggestion:** Per the BUILDER's note, **`fix(p1.3.1.c): Int64Dtype + force_refresh`** is next. Two micro-decisions to pin BEFORE writing the code: **(1) For `Int64`, you need to update `_assert_specs_2_4_schema` from `dtype.name == "int64"` → accepting either `int64` or `Int64`, AND amend SPECS §2.4 to say "nullable integer (Int64) when upstream blanks are possible; plain int64 otherwise". The semantically right choice IMO is `Int64` for `oi` / `oi_change` (legitimately unknown is meaningful) and `int64` for `contracts` (an absent value means 0 traded, fillna(0) is the truth-preserving move). State this in SPECS so it's not a runtime surprise. (2) `force_refresh=True` must pass `cache.write(..., overwrite=True)` AND the test should assert that with cache present + `force_refresh=True`, `_fetch_raw` is called once (mirrors `spot_loader.test_force_refresh_refetches`). After those land, **immediately** kick off `feat(p1.3.2): expiry_calendar` — the MissingDataError wrap just made the calendar's iteration loop trivial; don't let the followup-bundle grow.

---

## Review of 765c49d — fix(p1.3.1.b.1): narrow MissingDataError wrap to 404/410; propagate 403/5xx

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Tighten the wrap policy so a stale-UA WAF block (403) or a transient NSE outage (5xx) doesn't masquerade as "no data" during a calendar iteration loop.

**What works:**
- `_NO_DATA_STATUSES = frozenset({404, 410})` ([src/data/bhavcopy_fo_loader.py:88](src/data/bhavcopy_fo_loader.py#L88)) — explicit allowlist with inline rationale per excluded code (403 → WAF, 5xx → retryable, other 4xx → code bug).
- Conditional wrap pattern ([src/data/bhavcopy_fo_loader.py:120-125](src/data/bhavcopy_fo_loader.py#L120-L125)) — `if status in _NO_DATA_STATUSES` then wrap, else bare `raise` to propagate the original HTTPError with its traceback intact. Clean.
- `test_udiff_403_propagates_not_wrapped` ([tests/test_bhavcopy_fo_loader.py:385-398](tests/test_bhavcopy_fo_loader.py#L385-L398)) and `test_udiff_5xx_propagates_not_wrapped` ([tests/test_bhavcopy_fo_loader.py:401-414](tests/test_bhavcopy_fo_loader.py#L401-L414)) pin the policy at both ends — 403 raises HTTPError("403"), 503 raises HTTPError("503"). A future regression that re-broadens the wrap fires both tests.
- Docstring cleanup removes "post-cutover" / "pre-cutover" from the causes list — those are dispatch errors, not data gaps. Right call.
- The reasoning in the UDiff docstring ("a calendar build silently skipping every date because the UA went stale would be the worst kind of quiet failure") captures exactly the loud-over-silent mental model.
- 47/47 pass in 0.34s.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Asymmetry between legacy and UDiff paths.** Legacy can't distinguish 403/404/5xx because jugaad's `@unzip` swallows them all into `BadZipFile`. So a 403 to jugaad would wrap as MissingDataError — silently. In practice, jugaad has worked for legacy dates for years and the WAF rarely 403s old endpoints; the asymmetry is unlikely to bite. But worth a one-line acknowledgment in the legacy docstring: "if jugaad's underlying response was anything other than a non-trading-day HTML page, the wrap is wrong — but we can't tell from the BadZipFile alone."
- **`_FakeResp` is inlined in 5 tests now**. Could be a tiny test helper `def _http_resp(status, content=b''):`. Cosmetic — DRY only if a 6th test appears.
- The 5xx test uses 503 only. 500/502/504 follow the same code path; pinning 503 as the representative is fine, but if you ever switch the policy to "retry 5xx N times" you'll want to test each. Defer.

**Domain / correctness checks:**
- **jugaad-data usage:** correct — legacy uses NSEArchives, UDiff uses requests directly, no overlap.
- **Look-ahead bias / options math / stats:** N/A.

**What I tried:**
- `python -m pytest tests/` → 47/47 in 0.34s.
- Read the diff; mentally walked through what would happen on a 4xx-not-in-allowlist (e.g. 400) → propagates as raw HTTPError → caller sees code bug. Correct.

**Next-commit suggestion:** Stay on `fix(p1.3.1.c): Int64Dtype + force_refresh` as previously planned. The Int64-vs-int64 split per column from the bc1add4 review still holds (`Int64` for `oi`/`oi_change` — legitimately unknown; `int64` for `contracts` — absent = 0 traded, `fillna(0)` is truth-preserving). One add: with the wrap policy now this tight, the BUILDER may discover during p1.3.2 implementation that NSE's actual missing-date behavior includes **HTTP 200 with a JSON error body** (third format some endpoints do) — keep an eye on that edge case during the p1.3.verify live run and add it as a third wrap site if it bites. For now, no action needed.

---

## Review of 4b8cf2f — fix(p1.3.1.c): Int64Dtype for oi/oi_change (nullable); int64 for contracts (fillna(0))

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Implement the per-column dtype split from the bc1add4 review — `contracts` stays plain `int64` (absent = 0 traded, fillna preserves truth), `oi` / `oi_change` become nullable `Int64` (legitimately unknown is meaningful).

**What works:**
- SPECS §2.4 amended row-by-row with explicit rationale per column ([SPECS.md:138-140](SPECS.md#L138-L140)). Future readers won't relitigate the choice.
- Parser updates symmetric across both formats:
  - Legacy: [src/data/bhavcopy_fo_loader.py:194-196](src/data/bhavcopy_fo_loader.py#L194-L196)
  - UDiff: [src/data/bhavcopy_fo_loader.py:248,262-263](src/data/bhavcopy_fo_loader.py#L248)
- `_assert_specs_2_4_schema` split ([tests/test_bhavcopy_fo_loader.py:68-74](tests/test_bhavcopy_fo_loader.py#L68-L74)) — `contracts` → `int64`, `oi`/`oi_change` → `Int64`. Structurally enforced.
- `test_parser_handles_blank_oi_via_nullable_int` ([tests/test_bhavcopy_fo_loader.py:315-328](tests/test_bhavcopy_fo_loader.py#L315-L328)) — synthesizes a legacy row with blank `OPEN_INT`/`CHG_IN_OI`; asserts they parse as `pd.NA` AND that `contracts=1` is preserved (not coerced). Future upstream blanks won't crash.
- Parquet round-trip preserves Int64 via pyarrow — exercised implicitly by `test_load_bhavcopy_fo_cache_hit_skips_fetch` which calls `_assert_specs_2_4_schema` on the post-roundtrip frame.
- 48/48 pass.

**Blocking issues / non-blocking suggestions:** None. This is the clean, mechanical implementation of the bc1add4 framing.

**Domain / correctness checks:**
- **Options math:** `contracts` semantically = "trades executed this day, zero if untouched" — `fillna(0)` is correct.
- **Statistical claims:** Int64-typed `oi` will surface as `pd.NA` in aggregations, not as 0 — important for future sweep stats so a "skipped on bootstrap day" row doesn't get silently averaged in as 0.
- **Look-ahead / jugaad:** N/A.

**Next-commit suggestion (rolled into a43e9d4 below).**

---

## Review of a43e9d4 — fix(p1.3.1.d): force_refresh kwarg on load_bhavcopy_fo

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close the last f5ff10c flag — mirror `spot_loader.load_spot`'s `force_refresh` semantics on the bhavcopy_fo loader.

**What works:**
- `force_refresh: bool = False` keyword-only kwarg ([src/data/bhavcopy_fo_loader.py:273](src/data/bhavcopy_fo_loader.py#L273)). Pass-through to `cache.write(..., overwrite=force_refresh)` ([src/data/bhavcopy_fo_loader.py:285](src/data/bhavcopy_fo_loader.py#L285)).
- `test_force_refresh_refetches` ([tests/test_bhavcopy_fo_loader.py:458-481](tests/test_bhavcopy_fo_loader.py#L458-L481)) walks all four phases: (1) cold fetch, (2) cache hit (no re-fetch), (3) `force_refresh=True` → re-fetch (calls=2), (4) subsequent normal call uses overwritten cache (still calls=2). Comprehensive.
- 49/49 pass. Phase 1.3.1 followup work is now complete; loader is behavior-symmetric with spot_loader.

**Blocking issues / non-blocking suggestions:** None.

**Domain / correctness checks:** N/A — purely a behavior surface added with mirror semantics.

**What I tried:** `python -m pytest tests/ -v` → 49 passed in 0.36s. Read both diffs end-to-end.

**Next-commit suggestion:** `feat(p1.3.2): expiry_calendar` — the **load-bearing test from commit one is determinism**: call `monthly_expiries(symbol, from_date, to_date)` twice with the same inputs (monkeypatch `load_bhavcopy_fo` to return a fixed frame); assert byte-identical sorted output. The entire reason this module exists is to escape the `list(set(dts))` non-determinism we logged in PLAN.md change-log on 2026-05-24; if the calendar's output isn't deterministic, every Phase-3 backtest is too. **Sampling strategy I'd commit to**: for each calendar month in the window, iterate days 1..7 and take the first that resolves (`except MissingDataError: continue`) — the MissingDataError wrap from bc1add4 makes this trivial. One bhavcopy per month gives ALL listed expiries (near + far months), so a 12-month window's union is essentially complete. Document the strategy in SPECS §2.3. Hand-check the BUILDER planned originally: `monthly_expiries("RELIANCE", 2024-01-01, 2024-01-31) == [date(2024,1,25)]`. With the legacy fixture already containing RELIANCE expiries [Jan-25, Feb-29, Mar-28], the determinism test can drive end-to-end without live network.

---

## Review of ce95d70 — chore(p1.3.2.prep): SPECS §2.3 sampling strategy + legacy wrap-precision note

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin the sampling strategy and determinism contract in SPECS §2.3 before the p1.3.2 implementation lands, and acknowledge the legacy/UDiff wrap-precision asymmetry I flagged on 765c49d.

**What works:**
- **SPECS §2.3 sampling strategy** ([SPECS.md:118-130](SPECS.md#L118-L130)) — exactly the four-step pattern from my prior suggestion: iterate days 1..7 per calendar month → first to resolve wins → filter OPTSTK-for-symbol → union & sorted.
- **Determinism contract named explicitly**: "two calls return byte-identical lists" ([SPECS.md:128-130](SPECS.md#L128-L130)). The reason for the module exists in writing.
- `expiry_date` / `month_anchor` now reference §2.0 — closes the date-dtype generalization properly.
- Legacy `_fetch_legacy` docstring update ([src/data/bhavcopy_fo_loader.py:95-104](src/data/bhavcopy_fo_loader.py#L95-L104)) names the asymmetry, points the next debugger at the WAF-after-update failure mode. Closes the 765c49d flag with words, not extra code.

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**
- **Days-1..7 strategy is undefended against pathological months.** Extremely unlikely (NSE has at most ~3 consecutive non-trading days), but if a future calendar disruption ever produced 7 consecutive non-trading days (force-majeure suspension), the iteration would exhaust. Decide now: extend to day 8+? log warning + skip month? Document the fallback.
- **Cache invalidation contract is ambitious.** SPECS §2.3 says "subsequent call for a new month range only fetches the missing months" — that's incremental cache, which requires tracking *which* months are present (a month with zero expiries leaves no rows). For v1, **commit to a simpler "full-window rebuild" semantic** and defer incremental to Phase 7 polish. Otherwise p1.3.2 will need a sentinel-row scheme just to mark "this month was sampled, found nothing" — yak-shaving for a feature we don't need yet. Add to SPECS: "v1: full rebuild when window changes; incremental optimization deferred."
- **`expiry` vs `expiry_date` naming inconsistency.** §2.4 (bhavcopy) uses `expiry`; §2.3 (calendar) uses `expiry_date`. Different names for the same date semantics. Fine if intentional (calendar output is conceptually a list of dates, hence the suffix) — but a one-line note explaining the rename will save the next reader a grep.

**Domain / correctness checks:**
- **Look-ahead bias:** N/A pure docs; but the sampling-day strategy implicitly assumes day-1-of-month is in the past relative to the call site. Caller responsibility.
- **jugaad-data / options math / stats:** N/A.

**What I tried:** Read the diff; verified the sampling strategy's "one bhavcopy per month is sufficient" claim against the recorded fixtures (legacy 20240125 has RELIANCE expiries Jan-25/Feb-29/Mar-28 visible — one sample → 3 expiries listed → consistent with the claim).

**Next-commit suggestion:** `feat(p1.3.2): expiry_calendar` — the prior suggestion still holds (determinism is the load-bearing first test, candidate-day iteration via `MissingDataError`, hand-check `RELIANCE 2024-01 == [2024-01-25]`). One sharpening: **make v1 a full-window rebuild, not incremental** — the cache is a single per-symbol parquet, blow it away on window change. The SPECS §2.3 incremental phrasing can be revised in the same commit (or deferred to a fix later) — but don't yak-shave a sentinel-row scheme for the empty-month case in p1.3.2 itself. Get the deterministic, correct, hand-check-passing calendar landed first; optimize cache invalidation in Phase 7.

---

## Review of 26b964e — feat(p1.3.2): expiry_calendar.monthly_expiries — sampled-bhavcopy union

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Implement the SPECS §2.3 sampling strategy: enumerate month anchors, sample days 1..7 per anchor, filter OPTSTK-for-symbol, union, sort, cache. Determinism is the contract.

**What works:**
- Algorithm follows the SPECS §2.3 sampling strategy faithfully ([src/data/expiry_calendar.py:10-21](src/data/expiry_calendar.py#L10-L21) docstring; matches the steps in §2.3 1:1).
- **Three deduplication / sort gates** kill non-determinism on every path: `sorted()` inside `_sample_expiries_for_month`, `drop_duplicates + sort_values` before persisting ([src/data/expiry_calendar.py:131-139](src/data/expiry_calendar.py#L131-L139)), and `sorted(set(...))` on the final return ([src/data/expiry_calendar.py:149](src/data/expiry_calendar.py#L149)).
- `_empty_calendar_frame()` ([src/data/expiry_calendar.py:71-78](src/data/expiry_calendar.py#L71-L78)) shapes the cold-cache case so the concat/dedupe path doesn't have to special-case it. Clean.
- `_CANDIDATE_SAMPLE_DAYS = tuple(range(1, 8))` ([src/data/expiry_calendar.py:33](src/data/expiry_calendar.py#L33)) — module-level constant; trivially extended later.
- `MissingDataError` caught and silently continues to next candidate day ([src/data/expiry_calendar.py:62-63](src/data/expiry_calendar.py#L62-L63)) — exactly what the bc1add4 wrap was designed for. Other exceptions propagate.
- Cache pattern uses `cache.write(..., overwrite=True)` ([src/data/expiry_calendar.py:139](src/data/expiry_calendar.py#L139)) because cache is being REPLACED with the merged set — correct for an incremental-merge model.
- **Verified end-to-end** with synthetic bhavcopy fixture:
  - Two calls → byte-identical output (`[date(2024,1,25)]`); 2nd call: 0 new fetches.
  - Jan-Mar window with one-month-per-sample → 3 expiries returned, 3 fetches issued.
  - Narrow Jan 1-10 window → `[]` even though Jan-25 is in cache (window filter works).
  - Lowercase `"reliance"` → normalized to `RELIANCE` cache.
  - `from_date > to_date` → `ValueError`.
  - Incremental extension: 1st call covers Jan (1 fetch); 2nd call asks Jan-Mar (2 new fetches for Feb+Mar, Jan from cache).

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Empty-month sentinel gap (the incremental-cache caveat I raised on ce95d70).** A month where the symbol has no OPTSTK rows (RELIANCE will never trip this; some delisted/pre-F&O exotic might) yields zero new rows in `_build_new_rows`, so the anchor never appears in `cached["month_anchor"].unique()`, so it'll be re-sampled on every future call. Two paths: (a) document the limitation in the module docstring + SPECS §2.3; (b) add a sentinel row (`expiry_date=NaT, month_anchor=anchor`) per sampled month. For v1 (a) is fine; flag it in writing.
- **Silent loss when all 7 candidate days raise MissingDataError.** `_sample_expiries_for_month` returns `[]` ([src/data/expiry_calendar.py:64-65](src/data/expiry_calendar.py#L64-L65)) with no warning. NSE has never had 7 consecutive non-trading days, but if a future calendar disruption produces that, the calendar will silently miss expiries. One-line `warnings.warn(f"no usable bhavcopy in days 1..7 for {anchor}")` before returning would surface it.
- **`force_refresh` kwarg not added** for symmetry with `load_spot` / `load_bhavcopy_fo`. Defensible (calendar is a derived view; force-refresh the underlying bhavcopies) but worth documenting why we didn't add it.
- The same expiry can appear under multiple `month_anchor` rows by design (Jan sample lists Jan/Feb/Mar expiries; Feb sample lists Feb/Mar/Apr; …). Dedupe on full tuple keeps them. The final `unique()` on `expiry_date` collapses correctly. Worth a test to pin this against future refactors that might dedupe-on-(symbol,expiry_date) and silently lose the audit trail of which sample-month observed an expiry.

**Domain / correctness checks:**
- **jugaad-data usage:** indirect — through `load_bhavcopy_fo`. Correct.
- **Options math:** filters strictly for `instrument == "OPTSTK"` ([src/data/expiry_calendar.py:66](src/data/expiry_calendar.py#L66)) — excludes FUTSTK and any future-only contracts. Correct for short-straddle.
- **Look-ahead bias:** the sampling iterates candidate dates *within the month being sampled* — caller's `to_date` could be in the past, so candidate days could be in the past or near-future. The calendar doesn't enforce "candidate ≤ today". For a backtest at-time-T, this is acceptable because the candidate is days-of-month-in-question, not days-of-today. But callers querying a future month would silently fetch a non-existent bhavcopy → MissingDataError → empty.
- **Statistical claims:** N/A.

**What I tried:**
- Monkeypatched `bhavcopy_fo_loader.load_bhavcopy_fo` with a synthetic RELIANCE OPTSTK frame (3 forward expiries) for days 1..7 of each tested month; MissingDataError otherwise.
- Drove 6 distinct scenarios end-to-end (determinism, window, narrow window, lowercase, validation, incremental extension). All green.

**Next-commit suggestion:** `test(p1.3.2)` — make determinism `test_monthly_expiries_is_deterministic` THE FIRST test in the file, with a comment naming it as load-bearing per the module's reason-to-exist. Two calls under the same monkeypatch → `assert result1 == result2` AND `pd.testing.assert_frame_equal(read_cache(), read_cache())` on the on-disk parquet (catches any cache-write nondeterminism). Then pin the **hand-check** against the recorded legacy fixture: monkeypatch `_fetch_raw` so day-1 of Jan-2024 returns the real legacy fixture; assert `monthly_expiries("RELIANCE", Jan-1, Jan-31) == [date(2024,1,25)]`. Plus tests for incremental extension (Jan-only first → Jan-Mar second triggers only 2 new fetches) and the empty-result case (all 7 days MissingDataError → `[]`, ideally with a recorded warning per the silent-loss flag above).

---

## Review of 2b00c68 — test(p1.3.2): expiry_calendar — 10 tests with determinism as the load-bearing first

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin every contract from `monthly_expiries` with determinism as the FIRST test in the file. Use the recorded legacy fixture to drive the RELIANCE Jan-2024 hand-check.

**What works:**
- **59/59 pass** in 0.42s.
- `test_determinism_byte_identical_repeated_calls` ([tests/test_expiry_calendar.py:65-81](tests/test_expiry_calendar.py#L65-L81)) is FIRST in the file. Three calls → `a == b == c` AND `a == sorted(a)` (the second assertion catches a regression where one call's set-iteration order *happened* to be sorted, the next wasn't). Naming the test as load-bearing in the docstring keeps it visible.
- `test_reliance_jan_2024_hand_check` ([tests/test_expiry_calendar.py:88-100](tests/test_expiry_calendar.py#L88-L100)) — uses the **real parsed legacy fixture** (not a synthetic frame). Error message names the reference's provenance: "This is the load-bearing reference value the entire Phase-1.3 plan was anchored on." A future regression's failure message tells you exactly why it matters.
- `test_skips_non_trading_days_at_start_of_month` ([tests/test_expiry_calendar.py:145-164](tests/test_expiry_calendar.py#L145-L164)) — call_log pins the EXACT iteration order `[Jan 1, 2, 3, 4]`. Catches off-by-one regressions in the candidate-day loop.
- `test_extending_window_samples_only_new_months` ([tests/test_expiry_calendar.py:217-264](tests/test_expiry_calendar.py#L217-L264)) — proves the incremental cache contract: Jan-only first → Jan-Mar second samples ONLY Feb+Mar, not Jan again. Avoids the "wider window re-samples everything" bug class.
- `_make_fake_loader` helper ([tests/test_expiry_calendar.py:36-58](tests/test_expiry_calendar.py#L36-L58)) is a small, configurable loader with optional `call_log`. Reusable for any future expiry_calendar test.
- `test_only_requested_symbol_returned` includes both positive (RELIANCE → [Jan-25]) and **negative** (DOES_NOT_EXIST → []) — catches symbol-confusion silently.
- `test_filters_expiries_outside_window` — sample lists Jan/Feb/Mar expiries, narrow Jan window returns Jan only. Closes the leak-from-sample concern.
- `test_month_with_no_trading_in_first_7_days_returns_empty` pins my flagged silent-loss case as a behavior contract (returns `[]`, no crash).

**Blocking issues:** None.

**Non-blocking suggestions:**
- **No test of on-disk parquet stability across regenerations.** Determinism is asserted at the return-list level only. If `sort_values(...).reset_index(drop=True)` ever stops being stable, the OUTPUT is still sorted at return time, but the CACHE bytes could vary call-to-call — a problem for byte-level reproducibility audits. Cheap add: read the on-disk parquet twice via `cache.read(cache.expiry_path("RELIANCE"))` and `pd.testing.assert_frame_equal(...)`.
- **`test_month_with_no_trading_in_first_7_days_returns_empty` doesn't assert a warning** (the BUILDER didn't add the warning to the implementation either — my prior flag still stands). The test pins "[] returned" but not "operator was told". If the warning gets added later, this test should be updated to `with warnings.catch_warnings(record=True) as wlog:` and assert one warning.
- **No multi-month partial-failure test.** What if a 3-month window has one month where all 7 candidate days fail? Currently: returns `[]` for that month, others succeed. Worth a test that drives this: months Jan + Mar populated, Feb totally dark → result is union of Jan + Mar only.
- **`test_only_requested_symbol_returned` uses `DOES_NOT_EXIST`** which would also produce an empty cache file `expiries/DOES_NOT_EXIST.parquet`. That's a minor disk-pollution edge case in the test fixture; harmless because tmp_path is per-test.
- The pretty `_make_fake_loader` works only for "any day in a configured month" — doesn't model "day X is a holiday but the bhavcopy for day Y exists". The `test_skips_non_trading_days_at_start_of_month` uses the `non_trading_days` set parameter — fine. But for the multi-month-partial-failure test above, the helper supports it (just leave a month out of `per_month_frames`).

**Domain / correctness checks:**
- **jugaad-data usage / options math / stats:** N/A this commit.
- **Look-ahead bias:** the tests don't check that the calendar refuses to sample future months — implicit "caller knows what they're doing" semantic. Fine for v1; tighten when Phase 3 plumbs through `today_fn`.

**What I tried:**
- `python -m pytest tests/ -v` → 59/59 in 0.42s.
- Read the test file end-to-end; cross-checked the `_make_fake_loader` configuration against each test's monkeypatch contract.

**Next-commit suggestion:** `chore(p1.3.verify): one live-NSE end-to-end run` — the **highest-de-risking single call** is one that **spans the Jul-8-2024 cutover**: `monthly_expiries("RELIANCE", date(2024, 6, 1), date(2024, 9, 30))`. This exercises (a) the legacy fetcher for June, (b) the UDiff fetcher live for July/August/September — which we've never run for real (the recorded fixture was Aug-29 only, captured by the discovery script, not by the loader's actual fetch path). It confirms in one shot: dispatch picks the right channel across the boundary, UDiff fetch works end-to-end with the pinned Chrome UA, and the resulting expiry list matches NSE's published monthly schedule (Jun-27 / Jul-25 / Aug-29 / Sep-26 are the canonical last-Thursday-of-month for 2024). Print the result to stderr + cross-check those 4 dates against known truth. If anything's off, the discovery is contained and offline tests still pass.

---

## Review of 4d9b544 — chore(p1.3.verify): live-NSE cutover-spanning verification — ALL GREEN

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Run a single live call that spans the Jul-8-2024 cutover and corroborates the offline test suite against real NSE data — exercising both fetch paths, dispatch, WAF UA, cache, and window filter end-to-end.

**What works:**
- **I ran the script independently** (cold cache, no prior state) — `python scripts/verify_p1_3.py` → **ALL 4 SCENARIOS GREEN**:
  - Cold call: `[2024-06-27, 2024-07-25, 2024-08-29, 2024-09-26]` in 3.4s. **Exact match** against the canonical last-Thursday-of-month schedule.
  - Hot call: same result in 32ms (cache hit confirmed).
  - Narrow Aug window: `[2024-08-29]` only.
  - Cross-check: Jun-3 bhavcopy independently lists RELIANCE expiries `[2024-06-27, 2024-07-25, 2024-08-29]` — Jun-27 corroborated.
- **My result == the BUILDER's reported result, byte-for-byte.** Independent reproducibility confirmed.
- 4 scenarios chosen for de-risking value, not coverage volume:
  1. Cold across cutover → dispatch + both fetch paths + WAF UA in one shot.
  2. Hot → cache contract.
  3. Narrow window → window filter on cached data.
  4. Direct bhavcopy load → independent corroboration without going through the calendar.
- Hand-check truth named in code ([scripts/verify_p1_3.py:34-39](scripts/verify_p1_3.py#L34-L39)) with per-line dates and "Thursday" annotations — so a future reader doesn't need to relook up what the canonical schedule is.
- Failure handling is explicit (`return 1` per scenario, useful messages).

**Blocking issues:** None.

**Non-blocking suggestions:**
- **No assertion that BOTH fetch paths actually fired during the cold call.** If a future regression forced `_udiff_start_date` to far-future, the cold call would route Jul/Aug/Sep through legacy → those would all `MissingDataError` (no legacy bhavcopies post-cutover) → calendar returns empty → script's `expected != []` test fires. So the existing test catches it indirectly. But explicit logging (`print(f"_udiff_start_date={...}")` + a one-shot assertion that the path was exercised) would surface the dispatch decision visibly. Cheap add.
- **Cold timing not asserted upper bound.** 3.4s on my machine, 5.6s on the BUILDER's. If a future change accidentally makes the cold path 30s, the script still passes. A `if cold_s > 15: print("WARN: cold path slow")` would flag drift. Defer; the script is one-off.
- **Script can't re-verify cold path on a populated cache** (running it twice in a row turns the "cold" call into a hot call). A `--clean` flag that `rm -rf data/cache/expiries/RELIANCE.parquet` + the relevant bhavcopy parquets before the cold call would let you re-verify on demand. Defer to next time someone wants to re-run.

**Domain / correctness checks:**
- **jugaad-data usage:** legacy via NSEArchives, UDiff via direct requests — both proven live.
- **Options math:** the 4 returned dates are the actual NSE monthly stock-option expiries for Jun-Sep 2024. Verified against my own recollection of the NSE calendar (last Thursday of each month, with the standard convention that they ARE last Thursday because none of these months had a Thursday-on-holiday situation).
- **Look-ahead bias:** N/A this commit.
- **Statistical claims:** N/A.

**What I tried:**
- `rm`'d nothing manually — verified `data/cache/` didn't exist locally (BUILDER's run was gone).
- `python scripts/verify_p1_3.py` cold → all green as reported, with timings within ~40% of the BUILDER's.

**Next-commit suggestion:** Per the BUILDER's note, the next is a tiny `fix(p1.3.x)` for the open non-blocking flags: (1) `warnings.warn(...)` in `_sample_expiries_for_month` when all 7 candidate days raise `MissingDataError`; (2) SPECS §2.3 note on the empty-month sentinel-row gap; (3) update `test_month_with_no_trading_in_first_7_days_returns_empty` to use `warnings.catch_warnings(record=True)` and assert the new warning fires. Then **straight to `feat(p1.4): options_loader`** — the load-bearing concern there is the **strike-key collision** (cache file path uses `int(strike)`, but the bhavcopy stores `strike: float64`; ensure the loader rejects non-integer strikes via the same `StrikeNotIntegerError` guard `cache.option_path` has, since this is the layer where strike values cross from float to int-keyed-on-disk).

---

## Review of fe6f1e0 — fix(p1.3.2.b): all-7-fail warning + multi-month-partial + byte-stable tests

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close the three 2b00c68 non-blocking flags with a tiny commit, then mark Phase 1.3 done.

**What works:**
- **All-7-fail warning** ([src/data/expiry_calendar.py:78-84](src/data/expiry_calendar.py#L78-L84)) — informative message with month + symbol + "investigate if you see this in production" guidance. Right tone for an operator-facing surface.
- **`test_multi_month_partial_failure_returns_only_successful_months`** ([tests/test_expiry_calendar.py:198-238](tests/test_expiry_calendar.py#L198-L238)) — Jan + Mar populated, Feb dark; asserts `[Jan-25, Mar-28]` (union, not all-or-nothing) AND exactly one Feb warning. Pins the "calendar is graceful under partial failure" contract.
- **`test_on_disk_parquet_is_byte_stable_across_regenerations`** ([tests/test_expiry_calendar.py:241-261](tests/test_expiry_calendar.py#L241-L261)) — captures bytes, wipes, rebuilds, asserts bytes equal. Catches the class of regression where return-list is sorted but on-disk row-order varies across runs.
- **Module docstring updated** ([src/data/expiry_calendar.py:21-31](src/data/expiry_calendar.py#L21-L31)) with explicit "Known v1 limitations" listing the empty-month sentinel gap (deferred to Phase 7) and the all-7-fail behavior (now warning + empty). Future readers don't re-derive.
- **`force_refresh` deferred with reasoning** that mirrors my own framing in the prior review — accepted my "calendar is derived; force-refresh bhavcopies instead" argument verbatim.
- 61/61 pass in 0.45s.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`read_bytes()` byte-equality test could be brittle to pyarrow metadata changes.** Today pyarrow doesn't include creation-timestamps in parquet metadata; if a future pyarrow rev does, this test fails for unrelated reasons. Equivalent-but-more-semantic: `pd.testing.assert_frame_equal(read1, read2)` on the loaded parquets. Same regression coverage, less metadata-dependence. Defer; the current test catches the actual bug class.
- **Warning `stacklevel=3`** points 3 frames up from the warn site → `_sample_expiries_for_month`'s caller's caller = `monthly_expiries`'s caller. That's typically the right depth for an operator-facing surface. If you ever observe `:_sample_expiries_for_month:` paths in production warning logs, drop to `stacklevel=2`.
- The fix bundle absorbed three flags in one commit instead of one per — defensible because they're tightly related (all are silent-loss surface fixes), but per nuclear-step doctrine the cleanest pattern would have been 3 micro-commits. Not worth splitting now.

**Domain / correctness checks:**
- **jugaad-data usage / options math / look-ahead / stats:** N/A this commit.

**What I tried:**
- `python -m pytest tests/ -v` → 61/61 in 0.45s.
- Read both new tests + the warning message text.

**Phase 1.3 status:** **DONE.** 61 offline tests + 1 live NSE end-to-end run (cutover-spanning RELIANCE Jun-Sep 2024) all green. The whole data layer up through the expiry calendar is provably correct, deterministic, and resilient to NSE's known weirdness.

**Next-commit suggestion:** `feat(p1.4): data/options_loader.py` — mirror `spot_loader`'s structure (`_normalize`, `_fetch_year`-equivalent, per-(symbol, expiry, strike, type) parquet cache, `force_refresh` kwarg, `MissingDataError` wrap). Three things to bake in from commit one: **(1)** the **+5h30m IST date-shift fix** — `derivatives_df` likely returns the same `YYYY-MM-DD 18:30:00` representation as `stock_df`; verify by inspecting one raw row before normalizing. If true, normalize via the same idiom; if not, document the difference. **(2)** the `expiry` argument MUST go through the same `isinstance(_, datetime)` rejection as `bhavcopy_fo_path` — strike-int and expiry-date integrity at the API boundary, not deep inside the fetcher. **(3)** the **single load-bearing test**: hand-check `load_option("RELIANCE", date(2024,8,29), 2840, "CE", date(2024,8,29), date(2024,8,29))` against the recorded UDiff fixture values — `close=201.70, oi=41500, oi_change=-1500, contracts=26, lot_size=250`. Same row we already pinned in the bhavcopy_fo tests; if the options_loader returns the same numbers, the layers agree.

---

## Review of 1cff529 — chore(p1.4.prep): SPECS §2.2 amended with live-discovered derivatives_df facts

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Mirror the 641276e discovery pattern for derivatives_df — go look at real data, pin everything surprising in SPECS before writing the loader.

**What works:**
- **All three claims verified live by me**:
  - **No IST shift on `derivatives_df`** ✓ — confirmed Timestamp values at `00:00:00` for Aug-28/29. SAVES THE BUILDER from copy-pasting the spot_loader shift logic blindly.
  - **OI / CHANGE IN OI are float64 in jugaad's output** ✓ — Int64 nullable cast in the SPECS is exactly right.
  - **TOTAL TRADED QUANTITY = share units, not contracts** ✓ — empirically 6500 / lot 250 = 26 contracts, matching bhavcopy_fo's reported contracts=26 byte-for-byte.
- **Cross-layer agreement holds**: `derivatives_df` for the Aug-29 row shows `CLOSE=201.7, OI=41500, CHANGE IN OI=-1500` — exact match against the bhavcopy_fo fixture's `close=201.70, oi=41500, oi_change=-1500`. Two completely different upstream channels surfacing the same truth.
- SPECS §2.2 amendments are precise per-column ([SPECS.md:96-113](SPECS.md#L96-L113)), with rationale embedded next to each non-obvious dtype/units choice. Future readers don't re-derive.
- "One parquet per (symbol, expiry, strike, option_type); first fetch pulls full contract lifetime" ([SPECS.md:97-101](SPECS.md#L97-L101)) — explicit policy decision before implementation. Right move.
- `contracts = volume // lot_size` in the SPECS note ([SPECS.md:111](SPECS.md#L111)) — closes the same TtlTradgVol/lot confusion that bit f5ff10c, preemptively.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **NEW finding: `derivatives_df` returns rows in descending date order** (newest first). I tripped over this myself in the verify run — `df.iloc[-1]` got me Aug-28 not Aug-29 until I sorted ascending. The loader **must** sort ascending in `_normalize` (mirrors spot_loader). Add one line to SPECS §2.2: "rows returned by `derivatives_df` are in descending order; loader sorts ascending and asserts monotonicity per the data-layer invariant".
- **"~120 calendar days back from expiry"** ([SPECS.md:99](SPECS.md#L99)) as first-fetch policy — why 120? NSE typically lists stock-option contracts ~90 days before expiry (3 forward monthly expiries). Either pin the value to a real listing convention (90) or document the rationale (e.g. "120 gives a comfortable buffer against the 3-month listing window"). Currently it reads like a magic number.
- **`MARKET LOT` dtype not verified** as plain int. My run showed `LOT=250` int-looking but I didn't dump `df.dtypes`. The BUILDER's empirical findings should include this explicitly if they want to assert plain `int64`. Defer; the cast `.astype("int64")` will fix any float-typed `MARKET LOT` silently anyway.

**Domain / correctness checks:**
- **jugaad-data usage:** the asymmetry between `stock_df` (needs +5h30m) and `derivatives_df` (doesn't) is real, surprising, and now documented. Saves a half-hour of reconfusion later.
- **Options math:** lot_size + share-units volume → contracts derivation makes the relationship explicit. Good for Phase 3 backtester's lot-size accounting.
- **Look-ahead bias:** N/A this commit.
- **Statistical claims:** N/A.

**What I tried:**
- `derivatives_df("RELIANCE", Aug-28..Aug-29, 2840 CE Aug-29 expiry)` live, sorted ascending, cross-checked all three discovery claims against the existing bhavcopy_fo fixture's pinned values.

**Next-commit suggestion:** `feat(p1.4): options_loader` — the spot_loader pattern transplants almost directly with one structural change because of the new findings: **(1) `_normalize` does NOT add +5h30m** (derivatives_df is already midnight IST — verified). **(2) `_normalize` MUST sort ascending** (derivatives_df returns descending — also verified). **(3) Cast `OPEN INTEREST` / `CHANGE IN OI` from float64 → Int64** (jugaad emits float with NaN; SPECS says nullable Int64). **(4) Hand-check test pins the Aug-29 cross-layer agreement**: `load_option("RELIANCE", date(2024,8,29), 2840, "CE", date(2024,8,29), date(2024,8,29))` must return one row with `close=201.7, oi=41500, oi_change=-1500, volume=6500, lot_size=250` — same numbers as the bhavcopy_fo test. If the two layers ever disagree, ONE of them is wrong, and the test tells you which by name. **(5) `isinstance(expiry, datetime)` rejection at the load_option API boundary** mirrors the bhavcopy_fo_path discipline.

---

## Review of 95175dd — feat(p1.4): data/options_loader.py — cached per-contract option-price loader

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the options loader mirroring spot_loader's frozen-invariants pattern, adapted to per-contract granularity. Cross-layer hand-check is the canonical regression block.

**What works:**
- **Cross-layer hand-check verified LIVE on my run**: `load_option("RELIANCE", date(2024,8,29), 2840, "CE", ...)` returned `close=201.7, oi=41500, oi_change=-1500, volume=6500, lot_size=250` — every number matches the bhavcopy_fo fixture exactly. Two completely different upstream channels surfacing the same NSE truth.
- **All 15 SPECS §2.2 dtypes correct** in my run: `date/expiry=datetime64[us]`, `symbol/option_type=string`, `oi/oi_change=Int64`, `lot_size/volume=int64`, OHLC/strike/ltp/settle_price=float64.
- **Frozen invariants 1–5 implemented** ([src/data/options_loader.py:7-17](src/data/options_loader.py#L7-L17)):
  - Full-lifetime first fetch ([src/data/options_loader.py:93-122](src/data/options_loader.py#L93-L122)) — verified: 62 rows from 2024-05-31 to 2024-08-29 on the canonical contract (~90 days = NSE's actual 3-month listing window).
  - Closed-expiry immutability via `is_closed = expiry < today` branch ([src/data/options_loader.py:174-180](src/data/options_loader.py#L174-L180)).
  - Open-expiry subset-checked refetch ([src/data/options_loader.py:188-208](src/data/options_loader.py#L188-L208)) mirrors the fix(p1.2.b) policy from spot_loader.
  - Sort + monotonicity assert ([src/data/options_loader.py:88-89](src/data/options_loader.py#L88-L89)).
  - MissingDataError on empty raw ([src/data/options_loader.py:114-120](src/data/options_loader.py#L114-L120)) with an informative diagnostic message.
- **Midnight assertion** ([src/data/options_loader.py:81-86](src/data/options_loader.py#L81-L86)) — catches the case where a future jugaad change starts emitting offset timestamps. Loud failure mode is correct.
- **Input guards loud, not silent**: datetime expiry → TypeError, bad option_type → ValueError, from > to → ValueError, non-int strike → StrikeNotIntegerError (via cache.option_path). All four verified live.
- Narrow window (Aug 25–29) returned 4 trading days (Mon–Thu) correctly, with the full lifetime still cached.
- Hot read: 2ms (true cache hit — `_filter_window` on a 62-row frame).

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Network errors not wrapped as MissingDataError** in `_fetch_contract_lifetime`. `derivatives_df`'s internal HTTPError / BadZipFile / connection-reset propagates raw, breaking the symmetry bhavcopy_fo_loader has via `_fetch_legacy` / `_fetch_udiff`. If a weekend `load_option` call gets a different exception type than a weekend `load_bhavcopy_fo` call, Phase 3 backtester code will have to catch two error families. Wrap the empty-result path AND the upstream-failure path under one MissingDataError.
- **Midnight assertion uses `assert`** ([src/data/options_loader.py:83](src/data/options_loader.py#L83)) — disabled with `python -O`. Convert to `if not (times == midnight).all(): raise BhavcopyFormatError(...)` (or a new `OptionsFormatError`) so the invariant holds regardless of optimization flags.
- **`_normalize` doesn't assert "no duplicate dates"**. If `derivatives_df` ever returns two rows for the same date (NSE bhavcopy quirk?), they'd both end up in the cache silently. One-line `assert not df["date"].duplicated().any()` before write would close that gap.
- **First-fetch lifetime is calendar-days-based** (`expiry - timedelta(days=120)`). Trading-day-based would be more semantic but requires the trading_calendar from p1.5 — defer; the 120-day buffer comfortably covers NSE's ~90-day listing window.
- **Caller's `from_date` doesn't reduce the network fetch**. The full lifetime is fetched regardless of how narrow the caller's request is. By design (first-fetch policy), but worth a one-line SPECS §2.2 callout: "Caller's [from_date, to_date] only filters the *return*; the *fetch* always spans full contract lifetime."
- My "cold" 30ms is suspiciously fast → jugaad's pickle cache was warm from the Phase-1.3 verify run. The actual cold-network behavior wasn't measured here. Worth a `--clean-jugaad-cache` flag on the verify script later, or noting in the eventual verify commit that jugaad's `~/Library/Caches/nsehistory-stock/` should be wiped to measure true cold.

**Domain / correctness checks:**
- **jugaad-data usage:** correct — `derivatives_df` with all the right args; no IST shift (per the prep-commit empirical finding); descending order → ascending via sort.
- **Options math:** `lot_size=250, volume=6500, contracts=volume/lot=26` cleanly reconciles with bhavcopy_fo's reported `contracts=26`. Phase 3 backtest can use either column.
- **Look-ahead bias:** `today_fn` injection works; `is_closed = expiry < today_fn()` is the right branch for the immutability optimization. The fetch's `end = min(expiry, today)` also respects the boundary.
- **Statistical claims:** N/A this commit.

**What I tried:**
- 9 scenarios end-to-end against live NSE, all green. Cross-layer hand-check passes byte-for-byte against the existing bhavcopy_fo pinned values.
- Read [src/data/options_loader.py](src/data/options_loader.py) line by line.

**Next-commit suggestion:** `test(p1.4)` — the **load-bearing test is `test_cross_layer_handcheck_reliance_aug29`**: build a synthetic frame matching `derivatives_df`'s shape (15 jugaad cols, descending date order, OI as float64 with one NaN to exercise the Int64 cast) for the RELIANCE Aug-29 2840 CE contract; monkeypatch `derivatives_df` to return it; assert `load_option(...)` returns the same 5 values the bhavcopy_fo test pins (`close=201.7, oi=41500, oi_change=-1500, volume=6500, lot_size=250`). If the two layers ever diverge, the test names which one regressed. Beyond that, mirror the spot_loader test layout: separate tests for **(a) midnight assertion fires** on a synthetic frame with 18:30:00 timestamps (catches a future jugaad change), **(b) sort-ascending invariant** by feeding shuffled rows, **(c) closed-expiry cache immutability** + open-expiry subset-checked refetch (use today_fn to flip the branch), **(d) all four loud-rejection paths** (datetime expiry, bad option_type, from > to, non-int strike) — these I already exercised live but tests pin them offline. Skip the live-NSE verification commit until p1.5 lands; the cross-layer test against the recorded bhavcopy_fo values is enough for p1.4.

---

## Review of 488deae — test(p1.4): options_loader — 13 tests with cross-layer hand-check as load-bearing

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin every contract from `options_loader` with the cross-layer hand-check as the FIRST test in the file. 74/74 pass.

**What works:**
- `test_cross_layer_hand_check_matches_bhavcopy_fo` ([tests/test_options_loader.py:95-142](tests/test_options_loader.py#L95-L142)) is FIRST. Synthetic frame uses the RELIANCE Aug-29 2840 CE values verified in the prep commit. Asserts the 5 cross-layer numbers (`close=201.70, oi=41500, oi_change=-1500, lot_size=250, volume=6500 = 26 contracts × 250 lot`). Comment names what regression this catches.
- `test_returned_schema_matches_specs_2_2` ([tests/test_options_loader.py:149-175](tests/test_options_loader.py#L149-L175)) — explicit dtype assertions per SPECS §2.2: `StringDtype()`, `is_datetime64_any_dtype` (per §2.0), plain `int64` for lot_size/volume, nullable `Int64` for oi/oi_change.
- `test_first_fetch_pulls_full_contract_lifetime` ([tests/test_options_loader.py:182-209](tests/test_options_loader.py#L182-L209)) — captures the `from_date` passed to `derivatives_df` and asserts ≥100 days back. Pins the lifetime-not-window-fetch invariant.
- `test_closed_expiry_cache_hit_skips_refetch` ([tests/test_options_loader.py:216-241](tests/test_options_loader.py#L216-L241)) — re-monkeypatches `derivatives_df` to RAISE after the cold fetch, second call must succeed from cache. Same regression-block pattern as the other loaders.
- `test_non_midnight_date_fails_loud` ([tests/test_options_loader.py:409-428](tests/test_options_loader.py#L409-L428)) — injects 18:30:00 (mimicking a future jugaad change to match stock_df's behavior), asserts the midnight assertion fires. The exact regression class my last review named.
- `test_open_expiry_refetches_when_stale` ([tests/test_options_loader.py:365-402](tests/test_options_loader.py#L365-L402)) — clever state-tracking factory that simulates "today" advancing past the cache's max date; verifies the open-expiry refresh policy.
- `_fake_derivatives` helper ([tests/test_options_loader.py:32-64](tests/test_options_loader.py#L32-L64)) and `_patch_derivatives` ([tests/test_options_loader.py:67-84](tests/test_options_loader.py#L67-L84)) are clean reusables; the call-log allows fetch-count assertions in multiple tests.
- **74/74 pass** in 0.53s.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Subset-based partial-response check is implemented but untested.** `options_loader._load_year`'s subset path ([src/data/options_loader.py:195-208](src/data/options_loader.py#L195-L208)) mirrors spot_loader's `test_partial_response_with_dropped_dates` — but no analogous test for options. A same-length-but-content-shifted fresh response should keep cache + warn; without a test, the next refactor can regress the subset upgrade silently.
- **`test_non_midnight_date_fails_loud` catches `AssertionError`** — works under default Python, but `python -O` strips asserts → loader becomes silent again on stale jugaad. My prior non-blocking flag (use `raise OptionsFormatError(...)` instead of `assert`) is still open; once addressed, this test catches the new exception type too.
- **Network-error wrap symmetry still missing** ([src/data/options_loader.py:103-113](src/data/options_loader.py#L103-L113)) — `derivatives_df`'s HTTPError/BadZipFile propagates raw; bhavcopy_fo_loader wraps. Phase 3 will have to catch both error families. Re-flagging from 95175dd review.
- **No "no-duplicate-dates" assertion**. If `derivatives_df` ever returns two rows for the same date, they survive into cache silently. One-line check in `_normalize` would close it.

**Domain / correctness checks:**
- **jugaad-data usage / options math / look-ahead / stats:** N/A this commit (pure tests).
- **Schema/dtype contract:** every dtype mandated by SPECS §2.2 has a test assertion.

**What I tried:**
- `python -m pytest tests/ -v` → 74/74 in 0.53s.
- Read the full test file (442 lines); cross-checked the load-bearing test's values against the bhavcopy_fo test file's pinned numbers.

**Next-commit suggestion:** `chore(p1.4.verify)` — the **highest-de-risking single call** is a runtime cross-layer comparison that triangulates real NSE truth: `load_option("RELIANCE", date(2024, 8, 29), 2840, "CE", date(2024, 8, 29), date(2024, 8, 29))` AND `load_bhavcopy_fo(date(2024, 8, 29))` on the same row; assert close/oi/oi_change/lot_size are equal across the two layers. **Bonus**: run a SECOND comparison on a pre-cutover contract — `RELIANCE 2024-01-25 2620 CE` (matches the legacy fixture's expiry). That exercises (a) the legacy bhavcopy path under bhavcopy_fo_loader, (b) `derivatives_df` for a pre-Jul-8-2024 contract, and confirms both data sources agree across the cutover boundary. Cross-layer agreement on both sides of the cutover is the strongest end-to-end guarantee the data layer can offer before Phase 1.5 lands.

---

## Review of 02e3644 — fix(p1.4.b): OptionsFormatError + duplicate-date guard + 4xx/5xx wrap policy

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close all four 488deae flags in one targeted fix commit; bring the options_loader to behavior-parity with bhavcopy_fo_loader.

**What works:**
- **`assert` → `raise OptionsFormatError`** ([src/data/options_loader.py:80-92](src/data/options_loader.py#L80-L92)). New class in errors.py with docstring naming the rationale ("loud-failure replacement for `assert` statements that would be stripped under `python -O`").
- **No-duplicate-dates guard** ([src/data/options_loader.py:96-104](src/data/options_loader.py#L96-L104)) with sample-of-3 in the error message. Same loud-failure pattern.
- **Network-error wrap policy** ([src/data/options_loader.py:120-148](src/data/options_loader.py#L120-L148)) — symmetric with bhavcopy_fo's fix(p1.3.1.b.1): 404/410 → MissingDataError, BadZipFile → MissingDataError, everything else (403/5xx) propagates raw. Phase 3 backtester now catches ONE error family across spot/bhavcopy_fo/options.
- **Subset partial-response test** ([tests/test_options_loader.py:534-591](tests/test_options_loader.py#L534-L591)) uses an **open-expiry** future contract so the refetch path actually fires; state-driven factory flips from `full` → `shifted` between the two calls; asserts (a) dropped middle date survives, (b) spurious far-future date doesn't leak, (c) warning emitted. Comprehensive.
- New tests: `test_duplicate_dates_fail_loud`, `test_404_wraps_as_missing_data`, `test_403_propagates_not_wrapped`, `test_badzipfile_wraps_as_missing_data`, `test_partial_response_with_dropped_dates`. Plus `test_non_midnight_date_fails_loud` updated to expect `OptionsFormatError`.
- SPECS §2.2 callout ([SPECS.md:102-104](SPECS.md#L102-L104)) — "caller's window only filters the return; fetch always spans full lifetime". Closes the doc gap I flagged on 95175dd.
- **79/79 pass** in 0.54s.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **No `test_5xx_propagates_not_wrapped` for options_loader.** bhavcopy_fo has both 403 and 5xx tests; options_loader has only 403. If someone "simplifies" the condition to `if status >= 400: wrap`, 5xx would start wrapping silently. Cheap to mirror: add `test_5xx_propagates_not_wrapped` with `status=503`. Same shape as the 403 test.
- **`(404, 410)` inline tuple** in options_loader vs bhavcopy_fo's `_NO_DATA_STATUSES = frozenset({404, 410})` module constant — minor aesthetic drift. Lifting to a shared constant in `errors.py` would prevent future divergence. Defer; both work equivalently today.
- **`OptionsFormatError` is options-specific** but the *pattern* (loud-raise instead of `assert`) might be reused by other loaders. If a similar non-midnight assertion ever lands in spot_loader, the BUILDER might want a shared `DataFormatError` parent. Defer until a second use case.
- **`test_partial_response_with_dropped_dates` uses future-dated open expiry 2026-06-26**. Cute trick to force the refetch path. When `today_fn` is the real `date.today()` and the test runs after that expiry, the contract becomes closed → refetch path no longer fires → test silently changes meaning. The `today_fn=` injection means this can't happen in practice, but worth a comment that the future-date is deliberate. Cosmetic.

**Domain / correctness checks:**
- **jugaad-data usage:** wrap policy now mirrors bhavcopy_fo's. Symmetry across loaders is the right design.
- **Options math / look-ahead / stats:** N/A this commit.

**What I tried:**
- `python -m pytest tests/` → 79/79 in 0.54s.
- Read the diff; cross-checked the wrap policy against bhavcopy_fo's `_NO_DATA_STATUSES`.

**Next-commit suggestion:** Stay on `chore(p1.4.verify)` — the cross-layer cutover-spanning live verification I suggested last time. Concretely: a single `scripts/verify_p1_4.py` that runs **two cross-layer comparisons** — RELIANCE Aug-29 2840 CE (post-cutover, `load_option` ↔ `load_bhavcopy_fo` UDiff path) AND RELIANCE Jan-25 2620 CE (pre-cutover, `load_option` ↔ `load_bhavcopy_fo` legacy path). Each comparison loads the same row via both loaders and asserts close/oi/oi_change/lot_size match. Print results to stderr. If both pre-cutover and post-cutover agree byte-for-byte across loaders, Phase 1.4 is provably correct end-to-end and the data layer is ready for Phase 1.5.

---

## Review of eef66cd — test(p1.4.c): mirror options_loader 5xx propagation + future-date comment

**Verdict:** ✅ accept

Trivial followup. Two tiny things closed from the 02e3644 review:

- `test_5xx_propagates_not_wrapped` ([tests/test_options_loader.py:511-538](tests/test_options_loader.py#L511-L538)) mirrors bhavcopy_fo's 503 test. Now both loaders symmetrically guard against the `status >= 400` shortcut regression.
- Comment on `test_partial_response_with_dropped_dates` ([tests/test_options_loader.py:563-566](tests/test_options_loader.py#L563-L566)) explains why the future-dated expiry is deliberate.

80/80 pass in 0.54s. No new flags.

**Next-commit suggestion:** Unchanged — proceed with `chore(p1.4.verify)`, the dual cross-layer cutover-spanning live run.

---

## Review of 5689cff — chore(p1.4.verify): cross-layer live verify BOTH sides of cutover — ALL GREEN

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Cross-layer triangulation against real NSE data on both sides of the 2024-07-08 cutover.

**What works:**
- **I ran the script independently → ALL GREEN, byte-for-byte match** with the BUILDER's reported values:

  | Side | close | oi | oi_change | volume | contracts |
  |---|---|---|---|---|---|
  | POST (Aug-29 2840 CE) | 201.7 | 41500 | -1500 | 6500 | 26 = 6500/250 ✓ |
  | PRE (Jan-25 2620 CE) | 83.7 | 838000 | -17500 | 59000 | 236 = 59000/250 ✓ |

- The **pre-cutover comparison is the strongest cross-validation in the project so far**: legacy bhavcopy parser AND `derivatives_df` for a pre-Jul-8-2024 contract both surface the SAME numbers as a real NSE record. If either layer regressed on the legacy path, this would catch it.
- Script architecture: dataclass-based `Case`, per-case `verify()` returning bool, single `main()` aggregator. Clean.
- Asserts the **contracts↔volume/lot relationship** ([scripts/verify_p1_4.py:106-110](scripts/verify_p1_4.py#L106-L110)) — the SPECS §2.4 documented unit invariant is now empirically corroborated on two real contracts (250 lot in both cases, 26 contracts and 236 contracts respectively).
- `today_fn=lambda: date(2026,5,24)` forces closed-contract regime for both cases — the `is_closed` branch in options_loader is exercised. Smart.

**Blocking issues:** None.

**Non-blocking suggestions:**
- The verify doesn't exercise the **open-contract refetch path** of options_loader — both cases are closed contracts. The offline `test_open_expiry_refetches_when_stale` covers it offline; live coverage would require a fresh contract whose expiry hasn't passed. Defer to phase-7 verify expansion, if ever.
- No cold/hot timing print like `verify_p1_3.py` had. Less essential here since the focus is correctness equality, not performance. Cosmetic.

**Domain / correctness checks:**
- **jugaad-data usage:** both endpoints exercised live; both work.
- **Options math:** lot_size + volume + contracts triangle holds across two completely different upstreams. Phase 3 backtester can use either column without ambiguity.
- **Look-ahead bias:** `today_fn` forces closed regime; no leak.
- **Statistical claims:** N/A.

**What I tried:**
- `python scripts/verify_p1_4.py` cold → both cases green, byte-for-byte match.

**Phase 1.4 status:** **DONE.** 80 offline tests + 1 live cross-layer verification on both cutover sides. The data layer's contracts (spot + bhavcopy + expiries + options) are provably consistent end-to-end.

**Next-commit suggestion:** `feat(p1.5): data/trading_calendar.py` — implement `trading_days(from, to)` and `offset_trading_days(anchor, n)`. The **load-bearing test is `offset_trading_days` correctness**: every Phase-3 backtest's entry/exit date depends on it; a single off-by-one breaks every backtest's prices silently. Concrete hand-check: `offset_trading_days(date(2024,1,25), 15) == date(2024,1,4)` (Jan-25 expiry → 15 trading days back, skipping weekends + Jan-1 Republic Day-adjacent holidays = Jan-4). Bake in three invariants from commit 1: (a) bootstrap trading-day calendar from `load_spot("RELIANCE", ...)` per SPECS §6 — don't introduce a separate data source; (b) **cross-validate against `jugaad_data.holidays`** as a sanity check (any date returned by `trading_days` that's also in the holidays list is a bug); (c) `offset_trading_days(holiday, 0)` semantics — pin the behavior explicitly (raise? round to next trading day? round to previous?). My recommendation: round-down to previous trading day, since that's what "T+0 means same day" really means when T-itself isn't a trading day.

---

## Review of fee312f — chore(p1.5.plan): pin offset_trading_days anchor semantics before impl

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pre-resolve the anchor-edge-case ambiguity I flagged on 5689cff so the impl doesn't have to relitigate. Five rules added to SPECS §3's `offset_trading_days` docstring.

**What works:**
- All five rules pinned ([SPECS.md:249-263](SPECS.md#L249-L263)):
  1. anchor IS trading day, n=0 → anchor (identity).
  2. anchor NOT trading day, n=0 → most recent trading day **strictly** before anchor (round-down, matching my recommendation).
  3. n=1 → "one trading day before anchor".
  4. n < 0 → ValueError.
  5. Insufficient history → ValueError.
- Bootstrap source named explicitly ([SPECS.md:265-266](SPECS.md#L265-L266)) — `load_spot(CALENDAR_SYMBOL, ...)` from SPECS §6, NO separate data source. Reuses existing infrastructure.
- jugaad_data.holidays cross-validation called out as a test responsibility, not a runtime hard-check (right call — tests catch upstream drift; runtime should trust the bootstrapped calendar).

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**
- **n=1-from-non-trading-anchor is subtly ambiguous.** Under the rule-3 wording "one trading day before anchor", Saturday→n=1 could mean either: (a) round-down first (Friday), then step 1 back → Thursday; OR (b) "1 trading day before Saturday" → Friday (the prior trading day from a non-trading anchor). These give different answers. The mathematically clean interpretation is **(a) compositional with rule 2**: `offset(anchor, n)` = trading_day_at_index(`rank(anchor) - n`) where `rank(anchor)` is the index of the round-down. Under (a), Saturday → n=0 = Friday, n=1 = Thursday, n=2 = Wednesday. Pin (a) explicitly with an example so the test writer doesn't have to derive it. As-is, the docstring's "regardless of whether anchor itself is a trading day" parenthetical could be read either way.
- **No timezone note.** `anchor: date` is naïve; NSE trades in IST. `date.today()` is system-tz-dependent. Not a practical issue if callers always use IST-system Python, but worth a one-liner: "anchor is interpreted as a naïve IST date".
- **No example in the docstring.** "n=15 from Jan-25-2024 expiry returns Jan-4-2024" would make the rules concrete and serve as a documentation hand-check. Cheap add.

**Domain / correctness checks:**
- **Look-ahead bias:** round-down semantics is the right call for non-trading anchors — round-up could leak future data.
- **jugaad-data usage / options math / stats:** N/A pure docs.

**What I tried:** Read the diff; mentally traced the rule-3 ambiguity through both interpretations to confirm the trap.

**Next-commit suggestion:** `feat(p1.5): trading_calendar.py` — implementation. Stay with the spot_loader pattern (pure functions, no global state); cache the trading-day list per-year-of-spot rather than its own parquet (the spot_loader cache already has all the dates we need — derived view, not new data source). **Crucial: include a `test_anchor_off_trading_day_compositional` that explicitly nails the n=1-from-Saturday case** so the rule-3 ambiguity gets resolved by code, not by re-reading SPECS. The Jan-25 → n=15 → Jan-4 hand-check is the canonical positive test; the Saturday-anchor case is the canonical edge test.

---

## Review of 19e0657 — feat(p1.5): data/trading_calendar.py — trading_days + offset_trading_days

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Implement the trading-day calendar. Bootstrap from `load_spot(CALENDAR_SYMBOL, ...)` (not a holidays database), so unusual sessions like the 2024-01-20 Saturday special-trading-day are picked up automatically.

**What works:**
- **Architectural elegance**: bootstrap-from-spot rather than holidays-database. The 2024-01-20 Saturday special session (NSE compensating for closing Monday Jan 22 for Ram Mandir) would be MISSING from any pre-computed forward-holidays calendar. By trusting "if RELIANCE traded, it's a trading day", we get this kind of NSE weirdness for free. Commit message ([commit 19e0657](src/data/trading_calendar.py) docstring lines 1-9) calls this out explicitly.
- **`offset_trading_days` chose the COMPOSITIONAL semantic** for non-trading anchors — exactly Definition A from my fee312f flag, resolved by code. The implementation `days_le[-(n+1)]` after filtering to `d <= anchor` automatically handles both cases (trading anchor: `[-1]` = anchor; non-trading anchor: `[-1]` = round-down). Clean.
- **Verified live triple**:
  - `offset_trading_days(2024-01-25, 15) == 2024-01-04` ✓ (the canonical hand-check)
  - `offset_trading_days(2024-01-22, 0) == 2024-01-20` ✓ (Jan-22 was Ram Mandir closure → round-down lands on Sat-special-session)
  - `offset_trading_days(2024-01-22, 1) == 2024-01-19` ✓ (Definition A: round-down then step back)
- **Buffer expansion** ([src/data/trading_calendar.py:75-90](src/data/trading_calendar.py#L75-L90)) is robust — initial `max(n*2 + 14, 60)`, doubles on miss, capped at 1500 days. Beyond cap → ValueError naming the limit.
- `today_fn` injection on both functions ([src/data/trading_calendar.py:43, 59](src/data/trading_calendar.py#L43)) — testable; mirrors spot_loader's pattern.
- `end = min(anchor, today_fn())` ([src/data/trading_calendar.py:79](src/data/trading_calendar.py#L79)) — load_spot won't return future data.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Buffer double-and-retry discards the previous fetch.** Since `spot_loader` caches the whole year, the second pass is essentially free (parquet hit + filter), so the practical cost is zero. But algorithmically the inner `while True` could be tightened: load spot ONCE for `from_date = anchor - MAX_BUFFER`, count trading days <= anchor, fail loud if `len < n+1`. Single pass, no retry. Cosmetic — the current code works.
- **Future-dated anchor semantics not documented.** `anchor = date(2030,1,1)` + n=0 → returns most recent trading day ≤ today (since `end = min(anchor, today)`). That's "n=0 from future date = today's last trading day", which is a reasonable round-down extension but not explicitly stated in the docstring. Add a one-liner: "if anchor is in the future, `today_fn()` is used as the upper bound" — Phase 3 sweepers iterating forward may hit this.
- **`days_le = [d for d in days if d <= anchor]`** ([src/data/trading_calendar.py:81](src/data/trading_calendar.py#L81)) is defensive but redundant when `end = min(anchor, today)` already caps. Either keep as defense-in-depth (current) or drop and rely on the load_spot window. Minor.
- **No caching of `trading_days` result itself.** Each call to `offset_trading_days` re-calls `load_spot` (which is parquet-cached, so fast). Across a Phase-4 sweep with thousands of `offset_trading_days` calls, an in-memory LRU cache could speed things up by ~10x. Defer until measured.

**Domain / correctness checks:**
- **jugaad-data usage:** indirect via spot_loader. Correct.
- **Options math:** N/A this commit.
- **Look-ahead bias:** `end = min(anchor, today_fn())` is the right guard — no leak.
- **Statistical claims:** N/A.

**What I tried:**
- Read the implementation line by line.
- Traced the algorithm for the three verified examples mentally — all check out.
- Cross-referenced the Saturday Jan-20-2024 claim against my own NSE knowledge (yes, that was a real special trading session for Ram Mandir).

**Next-commit suggestion:** `test(p1.5)` — make the **load-bearing test the Ram-Mandir-closure compositional case** (`offset_trading_days(2024-01-22, 0) == 2024-01-20` and `offset_trading_days(2024-01-22, 1) == 2024-01-19`). This single test proves THREE non-obvious things at once: (a) round-down semantics for non-trading anchors works; (b) the bootstrap-from-spot architecture captures Saturday special sessions that any pre-computed holidays database would have missed; (c) the Definition-A compositional interpretation of n=1 (my fee312f flag) is the one in code. Plus: the canonical hand-check (`Jan-25 → n=15 → Jan-4`), `n<0` raises ValueError, insufficient-history raises ValueError with the buffer-cap diagnostic, AND a **jugaad_data.holidays cross-check** (load `holidays(2024)`, intersect with `trading_days(2024-01-01, 2024-12-31)` — must be empty). That last one is the structural sanity check the SPECS mandates.

---

## Review of 46054a8 — test(p1.5): trading_calendar — 12 tests including Muhurat Trading cross-check

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin trading_calendar contracts offline + add live network tests that corroborate the offline behavior against real NSE data.

**What works:**
- **90/90 default + 2/2 network = 92/92 green** in my run.
- **Hand-check load-bearing test FIRST** ([tests/test_trading_calendar.py:61-73](tests/test_trading_calendar.py#L61-L73)) — `offset_trading_days(2024-01-25, 15) == 2024-01-04`. Docstring explicitly says "a single off-by-one breaks every backtest's prices silently".
- **`_JAN_2024_NSE_DAYS` synthetic fixture** ([tests/test_trading_calendar.py:43-54](tests/test_trading_calendar.py#L43-L54)) captures TWO real NSE quirks: Jan-22 Ram Mandir closure AND Jan-20 Saturday compensation. The fixture's correctness was live-verified before being baked offline.
- **The compositional / round-down semantics tests close my fee312f ambiguity by code**:
  - `test_n_zero_on_non_trading_day_rounds_down` ([tests/test_trading_calendar.py:89-97](tests/test_trading_calendar.py#L89-L97)) → Jan-22 → 0 → Jan-20.
  - `test_n_one_on_non_trading_day` ([tests/test_trading_calendar.py:100-110](tests/test_trading_calendar.py#L100-L110)) → Jan-22 → 1 → Jan-19 (Definition A compositional).
- **`test_overlap_with_jugaad_holidays_is_only_muhurat_trading`** ([tests/test_trading_calendar.py:195-218](tests/test_trading_calendar.py#L195-L218)) — **major real-NSE discovery**: 2024-11-01 (Diwali Lakshmi Puja Muhurat) appears in BOTH `trading_days` and `jugaad.holidays(2024)` because NSE runs a ~1-hour ceremonial session that produces real OHLC AND is marked as a "holiday" upstream. The test allowlists `KNOWN_MUHURAT_2024 = {date(2024,11,1)}` and asserts the difference is empty. Sets the right precedent: future Diwali muhurat days need adding.
- `test_offset_trading_days_live_reliance_jan_25` runs the same canonical hand-check via REAL `load_spot` — independent corroboration that the offline synthetic fixture matches reality.
- Network tests properly marked `@pytest.mark.network` per pytest.ini — opt-in, default-skipped.
- `test_insufficient_history_raises` ([tests/test_trading_calendar.py:122-130](tests/test_trading_calendar.py#L122-L130)) — uses a 5-day fixture + n=100 to force the buffer-cap ValueError.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`KNOWN_MUHURAT_2024` is inline in the test.** For 2025+ sweeps the test will fail loud (good!) but the update mechanic is hidden. Lifting to a module-level `_KNOWN_MUHURAT_BY_YEAR = {2024: {date(2024,11,1)}, 2025: {...}, ...}` would make future-year additions a one-line PR.
- **No `test_n_one_on_trading_day_anchor` for the n=1-from-trading-day case.** Implicitly covered by the n=15 hand-check but worth pinning: `offset(2024-01-25, 1) == 2024-01-24`. One line.
- **`test_offset_trading_days_live_reliance_jan_25` doesn't use `today_fn`** — uses real `date.today()`. If the test is run before 2024-01-25 (it won't be in practice, but hypothetically), the calendar's `end = min(anchor, today)` would change behavior. Cosmetic.
- The synthetic fixture is the "1 month" view. A larger fixture spanning 2-3 months with more holidays would let `test_insufficient_history_raises` use more realistic n values. Minor.

**Domain / correctness checks:**
- **jugaad-data usage:** cross-check works as designed; one expected overlap (Muhurat).
- **Options math / look-ahead / stats:** N/A this commit.
- **Architectural validation:** the Muhurat finding confirms that the bootstrap-from-spot strategy captures MORE accurate trading semantics than any pre-computed holidays database. Phase 3 backtest can trust this.

**What I tried:**
- `python -m pytest tests/` → 90/90 default in 0.56s.
- `python -m pytest tests/test_trading_calendar.py -m network -v` → 2/2 network tests pass live.
- Read the full test file; cross-checked the synthetic fixture against my own NSE knowledge.

**Phase 1.5 status:** **DONE.** Trading calendar works correctly even for the rare NSE weirdness (Saturday compensation, Muhurat).

**Next-commit suggestion:** Per the BUILDER's note, `chore(p1.5.verify)` next, then Phase 1.6 (offline-mode kwarg). For p1.5.verify I'd recommend going beyond a single-function live check: write a small **Phase-1 integration script** that strings the whole data layer end-to-end on one realistic backtest preamble. E.g.:
1. `monthly_expiries("RELIANCE", 2024-01-01, 2024-01-31)` → confirm `[date(2024,1,25)]`.
2. `offset_trading_days(date(2024,1,25), 15)` → confirm `date(2024,1,4)`.
3. `load_option("RELIANCE", date(2024,1,25), <ATM_strike>, "CE", date(2024,1,4), date(2024,1,25))` → confirm ~15 trading-day rows of real prices.
4. Independently `load_bhavcopy_fo(date(2024,1,4))` → assert ATM CE close from bhavcopy == load_option's Jan-4 close.

That single integration proves all four loaders + the calendar agree end-to-end — Phase 1 is then *operationally* ready for Phase 2 (universe) and Phase 3 (engine).

---
