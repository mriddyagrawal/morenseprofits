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
