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
