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

## Review of 2518c50 — chore(p1.5.verify): Phase-1 end-to-end integration verify — ALL GREEN

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** String all five data-layer modules together end-to-end on one realistic backtest preamble — the strongest single integration test possible before Phase 2 / Phase 3.

**What works:**
- **Independent live run: ALL GREEN, byte-for-byte match** with the BUILDER's reported values:
  - Step 1 (expiry_calendar): `monthly_expiries("RELIANCE", Jan-2024) == [date(2024,1,25)]` ✓
  - Step 2 (trading_calendar): `offset_trading_days(2024-01-25, 15) == 2024-01-04` ✓
  - Step 3 (spot_loader): RELIANCE Jan-4 close = 2596.65 → ATM 2600
  - Step 4 (options_loader): 16 rows, entry close = 56.50, exit close = 102.40, lot=250, max OI=3894250
  - Step 5 (bhavcopy_fo): cross-check Jan-4 close = 56.50 — **byte-identical** with options_loader
- **Realistic economic content** surfaces in the output. RELIANCE rallied ~4% from 2596 to ~2702 over the 15 trading days, so the short ATM straddle would have lost (entry premium ~56, exit intrinsic ~102 = ~₹46/lot loss × 250 = ₹11,500 per lot). That's the kind of trade Phase 3 will quantify.
- Script structure is clean: per-step `_h(section header)`, explicit per-step timing, fail-fast `return 1` with diagnostic context. Easy to read both during a run and in commit messages.
- The cross-layer comparison at step 5 is the load-bearing assertion — it triangulates the entire chain against an independent NSE source.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **All timings suspiciously fast** (Step 1: 1.56s; Step 4: 0.01s; Step 5: 0.99s). Step 4's 0.01s is impossible-cold — must be hitting jugaad's pickle cache or our own parquet cache from prior verify runs. Doesn't affect correctness, but for a true cold benchmark a `--clean` flag that wipes both `data/cache/options/RELIANCE/` AND `~/Library/Caches/nsehistory-stock/` before running would be useful documentation. Defer.
- **No sanity bounds on entry/exit closes.** If a future regression made the parser return premium in paise (×100), cross-layer agreement still holds and the test still passes. A loose check (`5 < entry_close < 500`) would catch that class. Cosmetic; the human-readable output makes the absurdity easy to spot.
- **Only the CE side is exercised** — short straddle is CE + PE. A `_check_side("PE")` pass would round out the integration. Cheap to add; defer to Phase 3 if not done now.
- **`ATM = round(spot_close / 20) * 20`** is a magic-step. NSE strike-step is actually variable by underlying price band. For RELIANCE at ~2600 the step IS ₹20 (matches the legacy bhavcopy fixture's 1840/1860/1880/...), so the script is correct. Worth a one-line comment naming this assumption.

**Domain / correctness checks:**
- **jugaad-data usage:** full pipeline exercised via real endpoints.
- **Options math:** entry CE @ 56.50 + PE @ ~56 = premium ~₹112 total; exit ATM CE @ 102.40 + ATM PE @ ~0 = ~₹102 intrinsic; net loss ≈ ₹10 per share × 250 lot = ₹2500 per lot. (My napkin math; the BUILDER's commit message says ~lost money — agreed.) The numbers are *economically plausible*, which is more than the schema tests can verify.
- **Look-ahead bias:** `today_fn = date(2026,5,24)` puts the contract firmly in the past; no leak.
- **Statistical claims:** N/A this commit.

**What I tried:**
- `python scripts/verify_phase1_integration.py` independently → 5/5 steps green, byte-for-byte agreement at the cross-layer comparison.

**PHASE 1 STATUS:** **DONE.** Six data-layer modules (cache, spot, bhavcopy_fo, expiry_calendar, options, trading_calendar) + 92 offline tests + 4 live verification scripts. All known NSE weirdness captured: dual bhavcopy format, IST date shift in stock_df, holiday-shifted expiries, Saturday special sessions, Diwali Muhurat. Cross-layer agreement holds end-to-end.

**Next-commit suggestion:** PLAN.md sequence has Phase 1.6 (offline-mode kwarg) and Phase 1.7 (cache-hit telemetry) before Phase 2. They're hardening, not new capability. If you want to **defer 1.6/1.7 to start Phase 2 (universe selection) immediately**, that's defensible — the Phase 1 verify run proves the data layer works without offline-mode. If you do continue with 1.6 first, the **load-bearing concern is uniformity**: the `offline: bool = False` kwarg must reach ALL four loaders (spot, bhavcopy_fo, options, expiry_calendar) with identical semantics — `offline=True` AND `MORENSE_OFFLINE=1` env → cache miss raises `MissingDataError` instead of network-fetch. A leaky implementation (one loader respects it, another doesn't) defeats the whole point. Add a parameterized test that hits every loader and asserts the behavior.

---

## Review of dbb4c65 — feat(p1.6): offline-mode kwarg across all loaders + MORENSE_OFFLINE env

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Implement SPECS §6a uniformly across all 6 public loader entry points. Use a distinct error class (`OfflineCacheMiss`, NOT a subclass of `MissingDataError`) so the existing swallow loops can't accidentally mask offline failures.

**What works:**
- **The error-class taxonomy decision is the highlight of this commit.** [src/data/errors.py:30-38](src/data/errors.py#L30-L38) makes `OfflineCacheMiss` a sibling of `MissingDataError`, not a child. Without this, every existing `except MissingDataError: continue` loop (expiry_calendar's candidate-day iteration, options_loader's stale-cache fallback) would silently swallow offline failures → empty results with no operator signal. The reasoning is documented in the class docstring and structurally enforced by `test_offline_cache_miss_is_not_missing_data_error` ([tests/test_offline_mode.py:208-215](tests/test_offline_mode.py#L208-L215)).
- **`effective_offline` helper** ([src/data/offline.py:22-28](src/data/offline.py#L22-L28)) — single point of truth for `(kwarg OR env)`. Strict env-var spec (only literal "1"). Test pins the strictness via `test_effective_offline_env_var_other_values_ignored`.
- **6/6 public loaders threaded uniformly**: `load_spot`, `load_bhavcopy_fo`, `load_option`, `monthly_expiries`, `trading_days`, `offset_trading_days`. All 6 import from the same `offline` helper → no behavioral drift possible.
- **`test_monthly_expiries_offline_propagates_OfflineCacheMiss` is the load-bearing test** ([tests/test_offline_mode.py:111-124](tests/test_offline_mode.py#L111-L124)) — proves the class distinction works in practice (the candidate-day loop does NOT catch offline failures).
- **Network-must-not-be-called guards** in every loader's offline test (`must_not_be_called` raises RuntimeError) — a future regression that accidentally fetches in offline mode fires loudly.
- **Cache HIT + offline still works** ([tests/test_offline_mode.py:148-183](tests/test_offline_mode.py#L148-L183)) — offline ≠ "disabled", offline = "trust the cache only". Pre-populate via a normal call, then re-call with offline=True, verifies the hit path.
- **103/103 pass** in 0.58s.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`force_refresh=True` + `offline=True` interaction not explicitly tested.** Commit message says "offline takes precedence (we never hit the network, period)". The implementation likely does the offline check before reaching force_refresh, but without a test, a future refactor that reorders the checks could silently flip the precedence. Add `test_offline_wins_over_force_refresh` to all three loaders that have `force_refresh`.
- **Stale-cache + offline path covered for spot/options but no explicit test.** Both loaders' code paths return cached frames rather than raising in this case (defensible: stale-not-empty is still better than no data). Worth a one-line test that pre-populates a current-year cache, then calls offline=True with `today_fn` advanced past the cache's max date — assert it returns the cache without raising.
- **Env var documentation** — `MORENSE_OFFLINE="true"` is NOT honored (only literal "1" is). The test pins this strictness, but a SPECS callout would prevent docs-driven confusion. Cosmetic.
- **Cross-layer integration script (`verify_phase1_integration.py`) doesn't exercise offline.** When someone runs `MORENSE_OFFLINE=1 python scripts/verify_phase1_integration.py` after the script has populated the cache once, it should succeed (cache hits) — but if any loader leaked through to network, it'd fail. Worth a follow-up commit that exercises this on a populated cache. Defer.

**Domain / correctness checks:**
- **jugaad-data usage:** offline check happens BEFORE any jugaad call site in every loader. Verified.
- **Options math / look-ahead / stats:** N/A this commit.
- **Architectural:** the kwarg-then-env-var precedence (`offline_kwarg OR env`) is the right composition — kwarg-False + env=1 → offline mode. Aligns with "env enables a project-wide flag without code change".

**What I tried:**
- `python -m pytest tests/` → 103/103 in 0.58s.
- Read the error taxonomy + the offline helper. Walked through one loader (`spot_loader`) to confirm the offline check sits before any fetch call.

**Next-commit suggestion:** `chore(p1.7): cache-hit telemetry`. The simple shape: emit a one-line `warnings.warn(...)` at the moment a loader DECIDES to fetch (after offline-check passed, after cache-exists check failed). One warning per fetch, not per call. Keep it opt-in: another env var `MORENSE_WARN_ON_FETCH=1` so legitimate Phase-4 sweeps with 60 cold fetches don't spam by default. Mirror the offline `effective_*` helper pattern in `offline.py` (or a new `telemetry.py`). The load-bearing test: monkeypatch the actual fetch function, set the env var, call the loader on a cold cache, assert one warning emitted naming both the loader and the key. After 1.7 lands, **immediately move to Phase 2 (universe selection)** — the data layer is then both feature-complete AND auditable for accidental fetches in production runs.

---

## Review of 702c1dc — feat(p1.7): cache-hit telemetry — opt-in fetch warnings via MORENSE_WARN_ON_FETCH

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Add opt-in telemetry that warns when a loader hits the network. Phase-4 sweeps can set `MORENSE_WARN_ON_FETCH=1` to surface accidental fetches without spamming legitimate cold-cache runs.

**What works:**
- **`src/data/telemetry.py` mirrors `offline.py`'s shape** — strict env-var pattern (only literal "1"), `warn_fetch(loader_name, key)` helper that's a no-op unless enabled.
- **Module docstring frames the WHY precisely** ([src/data/telemetry.py:4-7](src/data/telemetry.py#L4-L7)): "an accidental refresh during a backtest can pull in rows dated after the backtest's nominal 'now'". That's the look-ahead-bias angle — the real reason this matters, not just performance.
- **Three fetch-decision sites wired** with appropriate keys:
  - `spot_loader._fetch_year` → "RELIANCE 2024"
  - `bhavcopy_fo_loader._fetch_raw` → trade date
  - `options_loader._fetch_contract_lifetime` → "RELIANCE 2024-01-25 2620-CE"
- **expiry_calendar and trading_calendar inherit telemetry transitively** — they call the wired loaders, so any fetch they trigger surfaces. No separate wiring. Right design.
- **`stacklevel=3`** so the warning points at the caller's caller, not at `warn_fetch` itself. Operators see where the fetch decision was made.
- **Opt-in by default** — verified by the existing test suite running with mostly no warnings.
- **Hot-call silent** — pinned via `test_cache_hit_after_cold_does_not_re_warn` per the commit message. Catches the per-call-spam regression class.
- **112/112 pass** in 0.61s.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`warn_fetch` fires on fetch ATTEMPT, not on fetch SUCCESS.** If `_fetch_raw` is called and then raises `MissingDataError` (weekend, holiday), the warning fires for what looks like a "successful fetch attempt". That's semantically correct (the loader DID decide to hit the network), but could mislead an operator into thinking the cache was hit when really data is just missing. Worth a one-line docstring clarification.
- **No process-level summary.** Phase-4 sweeps with `MORENSE_WARN_ON_FETCH=1` could log dozens of warnings in chronological order. A simple `telemetry.fetch_count` counter that summarizes at process exit (or via an explicit `dump_stats()`) would be useful when investigating "why did this sweep take 30 minutes". Defer; opt-in via the env var is enough for v1.
- **No `warn_fetch` for the live verify scripts.** Running `MORENSE_WARN_ON_FETCH=1 python scripts/verify_phase1_integration.py` should produce 4-5 cold-cache warnings (one per fetch site) on a fresh cache, and zero on a warm cache. Verifying that interactively would tighten the contract; defer.
- **`loader_name` is a free-form string.** A future typo like `"spot_loaders"` would silently produce inconsistent telemetry. A module-level constant per loader (`_TELEMETRY_NAME = "spot_loader"`) would lock the spelling. Cosmetic.

**Domain / correctness checks:**
- **jugaad-data usage / options math / stats:** N/A pure observability.
- **Look-ahead bias:** the telemetry IS the bias-detection mechanism. A future-dated cache refresh during a backtest of past data would now emit a warning naming the loader + key. That's exactly the contract.

**What I tried:**
- `python -m pytest tests/` → 112/112 in 0.61s. The "1 warning" in pytest output is a test deliberately exercising the warning path with the env var set — not a leak.
- Read [src/data/telemetry.py](src/data/telemetry.py) and verified the wire-in points in all three loaders.

**Phase 1 status:** **TRULY DONE NOW.** 6 data-layer modules + 105 offline + 7 network-marked tests + 4 live verify scripts + offline-mode + cache-hit telemetry. Data layer is feature-complete, deterministic, auditable, and offline-capable.

**Next-commit suggestion:** **Move to Phase 2 (universe selection).** The PLAN.md sequence is p2.1 `blue_chip` → p2.2 `momentum classifier` → p2.3 CLI → p2.4 tests. For **`feat(p2.1): blue_chip universe`**, the load-bearing design decision is **how to handle membership drift over time**. Nifty 50 has changed composition ~12 times since 2019, and a true reproducible backtest sweeping 2019→2024 must use the correct membership *as of each year*, not a 2024 snapshot retrospectively applied to 2019 prices (that's the classic *survivorship bias*). Two paths: **(a)** hardcoded `BLUE_CHIP_BY_QUARTER: dict[date, list[str]]` with explicit `as_of` keys and a source citation per snapshot; OR **(b)** a single `BLUE_CHIP_2024_07_01` snapshot with a SPECS callout that v1 ignores survivorship bias (and Phase 7 fixes it). I lean (b) for v1 simplicity, but the *survivorship caveat must be visible in every UI rendering of universe-rooted backtest results* — Phase 5/6 plumbing. Pin the choice + caveat in SPECS before writing the list.

---

## Review of d61b164 — chore(p2.0): SPECS for universe — survivorship-bias policy + schema + sigs

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin the universe contracts (blue-chip + momentum + survivorship caveat) BEFORE writing any code. Phase 2 work then becomes mechanical.

**What works:**
- **Chose option (b) with explicit caveat** — matches my recommendation. Single 2024-07-01 Nifty 50 snapshot for v1.
- **`as_of: date` parameter required even though v1 ignores it** ([SPECS.md:282-283](SPECS.md#L282-L283)) — future-proofs the API for Phase 7's `BLUE_CHIP_BY_QUARTER` without breaking callers. Smart.
- **Survivorship bias is §6b.3** ([SPECS.md:399-414](SPECS.md#L399-L414)) — explicit section with three mitigations: UI disclaimer, Phase 7 backlog item, and visible in §6b.3 itself. The "load-bearing caveat" framing is the right level of severity.
- **Momentum classifier defined precisely** ([SPECS.md:387-397](SPECS.md#L387-L397)) — tercile on trailing-6mo returns, bullish/neutral/non_bullish, output sorted alphabetically per list for determinism.
- **PLAN.md decomposed into 6 nuclear steps** ([PLAN.md:112-117](PLAN.md#L112-L117)), CLI dropped (deferred to Phase 7, not load-bearing).
- **Exit criterion strengthened** from "identical" → "byte-identical" ([PLAN.md:120](PLAN.md#L120)).

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**
- **Why 2024-07-01 as the snapshot date?** SPECS picks it without justification. Likely "recent + first day of H2 2024 + post the Adani/Zomato/etc. recent additions". A one-line rationale would prevent "should we update to 2024-12-31?" debates later. Cosmetic.
- **Tercile boundary math under-specified.** For Nifty 50 = 50 symbols, top third = 17 (ceil) or 16 (floor)? Spec says "top third → bullish; middle third → neutral; bottom third → non_bullish" without resolving the 50/3 remainder allocation. State explicitly: "with `n = len(universe)`, bullish = first `ceil(n/3)`, neutral = next `n - 2*ceil(n/3) + ceil(n/3)` ≈ `n - ceil(n/3) - floor(n/3)`, non_bullish = last `floor(n/3)`"; or pick a simple rule like `ceil/floor/floor`. Otherwise the implementer makes an arbitrary call and the test pins whatever they chose. Worth one line.
- **`as_of - lookback_months` may land on a holiday/weekend.** For `lookback_months=6` from `as_of=2024-07-01`, the lookback date is `2024-01-01` — Republic Day weekend territory. `load_spot` will then return zero rows for that exact date, and the trailing-return calc divides by 0 or KeyErrors. The momentum classifier needs to **round the lookback date to the most recent trading day on or before `as_of - lookback_months`** — `trading_calendar.offset_trading_days(as_of - lookback_months_as_days, 0)` works. Pin this in SPECS §6b.2 before implementation.
- **Delisted symbols.** If a 2024-07-01 Nifty 50 stock had been delisted before `as_of`, `load_spot` would `MissingDataError`. Should the classifier (a) drop the symbol with a warning, or (b) propagate? Pick now, document.
- **No mention of Nifty 50 vs other indices.** "Blue chip" loosely; Phase 7 may want Sensex/Nifty100. Worth one line noting v1 is Nifty 50 only and Phase 7 can add other index_snapshots.

**Domain / correctness checks:**
- **Survivorship bias:** correctly identified as the dominant statistical concern.
- **Look-ahead bias:** the `as_of` parameter is the right abstraction; the classifier uses prices through `as_of`, not future. Implicit but worth a comment.
- **Statistical claims:** tercile cut on trailing return is a reasonable proxy for momentum — defensible methodology; can sensitivity-test in Phase 5.

**What I tried:** Read the SPECS diff in full; cross-referenced the function signatures against the planned p2.1 + p2.2 implementations.

**Next-commit suggestion:** `feat(p2.1): src/universe/blue_chip.py`. Two load-bearing things to get right: **(1)** the 50 symbols themselves — pull from NSE's published Nifty 50 list as of 2024-07-01 (e.g. NSE's index info page) and cite the exact source URL + access date in the file header. A future "update to 2024-12-31" then has a single-source-of-truth to consult. **(2)** the `as_of` parameter is required but ignored in v1 — return the same list regardless. **Test** (next commit): assert `len(blue_chip(any_date)) == 50`; assert `blue_chip(date(2024,1,1)) == blue_chip(date(2024,12,31))` (the ignored-as_of contract); assert the list is sorted alphabetically; spot-check a few known constituents (RELIANCE, TCS, HDFCBANK, INFY all in). The exact 50-list itself doesn't need a `pd.testing.assert_frame_equal`-style pin — a count + sort + spot-check is enough; if a deliberate update happens, the file changes but the test invariants hold.

---

## Review of acab8a7 — feat(p2.1): blue_chip universe — 40 large-cap NSE names

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the v1 blue-chip universe as a hardcoded 40-name list per user direction (sized down from 50 to drop low-options-liquidity tail). Survivorship-bias caveat from §6b.3 preserved at source.

**What works:**
- **40-name list is well-curated** — verified live: all major banks (HDFC/ICICI/SBI/AXIS/KOTAK/INDUSIND), IT majors (TCS/INFY/WIPRO/HCL/TECHM), pharma (CIPLA/DRREDDY/SUNPHARMA), Reliance/L&T/ITC/HUL etc. Defensible "thick options market" cut.
- **The 10 dropped names** (APOLLOHOSP, BEL, BPCL, HDFCLIFE, INDIGO, JIOFIN, SBILIFE, SHRIRAMFIN, TATACONSUM, TRENT) are indeed the lower-options-liquidity tail per the commit message. All are real NSE-listed; defensible drops.
- **Spelling matches NSE conventions exactly** ([src/universe/blue_chip.py:39-47](src/universe/blue_chip.py#L39-L47)) — `BAJAJ-AUTO` with hyphen, `M&M` with ampersand. Will work directly with `jugaad-data` without renames.
- **3 module-level invariants** ([src/universe/blue_chip.py:50-56](src/universe/blue_chip.py#L50-L56)): count=40, no dups, alphabetically sorted. Fire at import time.
- **Source honestly cited** as Wikipedia + "not a canonical published-research-grade composition" ([src/universe/blue_chip.py:22-23](src/universe/blue_chip.py#L22-L23)) — the right level of disclosure for a v1 shortcut.
- **`as_of` required, not defaulted** ([src/universe/blue_chip.py:58](src/universe/blue_chip.py#L58)) — forces caller intent at every call site even though v1 ignores it. Phase-7 upgrade then needs no API change.
- **Three change-log entries**: 50→40 sizing rationale, Phase-7 user-curated-universe skill, Phase-7 BLUE_CHIP_BY_QUARTER. Both deferrals trackable.
- **Live verify on my end**: 40/40 names, sorted, deduped, `as_of` truly ignored (three different dates return identical lists).

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Module-level `assert` for invariants** ([src/universe/blue_chip.py:50-56](src/universe/blue_chip.py#L50-L56)) — same `python -O` stripping risk as the previous options_loader case. The asserts are over a *static literal* so technically the invariants are correct at write time regardless; but if a future drive-by edit accidentally adds a duplicate, `python` would fail at import but `python -O` would silently load the broken list. Convert to `if ... : raise RuntimeError(...)` for consistency with the rest of the project. Cosmetic, low priority.
- **No `delisted/renamed symbol` guard.** If RELIANCE ever got delisted/renamed, the static list would still ship the old symbol and every downstream call would fail. Outside v1 scope; just noting.
- **Wikipedia source is fine but ephemeral.** The cited URL doesn't include an access-date in the URL itself (Wikipedia URLs don't snapshot by default). The docstring says "retrieval date ~2024-07-01" but a permanent URL via Wikipedia's "permalink" (`?oldid=N`) would lock the exact snapshot consulted. Defer; for v1 the list is what it is.
- **`blue_chip(as_of)` returns `list[_BLUE_CHIP_V1]`** which is a new list each call. Cheap (~40 string refs), so the GC churn is negligible. Worth noting that the v1 contract returns a copy (not the tuple) so callers can `.sort()`/`.append()` without mutating the source. Good.

**Domain / correctness checks:**
- **Survivorship bias:** acknowledged in the docstring with three explicit mitigations referencing SPECS §6b.3 + the Phase 7 backlog items.
- **Look-ahead bias:** N/A this commit (static list).
- **Options math / stats:** the "drop low-options-liquidity tail" is a reasonable selection rule for a straddle backtest universe — those names have wider bid-asks and would dominate the realized cost model.

**What I tried:**
- `python -c "from src.universe.blue_chip import blue_chip; ..."` → 40 names, sorted, dedup, canonical names present, `as_of` ignored across 3 different dates.
- Read the file end-to-end.

**Next-commit suggestion:** Per the BUILDER's plan, `test(p2.1)` next. The module-level asserts already pin count/sort/dedup at import time, so test value is mostly **API contract** (regression-blocker against a future refactor that breaks the public surface). Recommended tests: (1) `blue_chip(any_date)` returns a `list` (not `tuple` — pin the return type since `_BLUE_CHIP_V1` is a tuple internally); (2) `blue_chip(date1) == blue_chip(date2)` for arbitrary date1, date2 (the as_of-ignored contract — pin it explicitly so a future Phase-7 upgrade has to deliberately UPDATE this test, not silently drift); (3) one spot-check `"RELIANCE" in blue_chip(any_date)` since RELIANCE drives every reference contract in the test suite; (4) `len(blue_chip(any_date)) == 40` — guards against the 40→50 (or any other count) regression. After that, **immediately move to `feat(p2.2): momentum classifier`**. The tercile-boundary + holiday-lookback flags from my d61b164 review still need resolving in SPECS §6b.2 before the impl lands.

---

## Review of 019663e — test(p2.1): blue_chip — 8 tests pinning v1 universe contract

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin the v1 universe contract with focused regression-blockers; cover both the public API and the `python -O` strip risk on the module-level asserts.

**What works:**
- **120/120 pass** in 0.63s.
- 8 tests that line up exactly with the contract surface:
  - count=40, unique, sorted (the determinism trio)
  - `as_of` independence across 3 wildly-different dates ([tests/test_blue_chip.py:30-37](tests/test_blue_chip.py#L30-L37)) — locks the v1 behavior so a Phase-7 upgrade requires deliberately changing this test, not silently drifting
  - Canonical name presence (5 names: RELIANCE/HDFCBANK/INFY/TCS/ICICIBANK) — wider than I suggested (good)
  - **Mutation safety** ([tests/test_blue_chip.py:48-54](tests/test_blue_chip.py#L48-L54)) — caller appends "HACKED", subsequent call doesn't see it. Implicitly pins the "returns a list copy, not the internal tuple cast" contract.
  - **NSE spelling pins** ([tests/test_blue_chip.py:57-66](tests/test_blue_chip.py#L57-L66)) — BAJAJ-AUTO, M&M. A drive-by "clean up the punctuation" edit would break jugaad-data lookups silently; this test fires loud.
  - **`python -O` defense** ([tests/test_blue_chip.py:69-73](tests/test_blue_chip.py#L69-L73)) — re-checks the module-level asserts so they hold even if `assert` gets stripped. Sister-pattern to the OptionsFormatError discussion.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **No explicit `isinstance(out, list)` assertion.** Implicit via `.append("HACKED")` on the mutation test (tuples don't have append), but explicit type pin would be one extra line. Cosmetic.
- **`pytest` import unused** ([tests/test_blue_chip.py:6](tests/test_blue_chip.py#L6)) — minor.
- **NSE-spelling test pins only 2 names.** A "no-hyphen" name like BAJFINANCE could regress without firing this test. One more assertion (`"BAJFINANCE" in out` ensures the convention is "BAJFINANCE" not "BAJ-FINANCE") would tighten the regression net. Cosmetic.

**Domain / correctness checks:** N/A — pure-data contract pin.

**What I tried:** `python -m pytest tests/` → 120 passed in 0.63s.

**Next-commit suggestion:** `feat(p2.2): src/universe/momentum.py`. BEFORE writing code, pin three loose ends from the d61b164 review in SPECS §6b.2: **(a) tercile boundary for n=40** → 40/3=13.33, so pick e.g. `bullish=14, neutral=13, non_bullish=13` (top-heavy gives the higher-conviction bucket the larger sample) — and write `len(out["bullish"]) >= len(out["non_bullish"])` into the test contract; **(b) holiday-aligned lookback** → `lookback_date = trading_calendar.offset_trading_days(as_of, lookback_trading_days)` where `lookback_trading_days ≈ 6 * 21` (avg trading days/month) — switching from "6 calendar months" to "126 trading days" sidesteps the Jan-1-is-holiday trap entirely AND makes the lookback determinable from the trading calendar without month-arithmetic; **(c) delisted-symbol policy** → if `load_spot` for a universe symbol raises `MissingDataError` (delisted/renamed), the classifier **must drop the symbol with a `warnings.warn(...)` listing which one** and continue with the rest, NOT propagate. Otherwise one stale name in `blue_chip` would break the whole classifier. Test for this: monkeypatch `load_spot` to raise for one symbol; assert the symbol is missing from all three output lists AND a warning was emitted. The load-bearing test for p2.2 is `test_classify_momentum_is_deterministic` (two calls → byte-identical splits) — same pattern as expiry_calendar.

---

## Review of 397ad65 — chore(p2.2.prep): pin tercile + holiday lookback + delisted policy in SPECS §6b.2

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Resolve the three loose ends I flagged on d61b164 + 019663e in SPECS BEFORE writing the classifier, so the impl is mechanical.

**What works:**
- **Tercile pinned 14/13/13 top-heavy** ([SPECS.md:405-411](SPECS.md#L405-L411)) — exactly my suggested split, with the "higher-conviction bucket gets larger sample" rationale.
- **Lookback switched to trading days** ([SPECS.md:395-399](SPECS.md#L395-L399)) — `lookback_trading_days=126` (~6×21) routed through `offset_trading_days`. Sidesteps the calendar-month holiday trap by construction. Function signature updated.
- **Delisted policy explicit and load-bearing** ([SPECS.md:413-418](SPECS.md#L413-L418)) — `MissingDataError` → warn+drop, **NOT** propagate. `OfflineCacheMiss` (distinct class per SPECS §6a) DOES propagate. The two-class distinction we baked in for offline mode pays off here.
- **Anchor close logic explicitly defined** ([SPECS.md:400-404](SPECS.md#L400-L404)) — numerator = "largest date ≤ as_of", denominator = "smallest date ≥ lookback_date". Handles partial-history symbols cleanly (no assumed full window).
- **`lookback_trading_days` framed as Phase-5-tunable** — comment notes "Phase 5 can sensitivity-test lookback_trading_days as a parameter". Right call.

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**
- **126 magic constant** — define as `_DEFAULT_LOOKBACK_TRADING_DAYS = 126` in `momentum.py` (or a module-level constant) so Phase 5 sensitivity tests can reference the constant rather than hardcoding 126 in two places.
- **Insufficient-history at the front edge.** If a caller runs `classify_momentum(date(2019,1,1), ..., lookback_trading_days=126*5)`, `offset_trading_days` raises ValueError ("cannot find N trading days back"). The classifier doesn't catch — propagates. That's the right behavior (loud failure on impossible request) but worth a one-line SPECS callout so the implementer doesn't accidentally wrap it.
- **Partial-history symbols.** If a symbol started trading mid-window (e.g. ADANIGAS pre-listing), the "smallest date ≥ lookback_date" denominator picks the listing date itself → much shorter realized lookback than other symbols. The trailing-return number is then heterogeneous across the universe. Defensible (anything else requires synthetic baseline), but worth noting the partial-history case in §6b.2 so reviewers of backtest results understand a "missing window" symbol isn't excluded — it's just measured on a shorter window.
- **No worked example** — adding `monthly_expiries`-style example would help: "for `as_of=date(2024,7,1)`, lookback_date = `offset_trading_days(as_of, 126)` ≈ `date(2023,12,28)`; expected output split sizes for `len(blue_chip())=40` are `bullish=14, neutral=13, non_bullish=13`". Cosmetic.

**Domain / correctness checks:**
- **Look-ahead bias:** anchor close pinned to "largest date ≤ as_of" — no leak by construction.
- **Statistical claims:** tercile cut is a reasonable proxy for momentum; the top-heavy split is defensible; the 126-day lookback is a common momentum factor convention.
- **jugaad-data / options math:** N/A this commit.

**What I tried:** Read the SPECS diff; mentally traced the lookback-date math for `as_of=date(2024,7,1)`.

**Next-commit suggestion:** `feat(p2.2): src/universe/momentum.py` is now mechanical. The **load-bearing test** is `test_classify_momentum_is_deterministic` — two calls with identical inputs → byte-identical bullish/neutral/non_bullish lists. Same pattern as expiry_calendar. Three other tests must land in the immediately-following `test(p2.2)` commit because the implementation surfaces them as risks: **(1)** `test_split_sizes_sum_to_universe` (bullish+neutral+non_bullish == len(universe), no leaks) — guards against an off-by-one in the slice arithmetic; **(2)** `test_delisted_symbol_dropped_with_warning` — monkeypatch `load_spot` to `MissingDataError` for one universe entry, assert it's absent from ALL three lists AND a warning was emitted; **(3)** `test_OfflineCacheMiss_propagates` — sister test ensures the distinct-class semantic from SPECS §6a still holds at the classifier layer (one stale name should NOT silently mask an offline failure). Pin those three at minimum.

---

## Review of d581ab5 — feat(p2.2): momentum classifier + tests — tercile split on trailing return

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Implement SPECS §6b.2 momentum classifier + 9 tests covering determinism + all three load-bearing decisions (tercile, lookback, delisted) plus edge cases. Single combined feat+test commit since the contract was fully pinned in 397ad65.

**What works:**
- 129/129 pass; 9/9 momentum-specific tests in 0.11s.
- **Tercile arithmetic** ([src/universe/momentum.py:114-117](src/universe/momentum.py#L114-L117)) — `n_bullish=ceil(n/3)`, `n_non_bullish=floor(n/3)`, `n_neutral=n - n_bullish - n_non_bullish`. Sums to n by construction. `test_tercile_split_n40_top_heavy` pins 14/13/13.
- **Sort key `(-return, symbol_asc)`** ([src/universe/momentum.py:112](src/universe/momentum.py#L112)) — tie-break alphabetical ascending. `test_tie_break_by_symbol_name_ascending` exercises all-equal-returns case → `bullish==[A,B]`. Smart.
- **Three determinism sort gates**: rank-sort by `(-return, symbol_asc)` then output-list `sorted(...)` per bucket. `test_determinism_byte_identical` calls THREE times and asserts `a==b==c` AND each list is `== sorted(list)`.
- **Delisted-symbol policy** ([src/universe/momentum.py:46-52](src/universe/momentum.py#L46-L52)) — `MissingDataError` swallow with `warnings.warn`. `test_delisted_symbol_dropped_with_warning` pins three sub-properties at once: symbol absent from all 3 buckets, remaining 3 still classify normally (n=3 → 1/1/1 split), exactly one warning naming DELISTED.
- **OfflineCacheMiss propagates** — implementation just doesn't catch it (the `except MissingDataError` is sibling-only). `test_offline_cache_miss_propagates` explicitly pins the SPECS §6a class-distinction guarantee at the classifier boundary.
- **`test_lookback_routed_through_offset_trading_days`** is the clever one ([tests/test_momentum.py:210-246](tests/test_momentum.py#L210-L246)) — monkeypatches `offset_trading_days` to return a sentinel date (2023-12-21) that no naive arithmetic could produce, then asserts that exact date flowed into `load_spot.from_date`. A future "optimization" that bypasses the trading_calendar regresses LOUDLY.
- **Zero-denominator guard** ([src/universe/momentum.py:66-72](src/universe/momentum.py#L66-L72)) — covers the corrupt-data case where lookback close is 0. Defensive.
- **Edge cases**: empty universe returns `{"bullish": [], "neutral": [], "non_bullish": []}` via early-return; `lookback_trading_days <= 0` raises `ValueError`.
- **Live sanity in commit message**: ICICIBANK+RELIANCE bullish, INFY+TCS neutral, HDFCBANK non_bullish for 5-stock blue chips on 2024-07-01. Plausible regime classification (banks split, IT in the middle, HDFCBANK was indeed a 2024 H1 laggard).

**Blocking issues:** None.

**Non-blocking suggestions:**
- **No test for the zero-denominator guard.** The `denom_close == 0` branch ([src/universe/momentum.py:66-72](src/universe/momentum.py#L66-L72)) emits a warning and skips the symbol but isn't exercised by any test. Future regression that drops the guard would silently propagate a `ZeroDivisionError`. One test mirroring the delisted-symbol pattern would close it.
- **`_make_fake_spot` helper** sets the denom + numer based on `returns[symbol]` directly. Means the helper doesn't actually exercise the "from_date+to_date filter" path inside the classifier — the synthetic frame has exactly 2 rows regardless of how many trading days span the window. Defensible because the impl picks `.iloc[0]` and `.iloc[-1]`, but if someone refactors to a date-mask-based selector, the test still passes spuriously. Cosmetic; functional correctness pinned by other tests.
- **No `partial-history` test.** A symbol that started trading mid-window (`load_spot` returns 30 rows for what should be 126) wouldn't crash but would have a *different effective lookback* than its peers. Worth a one-liner: `assert classify_momentum(...) doesn't blow up when one symbol has 5 rows and another has 126` — pins the "smaller window doesn't crash" behavior.
- **`_trailing_return` swallows `df.empty` separately** ([src/universe/momentum.py:53-59](src/universe/momentum.py#L53-L59)) — different warning text vs the MissingDataError case. Both result in `None`. Defensible separation; alternatively, combining into one branch would be tighter. Cosmetic.

**Domain / correctness checks:**
- **Look-ahead bias:** `load_spot(symbol, lookback_date, as_of)` is bounded above by `as_of`. No leak.
- **Statistical claims:** trailing-126-trading-day return is a standard momentum factor. Tercile cut is reasonable. The top-heavy split is a convention, not a measurement bias.
- **jugaad-data:** classifier never calls it directly — delegates to `load_spot` + `offset_trading_days`, both already tested.

**What I tried:**
- `python -m pytest tests/test_momentum.py -v` → 9/9 in 0.11s.
- `python -m pytest tests/` → 129/129 in 0.63s (1 warning from the intentional MORENSE_WARN_ON_FETCH test).
- Read the impl + tests end-to-end.

**Next-commit suggestion:** Per the BUILDER's plan, `chore(p2.verify)` next. The strongest single live check: run `classify_momentum(date(2024, 7, 1), blue_chip(date(2024, 7, 1)))` end-to-end against real NSE and assert (a) the three buckets sum to ≤40 (some symbols may be delisted post-2024-07-01 in NSE's archives), (b) exact split sizes for the non-delisted slice (14/13/13 if all 40 resolve), (c) a few hand-verifiable economic constraints — e.g. RELIANCE's classification matches its actual H1-2024 return (rallied → likely bullish); HDFCBANK's classification matches its H1-2024 underperformance (likely non_bullish). Print everything to stderr for human cross-check. Independent reproducibility against the BUILDER's own run is the strongest test we can do before Phase 3 lands.

---

## Review of 9989967 — chore(p2.verify): live universe classification end-to-end — ALL GREEN

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Live end-to-end verification of Phase 2 — exercise blue_chip + classify_momentum against real NSE, assert top-heavy invariant, determinism, and two hand-verifiable economic constraints.

**What works:**
- **I ran the script independently — ALL GREEN, byte-identical split** with the BUILDER's reported buckets. Determinism holds across the second call.
- **Economic plausibility is striking**: PSU/commodity/telco bullish (COALINDIA, ONGC, POWERGRID, SBIN, TATASTEEL, TATAMOTORS, BHARTIARTL); private bank + FMCG non_bullish (HDFCBANK, KOTAKBANK, INDUSINDBK, HINDUNILVR, ITC, NESTLEIND). These line up with what Indian financial press actually reported for H1 2024 — the classifier isn't just internally consistent, it tracks reality.
- **RELIANCE → bullish, HDFCBANK → non_bullish** — the two hand-checks the BUILDER pinned. Both confirmed live.
- **Top-heavy invariant**: 14/13/13 verified.
- Script handles the "drop delisted" path gracefully ([scripts/verify_p2.py:61-64](scripts/verify_p2.py#L61-L64)) — would print a WARN if any of the 40 names dropped (they didn't this time, but the script is robust).
- **`OK-ISH` branch for HDFCBANK** ([scripts/verify_p2.py:112-115](scripts/verify_p2.py#L112-L115)) is a pragmatic relaxation — `neutral` also accepted since the non_bullish/neutral boundary is a tercile cut. Captures the right level of looseness for a regime classification.
- 0.8s cold-ish (cache mostly warm from earlier verify runs) vs the BUILDER's 115.6s true-cold. Both reasonable.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **No telemetry / `MORENSE_WARN_ON_FETCH=1` exercise.** A second sub-run with the env var set, on a warm cache, would corroborate that the classifier doesn't make accidental fetches — i.e. the parquet cache really absorbs every load_spot call. Defer.
- **No assertion that the dropped-symbol list is empty.** The script prints a WARN but exits 0 even if 5 symbols dropped. The "40/40 classify" expectation is implicit. Could tighten with `assert total == 40` if you want a regression block for any future jugaad-archive shrinkage. Defer; the WARN is visible.
- **Only two economic hand-checks** (RELIANCE bullish, HDFCBANK non_bullish). With more known H1-2024 narratives — TATASTEEL bullish, ASIANPAINT non_bullish — the script could pin 3-4 more. Each adds regression coverage with very little code. Cosmetic.

**Domain / correctness checks:**
- **jugaad-data usage:** classifier delegates to load_spot which is already tested live in Phase 1.
- **Look-ahead bias:** the classifier uses `load_spot(symbol, lookback_date, as_of)` — bounded above by `as_of`. No leak.
- **Statistical claims:** tercile cut at 14/13/13 matches the canonical case; the actual buckets are economically sensible.

**What I tried:**
- `python scripts/verify_p2.py` independently → all 6 sub-checks green; same split as the BUILDER's run.

**PHASE 2 STATUS: DONE.** Universe + momentum classifier work end-to-end on real NSE data with economically validated output. 129 offline tests + 1 live verify all green.

**Next-commit suggestion:** **Phase 3 — short straddle engine.** This is the user's original ask actualized: a backtester that says "if you'd entered this trade on this day, you'd have made/lost ₹X." Per PLAN.md the first commit is `feat(p3): Trade + Leg dataclasses; per-trade P&L kernel`. The **load-bearing decision is the sign convention** — for a SELL leg, `pnl = (entry_price - exit_price) × qty × lot_size`; for BUY it's the opposite. A single sign flip and every backtest is wrong by 100%. Pin in SPECS §4: `pnl_per_leg = (entry - exit) × side_sign × qty × lot_size` where `side_sign("SELL")=+1, side_sign("BUY")=-1`. The **load-bearing test** is a two-leg short-straddle hand-check on the canonical RELIANCE Jan-2024 contract we already pinned in Phase 1: entry T-15 (= Jan-4, ATM 2600), exit T-1 (= Jan-24). CE entry 56.50 (Phase-1 verified), PE entry need-to-fetch; CE exit need-to-fetch (was deep ITM in the integration verify at 102.40 on Jan-25, so Jan-24 should be close), PE exit need-to-fetch. The engine output (gross P&L = (56.50 - CE_exit) + (PE_entry - PE_exit)) × 250 lot should match a hand-computed number. **No look-ahead enforcement**: the engine must reject if any code path inside the trade-pricing kernel reads data with `date > exit_date`. PLAN.md §4.1's hard rule from the start of the project; now we land it.

---

## Review of 8aac2af — chore(p3.0): SPECS for engine — sign convention + no-lookahead + LookaheadError

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pin the sign convention + no-look-ahead enforcement BEFORE the engine kernel lands. Decompose Phase 3 into 9 nuclear steps.

**What works:**
- **§3a Sign convention is now SPECS-canonical** ([SPECS.md:338-356](SPECS.md#L338-L356)) with the exact formula `gross_pnl_per_leg = (entry - exit) * side_sign * qty_lots * lot_size` where `side_sign = +1 if SELL else -1`. Verified by mental walk-through: all four combinations (SELL+drop=+, SELL+rise=-, BUY+rise=+, BUY+drop=-) are correct. Test rule pinned: "SELL leg with entry > exit ⇒ gross_pnl > 0".
- **§3b No-look-ahead enforcement** ([SPECS.md:358-372](SPECS.md#L358-L372)) — PLAN §4 hard rule #1 now translated into a code requirement at the engine boundary. Tests pattern named: post-exit_date rows in the fixture + assert `LookaheadError`.
- **`LookaheadError(DataError)`** added to §8 error taxonomy ([SPECS.md:499](SPECS.md#L499)).
- **PLAN §3 Phase-3 decomposed into 9 nuclear steps** ([PLAN.md:127-135](PLAN.md#L127-L135)) — SPECS chore → Trade/Leg → P&L kernel → P&L tests → cost model → cost tests → ShortStraddle → strategy tests → live verify. Each step has a paired test commit where it makes sense.
- **Exit criteria amended** ([PLAN.md:140](PLAN.md#L140)) to require no-look-ahead enforcement by code.

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**
- **"Consults" vs "loads"**: §3b says the kernel "MUST NOT consult any market data with `date > x`". But `load_option(..., from_date=e, to_date=x)` actually fetches the **full contract lifetime** into the parquet cache (per SPECS §2.2 — first-fetch policy). So the cache HAS data with `date > x` available; the kernel just mustn't USE it. Worth one line: "the cache may contain data past exit_date as a fetch artifact; the kernel's enforcement is at the DataFrame access boundary — filter to `df.date <= exit_date` before any aggregation, and the engine asserts the filter happened."
- **`entry_date == exit_date` not addressed.** PLAN §4 doesn't reject it, but a zero-day trade has no economic meaning (same-day entry+exit at the same close = 0 P&L). Pin: `entry_date < exit_date` strictly, raise `ValueError` if not. Or explicitly allow same-day (intraday turnaround) for future-flexibility — pick one and document.
- **Validation in Trade/Leg dataclasses not mentioned.** `Leg(option_type="XX")`, `Leg(qty_lots=0)`, `Trade(legs=())` — should they raise? Adding `__post_init__` validation in `frozen=True` dataclasses is straightforward. Pin in SPECS §3 or in the upcoming p3.1 commit.
- **No `LookaheadError` test pattern** vs general `MissingDataError` test pattern. §3b says "tests assert the engine raises", but the test fixture construction is the load-bearing part — it has to include both pre- AND post-exit_date rows so a bug that includes ALL rows is caught (not just a bug that drops everything). Worth a one-line callout: "fixture must include at least one row past exit_date AND one row at/before exit_date, so the engine has something legitimate to use AND something illegitimate to reject."

**Domain / correctness checks:**
- **Sign convention:** correctly pinned. The four-combination mental check passes.
- **Look-ahead bias:** the SPECS-canonical enforcement (loud `LookaheadError`) is the right abstraction.
- **Options math:** `qty_lots * lot_size` = total shares; multiplied by price gives notional. Correct.
- **Statistical claims:** N/A this commit.

**What I tried:**
- Read SPECS §3a + §3b diff in full; mentally walked through the four sign combinations.
- Verified `LookaheadError` is the only addition to §8.

**Next-commit suggestion:** `feat(p3.1): src/strategies/base.py — Trade, Leg, Strategy`. Three load-bearing decisions to pin in code: **(1)** `frozen=True` for both `Leg` and `Trade` (per SPECS §3) — immutability matters because a Trade is identity-equivalent to its legs+dates and accidental mutation during sweep iteration would silently shuffle results. **(2)** `__post_init__` validation: `Leg.option_type in ("CE", "PE")` raises ValueError; `Leg.side in ("BUY", "SELL")` raises; `Leg.qty_lots > 0` raises; `Trade.legs` is non-empty tuple; `Trade.entry_date < Trade.exit_date` raises (or `<=` — pin the same-day question in SPECS first). **(3)** `Strategy` is a `Protocol` (not ABC) so concrete strategies need only implement `name` + `generate_trades(...)` — duck-typed registration in Phase 4. Tests for p3.1 are tiny but mandatory: each `__post_init__` rule fires with the right ValueError. **After p3.1 lands, immediately move to `feat(p3.2): src/engine/pnl.py`** — that's where the load-bearing P&L+lookahead+missing-data logic actually lives.

---

## Review of 354fc73 — feat(p3.1): src/strategies/base.py — Trade, Leg dataclasses + Strategy protocol

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Lay down the engine's input primitives: immutable `Leg` + `Trade` dataclasses with `__post_init__` validation, and a `Strategy` Protocol the engine can type-check producers against. Per the 8aac2af plan, this is the foundation for the P&L kernel landing next.

**What works:**
- **`side_sign(side)` is a free function** ([src/strategies/base.py:25-33](src/strategies/base.py#L25-L33)) — keeps the sign convention out of inline `if-else` in the kernel. Raises on invalid side too.
- **Leg `__post_init__`** validates all four fields ([src/strategies/base.py:55-66](src/strategies/base.py#L55-L66)) — option_type, side, qty_lots, strike-integer. Each with descriptive error messages.
- **Trade `__post_init__`** validates 3 things ([src/strategies/base.py:88-99](src/strategies/base.py#L88-L99)) — non-empty legs, entry ≤ exit, exit ≤ expiry (no holding past expiry). All three confirmed live.
- **Both `frozen=True`** — immutability confirmed via `t.symbol = "TCS"` → `FrozenInstanceError`.
- **`legs: tuple[Leg, ...]`** — frozen-compatible (not a list).
- **`Strategy` is `Protocol`** — duck-typed registration in Phase 4; no ABC inheritance needed.
- **Verified live**: all validation paths fire with the right error type and message.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`entry_date == exit_date` is allowed** ([src/strategies/base.py:91-94](src/strategies/base.py#L91-L94)) — same-day trade returns zero P&L on daily bars. Defensible (intraday turnaround can be modeled later if we ever go intraday) but **document the decision in SPECS §3a**. The 8aac2af commit didn't resolve this; the code resolved it implicitly. Lock the answer in writing.
- **`Trade.params: dict = field(default_factory=dict)`** is mutable through reference even though `Trade` is frozen — `t.params["x"] = 1` works post-construction. SPECS §2.5 wants `params_json` to be the canonical serialization, and a mutated dict would drift from what the engine saw at pricing time. Belt-and-suspenders fix: `MappingProxyType(dict)` or convert to `tuple[tuple[str, Any], ...]` if you want true immutability. Cosmetic for v1.
- **`legs: tuple[Leg, ...]`** doesn't validate that all legs share the same `(symbol, expiry)` — that's pinned at the Trade level via the symbol+expiry field, not at the Leg level (Leg doesn't carry symbol/expiry). Correct architecturally; just noting the design choice.
- **No test commit yet** — BUILDER explicitly says "Tests + the P&L kernel land in feat(p3.2)". Reasonable to combine them given how tiny p3.1 is.

**Domain / correctness checks:**
- **Sign convention:** `side_sign` mirrors SPECS §3a verbatim. Verified.
- **Options math:** strike-int guard mirrors `cache.option_path` — consistent across the project. NSE stock-option strikes are whole rupees only.
- **Look-ahead bias:** N/A this commit; will land in p3.2.
- **Statistical claims:** N/A.

**What I tried:**
- Constructed Legs (valid + 4 invalid variants), Trades (valid + 3 invalid variants), exercised `side_sign` happy + error paths. All matched expectations.

**Next-commit suggestion:** `feat(p3.2): src/engine/pnl.py — per-trade gross P&L kernel`. THIS is where the user's original ask materializes as a callable function. Load-bearing decisions: **(1) `price_trade(trade) -> dict` matches SPECS §2.5's `results` schema** (`gross_pnl`, `costs=0` for now, `net_pnl`, `entry_spot`, `exit_spot`, `legs_json`). **(2) Per-leg pricing**: `load_option(trade.symbol, trade.expiry, leg.strike, leg.option_type, trade.entry_date, trade.exit_date)` → filter the returned frame to `df.date <= trade.exit_date` (the no-lookahead enforcement point), then `entry_close = df[df.date == entry_date].iloc[0]["close"]` (raise `MissingDataError` if empty) and similarly for exit. **(3) lot_size from historical data**: `leg_lot_size = df[df.date == entry_date].iloc[0]["lot_size"]` — read per-row, not from a constant. PLAN §4.3. **(4) Aggregate**: `gross_pnl = sum((entry - exit) * side_sign(leg.side) * leg.qty_lots * leg_lot_size for leg in trade.legs)`. **Paired test (`test(p3.2)`)** must hand-check: short straddle with CE entry=100, exit=50, PE entry=100, exit=30, lot=250 → gross_pnl = (100-50)×250 + (100-30)×250 = 12,500 + 17,500 = 30,000. SECOND test: LookaheadError fires when the fixture frame contains a row past exit_date — proves the filter happens. THIRD test: MissingDataError when entry_date is missing from the fixture frame. Those three together are the engine's load-bearing contract.

---

## Review of 4afb8be — feat(p3.2): src/engine/pnl.py — per-trade gross P&L kernel + LookaheadError

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the per-trade gross P&L kernel. Sign convention, no-look-ahead, missing-data, lot-size-from-data all enforced. The user's original ask materializes here.

**What works:**
- **138/138 pass; 9/9 pnl-specific in 0.10s.**
- **Sign convention pinned by test**: `test_sign_convention_short_straddle` — SELL CE 100→10, SELL PE 100→10, lot 250 → +₹45,000. The load-bearing assertion. A sign flip anywhere in the kernel inverts this.
- **Long-straddle sister test**: same fixture, BUY side → -₹45,000. Pins BUY=-1.
- **RELIANCE Jan-2024 hand-check** ([tests/test_pnl.py:100-131](tests/test_pnl.py#L100-L131)) — CE entry 56.50 (anchored on Phase-1 integration verify against real NSE), plus three synthesized values, hand-arithmetic produces gross_pnl=+₹2,750. Walking through it: CE (56.50-95)×250 = -₹9,625; PE (50-0.50)×250 = +₹12,375; sum = +₹2,750 ✓.
- **No-look-ahead enforcement** ([src/engine/pnl.py:101-107](src/engine/pnl.py#L101-L107)): explicit `df.date.dt.date > trade.exit_date` check on the loader's return BEFORE any price-pick. Test (`test_lookahead_rejected`) feeds a leaky loader that bypasses its window filter; engine raises `LookaheadError` with the offending dates named.
- **MissingDataError on both bounds** — separate tests for entry-missing and exit-missing.
- **Lot-size invariant** ([src/engine/pnl.py:113-117](src/engine/pnl.py#L113-L117)) — if entry's lot != exit's lot, raise `LookaheadError` ("loud-failure class" per the inline comment). Test pins the 250→500 case.
- **Dependency injection** — `load_option_fn` defaults to `options_loader.load_option` but is pluggable, so tests construct deterministic stubs without monkeypatching the module. Cleaner than the spot/options test pattern.
- **Per-leg results carry `entry_px`, `exit_px`, `lot_size`, `gross_pnl`** ([src/engine/pnl.py:120-129](src/engine/pnl.py#L120-L129)) — serialized into `legs_json`. Sweeper Phase 4 can reconstruct exactly which prices were used.
- **Linear scaling** test pins `gross_pnl(qty=3) == 3 * gross_pnl(qty=1)`.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Result dict is missing 7 SPECS §2.5 fields**: `run_id`, `entry_offset_td`, `exit_offset_td`, `costs`, `net_pnl`, `notional_at_entry`, `entry_spot`, `exit_spot`. Most belong elsewhere (run_id+offsets at sweeper layer; costs+net_pnl in Phase 3.3) but `entry_spot` and `exit_spot` *could* land here. Worth one line in the docstring stating which fields p3.2 emits vs which are added downstream.
- **`LookaheadError` reused for "lot_size changed mid-contract"** ([src/engine/pnl.py:114](src/engine/pnl.py#L114)) and "duplicate dates" ([src/engine/pnl.py:71](src/engine/pnl.py#L71)) — both are data-corruption signals, not look-ahead per se. The inline comment acknowledges this. Eventually worth a `DataCorruptionError(DataError)` sibling. Cosmetic for v1; the behavior is "loud failure" either way.
- **`json.dumps(trade.params, sort_keys=True)`** ([src/engine/pnl.py:157](src/engine/pnl.py#L157)) — if `trade.params` ever contains a non-JSON-serializable value (date, np.float, etc.), the call raises at price time. Worth `default=str` here too (already used on legs_json) for symmetry. Cheap.
- **No test for `params_json` round-trip** — if the strategy passes `{"strike_offset_pct": 0.0}`, the test should verify `out["params_json"]` parses back. Cosmetic.
- **`pd.Series.dt.date == target`** ([src/engine/pnl.py:65](src/engine/pnl.py#L65)) — creates a Python-object Series per call. For 1000s of pricings in a sweep, mild perf cost. Could be `df["date"] == pd.Timestamp(target)`. YAGNI.

**Domain / correctness checks:**
- **Sign convention:** correctly implemented — `gross = (entry_px - exit_px) * sign * leg.qty_lots * entry_lot`. The four-combination mental check still passes.
- **Look-ahead bias:** filter-level enforcement at the kernel boundary. Loud `LookaheadError` if loader leaks. Test covers it.
- **No silent interpolation:** `_pick_close_on` raises `MissingDataError` on absence, never falls back. PLAN §4 rule #2 honored.
- **Lot-size from data:** `entry_lot` read per-row, not constant. PLAN §4 rule #3 honored.
- **Statistical claims:** N/A this commit (single-trade pricing).

**What I tried:**
- `python -m pytest tests/test_pnl.py -v` → 9/9 in 0.10s.
- Read the kernel + tests end-to-end. Hand-walked the RELIANCE hand-check arithmetic to confirm +₹2750.

**Next-commit suggestion:** `feat(p3.3): src/engine/costs.py — COST_MODEL_V1`. Per SPECS §4: brokerage ₹20/order × 4 orders/leg-pair = ₹80 flat; STT 0.0625% × premium turnover × SELL-side only; exchange txn 0.0503% × premium turnover (both sides); GST 18% on (brokerage + exchange); SEBI ₹10/crore of premium turnover; stamp duty 0.003% on BUY-side premium turnover (the closing leg of a short trade, the opening leg of a long trade). **Load-bearing test**: hand-compute total cost on the same RELIANCE Jan-2024 short straddle. With CE entry 56.50 + PE entry 50 + CE exit 95 + PE exit 0.50, lot 250: SELL-side premium turnover = (56.50 + 50) × 250 = ₹26,625; BUY-side = (95 + 0.50) × 250 = ₹23,875; brokerage = 4 × ₹20 = ₹80; STT = 0.000625 × 26,625 = ₹16.64; exchange = 0.000503 × (26,625 + 23,875) = ₹25.40; GST = 0.18 × (80 + 25.40) = ₹18.97; SEBI = (50,500 / 1e7) × 10 = ₹0.05; stamp = 0.00003 × 23,875 = ₹0.72; total ≈ ₹141.78. Pin that arithmetic. Once costs land, `price_trade` should also emit `costs` and `net_pnl` — wire them in once the cost module is testable.

---

## Review of de46d40 — docs(plan): add Phases 8/9/10 as DEFERRED — agent-API, paper trading, live trading

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Docs-only roadmap extension. User asked to track three new phases as DEFERRED (not active work) so they're discoverable in PLAN.md without disrupting the in-flight Phase 3.

**What works:**
- **Three phases clearly DEFERRED** — explicit labels, not interleaved with Phase 3-7 sequence. PLAN.md remains a usable roadmap.
- **Phase 8 (agent-callable research API)** is correctly scoped READ-ONLY ([PLAN.md:191-208](PLAN.md#L191-L208)). 6 tools cover the natural research-question surface: universe membership, regime classification, expiry lookup, single backtest, sweep, summary. The dependency on Phase 5 (aggregation) for `summarize` is implicit; worth one line noting the prerequisite.
- **Phase 9 (paper trading)** ([PLAN.md:210-221](PLAN.md#L210-L221)) sketches the right primitives — positions store, mtm, 3 MCP tools (paper_open/status/close). The "close-on-expiry rule" callout in §11 SPECS is exactly the kind of subtle invariant that bites paper-trading systems for short straddles.
- **Phase 10 (live trading) is sized as a separate project** ([PLAN.md:223-237](PLAN.md#L223-L237)). The four hard prerequisites — 3-month paper track, written runbook, per-trade approval, kill switch — are the right risk-aware discipline. "Agent proposes, human approves, system executes" is the safe v1 model.
- **Change-log entry** ([PLAN.md:267](PLAN.md#L267)) records the addition + rationale. Trackable.

**Blocking issues:** None — docs-only, no code impact.

**Non-blocking suggestions:**
- **Phase 10's "≥ 3 months of paper-trading track record matching backtest expectations"** — "matching" is fuzzy. Pin a concrete acceptance criterion before launching Phase 10: e.g., "paper realized P&L per trade is within ±1σ of backtested P&L distribution for ≥80% of trades", or "Sharpe ratio matches within 0.3". Otherwise the prerequisite is unenforceable and Phase 10 launches based on vibes.
- **Phase 9 `mtm.py` uses NSELive** ([PLAN.md:218](PLAN.md#L218)) — jugaad's NSELive has a 5s in-memory cache per the docs we read in Phase 1. For frequent `paper_status` polling (1-min cadence), that's fine; for continuous mtm loop with subsecond granularity, the cache will surprise. Worth a SPECS §11 callout when Phase 9 lands.
- **Phase 8's `backtest_one` / `sweep_windows`** could trigger expensive sweep computations on an MCP call. Worth thinking about resource limits / timeouts at the MCP boundary — an agent calling `sweep_windows(..., entry_grid=range(1,21), exit_grid=range(1,21))` could trigger 400 backtests per symbol. Pin a max grid size before Phase 8 lands.
- **Read-only via what mechanism?** Phase 8 says "read-only scope, no order execution" but doesn't pin HOW that's enforced architecturally. By convention (the MCP server simply doesn't import the trading layer) or by hard wall (separate Python process)? The architectural choice matters for Phase 10 (live) when read-only-vs-execute becomes a runtime security property.

**Domain / correctness checks:**
- **Phase 10's per-trade approval gate** is the right model for v1 live trading. Auto-execute is the bigger risk for a backtested-but-not-paper-validated strategy.
- **Paper-trading mtm** uses NSE live data which has different semantics than historical (e.g., snapshot prices vs daily settle). Worth a SPECS §11 callout that paper P&L is computed on LIVE LTP (or VWAP if available), NOT on the daily-settle convention used in backtests.

**What I tried:** Read the diff end-to-end. Cross-checked the deferred-phase commit sketches against the existing Phase-1-7 nuclear-step doctrine.

**Next-commit suggestion:** No change from my prior `feat(p3.3): costs.py` recommendation. The roadmap additions are background; the critical path is still the Phase-3 short-straddle engine. After p3.3 (cost model) + p3.4 (short_straddle strategy) + p3.verify (live first ₹P&L) land, the user has their original ask working end-to-end. That's the v1 milestone — Phases 4-7 build the platform around it, Phases 8-10 extend it.

---

## Review of 5ce2929 — feat(p3.3): src/engine/costs.py — COST_MODEL_V1 + 12 tests, ₹141.78 hand-check

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Implement the SPECS §4 cost model with the 6-component breakdown, pinned to a hand-checked total on the RELIANCE Jan-2024 short straddle.

**What works:**
- **Hand-check matches my prior review's napkin estimate EXACTLY**: brokerage 80 + STT 16.6406 + exchange 25.4015 + GST 18.9723 + SEBI 0.0505 + stamp 0.7163 = **₹141.7811**. Independently verified live.
- **`CostModelV1(frozen=True) dataclass`** ([src/engine/costs.py:31-40](src/engine/costs.py#L31-L40)) — pinned rates as keyword defaults. Frozen → safe to share as singleton.
- **Side accounting subtlety correctly handled** ([src/engine/costs.py:67-79](src/engine/costs.py#L67-L79)):
  - SELL leg: entry → sell-side turnover (STT applies), exit → buy-side (stamp applies)
  - BUY leg: entry → buy-side (stamp applies at open), exit → sell-side (STT applies at close)
  - The long-straddle case (STT on exit, not entry) is the subtle one — `test_stt_sell_side_only` pins both directions explicitly.
- **`COST_MODEL_V1` singleton** ([src/engine/costs.py:105](src/engine/costs.py#L105)) is the default for every backtest; Phase-5 sensitivity analysis constructs new `CostModelV1` instances (or a future `CostModelV2`) without mutating the default — `test_v2_can_be_constructed_without_mutating_v1` pins this pattern.
- **12 tests cover every contract**:
  - Load-bearing hand-check at 1e-6 precision per component
  - Brokerage flat regardless of premium size (catches "scale by premium" regression)
  - STT sell-side-only verified on both short AND long contracts
  - Stamp duty buy-side-only verified analogously
  - GST applies to brokerage+exchange only (not STT/stamp/SEBI) — real Indian tax law
  - `total == sum(components)` invariant (catches "computed but excluded from total" typo)
  - Linear scaling with `qty_lots` (turnover components scale, brokerage stays flat)
  - Frozen immutability via `pytest.raises(FrozenInstanceError)`
  - Input validation (empty legs, invalid side)
- **150/150 in full suite.**

**Blocking issues:** None.

**Non-blocking suggestions:**
- **"Options-only" assumption not in the docstring.** SPECS §4 says STT 0.0625% is the option-specific rate; equity/futures have different rates. If a future strategy ever uses non-option legs, this cost model would silently apply the wrong STT rate. Worth a one-line callout in the `CostModelV1` docstring: "rates assume STOCK OPTION legs; not valid for equity or futures".
- **`brokerage_per_order = ₹20` is the simplification.** Real Zerodha is ₹20 OR 0.03% whichever lower. For NSE options the flat ₹20 always wins (premium turnover × 0.03% << ₹20 in typical cases), but documenting the simplification matches the project's "loud > silent" pattern.
- **`n_orders = len(legs) * 2`** assumes every leg has clean entry + exit. For early-exit / partial-fill / mid-trade adjustments (none of which v1 backtests support), this would over-count. Fine for v1.
- **`exchange_txn_pct = 0.000503`** — exchange transaction charge for NSE has actually changed twice in 2024 (rate updates by NSE in Sep + Oct 2024). The 0.0503% is the late-2024 rate; pre-Sep-2024 backtests would over-state costs by ~5%. Worth one line in SPECS §4 acknowledging this is a 2024-late snapshot; Phase-5 sensitivity test or Phase-7 historical-rate-curve can fix.
- **No `cost_model_fn` injection into `engine.pnl.price_trade` yet** — but the BUILDER's commit message says "Next: wire costs into engine.pnl.price_trade". So the integration is the very next micro-step.

**Domain / correctness checks:**
- **Sign convention:** costs are always positive; `net_pnl = gross - costs`. Correctly modeled.
- **Side accounting:** the SELL-side-STT and BUY-side-stamp rules are the subtlest part of Indian options tax law, and the implementation gets them right for both long and short trades.
- **Statistical claims:** N/A this commit (pure cost arithmetic).
- **Look-ahead bias:** N/A.

**What I tried:**
- `python -c "..."` → hand-check breakdown line-by-line against my prior napkin math. Every component matches to 4 decimal places.
- Read [src/engine/costs.py](src/engine/costs.py) end-to-end.

**Next-commit suggestion:** Per the BUILDER's note, **wire `cost_model` into `engine.pnl.price_trade`** as the immediate next micro-step. Add a `cost_model: CostModelV1 = COST_MODEL_V1` parameter (defaulted, injectable like `load_option_fn`). In the kernel, compute `cost_breakdown = cost_model.total_cost(leg_results)` after summing gross, then return `costs = cost_breakdown["total"]` and `net_pnl = gross_pnl - costs` in the result dict. **Test: update the RELIANCE Jan-2024 hand-check** to assert `gross_pnl == 2750.0`, `costs == 141.78` (or precise: 141.7811...), `net_pnl ≈ 2608.22`. That single assertion proves the gross+cost pipeline ties together correctly. After that → `feat(p3.4): ShortStraddle strategy`.

---

## Review of 3c82ee0 — fix(p3.3.b): wire COST_MODEL_V1 into price_trade — costs + net_pnl in result

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Mechanical wire-up of the cost model into the P&L kernel. `price_trade` now returns gross + costs + net + breakdown — the full pipeline a sweeper consumes.

**What works:**
- `cost_model: CostModelV1 = COST_MODEL_V1` kwarg ([src/engine/pnl.py:137](src/engine/pnl.py#L137)) — injectable like `load_option_fn`, default to the singleton. Mirror pattern. Clean.
- 3 new keys in result dict: `costs`, `net_pnl`, `costs_breakdown_json`. Sweeper / analytics can consume net_pnl directly without re-running the cost layer.
- **Load-bearing test ties the layers together**: `test_reliance_jan_2024_full_pipeline_gross_costs_net` asserts `gross_pnl=2750.0`, `costs=141.7811`, `net_pnl=2608.22`. If gross and cost computations drift at the boundary, this fires immediately. **This is the test I suggested verbatim.**
- `test_cost_model_is_injectable_for_sensitivity` pins the Phase-5 sensitivity pattern with a zero-brokerage variant. Singleton unaffected.
- 152/152 in full suite.

**Blocking issues:** None.

**Non-blocking suggestions:** None worth flagging — this is a tight 2-file, ~30-line wire-up that does exactly what was needed.

**Domain / correctness checks:**
- **Net P&L:** `gross - costs` with costs always positive. Correct.
- **Cost injection:** kwarg pattern matches `load_option_fn`'s injection — consistent.

**What I tried:** `python -m pytest tests/` → 152/152 in 0.71s. Read the diff end-to-end.

**Next-commit suggestion:** Per the BUILDER's note, **margin module** comes next ("Indian-specific: SELL legs need SPAN-style margin block ~20% of underlying notional; BUY legs only need the premium"). This is a SPECS-amendment-worthy decision — margin is a P&L-relevant concept that hasn't been in the project yet. Before writing code, pin in SPECS: (a) margin formula (SPAN approximation: max(20% × underlying notional, premium × 1.5) for short option legs, premium-only for long); (b) WHERE margin lives in the results schema — as a separate column `margin_required` per SPECS §2.5, or as a `params` field?; (c) what does the engine *do* with margin — does `price_trade` enforce "trade requires more margin than caller's capital"? Or is margin just a reported metric? I lean **reported metric only** for v1 — let the strategy/sweeper decide what to do with it. Implementation can then be a small module like `src/engine/margin.py` with `compute_margin(trade, spot_at_entry, cost_model) -> dict`, wired into `price_trade` via the same injectable-default pattern as `cost_model`.

---

## Review of 3f975ae — feat(p3.5): margin model (Indian options-specific) + wire into price_trade

**Verdict:** ⚠️ accept-with-followups

**Phase / commit goal (as I understood it):** Add margin to the result pipeline. BUY legs pay premium, SELL legs block ~20% × notional (SPAN+Exposure approx.). ROI = net_pnl / margin_at_entry becomes the cross-strategy ranking metric.

**What works:**
- **The BUY/SELL margin asymmetry is real and correctly modeled.** Indian F&O does exactly this: long premium-only, short SPAN-blocked.
- **Hand-check arithmetic correct**: 0.20 × 2600 × 250 × 2 legs = ₹2,60,000. Verified live.
- **The "intentionally conservative" framing is defensible**. Real Zerodha SPAN for this position is ~₹1.5L (single-leg offset credit applies); BUILDER's ₹2.6L is ~1.6× overstated. Overstating margin → understating ROI → SAFER for paper-to-live pipeline. Right direction of bias.
- **Phase-7 backlog clearly named**: parse NSE's daily SPAN file for accurate per-position margin. Defers correctly.
- **`roi_pct` added to result dict** with None-on-zero-margin guard. Phase-5 ranking has its primary metric.
- **Frozen dataclass + injectable default** = same pattern as cost_model. Consistent.
- **12 tests + extended pnl hand-check** = `gross 2750 / costs 141.78 / net 2608.22 / margin 260000 / ROI 1.00%`. Four-layer tie-together is the load-bearing assertion.
- 164/164 pass.

**GRILLING — issues that warrant SPECS clarification (not blocking, but the user said "we need to get this right"):**

1. **`margin = SPAN_PCT × STRIKE × shares`** uses the contract's strike, NOT the spot. For ATM trades these are equal so the v1 canonical short straddle hand-check works perfectly. **For non-ATM strategies the divergence is material** (verified live):
   - Far-OTM short put (2000 strike, spot 2600): BUILDER 100K vs real-SPAN-on-spot 130K → **23% understated**
   - Far-OTM short call (3200 strike, spot 2600): BUILDER 160K vs real-SPAN-on-spot 130K → **23% overstated**
   - For **symmetric** short-vol strategies (short straddle, symmetric short strangle): the over/under partially cancel because put-strike < spot < call-strike.
   - For **asymmetric** strategies (single-leg short, asymmetric wings, iron condors with uneven wings): real bias.
   - Real NSE SPAN is fundamentally **spot-driven** (worst-case price-move scenarios applied to the contract); strike-based is a simplification. **Recommend SPECS §4a update**: explicitly use `spot_at_entry` (which the strategy already has) rather than `leg.strike`. Same 0.20 constant; just change the multiplicand. Phase-5 multi-strategy ranking will be more accurate without this strike-vs-spot bias.
   - The BUILDER may have intentionally chosen strike for **stability** (strike is a fixed contract property; spot fluctuates over the trade's life). For backtest reproducibility, strike is invariant. That's a defensible reason — but a different one than "this is what SPAN does". Pin the rationale either way.

2. **`roi_pct` is holding-period return, NOT annualized.** A 30-day-hold strategy will look ~6× better than a 5-day-hold strategy at the same daily rate. Phase-5 ranking will silently favor longer holds. SPECS §2.5 should call out: "roi_pct is non-annualized holding-period return; cross-strategy ranking should normalize by hold length when comparing different (entry_offset, exit_offset) windows."

3. **The 0.20 constant doesn't vary by symbol.** Low-vol HDFCBANK has SPAN ~14%; high-vol ADANIENT has SPAN ~25%. Same 0.20 for both means ADANIENT trades look better than reality, HDFCBANK trades look worse. Phase-7 SPAN-file parsing fixes this, but the v1 ranking bias is real. Worth an explicit caveat for the eventual UI: "v1 margin estimate is uniform across symbols; high-vol stocks would have higher real margin and lower realized ROI."

4. **Multi-leg conservatism (1.6× overstatement)** is acknowledged in the docstring but the **ranking implication** isn't named: short straddle's real-margin offset credit is BIG (~2× reduction); a "long calendar spread" has SMALL offset credit. Comparing them by v1 ROI will silently favor calendars because their margin estimate is closer to real, while short straddle's is 60% too high. Worth a caveat in Phase-5 ranking docs.

**Non-blocking suggestions:**
- Switch `leg.strike` → `spot_at_entry` parameter (have to add it to the margin model's interface). Most defensible single change.
- Add `roi_pct_annualized` as a separate column = `roi_pct * 252 / hold_trading_days`. Or compute it at sweep aggregation time.

**Domain / correctness checks:**
- **BUY/SELL asymmetry:** correct.
- **Conservative-bias direction:** correct (overstate margin → understate ROI → paper-to-live safe).
- **Hand-check arithmetic:** correct.
- **Strike-vs-spot basis:** technically diverges from real SPAN; defensible for ATM-canonical v1 but **must be documented** before Phase 4 multi-strategy sweeps land.

**What I tried:**
- `python -m pytest tests/` → 164/164.
- Hand-arithmetic on 4 scenarios (ATM straddle, far-OTM put, deep-ITM call, far-OTM call) to grill the strike-vs-spot question.

**Next-commit suggestion:** **Before `feat(p3.4): ShortStraddle`, do a small `chore(p3.5.b): SPECS §4a — strike-vs-spot rationale + ROI-non-annualized caveat + uniform-rate symbol-bias`.** Three or four added sentences. Pins the v1 simplifications IN WRITING so a Phase-5 reader doesn't draw wrong ranking conclusions. Then `feat(p3.4): ShortStraddle`. The strategy itself is mechanical given the SPECS §5 ATM rule already pinned.

---

## Review of e7a9058 — chore(p3.5.b): SPECS §4a — pin 4 v1 margin simplifications + bias direction

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Document the 4 grilling-surfaced margin caveats in SPECS §4a so downstream consumers (Phase 5 ranker, Phase 6 UI, future operator) cannot claim ignorance. Code-level fix deferred per "trade-offs, not bugs" framing.

**What works:**
- **All 4 caveats addressed verbatim** ([SPECS.md:438-477](SPECS.md#L438-L477)) with the exact ranking implications I flagged:
  1. Strike-vs-spot with symmetric/asymmetric cancellation explained
  2. `roi_pct` non-annualized + explicit `× 252 / hold_trading_days` formula
  3. Uniform 20% with "rankings rotate by symbol vol" tight phrasing
  4. Multi-leg conservatism — "Phase-5 UI must surface this caveat alongside any ROI-based ranking" makes it a UI requirement
- **Bias direction explicit**: "margin overstated → ROI understated → paper-to-live safer" — names the trade-off intentionally rather than apologetically.
- **"baked into the engine's documentation so no downstream consumer can claim ignorance"** ([SPECS.md:478-480](SPECS.md#L478-L480)) — exactly the right framing for a v1 simplification.

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**
- **Caveat #1 says "Phase 4 multi-strategy may revisit"** — "may" is soft. Either commit to "Phase 4 will revisit IF Phase-5 ranking shows obvious asymmetric-strategy mis-ranking", or defer firmly to Phase 7. Soft "may" creates a decision point with no clear trigger.
- **Caveat #4 implies a Phase-5/6 UI requirement** but doesn't specify HOW to surface it. Worth a one-line callout: e.g., "rendered as a permanent disclaimer banner alongside any ROI-leaderboard view, similar to the survivorship-bias note at §6b.3". Otherwise the requirement could land as a footnote nobody reads.
- **No worked example for caveat #3** (rankings rotate by symbol vol). One paragraph: "e.g., short straddle on ADANIENT might show ROI 1.5% (real margin 25% → realized ROI 1.2%); short straddle on HDFCBANK might show 0.8% (real margin 14% → realized ROI 1.15%) — the v1 ranking has ADANIENT > HDFCBANK; reality is closer than that gap suggests." Cosmetic.

**Domain / correctness checks:**
- **Statistical claims:** the bias directions are correctly characterized.
- **Look-ahead bias:** N/A.
- **Other:** N/A pure docs.

**What I tried:** Read the SPECS diff in full. Cross-checked each caveat against the grilling math from the prior review — all four numerical claims accurate.

**Next-commit suggestion:** `feat(p3.4): src/strategies/short_straddle.py — picks ATM CE+PE per SPECS §5`. The strategy is mechanical given everything pinned. Three implementation decisions: **(1) Where does the strike-grid come from?** — call `load_bhavcopy_fo(entry_date)` and filter to `(symbol, expiry, OPTSTK)` to get available strikes; pick `argmin(|K - spot_at_entry|)` with tiebreaker = lower strike per SPECS §5. **(2) The returned Trade has two `SELL` legs at the same ATM strike**, one CE one PE, qty_lots=1 (or `params.get("qty_lots", 1)`). **(3) The strategy.name is `"short_straddle"` — matches the `Trade.strategy` string the kernel already supports. The load-bearing test: hand-check `ShortStraddle().generate_trades("RELIANCE", date(2024,1,25), date(2024,1,4), date(2024,1,24), spot_at_entry=2596.65, params={})` → returns one Trade with legs `(Leg("CE",2600,"SELL",1), Leg("PE",2600,"SELL",1))`. Plus the tiebreaker test: spot exactly between two strikes (e.g. 2610 with strikes at 2600 and 2620) → picks 2600 (lower). After p3.4 → `chore(p3.verify): live short straddle on RELIANCE Jan-2024 (T-15 → T-1) — first real ₹P&L number`. THAT is when the user's original ask materializes end-to-end with real NSE numbers.

---

## Review of f8f3720 — chore(p3.5.c): SPECS + PLAN for Tier-B margin (strategy_offset + vol-aware)

**Verdict:** ✅ accept

Part of the Tier-B margin cluster (f8f3720 → 4d6a6f33 → 93af1fb → 8d81e8c). Full assessment in the 8d81e8c review below.

**What works:**
- Three-tier accuracy ladder framing (Tier A sum-of-legs → Tier B strategy_offset+vol → Tier C real SPAN file) is sharp.
- **Key insight**: Tier C is impossible for historical backtests because NSE doesn't archive SPAN files. So Tier B IS the realistic ceiling for backtest accuracy. This dissolves my Phase-7 deferral worry on caveats #3 + #4.
- Strategy_offset table values are accurate against real NSE SPAN: short straddle 0.60 matches my prior grilling math; iron condor 0.35 matches risk-limited offset.
- Calibration table (HDFCBANK ~14% real / ADANIENT ~22% real) checks out.

---

## Review of 4d6a6f33 — feat(p3.5.d): MarginModelV1 gains strategy_offset_pct + symbol_margin_pct kwargs

**Verdict:** ✅ accept

Part of the Tier-B cluster. Implementation is mechanical:
- Both kwargs are keyword-only with backward-compatible defaults (so 16/16 existing margin tests don't break).
- `strategy_offset_pct` validation: ∈ (0, 1], rejects 0.0 / >1.0.
- Result dict adds `sell_leg_margin_raw` (pre-offset), `strategy_offset_pct` (what was used), `symbol_margin_pct` (what was used) — transparency.
- Hand-check at Tier-B: short straddle 0.60 → sell_leg_margin = ₹1.56L (drops from ₹2.6L). Matches real broker ~₹1.5L.
- 16 margin tests / 168 total pass.

---

## Review of 93af1fba — feat(p3.5.e): src/engine/vol.py — realized vol + vol_to_margin_pct

**Verdict:** ✅ accept

Part of the Tier-B cluster. Pure-Python vol calc from the existing spot cache (no new data dependency):
- `realized_vol`: annualized stdev of daily log-returns. Lookback via `offset_trading_days` (same holiday-trap dodge as momentum classifier).
- Returns `0.0` on <20 rows (safer than noisy estimate) — caller gets the floor margin pct (0.10).
- `vol_to_margin_pct`: `clamp(0.10 + 0.40 × vol, 0.10, 0.30)` — linear with hard bounds. Calibration pinned by `test_vol_to_margin_pct_calibration` against the SPECS §4a table.
- 11 vol tests / 179 total pass.

---

## Review of 8d81e8c — fix(p3.5.f): wire strategy_offset_pct + auto-vol symbol_margin_pct through price_trade

**Verdict:** ⚠️ accept-with-followups

**Phase / commit goal (as I understood it):** Final commit of the Tier-B cluster. `price_trade` now produces margin estimates ~10-15% off real (vs ~60% off with original Tier-A v1).

**What works (the Tier-B cluster as a whole):**
- **Two of my four caveats from the 3f975ae grilling are now FIXED IN CODE, not just documented**:
  - ✅ **Caveat #3 (uniform 20%)** — `symbol_margin_pct` derived from realized vol per symbol. ADANIENT gets 24%, HDFCBANK 16%, RELIANCE 19%. Calibrated against real NSE SPAN. Ranking bias by symbol vol → eliminated.
  - ✅ **Caveat #4 (multi-leg conservatism)** — `strategy_offset_pct` per strategy. Short straddle 0.60, iron condor 0.35. The canonical short straddle drops from ₹2.6L → ~₹1.5L (matches real broker SPAN). Cross-strategy ranking bias → from ~60% to ~10-15%.
- **Auto-vol fallback is sensible**: `_symbol_margin_pct(symbol, entry_date)` is called when caller doesn't pass `symbol_margin_pct`; failures fall back to the uniform default rather than breaking the trade pricing. ✓
- 181/181 pass in 0.77s. Tier-A baseline tests preserved via explicit `symbol_margin_pct=0.20` arg.
- The "Tier C is literally impossible for historical" insight in f8f3720 means Tier B isn't a placeholder — it's the realistic ceiling for backtest accuracy.

**Blocking issues:** None.

**STILL OPEN — the items I grilled that are STILL only documented, not code-fixed:**

1. **Caveat #1 (strike-vs-spot basis) — UNRESOLVED.** Tier-B still uses `0.20 × leg.strike × shares` as the SELL-leg base. Symbol_margin_pct now varies, but the strike-base remains. For symmetric short-vol strategies (short straddle, symmetric strangle) this cancels because put_strike < spot < call_strike. For asymmetric (single-leg, iron condor with uneven wings, ratio spreads, etc.) the 20-25% bias persists. Phase-4 multi-strategy sweeps will hit this.
   - **Fixable now**: change `MarginModelV1.estimate(legs, *, ..., spot_at_entry: float | None = None)` and substitute `spot_at_entry × shares` when provided. Strategy classes already have `spot_at_entry`; the kernel does too. ~10 lines.

2. **Caveat #2 (`roi_pct` non-annualized) — UNRESOLVED.** A 30-day-hold strategy still looks 6× better than a 5-day strategy at the same daily rate. Phase-5 ranker is documented to "normalize", but if it forgets, every leaderboard quietly favors longer holds.
   - **Fixable now**: add `roi_pct_annualized = roi_pct × 252 / hold_trading_days` to the result dict in `price_trade`. `hold_trading_days` = `len(trading_calendar.trading_days(entry_date, exit_date))`. ~5 lines.

**NEW — separate concern surfaced by the user's "asymmetric conservatism" question:**

3. **Slippage modeling absent.** The user explicitly wants asymmetric conservatism: backtest should under-promise gains AND over-warn about losses. Margin overstate is **symmetric** (smaller wins AND smaller losses in %) so it can't deliver this. The right tool is **slippage on prices**:
   - At SELL entry: realized = `close × (1 - slippage_pct)` (you got less than close — sold at bid)
   - At BUY exit: realized = `close × (1 + slippage_pct)` (you paid more — bought at ask)
   - Result: winning trades' gross_pnl is REDUCED, losing trades' gross_pnl is REDUCED MORE. **Asymmetric** in the direction the user wants.
   - For NSE liquid blue-chip options, real bid-ask spread is ~1-2% of premium. 1% slippage_pct is a reasonable default.
   - Add `src/engine/slippage.py` with `SlippageModelV1(slippage_pct=0.01)` + an injectable kwarg on `price_trade`. Mirrors the `CostModelV1` / `MarginModelV1` pattern.
   - Result dict adds `slippage`, `net_pnl_after_slippage` columns.
   - Phase-5 sensitivity test: 0.5% / 1.0% / 2.0% slippage tier shows how rankings shift. Strategies with thin profit margins (iron condors at 0.3% expected return) collapse first.

**Domain / correctness checks:**
- **Margin direction**: Tier-B is slightly conservative (margin overstated → ROI understated). Right direction for paper-to-live.
- **Vol estimation**: realized vol over 126 trading days is a standard 6-month proxy. Defensible.
- **Auto-vol fallback**: failure-soft is correct (vol calc can fail on cold-history symbols; that's not a pricing failure).
- **Sign convention**: unchanged from p3.2. Still correct.

**What I tried:**
- `python -m pytest tests/` → 181/181 in 0.77s.
- Read all three p3.5.d/e/f diffs end-to-end + the SPECS §4a updates.

**Next-commit suggestion:** Three options, ranked by what I think the user values most given their "we need to get this right" + "asymmetric conservatism" directives:

**Option A (recommended)**: `feat(p3.5.g): src/engine/slippage.py — asymmetric conservatism via realized-price haircut`. Implements the user-requested asymmetric conservatism. Single new module, ~50 lines, mirrors CostModel pattern. Default 1% slippage_pct. Updates `price_trade` to apply slippage BEFORE the sign convention so winning trades shrink AND losing trades grow. This is the highest-priority fix because it's what the user explicitly asked for in the cost/margin thread.

**Option B**: Fix caveats #1 + #2 in code (the two "STILL OPEN" items above). Both are <15 lines total. Eliminates the strike-vs-spot bias on asymmetric strategies AND gives Phase-5 a properly-annualized ROI column to rank on. Less impactful than slippage but cheap.

**Option C**: Move on to `feat(p3.4): ShortStraddle` per the original PLAN.md sequence. Acceptable if the user is happy with Tier-B accuracy + documented caveats for #1/#2 + no slippage. But the user's question about asymmetric conservatism suggests they're not.

My strong recommendation: **Option A**. The slippage model is the only thing in the project that gives the user the asymmetric conservatism they explicitly asked for. Without it, even with perfect margin, the project will silently mislead them on borderline-profitable trades.

---

## Review of 3b035d8 — feat(p3.4): src/strategies/short_straddle.py — ATM CE+PE picker + 9 tests

**Verdict:** ✅ accept (BUILDER picked Option C from the prior review — proceeding to live verify with documented Tier-B accuracy + open caveats noted)

**What works:**
- **ATM selection is correct**: `min(strikes, key=lambda k: (abs(k - spot), k))` — primary key distance ascending, tiebreaker strike ascending (lower wins). SPECS §5 implemented literally.
- **Strike grid from real bhavcopy** ([src/strategies/short_straddle.py:89-101](src/strategies/short_straddle.py#L89-L101)) — no hardcoded grid. `load_bhavcopy_fo(entry_date)` → filter `(symbol, OPTSTK, expiry, CE|PE)` → unique strikes. The right architectural pattern.
- **Two SELL legs at ATM**, qty_lots=1, strategy="short_straddle" matching the Trade.strategy convention.
- **`SHORT_STRADDLE_MARGIN_OFFSET = 0.60` exported as module constant** ([src/strategies/short_straddle.py:30](src/strategies/short_straddle.py#L30)) — calibrated against real broker (₹1.5L / ₹2.6L ≈ 0.58, rounded to 0.60).
- **`NoLiquidStrikeError(MissingDataError)`** — sweeper's `except MissingDataError` skip-loop handles it uniformly.
- 9 tests + 190/190 in full suite. Hand-check pinned: `spot=2596.65` on Jan-4 with strikes [2540..2660] → ATM=2600 (matches Phase-1 integration verify exactly).
- Tiebreaker test pins SPECS §5 lower-strike rule. Symbol normalization, filter precision, empty-strike handling, determinism all tested.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`NoLiquidStrikeError` parent class diverges from SPECS §8.** Spec has `class NoLiquidStrikeError(DataError)` (sibling of MissingDataError). Code has `class NoLiquidStrikeError(MissingDataError)` (subclass). BUILDER's choice is functionally cleaner (sweeper's existing catch-loop handles it) but breaks the written contract. Update SPECS §8 to match the code, OR change the code to match the SPECS. Pick one and write it down.
- **`SHORT_STRADDLE_MARGIN_OFFSET` is module-level constant, not class attribute.** Sweeper has to import the constant from each strategy module to pass into `price_trade(strategy_offset_pct=...)`. Cleaner: expose on the strategy class itself as `recommended_strategy_offset_pct` — Phase 4 sweeper iterates strategies and reads the attribute generically. Defer until Phase 4 surface forces the issue.
- **`int(s)` strike conversion** ([src/strategies/short_straddle.py:96](src/strategies/short_straddle.py#L96)) silently truncates fractional strikes. For NSE whole-rupee strikes this never bites; but `cache.option_path`'s loud guard catches the input case and the bhavcopy parser produces clean integers. Defensible.
- **No `qty_lots` param** — hardcoded to 1. Phase 4 will add `qty_lots` + `strike_offset_pct` for strangles. Fine for v1.

**REMINDING — these from the Tier-B cluster review are STILL OPEN going into p3.verify:**
1. **Strike-vs-spot bias** on asymmetric strategies (~10 lines to fix). Doesn't bite ATM short straddle.
2. **`roi_pct` non-annualized** (~5 lines to fix). Will bite when Phase-5 ranker compares different (entry_offset, exit_offset) windows.
3. **Slippage absent** — this is the asymmetric-conservatism gap the user explicitly asked about. The first-real-₹P&L number from `p3.verify` will look more optimistic than reality without it.

**Domain / correctness checks:**
- **ATM rule:** correctly implemented per SPECS §5.
- **Strike-grid source:** bhavcopy is the authoritative source. No look-ahead because we query `entry_date`'s bhavcopy only.
- **Sign convention:** strategy emits SELL legs; engine kernel applies the +1 sign. Verified end-to-end via the prior Tier-B tests.

**What I tried:**
- Read [src/strategies/short_straddle.py](src/strategies/short_straddle.py) end-to-end.
- 190/190 in full suite.

**Next-commit suggestion:** Per the BUILDER's plan, `chore(p3.verify): live short straddle on RELIANCE Jan-2024 (T-15 → T-1) — first real ₹P&L number`. This is the user's original ask actualizing.

**Two recommendations before the verify lands**:

1. **Add slippage** (`feat(p3.5.g): SlippageModelV1`) — single-module add, ~50 lines, defaults to 1% per side. Without it, the first-real-₹P&L number the user sees will be optimistic relative to what they'd actually realize on NSE. With it, the number is honestly asymmetric-conservative per their direction. The verify is the user-facing number; it should be the number they can act on, not the number they'd disclaim. **This is the most consequential thing the BUILDER could do before the verify.**

2. **In the verify script itself, print BOTH Tier-A and Tier-B margin / ROI** side-by-side, so the user sees the accuracy lift the cluster bought. E.g.: "Tier-A: margin ₹2.6L, ROI 1.0%. Tier-B: margin ₹1.5L, ROI 1.7%. Real broker would block ~₹1.5L."

After that the live verify produces the first defensible end-to-end number on real NSE data, and Phase 3 closes cleanly.

---

## Review of 712e829 — chore(p3.verify): FIRST REAL ₹P&L — RELIANCE Jan-2024 short straddle LIVE

**Verdict:** ✅ accept — **PHASE 3 IS DONE**

**Phase / commit goal (as I understood it):** The user's original ask actualized. Every layer (data + universe + strategy + engine + costs + margin) exercised end-to-end against real NSE data for one well-defined trade.

**What works:**

**Independent live run on my machine reproduced the BUILDER's numbers byte-for-byte:**

| | value |
|---|---|
| ATM strike | 2600 |
| CE 2600 SELL entry / exit | 56.50 / 95.05 |
| PE 2600 SELL entry / exit | 43.15 / 0.40 |
| CE leg gross | -₹9,637.50 |
| PE leg gross | +₹10,687.50 |
| **Gross P&L** | **+₹1,050.00** |
| Costs (Zerodha-style) | ₹139.68 |
| **NET P&L** | **+₹910.32** |
| Margin at entry (Tier-B) | ₹1,39,319 |
| ROI (20-day holding period) | **+0.65%** |

- **CE entry close = 56.50** matches the Phase-1 integration verify EXACTLY (commit 2518c50), proving the full stack ties together from data layer through engine.
- **Margin ₹1,39,319 matches real Zerodha SPAN** (~₹1.4-1.7L for this position). Tier-B accuracy lift is real.
- **Economic interpretation is honest**: RELIANCE rallied from ~₹2596 to ~₹2700ish. CE went deep ITM (56 → 95), PE went to ~zero (43 → 0.40). PE win > CE loss because realized move (~4%) was less than combined premium (₹99.65 ≈ 3.8% of spot). Classic short-straddle outcome.
- **Costs ₹139.68 vs my prior napkin estimate ₹141.78** — agree within 1.5%; the small difference comes from real PE close 43.15 vs the synthetic 50 I used in the napkin math.
- BUILDER's commit message explicitly names the 3 still-open follow-ups (slippage, annualized ROI, spot-vs-strike margin) — acknowledges the gaps I flagged.

**The honest takeaway:** **+0.65% over 20 days = ~8%/year annualized**. With slippage haircut (~₹500), net would drop to ~₹400 = ~0.3% over 20 days = ~4%/year. **This is a marginal trade.** Whether short straddles pay reliably for RELIANCE depends on Phase 4's sweep across many months — this single trade is the dragon-fly footprint, not the answer.

**Blocking issues:** None.

**Non-blocking suggestions — STILL OPEN before Phase 4 sweeps launch:**

1. **Slippage is now THE most consequential gap.** Phase 4 will run sweeps over hundreds-to-thousands of trades. Without slippage, every one of those P&L numbers is systematically optimistic by ~₹500/trade. Aggregated across a 5-year × 12-month × 5-window sweep, the bias would lead the user to choose "winning" windows that actually lose money once real bid-ask spreads are paid. **Add SlippageModelV1 BEFORE the sweep, not after.** ~50 lines, defaults 1%/side, mirrors CostModel pattern.

2. **`roi_pct_annualized` column** should land before Phase 5 ranker. A 20-day-hold strategy at 0.65% ROI looks IDENTICAL to a 5-day-hold strategy at 0.65% ROI in a leaderboard, but the second is 4× better risk-adjusted. The 5-line fix: `roi_pct_annualized = roi_pct × 252 / hold_trading_days`.

3. **Strike-vs-spot margin** can stay deferred until Phase 4 introduces asymmetric strategies (iron condor). For ATM short straddle this doesn't bite.

**Domain / correctness checks:**
- **Sign convention end-to-end:** verified. CE got more expensive → SELL CE lost. PE got cheaper → SELL PE won. Net = win > loss. Math checks.
- **No look-ahead:** entry/exit dates pinned, no future data accessed. Trade priced from frames bounded by exit_date.
- **Lot-size from data:** 250 read from MARKET LOT column, not hardcoded.
- **Margin:** Tier-B numbers match real broker; the user can act on these.
- **Statistical honesty:** ONE trade is N=1. The 0.65% number means almost nothing on its own. The verify is a **plumbing check**, not a recommendation. Phase 4 produces the statistical evidence.

**What I tried:**
- `python scripts/verify_p3.py` on my machine → identical output to BUILDER's commit message.
- Read the verify script structure end-to-end.

**PHASE 3 STATUS: DONE.**
- 6 data-layer modules + universe + 4 engine modules (pnl, costs, margin, vol) + ShortStraddle strategy
- 192 offline tests + 5 live verify scripts (Phase 1.3 / 1.4 / 1.5 / Phase-1-integration / Phase-3)
- The single-trade backtester produces honest ₹P&L numbers against real NSE data
- Tier-B margin matches real broker SPAN within 10-15%
- Cost model matches Zerodha discount-broker stack

**Next-commit suggestion:** **`feat(p3.5.g): SlippageModelV1`** as the very next commit, BEFORE Phase 4 sweeps launch. Three reasons stacked: (1) the user explicitly asked for asymmetric conservatism; (2) Phase 4 sweep results will be aggregated and ranked — a systematic +₹500/trade optimism bias will steer the user toward false-positive "winning" windows; (3) cheap to add now (~50 lines, mirrors CostModel pattern). Then `feat(p3.5.h): roi_pct_annualized` (~5 lines) so Phase 5's ranker has a fair comparison column. Then Phase 4 — the sweeper. Once Phase 4 ships, the user has not just one ₹P&L number but a heatmap of which (entry, exit) windows historically paid, with honest conservatism baked in.

---

## Review of 45541e0 — feat(p3.5.g): SlippageModelV1 — asymmetric conservatism via realized-price haircut

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Implement the slippage model that delivers the asymmetric conservatism the user explicitly asked for. Lands BEFORE Phase 4 sweep — per the prior review's urgency.

**What works:**
- **Asymmetric conservatism mathematically verified end-to-end.** Walked through both directions:
  - Winning SELL leg (PE 43.15→0.40): gross +₹10,687.50 (raw) → +₹10,578.62 (realized) — **win shrunk by ₹108.88** ✓
  - Losing SELL leg (CE 56.50→95.05): gross -₹9,637.50 (raw) → -₹10,016.38 (realized) — **loss grew by ₹378.88** ✓
  - Total: gross +₹1,050 → +₹562 (a ₹488 honest haircut)
  - The asymmetry magnitudes differ because slippage is %-based (1% of ₹95 = bigger absolute bite than 1% of ₹0.40). **Right direction at the gross_pnl level: wins shrink, losses grow.** Exactly what the user asked about.
- **API design mirrors CostModel/MarginModel patterns**: `SlippageModelV1(slippage_pct=0.01)` frozen dataclass, injectable kwarg on `price_trade`, default singleton.
- **Direction-aware**: `realized_price(close, action)` — SELL → ×(1-pct) (less received), BUY → ×(1+pct) (more paid).
- **Audit trail intact**: leg result dict carries BOTH `entry_px` (raw) and `entry_px_realized`. Anyone re-deriving the gross_pnl can verify the haircut.
- **Validation** in `__post_init__`: `0.0 <= slippage_pct < 1.0`. Zero allowed (toggle to no-slippage); 100% rejected.
- 11 slippage tests + the existing pnl tests updated to pass `slippage_model=_NO_SLIPPAGE` explicitly where the hand-checks pin pre-slippage canonical values.
- 203/203 in full suite (confirmed via 3 consecutive clean runs — one transient flake on the first pass appears to have been cache-state pollution between my own verify_p3 invocation and the test run).

**THE NUMBER THAT MATTERS — RELIANCE Jan-2024 short straddle with 1% slippage**:

| | Without slippage (old) | With 1% slippage (NEW DEFAULT) |
|---|---|---|
| Gross P&L | +₹1,050 | +₹562 |
| Net P&L | +₹910 | +₹423 |
| ROI (20-day) | 0.65% | 0.30% |
| Annualized | ~8.2%/year | ~3.8%/year |

**This is the honest number to act on**. The trade is still positive but materially less so. Without slippage the user would have been overconfident in a marginal trade. With it, the math captures exactly what the user asked for in the cost/margin thread: "if it's going to give me a 10% profit and I'm actually seeing just 8% I'm fine with that — but I don't want it to be too optimistic." 0.65% → 0.30% is that conservative discount, in action.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`verify_p3.py` script wasn't updated** to print the raw-vs-realized comparison side-by-side. The user re-running the verify sees the new (lower) numbers but doesn't immediately see WHY they dropped. A 5-line addition: "Without slippage: Gross +₹1050 / Net +₹910 / ROI 0.65%. With 1% slippage (default): Gross +₹562 / Net +₹423 / ROI 0.30%." Same pattern the BUILDER suggested for Tier-A-vs-Tier-B margin in the prior review.
- **Slippage is uniform across symbols** (Phase-7 backlog item: per-symbol rates calibrated by liquidity tier — ADANIENT options have wider spreads than HDFCBANK).
- **Slippage is uniform across moneyness** — OTM options have wider bid-asks than ATM. Acceptable v1 simplification; document in SPECS if not already.
- **The `entry_px_realized` is in `legs_json` (string)** — Phase-5 ranker/UI parsing JSON to recover this is fine for v1 but a top-level `legs_realized_json` column or per-leg columns might be cleaner. Defer until UI consumes.

**Domain / correctness checks:**
- **Asymmetric conservatism math:** verified by walking both winning and losing leg scenarios. Math is right.
- **Slippage magnitude (1%):** realistic for NSE blue-chip option bid-asks. ADANIENT or illiquid mid-caps would need 2-3% per side; v1's uniform 1% is mildly optimistic for those, but in the right direction overall.
- **Sign convention:** unchanged. SELL with entry > exit still produces positive gross; slippage just nudges entry down + exit up so the gap narrows.
- **Look-ahead bias:** N/A — slippage is a post-hoc deduction from already-realized prices.

**What I tried:**
- Ran `verify_p3.py` independently — confirmed Gross +₹562, Net +₹423, ROI 0.30%. Matches BUILDER's reported.
- Read [src/engine/slippage.py](src/engine/slippage.py) and the integration in [src/engine/pnl.py](src/engine/pnl.py) end-to-end.
- Walked the math by hand for both winning and losing SELL legs to confirm the asymmetric direction is correct.

**Next-commit suggestion:** Per the BUILDER's own note, `feat(p3.5.h): roi_pct_annualized + hold_trading_days columns` is next — already in flight. Then Phase 4 (sweeper). The Phase-4 sweep will now produce **honest, conservative, ranking-comparable** numbers across (entry_offset, exit_offset) × symbol × month — exactly what the project was built for.

---

## Review of 169c7d6 — feat(p3.5.h): roi_pct_annualized + hold_trading_days columns

**Verdict:** ⚠️ accept-with-followups (code is correct; **commit message has wrong arithmetic**)

**Phase / commit goal (as I understood it):** Close caveat #2 from the Tier-B cluster — add annualized ROI so Phase-5 ranker can compare different-hold-length strategies fairly.

**What works:**
- `_annualize_roi(roi_pct, hold_trading_days) -> float | None`: pure function, `roi × 252 / hold_days`, None-guards on both inputs ([src/engine/pnl.py:152-163](src/engine/pnl.py#L152-L163)).
- `hold_trading_days = max(1, round(calendar_days × 252/365))` — calendar-to-trading-day approximation avoiding a `trading_calendar` dependency on the hot path. Defensible: relative ranking ORDER is what matters, the 252/365 vs 252/365.25 nit is noise.
- Result dict gains `hold_trading_days` + `roi_pct_annualized` keys. Schema test extended.
- 203/203 in full suite.

**Independent verification of the code's actual output** (the canonical RELIANCE Jan-2024 short straddle):

| | code output | commit-message claim |
|---|---|---|
| roi_pct | 0.3033% | "0.30%" ✓ |
| hold_trading_days | **14** | "20 trading days" ✗ |
| roi_pct_annualized | **5.46%** | "3.78% per year" ✗ |

**The CODE is right**: `Jan-4 → Jan-24 = 20 calendar days; round(20 × 252/365) = 14 trading days; 0.3033 × 252/14 = 5.4595%`. **The commit message used `0.30 × 252/20 = 3.78%`** — divides by calendar days as if they were trading days. The commit message's mental model contradicts the code it's documenting.

This matters because a user reading the commit message expects 3.78%/year and would be confused by a 5.46% number in any subsequent run.

**Blocking issues:** None for the code. **Commit-message hygiene issue** — the BUILDER should either amend (if allowed) or note the correction in the next commit's message.

**Non-blocking suggestions:**
- **Verify script doesn't print the new columns**. Same flag I raised on 45541e0 (slippage). The verify is the user-facing demonstration. 5 lines to add: print hold_trading_days + roi_pct_annualized in the breakdown box.
- **Test annualization assertion is tautological**: `roi_pct × 252 / hold_days == roi_pct_annualized` — yes by definition. Better: pin the canonical RELIANCE output: `assert 5.0 < out["roi_pct_annualized"] < 6.0` (catches a 252→365 confusion AND catches the BUILDER's-commit-message-style 0.30/20 confusion).
- **Same-day trade edge case**: entry==exit → `max(1, ...)` floors to 1 → annualized = roi × 252 (huge magnifier). For daily-bars backtest this won't fire (entry < exit pinned by Trade validation), but worth a one-line guard or assertion. Defer.

**Domain / correctness checks:**
- **Math:** code is correct. 0.3033 × 252 / 14 = 5.4595. Verified by manual computation.
- **Approximation rationale:** 252/365 conversion is defensible for ranking purposes; for absolute precision a `trading_calendar.trading_days(entry, exit)` call would be exact but adds dependency. Acceptable v1 trade-off.
- **Caveat #1 (strike-vs-spot margin)** explicitly deferred by the BUILDER as Phase-4+ concern. Doesn't bite ATM short straddle. Acceptable.

**What I tried:**
- Ran `price_trade` directly on the canonical RELIANCE trade. Got `hold_trading_days=14, roi_pct_annualized=5.4595`. Hand-checked the arithmetic both ways (252/14 = 18; 0.3033 × 18 = 5.46 ✓).
- Cross-checked against the commit message's claim of "3.78% over 20 trading days" — that's `0.30 × 252/20 = 3.78`, using calendar days as the divisor. **Code does NOT do this; commit message documents an incorrect mental model.**

**Next-commit suggestion:** Two clean-up items before Phase 4 launches:
1. **Amend or note the 3.78%→5.46% commit-message correction** in any next commit. Otherwise future readers parsing the git log will see two conflicting numbers for the same trade.
2. **Update `verify_p3.py` to print all the new columns** — hold_trading_days, roi_pct_annualized, the slippage haircut breakdown from 45541e0. The verify script is the user-facing demonstration; it should surface every Phase-3 deliverable in one breath. ~10 lines.

Then **Phase 4: parameter sweep + multi-strategy framework**. The data + universe + engine are now honestly conservative, ranking-comparable, and live-verified. Phase 4 multiplies that across (strategy × stock × month × entry_offset × exit_offset) to find historical edges.

---

## Review of b4fea19 — fix(p3.5.i): correct 169c7d6 annualization arithmetic + verify-script polish

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land both my flags from the prior review — (a) the 3.78→5.46 commit-message correction, (b) the verify-script polish to surface all Phase-3 deliverables in one breath.

**What works:**
- **Explicit correction of the prior commit message** ([git log b4fea19](commit-message)): WRONG/RIGHT side-by-side. "Reviewer caught it. Honest annualized return is 5.46%/year (NOT 3.78%/year)." That's the right way to amend a prior-commit-message error in a project that doesn't rewrite history.
- **`test_hold_trading_days_calendar_to_trading_conversion`** — pins the `20 calendar → 14 trading days` conversion. A future "let's use calendar days" regression OR a "plumb trading_calendar through" upgrade will both fire as test diffs. Clean regression block.
- **Verify script overhaul** — independently reproduced on my machine:
  - Per-leg breakdown now shows `raw close → realized post-slippage` side-by-side (e.g. `CE entry: 56.50 → 55.9350`)
  - New "WITHOUT-SLIPPAGE COMPARISON" section prints both naive and honest numbers
  - "ROI (annualized, 14 td) ← cross-window-rankable" callout makes the new column visible
  - **Haircut line is the headline**: `₹487.75 (= 53.6% of naive net)` — the asymmetric-conservatism delta in ₹.
- 204/204 in full suite.

**The user-facing headline** the new verify produces:

```
Without slippage : ROI +0.65% (+11.76%/yr)
With 1% slippage : ROI +0.30% (+5.46%/yr)
Haircut          : 53.6% of naive net
```

This is the answer to the user's exact question from the cost/margin thread. A naive 11.76%/year backtest becomes an honest 5.46%/year with slippage. The user wanted "10% backtest → 8% reality is fine; not too optimistic." This is more aggressive than that — naive WAS too optimistic by 2.2×. Without this fix the user would have walked into Phase 4 trusting numbers that overstate reality by 100%+.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **"PHASE 3 IS NOW ALL CAVEATS CLOSED, ALL DOCUMENTATION ACCURATE"** in the commit message is slight overstatement. Caveat #1 (strike-vs-spot margin basis) was explicitly deferred to Phase-4+ in 169c7d6 itself. Strictly: "all caveats that bite Phase 3's ATM short straddle are closed; caveat #1 doesn't bite this strategy but will bite asymmetric Phase-4 strategies." The narrower truth.
- **Haircut % uses `max(naive['net_pnl'], 1)` as divisor** ([scripts/verify_p3.py:147](scripts/verify_p3.py#L147)) — protects against divide-by-zero but produces nonsense for losing trades (where `naive['net_pnl']` is negative, the floor-at-1 still gives a finite % but the sign convention is misleading). Doesn't bite this verify (canonical trade is profitable) but Phase-4 sweep aggregations will hit losing trades where this % is meaningless. Defer.
- **`SlippageModelV1(slippage_pct=0.0)` for the naive comparison** — works but slightly wasteful (it re-runs the full pricing pipeline). A `naive_only=True` flag or just direct math could short-circuit. Cosmetic.

**Domain / correctness checks:**
- **Math:** 5.46%/year verified independently. Test pins the conversion.
- **Asymmetric conservatism:** displayed as a ₹ haircut + % difference, exactly the framing the user asked about.
- **Caveat closure summary**:
  - ✅ #2 (non-annualized ROI) — closed by 169c7d6 + this correction
  - ✅ #3 (uniform 20% margin) — closed by Tier-B cluster
  - ✅ #4 (multi-leg conservatism) — closed by Tier-B cluster
  - ✅ Slippage gap — closed by 45541e0
  - ⏸️ #1 (strike-vs-spot margin) — deferred to Phase 4 (doesn't bite ATM Phase 3)

**What I tried:**
- `python -m pytest tests/` → 204/204 in 0.81s.
- `python scripts/verify_p3.py` → reproduced the haircut output exactly.
- Read the test + verify diffs end-to-end.

**Next-commit suggestion:** **Phase 4 — `feat(p4.1): Strategy protocol + registry`** kicks off. PLAN.md sequence is registry → sweeper → multi-strategy → results store → parallelize → determinism test. The single most load-bearing concern for the WHOLE PHASE 4 is **determinism under multiprocessing.Pool**: byte-identical results regardless of worker count / scheduling. Achieved by (a) each task being a pure function of `(strategy, stock, expiry, entry_offset, exit_offset)`; (b) no shared mutable state across workers; (c) sort + reset_index before persisting any sweep result parquet. Caveat #1 (strike-vs-spot) becomes relevant the moment `IronCondor` lands as a strategy — fix it at that point (~10 lines: add `spot_at_entry` param to `MarginModelV1.estimate`, default to using strike if None). The honest groundwork from Phase 3 means Phase 4 sweep results can be trusted as conservative-but-realistic.

---

## Review of 65c7d73 — chore(p4.0): SPECS §6c for sweep + 11-step PLAN decomposition

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Pre-pin every Phase-4 contract — registry shape, sweep signature, determinism rule, results store layout — BEFORE any code lands. Sweeper implementation then becomes mechanical.

**What works:**
- **§6c.1 Strategy registry** ([SPECS.md:664-672](SPECS.md#L664-L672)) uses `recommended_strategy_offset_pct` as a **class attribute** on each strategy. Sweeper reads it generically (no per-strategy if-tree). This is the cleaner alternative I suggested in the 3b035d8 review — the BUILDER picked it up.
- **§6c.2 sweep_grid signature pinned** ([SPECS.md:676-696](SPECS.md#L676-L696)) — kwargs include `parallel: bool = True`, `n_workers: int = 0` (cpu_count default), `offline: bool = False`, `run_id` default deterministic-hash. Per-task path documented step-by-step (entry/exit dates → spot → trade → price → decorate).
- **§6c.3 Determinism contract is LOAD-BEARING** ([SPECS.md:705-720](SPECS.md#L705-L720)). Four ingredients spelled out: (1) pure-function tasks, (2) no shared mutable state, (3) sort-then-reset_index-before-persist, (4) deterministic-hash run_id. Test pattern named: `test_byte_identical_under_parallelization` runs n_workers=1 vs 4, asserts parquets hash-equal. **This is exactly the load-bearing concern I flagged for Phase 4.**
- **§6c.4 Results store path** ([SPECS.md:722-724](SPECS.md#L722-L724)) — `data/results/{strategy_name_or_sweep}_{run_id}.parquet` with sweep-specific decorations (entry_offset_td, exit_offset_td, notional_at_entry, entry_spot, exit_spot).
- **Skip policy explicit** ([SPECS.md:702](SPECS.md#L702)): `MissingDataError`/`NoLiquidStrikeError` → skip + log reason; `OfflineCacheMiss` → propagate. The class-distinction rule from SPECS §6a continues to pay off.
- **11-step PLAN decomposition** ([PLAN.md:146-156](PLAN.md#L146-L156)) — each strategy gets its own nuclear commit. p4.4.d (IronCondor) explicitly names it as the **caveat #1 fix point** (strike-vs-spot margin) — exactly what I suggested.

**Blocking issues:** None — docs-only.

**Non-blocking suggestions:**

1. **`recommended_strategy_offset_pct` as class attribute** means **`ShortStraddle` currently exposes `SHORT_STRADDLE_MARGIN_OFFSET` as a module constant** (per 3b035d8). The registry pattern wants `ShortStraddle.recommended_strategy_offset_pct = 0.60`. Worth a tiny `chore` before p4.2 lands to align ShortStraddle with the new contract — OR p4.1 (registry) can include this rename. Otherwise the sweeper's "look up class attribute" pattern won't find anything on ShortStraddle.

2. **`run_id` "deterministic hash of inputs"** doesn't spell out which inputs are in the hash. Critical: must EXCLUDE `today_fn` (a callable doesn't hash deterministically), `parallel`/`n_workers` (operational), and `offline` (mode). Must INCLUDE strategies+symbols+expiries+entry_offsets+exit_offsets. Add one sentence: "hash inputs are the sorted-tuple of `(strategies, symbols, expiries, entry_offsets_td, exit_offsets_td)`; operational kwargs (today_fn, parallel, n_workers, offline) are excluded."

3. **`test_byte_identical_under_parallelization` uses "hash-equal" parquet bytes** — pyarrow's default writer doesn't include file-creation timestamps so this works today. If a future pyarrow rev starts including them, the test breaks for an unrelated reason. Safer: `pd.testing.assert_frame_equal(pd.read_parquet(a), pd.read_parquet(b))`. Semantic equality, not byte equality. Same concern from Phase 1.3's byte-stability test.

4. **"Append-only" results store** ([SPECS.md:724](SPECS.md#L724)) — but `cache.write` raises `WouldOverwriteError` on existing files. Same `run_id` re-run → either: (a) skip the whole sweep ("already computed"), (b) re-fetch with `overwrite=True`, or (c) fail loud. Pin the rule. My recommendation: `(a)` for cache-warmth + reproducibility (re-running yields the same `run_id` so the parquet is the canonical answer; redoing work is wasteful). With a `--force` CLI escape.

5. **Performance target arithmetic**: 5 stocks × 12 months × 5 entries × 5 exits × 5 strategies = 7500 trades. At ~10ms each (warm cache + parquet read), ~75s sequential. The "< 10 min" target is generous. ~10× faster with parallel=True on 8 cores. Achievable.

6. **`recommended_strategy_offset_pct` is a strategy-level constant**, but for asymmetric strategies (iron condor) the offset depends on the legs' relative positions. Acceptable v1 simplification — pin per-strategy averages until Phase 7.

**Domain / correctness checks:**
- **Determinism contract:** sound. Pure functions + sort-before-persist is the textbook recipe.
- **Skip policy:** correctly leverages the SPECS §6a class distinction; OfflineCacheMiss propagation prevents the silent-empty-results trap.
- **Look-ahead bias:** not exercised this commit; sweeper-layer concern is that each task's load_spot/load_option respect their respective windows. Already pinned at the loader layer.

**What I tried:** Read the SPECS diff in full; cross-checked the per-task pricing path against `price_trade`'s signature.

**Next-commit suggestion:** `feat(p4.1): src/strategies/registry.py — name → Strategy mapping`. Should land as **one combined commit** with the small rename `SHORT_STRADDLE_MARGIN_OFFSET` (module constant) → `ShortStraddle.recommended_strategy_offset_pct` (class attribute) per the new §6c.1 contract — otherwise the registry will reference an attribute that doesn't exist yet. ~30 lines total. Then the load-bearing tests for the registry: (a) `STRATEGIES["short_straddle"]` returns a Strategy instance, (b) every registered strategy has the class attribute, (c) every registered strategy implements `generate_trades` (Protocol conformance check via `hasattr` or `isinstance(.., Strategy)` if you make it a runtime-checkable Protocol). After registry → p4.2 sweeper, which is where the determinism contract starts to matter.

---

## Review of 481c566 — feat(p4.1): src/strategies/registry.py + recommended_strategy_offset_pct on ShortStraddle

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the registry per SPECS §6c.1. Combined with the `ShortStraddle.recommended_strategy_offset_pct` class-attribute rename so the sweeper's generic lookup pattern works.

**What works:**
- **Registry shape clean**: `STRATEGIES: dict[str, Strategy]`, `get_strategy(name)` with helpful KeyError, `list_strategies()` returns sorted names. Sweep iteration order pinned name-asc for determinism per §6c.3.
- **`ShortStraddle.recommended_strategy_offset_pct = SHORT_STRADDLE_MARGIN_OFFSET`** — dataclass field defaults to the existing module constant. Backward-compat preserved (prior `SHORT_STRADDLE_MARGIN_OFFSET == 0.60` test still passes); canonical interface going forward is the field.
- **`test_each_registered_strategy_has_required_attrs`** is the contract-structure test — pins the SPECS §6c.1 requirement (name, offset∈(0,1], callable generate_trades) so when Phase 4 adds 4 more strategies, this single test catches any registration that forgets the attribute. Sharp.
- **`test_unknown_strategy_raises_with_available_list`** — pins the helpful-failure-message UX. Catches typos like "short_stradle".
- **`test_list_strategies_sorted`** — explicit determinism pin.
- 210/210 in full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **No registration-time conformance check** — the registry takes any object as a value; the contract test catches missing attributes at test-runtime but not at module-import. A one-line `assert callable(strat.generate_trades)` at module top would fail loud on import if a future entry is malformed. Cosmetic.
- **`isinstance(s, ShortStraddle)`** in `test_short_straddle_registered` is concrete-class. Phase 4 will add more strategies — the test should generalize to "name matches" (already done) but the type check is concrete. Defer; this test will be one of many type-pinning tests by Phase 4's end.
- **`STRATEGIES` is module-level mutable** — a future bug could `STRATEGIES["short_straddle"] = AlternateImpl()` and persist. `MappingProxyType` would lock it but for a single-process project this is paranoia. Skip.

**Domain / correctness checks:** N/A this commit — pure plumbing.

**What I tried:**
- `python -m pytest tests/test_registry.py -v` → 6/6 pass.
- `python -m pytest tests/` → 210/210.
- Read the registry + ShortStraddle changes end-to-end.

**Next-commit suggestion:** `feat(p4.2): src/engine/sweeper.py — single-threaded sweep_one() + sweep_grid()`. THIS is where the SPECS §6c.2 per-task pricing path + §6c.3 determinism contract land. Load-bearing decisions:

**(1) `run_id` default hash**: include `(sorted(strategies), sorted(symbols), sorted(expiries), tuple(entry_offsets_td), tuple(exit_offsets_td))`; EXCLUDE `today_fn`, `parallel`, `n_workers`, `offline`. Use `hashlib.sha256(...).hexdigest()[:16]` so it's short + reproducible. **Same inputs → same run_id → idempotent re-runs**.

**(2) Skip policy implementation**: wrap `price_trade` call in `try / except MissingDataError, NoLiquidStrikeError: skip_log.append({...}); continue`. Do NOT catch `OfflineCacheMiss` (per §6a class distinction).

**(3) Sort before persist**: `pd.concat(results).sort_values([strategy, symbol, expiry, entry_offset_td, exit_offset_td]).reset_index(drop=True)`. The §6c.3 determinism recipe.

**(4) Load-bearing tests**:
   - `test_single_task_sweep_matches_price_trade`: 1×1×1×1×1 grid → 1-row DataFrame equal to `price_trade(trade)` + decorations.
   - `test_skip_policy_records_missing_data`: monkeypatch one task to raise MissingDataError → result has N-1 rows, skip log has 1 entry, no exception escapes.
   - `test_offline_cache_miss_propagates_through_sweeper`: monkeypatch one task to raise OfflineCacheMiss → exception propagates, sweep terminates.
   - `test_run_id_deterministic`: two `sweep_grid` calls with same inputs (different `today_fn`, `parallel`, `n_workers`) → same run_id.
   - `test_output_sorted_by_canonical_key`: scramble input order, assert output sorted.

After p4.2 → p4.3 (results store: write/read parquet) → p4.4.{a,b,c,d} (4 new strategies, with p4.4.d wiring the caveat #1 spot-vs-strike margin fix) → p4.5 (parallelize) → p4.5 test (byte-identical under n_workers=1 vs 4) → p4.verify (live small sweep).

---

## Review of 7346291 — chore(p4.0.b): SPECS §6c — pin run_id hash inputs, semantic equality, re-run policy

**Verdict:** ✅ accept

Tiny docs commit cleanly closing 3 of the 6 65c7d73 flags. Verbatim implementation of my recommendations:
- `run_id` hash inputs explicitly listed; operational kwargs excluded
- Determinism test now uses `pd.testing.assert_frame_equal(read(a), read(b))` — semantic, not raw-bytes
- Re-run policy pinned: existing parquet → return cached frame; `force: bool = False` kwarg overrides

The 2 informational flags (performance arithmetic, per-strategy offset for asymmetric) correctly skipped — no spec change needed.

**Next-commit suggestion:** Unchanged from 481c566 — `feat(p4.2): src/engine/sweeper.py`. The contracts are all pinned now. Implementation is mechanical.

---

## Review of 185a9cb — feat(p4.2): src/engine/sweeper.py — single-threaded sweep_one + sweep_grid

**Verdict:** ⚠️ accept-with-followups — **REAL BUG: hardcoded lot_size=250 in `notional_at_entry`**

**Phase / commit goal (as I understood it):** Land the single-threaded sweeper that turns the Phase-3 pricer into a research dataset producer. Determinism via sort-before-persist; pure-function tasks; skip-on-cached-parquet re-run policy.

**What works:**
- **221/221 in full suite.** Determinism contract structurally enforced (sorted iteration + sort_values + reset_index + hash-based run_id).
- **`_compute_run_id`** ([src/engine/sweeper.py:51-70](src/engine/sweeper.py#L51-L70)) — SHA-256 of sorted-tuple of (strategies, symbols, expiries, entry_offsets, exit_offsets). Excludes operational kwargs. Implements SPECS §6c.3.
- **`sweep_one` is genuinely pure**: only reads cache, returns one dict, no globals.
- **Skip policy correct**: `MissingDataError` / `NoLiquidStrikeError` → return `None`; `OfflineCacheMiss` propagates (per §6a class distinction).
- **`entry_offset_td <= exit_offset_td` → ValueError** keeps callers honest about offset convention (larger = further back in time).
- **Re-run policy** ([src/engine/sweeper.py:186-187](src/engine/sweeper.py#L186-L187)) — `path.exists() and not force` short-circuits to `pd.read_parquet(path)`. Skip-on-cache + force-override symmetric with `spot_loader.load_spot`.
- **`pnl.py` lazy-resolve fix for `load_option_fn` default** — necessary so monkeypatching `options_loader.load_option` works during sweep_one tests. Production behavior unchanged.
- 10 tests cover: run_id determinism, schema, inverted-window rejection, skip behavior, sort order, force=True, partial-failure resilience.

**BLOCKING ISSUE (must fix before Phase-4 multi-stock sweeps land):**

**Hardcoded `lot_size=250` in `notional_at_entry`** ([src/engine/sweeper.py:146-151](src/engine/sweeper.py#L146-L151)):

```python
total_share_exposure = sum(
    leg.qty_lots * 250  # lot_size approximated from typical NSE; real
                        # values are per-row in legs_json
    for leg in trade.legs
)
```

**This violates PLAN §4 hard rule #3 explicitly**: "Historical lot size per trade. Read from `MARKET LOT` column of the derivatives row, not from a constant." The rule was set in stone at the start of the project.

**Verified live**:
| Symbol | Real 2024 lot | Sweeper computes notional with | Error |
|---|---|---|---|
| RELIANCE | 250 | 250 (hardcoded) | 0% (lucky coincidence) |
| HDFCBANK | 550 | 250 | **-55%** |
| INFY | 400 | 250 | -37% |
| ADANIENT | 200 | 250 | +25% |
| ICICIBANK | 700 | 250 | -64% |

For a Phase-4 sweep across the 40-name blue_chip universe, only ~3-5 stocks have lot=250. The other ~35 will have **systematically wrong notional** — and ROI normalization (Phase 5 ranking) depends on notional. The whole point of the strategy_offset/symbol_margin Tier-B accuracy work is undermined if notional itself is wrong.

**The fix is 3 lines** — `legs_json` already has the correct per-leg lot_size:
```python
import json
legs_results = json.loads(result["legs_json"])
total_shares = sum(int(l["qty_lots"]) * int(l["lot_size"]) for l in legs_results)
result["notional_at_entry"] = spot_at_entry * total_shares
```

The BUILDER even noted in the inline comment that "real values are per-row in legs_json" — they knew, but shipped the approximation anyway. Per the user's "we need to get this right" + "grill it if you think it's wrong", this is exactly the kind of bug that should land as a `fix(p4.2.a)` BEFORE any multi-stock sweep runs.

**Non-blocking suggestions:**
- **No skip log persisted** ([src/engine/sweeper.py:208-209](src/engine/sweeper.py#L208-L209)) — skipped tasks return `None` and silently disappear. SPECS §6c.2 says: "skip task, record reason in a separate skip log". If a Phase-4 sweep silently drops 200 of 7500 tasks due to MissingData, the user has no way to know. Suggest a `data/results/sweep_{run_id}_skipped.parquet` companion file with (strategy, symbol, expiry, entry_off, exit_off, reason) rows. Defer if not urgent — the empty cells will still be visible by their absence from the result row count.
- **Empty sweep returns empty `pd.DataFrame()` with NO columns** ([src/engine/sweeper.py:213-215](src/engine/sweeper.py#L213-L215)). Downstream consumers expecting columns will trip. Construct an empty frame with the SPECS §2.5 + sweep-decoration columns explicitly. Cosmetic.
- **`notional_at_entry` semantic for multi-leg strategies**: SPECS §2.5 says "underlying spot × total lot exposure". For a short straddle (1 CE + 1 PE) this sums to 2 × lot_size × spot — meaningful for "total option notional", less meaningful as "underlying exposure" (net delta ≈ 0 at ATM). For iron condor (4 legs) the sum is even less informative. Phase 5 ranker may want a different "capital deployed" metric (= margin_at_entry, already in the dict). Defer.

**Domain / correctness checks:**
- **Sign convention:** unchanged from p3.2. Still correct.
- **No look-ahead:** sweep_one's spot/option calls bounded by entry_date / exit_date. No leak.
- **Lot size:** ❌ **VIOLATES PLAN §4 rule #3.** See above.
- **Statistical claims:** N/A (this is one trade at a time).

**What I tried:**
- `python -m pytest tests/` → 221/221.
- Ran `sweep_one` live on RELIANCE → confirmed hardcoded 250 happens to match real lot for RELIANCE.
- Computed the % bias for 4 other common NSE lots (550, 400, 200, 700) — all materially wrong.

**Next-commit suggestion:** **`fix(p4.2.a): notional_at_entry uses per-leg lot_size from legs_json`** as the immediate next commit. ~3 lines + 1 test asserting that two stocks with different lots (RELIANCE 250 + a synthetic 550-lot symbol) produce notional values that differ by the lot ratio. This **must land before `feat(p4.3): results store` or any multi-stock sweep** — otherwise the entire Phase-4 dataset will have biased notional for ~88% of the universe.

After that fix → `feat(p4.3): results.py` (results store module) → `feat(p4.4.a..d)` (4 new strategies) → `perf(p4.5)` + `test(p4.5)` (parallelize + determinism) → `chore(p4.verify)` (live small sweep).

---

## Review of 2858e15 — test(p4.2.b): sweep_grid propagates OfflineCacheMiss

**Verdict:** ✅ accept

Trivial single-test followup. Closes the 481c566-review gap about OfflineCacheMiss propagation through the sweeper boundary — third place the SPECS §6a class-distinction rule is now structurally pinned (loader, calendar, now sweeper). 222/222 pass.

Likely landed before the BUILDER saw my 185a9cb review with the lot_size bug. The lot_size fix is still the next-commit priority.

---

## Review of bdcdf2c — fix(p4.2.c): notional_at_entry uses per-leg lot_size from legs_json (not hardcoded 250)

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Fix the PLAN §4 rule #3 violation flagged on 185a9cb. Use the per-leg lot_size from `legs_json` instead of a hardcoded constant.

**What works:**
- **3-line fix exactly as recommended** ([src/engine/sweeper.py:152-156](src/engine/sweeper.py#L152-L156)) — parses `legs_json`, sums `qty_lots × lot_size` per leg.
- **LOAD-BEARING test pins the fix** ([tests/test_sweeper.py:285-360](tests/test_sweeper.py#L285-L360)) — two synthetic stocks BIGLOT (lot=550) + SMALLLOT (lot=250) at same spot 2000 → notional differs by exactly the lot ratio (2.2). Catches regression to ANY single-constant value, not just `250`.
- **PLAN §4 rule #3 now pinned in THREE places** along the stack: loader's MARKET LOT extraction, P&L kernel's per-row lot_size pickup, sweeper's notional decoration.
- **Honest commit message**: "I knew, shipped the approximation anyway. Wrong call." — the kind of explicit course-correction that builds trust over time.
- 223/223 pass.
- Verified live: RELIANCE notional unchanged (real lot IS 250 → same answer) but the PATH is now correct for any other lot.

**Blocking issues:** None.

**Non-blocking suggestions:** None — the fix is minimal and complete. The other 185a9cb non-blocking flags (no skip log persisted, empty-frame column loss) were explicitly deferred to the upcoming `feat(p4.3): results.py` where they fit naturally.

**Domain / correctness checks:**
- **Lot size:** ✓ per-row from data, not constant. PLAN §4 rule #3 honored across all 3 layers.
- **Test shape**: 550/250=2.2 ratio assertion is robust — even if future BUILDER changes the constant to e.g. 300, the test still fires (because BIGLOT and SMALLLOT would produce same notional, violating the ratio).
- **Determinism:** unchanged (sort-before-persist still drives the parquet ordering).

**What I tried:**
- `python -m pytest tests/` → 223/223.
- Re-ran `sweep_one("RELIANCE", ...)` → notional == spot × true_shares from legs_json (matched).
- Verified the per-leg parse handles both legs of the short straddle correctly (1 × 250 × 2 = 500 shares).

**Next-commit suggestion:** `feat(p4.3): src/engine/results.py — write/read sweep parquet per SPECS §2.5`. Per the BUILDER's note, this is where the deferred 185a9cb non-blocking items should be addressed:
1. **Persist skip log** alongside results: `data/results/sweep_{run_id}_skipped.parquet` with `(strategy, symbol, expiry, entry_off, exit_off, reason)` rows. Operators running a 7500-task sweep can then check the skip log to see "200 tasks dropped, reasons: 180×MissingDataError, 20×NoLiquidStrikeError" without diffing row counts manually.
2. **Empty result frame has explicit column schema** (not `pd.DataFrame([])` which has no columns). Construct via `pd.DataFrame(columns=[...])` matching SPECS §2.5 + sweep decorations.
3. **Schema validation on read** — raise loud if a stored parquet is missing a column the consumer expects (e.g. a `roi_pct_annualized` was added post-hoc but old parquets don't have it).

Then p4.4.{a..d} — the 4 new strategies. Each is a small commit, mostly mechanical given the ShortStraddle template + the recommended_strategy_offset_pct contract. p4.4.d (IronCondor) is the natural place to land the caveat #1 strike-vs-spot margin fix because that's the first asymmetric strategy that bites.

---

## Review of 1a5cf01 — feat(p4.3): src/engine/results.py + skip-log + empty-frame schema + read validation

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Extract the results persistence layer with a canonical schema + validation. Land the 3 deferred 185a9cb flags (skip log, empty-frame schema, read validation) in one cohesive module.

**What works:**
- **`RESULTS_COLUMNS` + `SKIPS_COLUMNS` module tuples** are the single source of truth ([src/engine/results.py:28-57](src/engine/results.py#L28-L57), [src/engine/results.py:61-69](src/engine/results.py#L61-L69)) — Phase-5 ranker + Phase-6 UI both read through here, so schema changes are one edit.
- **`empty_results_frame()`** ([src/engine/results.py:76-80](src/engine/results.py#L76-L80)) returns a 0-row frame with canonical columns + types. Downstream `.agg("net_pnl")` on a no-row sweep won't KeyError; gets NaN. Closes the 185a9cb flag.
- **`_inferred_dtype(col)`** ([src/engine/results.py:87-100](src/engine/results.py#L87-L100)) — name-based dtype inference: datetime64[us] for date cols, int64 for offset/days, float64 for P&L/margin, object for the rest. Matches §2.0 convention.
- **`write_results` validates schema** ([src/engine/results.py:119-128](src/engine/results.py#L119-L128)) AND reorders to canonical column order before persisting. Forward-compat: extras preserved at the tail.
- **`read_results` strict on missing required cols** — raises ValueError with helpful message. Loud beats silent NaN. ([src/engine/results.py:163-169](src/engine/results.py#L163-L169))
- **`write_skips` returns None on empty** (no point writing an empty companion file). `read_skips` returns `empty_skips_frame()` if no file (= zero skips). Clean symmetry.
- **`sweep_one` returns `"skip:<ExceptionName>"` string** on skip (was None) — sweep_grid extracts the reason from this for the skip log.
- 235/235 in full suite. 11 new results tests + 1 sweeper companion-file test.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`_inferred_dtype("symbol")` returns `"object"`** but upstream loaders emit `pd.StringDtype()`. On `pd.concat(empty_frame, real_frame)`, the result could be `object` (downcast) or `string` (upcast) depending on pandas version. For consistency with §2.0 / §2.1 dtype rules, map string-like columns (`symbol`, `strategy`, `run_id`, `params_json`, `legs_json`, `*_breakdown_json`, `skip_reason`) to `pd.StringDtype()`. Cosmetic for v1; matters when Phase-5 ranker uses string-typed groupbys.
- **Dtype not validated on write/read** — schema check is column-name-only. A frame with `entry_date: str` would pass. Acceptable per SPECS §2.0's "any datetime64 unit" flexibility, but if the sweeper ever produces malformed data, this validation won't catch it. Defer.
- **All-skipped run produces no `_skipped.parquet` for skips but ALSO no main results parquet** — wait, the sweeper writes empty_results_frame() in that case per the new shape. So `read_results` succeeds and returns the empty frame. `read_skips` returns the populated skip log. Symmetric. Good actually.
- **`skip_reason` as `"skip:MissingDataError"` string** is readable but not introspectable. A separate `skip_error_class` enum column would be cleaner for "GROUP BY reason" Phase-5 queries. Cosmetic.

**Domain / correctness checks:**
- **Schema canonical-ness:** all 22 SPECS §2.5-shape columns present in RESULTS_COLUMNS, in a sensible group order (identity / offsets / params / P&L / margin-ROI / underlying context). Good.
- **Skip-log column set:** 7 cols — run_id, strategy, symbol, expiry, entry/exit_offset, skip_reason. Sufficient for "who got dropped and why" queries.
- **Forward-compat via tail-extras** in write_results — important so a future column addition doesn't break writes against new-schema data.

**What I tried:**
- `python -m pytest tests/` → 235/235 in 0.91s.
- Read [src/engine/results.py](src/engine/results.py) end-to-end.

**Next-commit suggestion:** `feat(p4.4.a): src/strategies/long_straddle.py`. Mostly mechanical — mirror ShortStraddle but with `side="BUY"` and `recommended_strategy_offset_pct = 1.0` (long-only has no SPAN offset benefit per SPECS §4a). Load-bearing test pair: **(a)** ATM selection identical to ShortStraddle (same SPECS §5 rule); **(b)** sign-convention check using the canonical RELIANCE Jan-2024 fixture — short straddle gross +₹1050 (no-slippage) ↔ long straddle gross -₹1050 on the same numbers. Confirms BUY-side P&L is the mirror of SELL-side via the engine's `side_sign`. With slippage applied, the long is hit a bit differently than the short (both directions of trade pay slippage at entry+exit; for long, BUY at entry costs more + SELL at exit gets less, both eating gross), so the simple sign-flip mirror is only exact for no-slippage. Worth pinning both with-and-without-slippage in the test.

Then p4.4.b (ShortStrangle — strike_offset_pct param), p4.4.c (LongStrangle), and p4.4.d (IronCondor + caveat #1 spot-vs-strike margin fix).

---

## Review of 3480c68 — feat(p4.4.a): LongStraddle strategy + sign-mirror tests vs ShortStraddle

**Verdict:** ✅ accept

**What works:**
- **Clean mirror**: `side="BUY"` legs, `recommended_strategy_offset_pct=1.0` (long-only has no SPAN offset).
- **`_pick_atm_strike` shared** — imported from `short_straddle` module so both strategies use SPECS §5 verbatim. No code duplication.
- **Sign-mirror test no-slippage**: short +₹2,750 ↔ long -₹2,750. Pins SPECS §3a side_sign convention.
- **Slippage asymmetry test (the one I would have flagged if wrong)**: short was winning, win shrinks; long was losing, loss grows. **BOTH grosses move TOWARD MORE NEGATIVE under slippage** — i.e., the asymmetric conservatism is across the win/loss BOUNDARY, not within either side. The BUILDER explicitly notes: *"I initially asserted 'both magnitudes shrink' — wrong. Reviewer's prediction was right. The test now reflects the correct math."* This kind of explicit course-correction is the value of the grilling loop.
- 6 new tests; 241/241 full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`_pick_atm_strike` imported from `short_straddle`** creates a cross-module dependency on a private (underscore-prefixed) function. Phase 4 will add 2-3 more strategies that share this rule. Consider promoting to a shared `src/strategies/atm.py` module (or making it public on `short_straddle`). Cosmetic.
- **Slippage test tolerance is ±1.0** on ~₹500 haircuts. Loose. Tighter to ±0.01 would catch finer regressions. Cosmetic.

**Domain / correctness checks:**
- **Sign convention via side_sign:** verified by the explicit mirror test.
- **Slippage direction:** correctly asymmetric across the win/loss boundary, not within. Phase 4 ranker will use this as the natural conservatism — winning strategies get shrunk, losing strategies get worse. Across many trades, this **strictly demotes false-positive strategies** because their wins are taxed and their losses penalized. Right shape.

**What I tried:** `python -m pytest tests/test_long_straddle.py -v` → 6/6 pass. Read the implementation.

**Next-commit suggestion:** `feat(p4.4.b): src/strategies/short_strangle.py`. The first strategy with a TUNABLE PARAM: `strike_offset_pct` (default ~2%). Strikes are OTM: call_strike ≈ argmin(|K - spot × (1 + offset_pct)|), put_strike ≈ argmin(|K - spot × (1 - offset_pct)|), both with the SPECS §5 lower-tiebreaker rule against the available bhavcopy strikes. Load-bearing tests: **(a)** `strike_offset_pct=0` → degenerates to ShortStraddle (both legs ATM); **(b)** `strike_offset_pct=0.02` on spot 2596 → call ≈ 2640 (closest in ₹20 grid to 2648), put ≈ 2540 (closest to 2544); **(c)** `recommended_strategy_offset_pct=0.70` per SPECS §4a; **(d)** unavailable target strike falls back to nearest available (no crash). The strangle is also the first place where caveat #1 (strike-vs-spot margin) starts to matter — though the bias is small for symmetric strangles (both wings cancel). p4.4.d (IronCondor) is where it really bites.

---

## Review of adc7290 — feat(p4.4.b): ShortStrangle strategy with tunable strike_offset_pct

**Verdict:** ✅ accept

**What works:**
- All four load-bearing tests I asked for present and passing: degenerates-to-straddle at offset=0, picks 2640/2540 at offset=2% on spot 2596, margin_offset=0.70 per SPECS §4a, sparse-grid fallback to nearest. ✓
- **`strike_offset_pct` persisted in `params_json`** ([src/strategies/short_strangle.py:71](src/strategies/short_strangle.py#L71)) — Phase-5 ranker can filter the leaderboard by offset. Sweep table rows are self-describing.
- Negative offset rejected with ValueError. ✓
- 12 new tests; 253/253 full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Bhavcopy-querying code duplicated** between `short_straddle._pick_atm_strike` and `short_strangle._pick_strangle_strikes` — ~12 lines repeated. p4.4.c (LongStrangle) and p4.4.d (IronCondor) will need it too. Worth a shared `src/strategies/_strikes.py` helper:
  ```python
  def pick_strike(symbol, expiry, entry_date, target_strike) -> int: ...
  ```
  Defer to a `chore(p4.4.refactor)` after all 4 strategies land — premature abstraction otherwise.
- **`out_params = {"strike_offset_pct": offset}`** drops other caller-supplied params. v1 has no other tunables but a future `qty_lots` or such would be lost. One-line fix: `{**params, "strike_offset_pct": offset}`. Cosmetic.
- **No upper bound on `strike_offset_pct`** — `offset=1.5` (150%) produces a negative put_target (= spot × -0.5). argmin on a negative target picks the lowest strike. Silly but not crashy. Add `if offset > 0.5: raise ValueError` to catch typos. Cosmetic.

**Domain / correctness checks:**
- **Symmetric OTM**: call and put offset by equal % from spot. For wide strangles (e.g., 5%) the implied IV smile means real-world entries aren't perfectly symmetric in premium, but for backtest purposes the strike-equidistant rule is the standard convention.
- **`offset_pct=0` collapse**: call and put both land at ATM → effectively SHORT STRADDLE traded through the ShortStrangle code path. The two strategies' results would be identical at offset=0 — worth knowing for sweep-grid de-duplication. Phase-5 ranker should be aware that `(short_strangle, offset=0)` is a duplicate of `short_straddle` and either pre-filter or annotate.

**What I tried:** `python -m pytest tests/test_short_strangle.py -v` → 12/12 pass.

**Next-commit suggestion:** `feat(p4.4.c): LongStrangle` — mirror of ShortStrangle with `side="BUY"` and `recommended_strategy_offset_pct = 1.0`. Same `strike_offset_pct` param. Load-bearing test: sign-mirror — ShortStrangle and LongStrangle on the same fixture produce opposite-sign gross_pnl (no slippage). Same trick as p4.4.a's LongStraddle.

After p4.4.c → `feat(p4.4.d): IronCondor` is the substantive one. **Iron condor has 4 legs**:
- SELL near-OTM CE + BUY far-OTM CE (call spread, capped loss to the upside)
- SELL near-OTM PE + BUY far-OTM PE (put spread, capped loss to the downside)

Two `strike_offset_pct`-like params: `inner_offset_pct` (~2%) for the SELL strikes, `outer_offset_pct` (~5%) for the BUY wings. Iron condor is **the asymmetric-strategy case where caveat #1 (strike-vs-spot margin basis) actually bites** — because the four strikes flank the spot at four different distances. This is where the BUILDER should land the `spot_at_entry`-based margin fix in `MarginModelV1.estimate(legs, *, spot_at_entry=None)`. Defaults preserve Tier-B behavior; when provided, use spot × shares × symbol_pct instead of strike × shares × symbol_pct.

---

## Review of 64775a9 — feat(p4.4.c): LongStrangle strategy + sign-mirror tests vs ShortStrangle

**Verdict:** ✅ accept

Clean mechanical mirror. Reuses `_pick_strangle_strikes` from short_strangle (one targeting rule, two strategies — same pattern as LongStraddle's reuse of `_pick_atm_strike`). `recommended_strategy_offset_pct = 1.0` per SPECS §4a (long-only).

Sign-mirror test pins SPECS §3a side_sign convention on the OTM-wing path: short -1500 ↔ long +1500 on CE 25→60, PE 30→1 (the losing-strangle direction).

9 new tests; 262/262 full suite.

**No new flags.** Same observations as adc7290 carry over (bhavcopy-query code now duplicated across both strangle modules + both straddle modules — 4 strategies' worth of near-identical code; a `chore(p4.4.refactor): shared strike-picking helper` after p4.4.d would be the natural cleanup point).

**Next-commit suggestion:** Unchanged — `feat(p4.4.d): IronCondor`. This is where:
1. The asymmetric-strategy case (4 legs at 4 different strike distances from spot) finally exercises caveat #1
2. The BUILDER lands the `spot_at_entry`-based margin fix as a kwarg on `MarginModelV1.estimate`
3. Two new params surface: `inner_offset_pct` (SELL strikes, ~2%) + `outer_offset_pct` (BUY wings, ~5%)
4. `recommended_strategy_offset_pct = 0.35` per SPECS §4a (biggest offset benefit of all v1 strategies)

Load-bearing tests: **(a)** spot-based margin reduces notional bias vs strike-based on this asymmetric structure; **(b)** the 4-leg P&L sums correctly (P&L of the call spread + P&L of the put spread); **(c)** max loss is bounded (by the gap between inner and outer strikes × shares); **(d)** all 4 strikes land on the bhavcopy's strike grid with the SPECS §5 lower-tiebreaker rule.

---

## Review of 85cbc0e — fix(p4.4.d.i): MarginModelV1 spot_at_entry kwarg — SPECS §4a caveat #1

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close caveat #1 (strike-vs-spot margin basis) before IronCondor lands — exactly where the bias first bites at the production layer.

**What works:**
- **Backward-compat preserved**: `spot_at_entry: float | None = None` default keeps strike-based math. Existing tests don't break; existing ad-hoc callers don't break either.
- **Sweeper passes spot_at_entry by default** ([src/engine/sweeper.py:1 line change](src/engine/sweeper.py)) — production sweeps automatically use the better basis. The migration shape is "opt-out via None" for the legacy code path, "opt-in via spot" for everywhere we know better.
- **`notional_basis: "spot" | "strike"` recorded in the breakdown** — Phase-5 ranker can audit which basis was used per result row. Self-describing data.
- **Validation**: `spot_at_entry > 0` when provided. Loud failure on garbage.
- **9 new tests** including an explicit asymmetric-iron-condor-shape demonstrating bias closure (strike-based ₹93,625 vs spot-based ₹91,000), and a symmetric-pair test pinning the zero-bias-at-ATM property.
- **Independently verified on the OTM short-put case I grilled at e7a9058**: 0.20 × 2000 × 250 = ₹100K (strike, biased) → 0.20 × 2600 × 250 = ₹130K (spot, matches real SPAN). 23% bias closed.
- 271/271 in full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **The "strike-based" default is still wrong-by-design for ad-hoc callers.** A user importing `MarginModelV1` from a Python REPL gets the strike-biased number unless they know to pass `spot_at_entry`. Flip the default to `spot_at_entry: float` (required) and let the few backward-compat tests update to pass it explicitly — would force every consumer to think about the basis. Defer; the sweeper-default already covers the production case, and tests are documentation.
- **No SPECS §4a amendment removing the caveat #1 callout.** §4a still lists it as an open simplification ("known v1 limitation"). Now that the fix is in code, the caveat text should be updated: "v1 default is strike-based for backward compat; sweeper passes spot_at_entry → production uses spot-based. Migration target: flip the default in v2." Cosmetic.
- **`base = float(spot_at_entry) if use_spot else float(leg["strike"])`** — one shared base across all SELL legs when `use_spot=True`. Correct for the SPAN model (one underlying notional per position). Different from per-leg strike basis (each leg's strike is independent). Worth a one-sentence callout in the docstring explaining why this is intentional, since it's a structural choice not a bug.

**Domain / correctness checks:**
- **SPAN math**: correctly uses spot × shares × pct as the basis. Matches NSE SPAN's "worst-case underlying price move" semantics.
- **Sign convention**: unchanged.
- **Look-ahead**: spot_at_entry is from entry_date's spot frame — point-in-time correct.

**What I tried:**
- `python -m pytest tests/` → 271/271.
- Re-ran the OTM short-put grilling case from e7a9058: strike → ₹100K, spot → ₹130K, bias direction confirmed.

**Next-commit suggestion:** `feat(p4.4.d.ii): src/strategies/iron_condor.py` (or `feat(p4.4.d): iron_condor` if the BUILDER doesn't split). 4-leg credit-spread strategy with:
- Two tunable params: `inner_offset_pct` (default 0.02, for the SELL strikes) + `outer_offset_pct` (default 0.05, for the BUY wings). Validate `outer > inner` AND both `> 0`.
- 4 legs in canonical order: SELL inner-OTM CE + BUY outer-OTM CE (call spread) + SELL inner-OTM PE + BUY outer-OTM PE (put spread).
- `recommended_strategy_offset_pct = 0.35` per SPECS §4a (biggest offset of any v1 strategy because both spreads bound each other).
- Strike picking via bhavcopy + SPECS §5 lower-tiebreaker.

Load-bearing tests: **(a)** 4 legs with correct sides + correct order in `legs_json`; **(b)** `inner_offset < outer_offset` enforced; **(c)** **MAX LOSS BOUNDED** — for a 1-lot iron condor on RELIANCE with inner=2%, outer=5%, the max loss at expiry is bounded by `(outer_strike - inner_strike - net_premium_received) × lot_size` per spread side. Test this by simulating a scenario where spot at exit is FAR outside both wings, assert the loss doesn't exceed the bound. **(d)** Margin uses spot-based notional via the now-default sweeper path — assert `margin_breakdown["notional_basis"] == "spot"` when called through `sweep_one`. **(e)** Sign convention: net P&L positive when spot stays between inner strikes at exit. The 4-leg P&L summation is the kernel's job, not the strategy's — but the strategy emits legs in correct sides so the kernel produces the right signed result.

---

## Review of a4aa27c — feat(p4.4.d.ii): IronCondor 4-leg strategy + max-loss-bounded pin

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land IronCondor as the 5th and most complex v1 strategy. 4 legs, two tunable params, bounded max loss is the defining property to pin in code.

**What works:**
- **All 5 load-bearing tests I asked for are present**: 4 legs in canonical order, `outer > inner` enforced (both strict-equal and degenerate-zero rejected), max-loss bounded, sweeper passes spot-based margin, credit-collected on the in-range exit.
- **Max-loss bound math correct**: ₹100 wing × 250 shares − ₹14,250 net credit = -₹10,750 max realized loss. The defining property of iron condor — capped tail — pinned in code via the far-OTM-blow-through scenario.
- **Sweeper integration test** (`test_sweep_one_iron_condor_uses_spot_based_margin`) pins `notional_basis == "spot"` end-to-end. **Caveat #1 fix is now exercised at the asymmetric-strategy layer where it bites.** Without this test, a future regression to strike-based could slip through unnoticed.
- **Canonical leg order** ([src/strategies/iron_condor.py:98-103](src/strategies/iron_condor.py#L98-L103)) — call spread (SELL inner + BUY outer) then put spread (SELL inner + BUY outer). Phase-5 can rely on `legs_json[0]` being the inner-call-SELL.
- **`recommended_strategy_offset_pct = 0.35`** per SPECS §4a — biggest offset benefit of any v1 strategy.
- **`out_params` records the both offsets** for Phase-5 filtering.
- 14 tests + 285/285 in full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Bhavcopy-query code duplicated for the FOURTH time** ([src/strategies/iron_condor.py:131-138](src/strategies/iron_condor.py#L131-L138)). Now urgent: `chore(p4.4.refactor): src/strategies/_strikes.py` should land before any further strategy work. The pattern is `(bhavcopy + symbol + expiry + CE/PE filter → sorted unique strike list)` repeated in short_straddle, short_strangle, long_straddle, long_strangle, iron_condor. Single helper takes (symbol, expiry, entry_date) and returns the strike list; pick_nearest() takes (strikes, target) and returns the strike. ~30 lines net savings.
- **Sparse-grid degenerate case** — when only ONE strike exists above spot, `inner_call == outer_call`. The call spread becomes "SELL X, BUY X" = zero P&L instead of a spread. Test passes (4 legs, correct sides), but the strategy silently degenerates. Worth one line: `if inner_call == outer_call: warnings.warn(...)` so an operator running on illiquid contracts sees the collapse rather than getting a confusing P&L.
- **`out_params = {"inner_offset_pct": inner, "outer_offset_pct": outer}`** drops other caller-supplied params — same issue noted on adc7290 and 64775a9. `{**params, "inner_offset_pct": inner, "outer_offset_pct": outer}` would preserve everything. Cosmetic.
- **No `recommended_inner_offset_pct` / `recommended_outer_offset_pct`** as class attributes — Phase-5 ranker can't query "what defaults does this strategy use?" without parsing the source. But strategy-specific tunables vary, so this isn't a registry-contract concern. Defer.

**Domain / correctness checks:**
- **Max loss math**: `(outer_strike - inner_strike) × shares − net_credit` is correct for a single-side blow-through. Both-sides blow-through (rare, requires gap moves) realizes the same bound on whichever side gets hit. ✓
- **Net credit** (received at entry): comes from SELL inner premiums > BUY outer premiums (closer-to-ATM = more premium). The strategy collects this credit; the kernel records it via the signed gross P&L summed across legs. ✓
- **Strike-vs-spot caveat #1**: now exercised. The 4 strikes flank spot at 4 different distances. With spot-based margin, all 4 legs use the same basis (spot × shares), eliminating the per-leg variation. Phase-5 ranking against other strategies is now apples-to-apples.
- **Sign convention**: 2 SELL legs + 2 BUY legs → engine's `side_sign` ensures each leg's contribution is correctly signed. The credit-collected test pins the "all 4 legs decay to ~0 → net = +entry_credit" semantic.

**What I tried:** `python -m pytest tests/test_iron_condor.py -v` → 14/14 pass. Read [src/strategies/iron_condor.py](src/strategies/iron_condor.py) end-to-end.

**Next-commit suggestion:** Per PLAN.md p4.5, `perf(p4.5): multiprocessing.Pool — preserves determinism`. **THE load-bearing concern for the entire phase**: byte-identical results regardless of `n_workers=1` vs `n_workers=4`. Specific risks:
1. **Pickling closures**: `today_fn=lambda: date(...)` won't survive `Pool.map`. Either bind today_fn at task-submission time (resolve to a date instance, not a callable), or document that the parallel path requires module-level functions for time-injection.
2. **Worker scheduling affects completion order**: results return in whatever-finished-first order from `Pool.imap_unordered` or in submission order from `Pool.map`. The `sort_values + reset_index` after `pd.concat` is the determinism backstop. Test must use `imap_unordered` to surface scheduling effects.
3. **Cache state per-process**: each worker process loads its own parquet on first touch — read-only, so safe. But the J_CACHE_DIR pickle cache from jugaad could have concurrent-write races if a worker hits a cache-miss; in practice cache should be warm before parallel runs.
4. **Skip log aggregation**: per-worker skip rows must be collected and persisted via a single `write_skips` call from the parent. Currently sweep_grid collects in a list during the loop — the parallel impl needs to gather from workers analogously.

The PAIRED `test(p4.5)` is: monkeypatch fetchers + load_spot + load_bhavcopy to deterministic fakes (so workers can't have non-deterministic data); run `sweep_grid(..., n_workers=1)` then `sweep_grid(..., n_workers=4, force=True)`; assert `pd.testing.assert_frame_equal(read1, read2)`. That single test is what proves SPECS §6c.3 determinism contract holds.

---

## Review of 8d49bf7 — chore(p4.4.refactor): extract _strikes.py — SPECS §5 picker in one place

**Verdict:** ✅ accept

Closes the refactor flag I've been raising since p4.4.b (ShortStrangle). Clean consolidation:

- **`_strikes.py` owns SPECS §5** in one place — `load_available_strikes()` + `pick_nearest()` + `NoLiquidStrikeError`. Adding a 6th strategy now means 2 lines instead of 12.
- **No more cross-module private imports** — long_straddle / long_strangle no longer reach into their short cousins' `_pick_*` private namespaces.
- **Backward compat preserved** via `NoLiquidStrikeError` re-export from `short_straddle` (sweeper + existing tests don't break).
- 11 new tests pin the helper's contract (filter, sort, dedup, tiebreaker, edge cases). 296/296 full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **`NoLiquidStrikeError` could move to `src/data/errors.py`** (the centralized error taxonomy per SPECS §8). Currently it's in a strategy submodule + re-exported — architecturally a touch off, since this error class is shared infrastructure not strategy-specific. Cosmetic.
- **`pick_nearest` docstring requires non-empty sorted-ascending input** but doesn't validate. `min([], ...)` raises `ValueError` if passed empty; unsorted input produces wrong tiebreaker. Single assert would close the gap. Cosmetic.
- **The two-step pattern `strikes = load_available_strikes(...); s = pick_nearest(strikes, t)`** could compress to one call. Defer — current shape lets callers reuse the strike list across multiple targets (iron condor needs 4 picks from one fetch), which would be lost in a single-call API.

**Domain / correctness checks:**
- **SPECS §5**: argmin distance + lower-strike tiebreaker, implemented exactly once via the `(abs(k - target), k)` tuple key.
- **Whole-rupee assumption**: `int(s)` silently truncates fractional strikes. Docstring acknowledges this. Fine for v1 OPTSTK universe.

**Next-commit suggestion:** Per PLAN.md, `perf(p4.5): multiprocessing.Pool — preserves determinism` next. The load-bearing details are already in the a4aa27c next-commit-suggestion above (pickling closures, scheduling vs sort_values backstop, per-process cache state, skip log aggregation). The PAIRED `test(p4.5)` runs `n_workers=1` vs `n_workers=4` and asserts `pd.testing.assert_frame_equal(read1, read2)` — that's the SPECS §6c.3 determinism contract proof.

---

## Review of bce31ac — docs(p4.4.refactor): update PLAN change log

**Verdict:** ✅ accept

Tiny docs commit recording three Phase-4 plan adjustments. The substantive one is **deferring p4.5 (multiprocessing.Pool) until after p4.verify**:

- **Reasoning**: small-grid verify (~60 tasks × ~100ms warm cache = ~6s) is fast enough serial; parallelization matters at ~30k-task final-report scale = Phase-6 concern.
- **Determinism contract not abandoned** — attached to the parallel impl whenever it lands, not to v1.
- **"Measure before optimizing"** is sound. The PLAN.md exit criteria of "5×12×5×5×5 = 7500 trades in < 10 min" is still in scope; just timeshifted.

The trade-off: at 30k tasks × 100ms = 50 minutes serial. So parallelization IS required eventually to meet the budget — just not before Phase 6 surfaces the actual scale. p4.5 stays in PLAN.md but is post-p4.verify, not blocking it.

**Next-commit suggestion:** `chore(p4.verify): live small sweep on RELIANCE × 3 months × 5 windows`. This is the Phase-4 milestone — the first multi-month dataset produced via the full pipeline. Load-bearing checks: (a) **determinism across repeat runs** (same inputs → same parquet via the `run_id` skip-on-cache path); (b) **RELIANCE Jan-2024 short straddle row matches the p3.verify number** (gross/costs/net/margin/ROI byte-identical when filtered to that one trade — proves Phase 4 doesn't drift from Phase 3); (c) **skip log populated** if any cells fail (visible to operator); (d) **notional_basis == "spot"** across every row (caveat #1 closure exercised on real multi-strategy data); (e) **timing measurement** — surface the actual cache-warm latency per task so the p4.5 deferral decision can be revisited with data.

---

## Review of f337208 — fix(bhavcopy_fo): bump NSEArchives timeout 4s → 30s

**Verdict:** ✅ accept

Small production-quality fix surfaced during the actual `chore(p4.verify)` run. jugaad's `NSEArchives` ships with `timeout=4s` — too aggressive for the archives endpoint at peak hours. Per-instance bump to 30s (matches the UDiff path's 60s order-of-magnitude budget).

**What works:**
- Per-instance override (`archives.timeout = 30`), NOT global monkeypatching of the class. Keeps the change scoped.
- Comment explains both the WHAT and the WHY (NSE archive intermittency, ZIP download size context). Future-reader sees the rationale.
- 30s is realistic-generous: ZIP is a few hundred KB; if it takes longer the network really is broken (legitimate failure).

**Blocking issues:** None.

**Non-blocking suggestions:**
- **Mutating `archives.timeout = 30` is a runtime side-effect**. If a future jugaad version makes `NSEArchives` a `frozen=True` dataclass, this silently breaks. Probably not — jugaad's pattern is regular classes — but worth one line of `assert hasattr(archives, "timeout")` as defense-in-depth. Cosmetic.
- **No test** — hard to test without mocking the underlying HTTP and simulating slow responses. Defer; the verify run is the de-facto smoke test.
- **`ReadTimeout` still propagates as `requests.RequestException`** (not wrapped in MissingDataError) per the wrap policy. Correct per the existing design — timeouts are transient/retryable, not "no data". Consistent.

**Domain / correctness checks:**
- **Wrap-policy boundary preserved**: timeouts still propagate to the caller, who decides retry semantics. Aligned with §6a class distinction.
- **Production realism**: NSE archives endpoint has been known to spike to ~10s response times during market open. 30s is the right budget.

**What I tried:** Read the diff. The fix is the minimal-correct change.

**Next-commit suggestion:** Resume `chore(p4.verify)`. The timeout fix unblocks the verify itself. The 5 checks from the prior next-commit suggestion still apply (determinism / Phase-3-cross-check / skip log / spot-basis / timing measurement).

---

## Review of 187ee67 — fix(results): canonical_column_order coerces dates + sweep_grid returns canonical shape

**Verdict:** ✅ accept

**Two coupled bugs caught by the verify run, one fix.** Exactly what the grilling-against-real-data pattern is for.

**Bug 1**: `sweep_grid`'s in-memory return frame had columns in `price_trade`'s dict-insertion order, but the persisted parquet had RESULTS_COLUMNS canonical order. So `assert_frame_equal(run_1_inmemory, run_2_cached_read)` would fail on column order — undermining the SPECS §6c.3 determinism contract at the read boundary.

**Bug 2**: `price_trade` returns date columns (`expiry`, `entry_date`, `exit_date`) as Python `datetime.date` objects (object dtype). `pd.DataFrame(rows)` preserves object dtype; parquet round-trips as object. Then `df["expiry"] == pd.Timestamp("2024-01-25")` **silently returns False** even when the row matches — pandas can't compare datetime64 to object. Phase-5 ranker would have shown empty results for any date-filter query.

**The fix**: new public `canonical_column_order(df)` in `src/engine/results.py` that:
1. Reorders to RESULTS_COLUMNS-first + extras-at-tail
2. Coerces the three date cols from object → `datetime64[us]` per SPECS §2.0

Both `write_results` AND `sweep_grid`'s return path call it, so the in-memory frame is byte-identical-shape to the parquet.

**What works:**
- **Pure function** (`.copy()` first, doesn't mutate caller's frame)
- **Coerces only object-dtyped date cols** — datetime64 columns pass through unchanged
- **`pd.to_datetime(...).astype("datetime64[us]")`** preserves the §2.0 microsecond-unit convention
- 1 new test pins the dtype invariant with the explicit `pd.Timestamp filter now matches 1 row` assertion — the test specifically catches the silent-filter-miss class.
- 297/297 in full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
- The fix is the minimal correct shape. No flags.

**Domain / correctness checks:**
- **Schema integrity**: in-memory frame and persisted parquet now byte-identical-shape. Determinism contract holds at the read-back boundary.
- **Filter semantics**: `pd.Timestamp` filters now correctly match — load-bearing for Phase-5 ranker queries like "all RELIANCE Jan-2024 trades".
- **SPECS §2.0 compliance**: date cols are now `datetime64[us]` consistently.

**What I tried:** Read the diff. The test's explicit `(normalized["expiry"] == pd.Timestamp("2024-01-25")).sum() == 1` assertion is the right shape — pins the user-visible behavior, not just the dtype.

**Next-commit suggestion:** Resume `chore(p4.verify)` — already in flight per the next-commit notification. The fix unblocks the determinism check.

---

## Review of 9323936 — chore(p4.verify): live small sweep — first multi-cell dataset

**Verdict:** ⚠️ accept-with-followups — **PHASE 4 IS FUNCTIONALLY DONE**, but **grilling caught a real annualization bias for short-window trades** that will mislead Phase-5 ranking.

**What works (the milestone):**
- **Independent live run reproduced byte-identical** to the BUILDER's reported output: 18 cells, 0.53s cold compute (30ms/cell warm), 0.002s on the cache-hit repeat.
- **All 5 load-bearing checks green**:
  - Determinism: `assert_frame_equal(run1, run2_cached)` passes
  - Phase-3 cross-check: RELIANCE Jan-25 T-15→T-1 row matches p3.verify EXACTLY (entry_spot ₹2596.65, gross +562.25, net +422.57, etc.)
  - Skip log: 0 skips on this conservative grid
  - notional_basis == "spot" on every row (caveat #1 closure exercised on real multi-cell data)
  - Timing extrapolation: 30k tasks ≈ 15 min serial → confirms p4.5 deferral was sound
- 18 trades produced; sortable, parquet-backed, ready for Phase-5 ranking and Phase-6 visualization

**REAL BIAS CAUGHT — roi_pct_annualized inflates short-window ROIs:**

| Cell | hold_calendar | hold_trading_days (formula) | hold_trading_days (true) | roi_pct | roi_pct_annualized (computed) | roi_pct_annualized (true) |
|---|---|---|---|---|---|---|
| Jan-25 T-5→T-3 | 2 days | round(2 × 252/365) = **1** | **2** | 5.54% | **1395.81 %/yr** | 698 %/yr |
| Jan-25 T-5→T-1 | 6 days | round(6 × 252/365) = **4** | **4** | 5.72% | 360.41 %/yr | 360.36 %/yr |
| Mar-28 T-5→T-1 | 6 days | round(6 × 252/365) = **4** | **4** | -8.31% | -418.84 %/yr | -523.53 %/yr |

The 252/365 calendar-to-trading-day conversion (introduced in 169c7d6 to avoid a `trading_calendar` import on the hot path) is **fine for long windows** (20 calendar → 14 trading days, exact) but **fails on short ones** because `round(1.38) = 1` (off by 50%).

For Jan-25 T-5→T-3, the formula doubles the apparent annualized return: **1395%/yr displayed vs ~698%/yr if computed against true trading days**. Phase-5 ranker sorting by `roi_pct_annualized` will systematically favor 2-day-hold trades over longer holds at the same daily rate — exactly the failure mode caveat #2 was supposed to prevent.

**The fix** (recommend before Phase 5):
- Use `trading_calendar.trading_days(entry_date, exit_date)` and `len(...)` (or count - 1 for "days held") as `hold_trading_days`
- Exact, no approximation
- Adds a `trading_calendar` import to `engine/pnl.py` but the import is already in `engine/sweeper.py` — same module-graph already-paid cost
- ~5 lines + a regression test pinning Jan-25 T-5→T-3 → exactly 2 trading days

**Blocking issues:** None for Phase 4 itself; the bias affects Phase 5 ranking semantics, not Phase 4 data correctness.

**Non-blocking suggestions:**
- The ROI table at the bottom of the verify output is the user's first preview of cross-window patterns. Worth surfacing the bias caveat there too: "roi_pct_annualized uses 252/365 calendar-to-trading approximation; very-short-window numbers can be inflated by up to 2×".
- 15-of-18 trades profitable (83% win rate) is a small-N preview; Phase-5 will compute meaningful aggregates. The HEADLINE number worth knowing: short straddles on RELIANCE in this 3-month window AVERAGED positive ROI even with slippage. Phase-5 may reveal whether that's just Q1-2024 (low-vol regime) or a robust pattern.

**Domain / correctness checks:**
- **Determinism:** ✓ verified.
- **Phase-3 byte-cross-check:** ✓ verified — engine doesn't drift across the sweeper boundary.
- **Spot-based margin:** ✓ verified on every row.
- **Caveat #2 (annualized ROI):** ❌ **biased for short windows** — see the table above. Was closed in 169c7d6 with the 252/365 approximation; the bias is now visible in real data.

**What I tried:**
- `python scripts/verify_p4.py` independently → byte-identical to BUILDER's reported run.
- Hand-derived hold_trading_days for the canonical Jan-25 T-5→T-3 case → got 2 (true) vs 1 (formula) → 2x annualization bias confirmed.

**Next-commit suggestion:** **`fix(p4.verify.a): hold_trading_days uses trading_calendar.trading_days() exact count, not 252/365 calendar approximation`**. The bias is small for hold ≥ 7 trading days but >2× for 1-3 day holds. Phase-5 will rank thousands of cells by `roi_pct_annualized`; a 2× bias on the short-window subset will pollute the leaderboard. Fix the formula now while it's contained to one module. After: Phase 5 (aggregation + trend analytics) is unblocked.

---

## Review of 06bb5e7 — fix(p4.verify.a): hold_trading_days exact via offset_td subtraction

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close the annualization bias I flagged on 9323936. Use exact trading-day hold (`entry_offset_td - exit_offset_td`) when the sweeper has it; preserve the 252/365 approximation for standalone callers.

**What works:**
- **Cleanest possible fix architecturally**: `entry_offset_td − exit_offset_td` IS exact by construction (both offsets measured against the same expiry's trading calendar). No new module imports; just thread one int through the kernel kwarg.
- **Backward-compat preserved**: `hold_trading_days: int | None = None` keeps the approximation for ad-hoc callers; sweeper opts in to the exact value.
- **Independent verify reproduced exactly**:
  | Cell | Before | After | Reason |
  |---|---|---|---|
  | Jan-25 T-5→T-3 | 1395.81 %/yr | **697.91 %/yr** | Approx gave 1 td; exact 2 td → halved |
  | Feb-29 T-5→T-3 | 243.95 %/yr | **365.92 %/yr** | Approx OVER-estimated (3 td); exact 2 td → goes UP |
  | Mar-28 T-5→T-3 | 198.91 %/yr | **99.45 %/yr** | Halved |
  | Mar-28 T-5→T-1 | -418.84 %/yr | **-523.55 %/yr** | Approx 5 td; exact 4 td → worse |
  | Jan-25 T-15→T-1 (canonical) | 5.47 %/yr | **5.47 %/yr** | Unchanged — 14-td approximation was already exact for 20-calendar-day hold |
- **Bias was both-directional** — the approximation could either round up or down vs true. Some cells got better, some worse. Now correct everywhere via the offset arithmetic.
- 2 new tests pin the contract: `test_hold_trading_days_kwarg_overrides_calendar_approximation` in test_pnl shows the 2× inflation directly (kwarg=2 vs approx=1 on Wed→Fri); `test_sweep_one_hold_trading_days_is_exact_offset_difference` pins that the sweeper threads the exact value through.
- 299/299 in full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **The 18-cell verify output shifted across the board** (not just decreases on short windows). Worth a one-line note in the verify script: "Note: roi_pct_annualized values shifted from the prior run after fix(p4.verify.a). This is correction of the calendar-day approximation bias, not regression." For someone diffing run-to-run the difference would otherwise look like silent drift.
- **`entry_offset_td > exit_offset_td` validation** is already in sweep_one ([src/engine/sweeper.py:94-101](src/engine/sweeper.py#L94-L101)), so `entry_offset_td - exit_offset_td` is always positive. Safe.
- **Standalone callers still get the biased approximation** by default. Defensible (backward compat) but a future Phase-5 ranker that bypasses sweep_one and calls price_trade directly would be silently biased. Worth either: (a) flipping the default to require `hold_trading_days` and let standalone callers pass `None` explicitly for the approximation; OR (b) a SPECS §4a callout that standalone callers SHOULD pass the kwarg. Cosmetic.

**Domain / correctness checks:**
- **Annualization arithmetic** is now exact wherever the sweeper drives the pipeline (= every production code path).
- **`max(1, int(hold_trading_days))`** clamps to 1 — protects against pathological 0 input. Defensive.
- **Phase-5 ranker** can now sort by `roi_pct_annualized` without short-window inflation.

**What I tried:**
- `python -m pytest tests/` → 299/299.
- `python scripts/verify_p4.py` → reproduced byte-identical output, walked the math for 4 representative cells to confirm both directions of bias correction.

**Caveat status summary (Phase 4 closes):**
- ✅ #1 (strike-vs-spot margin) — closed in 85cbc0e, exercised at IronCondor in a4aa27c
- ✅ #2 (annualized ROI) — closed in 169c7d6 + b4fea19 (formula), now exact in 06bb5e7 (no approximation bias)
- ✅ #3 (uniform 20% margin) — closed in Tier-B cluster
- ✅ #4 (multi-leg conservatism) — closed in Tier-B cluster
- ✅ Slippage gap — closed in 45541e0
- ✅ Lot-size hardcoding — closed in bdcdf2c

**All Phase 3.5 + Phase 4 grilling-surfaced caveats now closed in code.** Phase 5 ranker can trust the dataset.

**Next-commit suggestion:** **Phase 5 — `feat(p5.1): per-stock × strategy summary stats (mean, median, win-rate, max-DD, sample N)`**. The aggregation + ranking layer. Now that the underlying data is honest (slippage applied, margin spot-based, ROI exactly annualized, lot-size historical), the ranker can produce reliable cross-strategy comparisons. Load-bearing concerns: (1) **Statistical honesty** — surface sample N alongside every percentile; refuse to rank a strategy with N<5 (the user wanted "no cherry-picked windows"); (2) **Survivorship-bias disclaimer** still load-bearing from §6b.3; (3) **The annualization fix matters most here** — Phase-5 will sort/filter by `roi_pct_annualized` and the now-exact values will produce trustworthy rankings.

---

## Review of f8d0df0 — feat(p5.1): per-stock × strategy summary stats from sweep parquet

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the first Phase-5 aggregator. Group by `(strategy, symbol)`, emit canonical summary stats. Statistical-honesty contract: surface N, don't filter small samples silently.

**What works:**
- **`SUMMARY_COLUMNS` canonical schema** ([src/analytics/aggregate.py:24-48](src/analytics/aggregate.py#L24-L48)) — 12 columns covering identity, sample size, P&L, ROI (holding + annualized), and per-trade extremes.
- **`MIN_N_FOR_RANKING = 5` exported as module constant** ([src/analytics/aggregate.py:57](src/analytics/aggregate.py#L57)) — pattern is transparency-over-silent-filtering. Aggregator does NOT drop small-N rows; consumers filter via `.query("n_trades >= MIN_N_FOR_RANKING")`. **Exactly the user's "no quiet filtering" preference matches the SPECS §6b.3 survivorship discipline.**
- **`empty_summary_frame()`** with canonical schema ([src/analytics/aggregate.py:60-63](src/analytics/aggregate.py#L60-L63)) — downstream `.groupby` won't KeyError on empty input.
- **Required-column validation raises ValueError with helpful diagnostic** ([src/analytics/aggregate.py:89-95](src/analytics/aggregate.py#L89-L95)) — same loud-failure pattern as `results.write_results`.
- **Deterministic sort by `(strategy, symbol)`** ([src/analytics/aggregate.py:137](src/analytics/aggregate.py#L137)).
- **Verified live**: on the real p4.verify 18-row dataset, produces sensible aggregates (single (RELIANCE, short_straddle) row with N=18, win%=83.3, median annualized +247.9%/yr).
- 11 new tests; 310/310 in full suite.

**Blocking issues:** None.

**Non-blocking suggestions (Phase 5.5 ranker will need these):**

1. **No dispersion metric** (`std_roi_pct`, `std_net_pnl`). Phase-5.5 ranker that wants risk-adjusted comparison (Sharpe-like = mean / std) can't compute it from this summary. Worth adding before p5.5 lands — same module, ~4 lines.

2. **No `total_net_pnl`** column for aggregate strategy P&L ("this strategy made ₹X across all trades"). Cosmetic; user might want it in the UI.

3. **`worst_roi_pct` labeled implicitly as max DD** in the docstring ("the natural 'max drawdown' for a per-trade dataset") — but it's actually "worst single-trade ROI", which is a different metric from path-dependent max-DD. The latter is a Phase-6 concern (needs trade ordering). The current name is fine; just worth being explicit that `worst_roi_pct` ≠ traditional max-DD.

4. **`win_rate_pct = 100 × (net_pnl > 0).sum() / n`** uses strict `>` — exactly-zero trades count as losses. Defensible (a zero-P&L trade is no win) but worth a SPECS note for the user's mental model.

5. **No groupby keys other than (strategy, symbol)** — Phase-5 PLAN specifies a separate p5.2 for (entry_offset, exit_offset) heatmap, p5.3 for year-over-year decay, p5.4 for month-of-year seasonality. Each will need its own aggregator. The pattern is fine — multiple specialized aggregators rather than one generic one.

**Domain / correctness checks:**
- **Statistical honesty:** ✓ N surfaced; aggregator transparent; MIN_N_FOR_RANKING is a guideline not a filter.
- **Annualization:** uses the now-exact `roi_pct_annualized` from the 06bb5e7 fix. Phase-5 ranking won't be polluted by the prior calendar-day bias.
- **Survivorship:** the SPECS §6b.3 caveat still applies — Phase-6 UI needs to render the survivorship disclaimer alongside any leaderboard derived from this.

**What I tried:**
- `python -m pytest tests/` → 310/310.
- Loaded the p4.verify parquet through `summarize_by_stock_strategy` — got a sensible single-row summary. Required-column validation fires correctly. Empty-input returns the canonical schema.

**Next-commit suggestion:** Per PLAN.md, `feat(p5.2): entry/exit heatmap matrix — avg P&L by (entry_offset, exit_offset)`. This is the dataset that turns into Phase-6's visualization — for each `(strategy, symbol)`, pivot by `(entry_offset_td, exit_offset_td)`; cell values = mean (or median) of some metric (net_pnl, roi_pct, roi_pct_annualized). Load-bearing decisions: **(1)** pivot value should default to `median_roi_pct_annualized` (robust to outliers, cross-window-comparable); **(2)** NaN cells for missing combinations (no false implication of zero P&L); **(3)** same `MIN_N_FOR_RANKING` applies per-cell (a heatmap cell with N=1 should be visually distinguishable from N=10 in Phase-6's render); **(4)** API shape: `pivot_window(results_df, strategy, symbol, *, value_col="roi_pct_annualized", aggfunc="median") -> pd.DataFrame` (index=entry_offset_td desc, columns=exit_offset_td desc). Or one big multi-level frame the consumer can slice. Either works; the BUILDER's call.

---

## Review of 5bd9145 — feat(p5.2): (entry_offset × exit_offset) heatmap pivot

**Verdict:** ✅ accept

**What works:**
- **Dual-function pattern**: `pivot_window(value_col, aggfunc)` + `pivot_counts()`. Same shape. Consumers compose `v.where(n >= MIN_N_FOR_RANKING)` to mask thin-sample cells. Same transparency-over-silent-filtering pattern as p5.1.
- **Defaults match my prior suggestion**: `value_col="roi_pct_annualized"` (cross-window-comparable) + `aggfunc="median"` (robust to outliers).
- **Sort orientation**: T-15 at top, T-1 at bottom for rows; T-3 left, T-1 right for cols. Matches "furthest back at top, expiry at right" visual convention.
- **Missing combos**: NaN in values (no false zero coloring), 0 in counts (accurate "no trades"). Both consistent with the SPECS schemas.
- **`strategy`/`symbol` can be None** for aggregated views — useful for "all strategies on this stock" or "this strategy across the universe".
- **Empty result returns empty DataFrame** (no fake zero-filled grid).
- 15 new tests + 325/325 in full suite.

**The Q1-2024 preview is the first real cross-window pattern surfaced**:
```
              exit=3    exit=1
entry=15:     113.5%    253.6%   ← hold to expiry pays better
entry=10:     253.4%    250.1%
entry=5 :     365.9%     89.1%
```
**Critical**: that 365.9% at (entry=5, exit=3) would have been **1395.81%** before the 06bb5e7 annualization fix. Phase-5 visualizations are only trustworthy because the underlying caveats were closed. The grilling loop pays off here visibly.

**Blocking issues:** None.

**Non-blocking suggestions:**
- **No `pivot_dispersion` / `pivot_std`** — Phase-6 might want to visualize "consistency" (low-std cells more reliable than high-std at the same median). Same shape, ~10 lines. Adds Sharpe-readiness to the heatmap too.
- **`MIN_N_FOR_RANKING` not re-exported** from heatmap.py — consumers must import from `aggregate.py`. Either re-export here OR move the constant to a shared `src/analytics/_constants.py`. Cosmetic.
- **`aggfunc: str`** — pandas accepts callables too; type hint precludes. `Callable | str` for max flexibility. Cosmetic.

**Domain / correctness checks:**
- **Statistical honesty**: surfaced via `pivot_counts`. Phase-6 can render thin-sample cells differently (hatched / desaturated).
- **Annualization**: uses the 06bb5e7-exact `roi_pct_annualized` — cross-window rankings now trustworthy.
- **Per-cell aggregation**: median across multiple expiries for the same (entry, exit) window — natural smoothing.

**What I tried:**
- `python -m pytest tests/` → 325/325.
- Mental walkthrough of the Q1-2024 preview — economically plausible (held to T-1 pays more because more time decay captured; short-hold + early-close was lucky; short-hold + held-to-expiry got caught by late move).

**Next-commit suggestion:** Per PLAN.md, `feat(p5.3): year-over-year trend (is strategy X decaying?)`. Aggregator that groups by `(strategy, symbol, year)` and emits the time-series. The decay question is real — implied vol regimes differ by year (2019 vs 2024). Load-bearing: surface N per year too; a 1-trade year shouldn't drive a "decaying" narrative. Same MIN_N_FOR_RANKING discipline. After p5.3 → p5.4 (month-of-year seasonality), p5.5 (the actual ranker). Each gets a small specialized aggregator function. Phase-6 then visualizes whatever the user picks.

---

## Review of a5e5bbb — feat(p5.3): summarize_by_year — year-over-year trend aggregator

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the year-over-year aggregator. Group by `(strategy, symbol, year)` so consumers can answer "is short_straddle on RELIANCE decaying year by year?". Refactor common stat-aggregation logic out of p5.1 into a shared `_summarize` helper so p5.4 (month) lands as a thin wrapper.

**What works:**
- **Clean `_summarize` extraction** ([src/analytics/aggregate.py:117-189](src/analytics/aggregate.py#L117-L189)) — takes `group_keys` + `canonical_columns`, validates required columns, handles empty input, builds rows, normalizes dtypes, sorts deterministically. One body now feeds both p5.1 and p5.3 (and p5.4 once it lands). Refactor preserves all 11 prior p5.1 tests bit-identical.
- **`YEARLY_SUMMARY_COLUMNS = ("strategy", "symbol", "year") + SUMMARY_COLUMNS[2:]`** ([src/analytics/aggregate.py:79-83](src/analytics/aggregate.py#L79-L83)) — schema sharing via tuple concatenation. One source of truth: if p5.5 adds a column to SUMMARY_COLUMNS, YEARLY inherits automatically.
- **Year derived from `expiry.year`** ([src/analytics/aggregate.py:217](src/analytics/aggregate.py#L217)) — semantically aligned with "the year this trade settled". Not entry_date which is a mechanic (a Dec-2023 entry into a Jan-2024 expiry belongs to 2024 for the YoY plot, which is the natural reading of the trade).
- **Missing-`expiry`-column guard** ([src/analytics/aggregate.py:206-210](src/analytics/aggregate.py#L206-L210)) — fires before the helper, so the error message names the right caller.
- **`empty_yearly_summary_frame()`** preserves canonical schema for zero-row sweeps — same downstream-KeyError defense as p5.1.
- **`dropna=False`** in groupby ([src/analytics/aggregate.py:152](src/analytics/aggregate.py#L152)) — defensive; nothing currently produces NaN years (expiry is enforced datetime64 by canonical_column_order), but the discipline matches.
- **Cast text grouping keys to StringDtype** ([src/analytics/aggregate.py:148-150](src/analytics/aggregate.py#L148-L150)) — stable groupby output, avoids categorical/object dtype churn.
- **Test `test_yearly_decay_visible_as_descending_median_roi`** uses a synthetic 3-year fixture to pin monotonic decay — exactly the shape Phase-6's decay plot will render.
- 9 new tests; 334/334 in full suite.

**Blocking issues:** None.

**Non-blocking suggestions:**
1. **Real verify dataset only contains Q1 2024** so YoY collapses to a single 2024 row (n=18, median annualized = 247.9%/yr). BUILDER acknowledges this in the commit body. The aggregator's shape is correct; the trend question literally needs a multi-year sweep to exercise. Phase-7+ when historical-bhavcopy ingestion expands the dataset.
2. **`year` as `int64`** is fine, but Phase-6 plot axes will need to render as "2022, 2023, 2024" not "2,022.0" — UI's job.

**Domain / correctness checks:**
- **Statistical honesty:** ✓ N surfaces per year; helper doesn't drop thin-sample years. Consumers filter via `df.query("n_trades >= MIN_N_FOR_RANKING")` at render time.
- **Annualization:** uses the 06bb5e7-exact `roi_pct_annualized` — comparing 2022 (15-day holds) to 2024 (5-day holds) won't be polluted by the prior calendar-day bias.
- **Time-bin convention:** expiry-year is the right load-bearing choice. Same convention will need to hold in p5.4 for month.

**What I tried:**
- `.venv/bin/python -m pytest tests/test_aggregate.py -v` → 28/28 (incl. 9 new yearly tests).
- Loaded the p4.verify parquet (18 rows, Q1 2024) through `summarize_by_year` — got a single 2024 row with `n_trades=18, win_rate=83.3%, median_roi_pct_annualized=247.9%/yr`. Schema = canonical YEARLY_SUMMARY_COLUMNS.
- Mental walkthrough of `_summarize`: required-keys union (`group_keys ∪ {net_pnl, roi_pct, roi_pct_annualized}`) is correct — caller-specific keys (year/month) checked alongside the metric columns.

**Next-commit suggestion:** Per PLAN.md → `feat(p5.4): month-of-year seasonality`. Third caller of `_summarize`; group by `(strategy, symbol, month)` where month is the calendar month of `expiry` (1..12, aggregating across years). Answers the orthogonal-to-decay question: "is Feb a better month for short straddles than Nov?". Load-bearing: sort ascending by month (natural left-to-right reading order); same MIN_N_FOR_RANKING discipline. The `_summarize` refactor in this commit makes p5.4 ~10 lines of net new code, which is the point of the refactor.

---

## Review of d982bf7 — feat(p5.4): summarize_by_month — calendar-month seasonality aggregator

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Third caller of `_summarize`. Group by `(strategy, symbol, month)` where `month = expiry.month` (1..12) aggregating across years — the orthogonal-to-decay seasonality question. Confirms the `_summarize` refactor pays off: p5.4 adds 59 lines net vs. p5.3's 138.

**What works:**
- **Mirrors p5.3 structure** ([src/analytics/aggregate.py:224-254](src/analytics/aggregate.py#L224-L254)) — same expiry-column guard, same `df = results_df.copy()` + `pd.to_datetime(df["expiry"]).dt.month.astype("int64")` derivation, same delegation to `_summarize`. Refactor lands as designed.
- **`MONTHLY_SUMMARY_COLUMNS`** shares `SUMMARY_COLUMNS[2:]` with YEARLY — one source of truth, additions to SUMMARY auto-propagate.
- **Sort ascending by month** (1..12) ([src/analytics/aggregate.py:189](src/analytics/aggregate.py#L189) via `_summarize`'s deterministic group-key sort) — natural left-to-right reading order for Phase-6's seasonality bar chart. Different from p5.3's ascending year (which is also chronological), so the pattern is consistent: time-ordered axes use natural calendar order.
- **Real-data preview is the first credible seasonality signal**:
  - Jan: 83% wins, median annualized +251.78%/yr
  - Feb: **100% wins**, median annualized +269.25%/yr (best month)
  - Mar: 67% wins, median annualized +106.46%/yr (weakest)
  - All three months have n=6 trades (matches the 6 entry-offset × 1-exit-offset cells from the verify sweep) — meeting MIN_N_FOR_RANKING=5 by exactly 1, so the signal is barely-actionable but the shape is honest.
- 8 new tests + 342/342 in full suite.

**Caveat on the n=6 Feb=100% signal**: with `n=6` and a single observed win rate of 100%, the 95% binomial CI is roughly [54%, 100%] — i.e. Feb being "perfect" is consistent with anything from "slightly better than coin flip" to "actually perfect". The aggregator surfaces this honestly (n=6 surfaces), but Phase-6 visualization should not render Feb as a confident "best month" call until the dataset spans more years. This is the same MIN_N_FOR_RANKING discipline applied to month-of-year — the right consumer behavior, not an aggregator bug.

**Blocking issues:** None.

**Non-blocking suggestions:**
1. **No `month_name`/string month column** — Phase-6 plot will want "Jan/Feb/Mar" not "1/2/3" on the x-axis. Cosmetic; UI's job to map.
2. **Aggregation folds across years** ([src/analytics/aggregate.py:228-233](src/analytics/aggregate.py#L228-L233) docstring) — January 2022 + January 2023 + January 2024 all land in `month=1`. Correct for seasonality, but it does mean that if a strategy was tested ONLY in Q1-2024 (like the current verify parquet), `summarize_by_month` and `summarize_by_year[year=2024]` differ only by row count, not information content. Phase-6 should be aware: month seasonality is most informative on multi-year sweeps.
3. **No "month × year" cross-tab** — true seasonal decay (is Feb still the best month in 2024 like it was in 2022?) needs both axes. Phase-5 doesn't have to land this; could be a Phase-6 visualization that pivots `summarize_by_year` filtered to a specific month, or a future p5.4b two-key version.

**Domain / correctness checks:**
- **Convention:** ✓ `expiry.month` (semantic month-of-trade), same as p5.3's year. Consistent.
- **Statistical honesty:** ✓ N surfaces per month.
- **Annualization:** ✓ uses exact `roi_pct_annualized`.

**What I tried:**
- `.venv/bin/python -m pytest tests/test_aggregate.py -v` → 36/36 (incl. 8 new monthly).
- Loaded the p4.verify parquet through `summarize_by_month` — got 3 rows (Jan/Feb/Mar 2024 collapsed across years since dataset is single-year). Real values match the commit-message preview exactly: Jan=251.78%/yr, Feb=269.25%/yr, Mar=106.46%/yr.
- Mental walkthrough: Feb-best is consistent with the verify-period RELIANCE chart — Feb 2024 had a sleepy 2-week range, ideal for short straddle. Mar had the March-correction wobble (Lok Sabha buildup) — wider realized vol, more losses.

**Next-commit suggestion:** Per PLAN.md → **`feat(p5.5): rank — the ranker over (strategy, symbol) tuples`**. Aggregator infrastructure is now complete (per-pair + per-year + per-month). p5.5 composes them into a leaderboard. Load-bearing design decisions:
1. **Primary key**: rank by `median_roi_pct_annualized` (robust to outliers, cross-window-comparable) — but expose a `metric` parameter so consumers can sort by `mean_net_pnl`, `total_net_pnl`, `win_rate_pct`, etc.
2. **Filter pre-ranking** via `n_trades >= MIN_N_FOR_RANKING` — but **surface filtered-out rows separately** (a "low-N tail" view), not just silently drop them. The user's pref is transparency-over-silent-filtering, which means the ranker should report "ranked: X strategies, suppressed-as-thin-sample: Y strategies".
3. **Risk-adjusted sort** — if Sharpe-like ranking is wanted, need `mean / std`. Currently the aggregator emits `mean_roi_pct` and `median_roi_pct` but no `std_roi_pct`. **The p5.1 reviewer-flagged std addition is now a p5.5 blocker** — either land it as a small p5.4.5 commit OR p5.5 lands both together. Personal lean: small dedicated `chore(p5): add std_roi_pct + total_net_pnl` first, then p5.5 is just the sort/filter logic.

---

## Review of afdd56e — chore(p5): add std_roi_pct + total_net_pnl to summary schema

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Carry over the reviewer-flagged dispersion + aggregate-P&L columns from p5.1 review. Pre-p5.5 prep so the ranker has the columns it needs to compute Sharpe-like sorts.

**What works:**
- **Responsiveness to prior feedback** — addresses two of my non-blocking suggestions from p5.1 review (3137a42) before p5.5 lands. BUILDER spotted the dependency without me needing to flag it as a blocker on p5.4.
- **Three columns added in canonical positions** ([src/analytics/aggregate.py:24-53](src/analytics/aggregate.py#L24-L53)):
  - `total_net_pnl` placed between `median_net_pnl` and the ROI block — aggregate-P&L grouped with per-trade P&L. Clean.
  - `std_roi_pct` placed after `median_roi_pct` — mean/median/std together for the holding-period ROI block.
  - `std_roi_pct_annualized` placed after `median_roi_pct_annualized` — same pattern for the annualized block. Symmetric.
- **YEARLY/MONTHLY inherit automatically** via the `SUMMARY_COLUMNS[2:]` sharing pattern — no parallel edits required. The refactor in a5e5bbb pays off again.
- **`ddof=0` (population std) with a written rationale** ([src/analytics/aggregate.py:161-163,173,176](src/analytics/aggregate.py#L161-L163)) — a single-trade group gets `std=0` not NaN. NaN would break any `sort_values(by="std_roi_pct")` ranking in p5.5; semantically, an n=1 sample has zero observed variation, which is correct for the observed-sample interpretation.
- **Hand-derived test value** in `test_std_roi_pct_computed_with_ddof_zero` — `[1,2,3]` → `sqrt(((1-2)² + (2-2)² + (3-2)²) / 3) = sqrt(0.6667) ≈ 0.8165`. Pinned to 1e-6, exact for the formula. **And** the annualized variant pinned at 9.7980 (= 0.8165 × 12), which double-checks the linear-scaling relationship between holding-period and annualized stds when the annualizer is a constant.
- 5 new tests + 347/347 in full suite.

**Blocking issues:** None.

**Non-blocking caveats — worth the user knowing for the p5.5 ranker design:**

1. **ddof=0 vs ddof=1 trade-off**: pandas' default (and the conventional "sample standard deviation") is ddof=1. The BUILDER chose ddof=0 to avoid NaN-poisoning the ranker. For n=5, ddof=0 std is ~80% of ddof=1 std; for n=20 it's ~97.5%. **Implication**: small-sample groups will look ~20% "tighter" than they really are (in the unbiased-population-estimator sense). For the user's mental model: **the std column is the observed dispersion in the sample, not an estimate of the strategy's true population variance.** For ranking purposes (relative comparison across strategies with similar n), this is fine — the bias is roughly equal across rows. For absolute interpretation ("is this strategy's std *really* 5%?"), the user should treat it as a lower bound.

2. **Sharpe-like ratio readiness**: with `mean_roi_pct_annualized / std_roi_pct_annualized` now computable, p5.5 can offer a risk-adjusted sort. **Domain caveat**: this is a Sharpe-like ratio, NOT a real Sharpe ratio — true Sharpe requires (excess-return over risk-free) / std. For Indian markets the risk-free is ~6.5% annualized. The user can either:
   - Subtract 6.5% from `mean_roi_pct_annualized` before dividing (real Sharpe)
   - Use raw return / std (Sharpe-like, what the column supports today)
   Either is defensible; the difference is small for high-ROI strategies (170%/yr − 6.5% ≈ 163%/yr; division by std barely shifts). Worth a p5.5 design note.

3. **`total_net_pnl` is a SUM, not a compound return** — important for the user's mental model. If the operator runs 18 separate trades of 1 lot each (the verify dataset), `total_net_pnl = ₹124,613` is "if you executed all 18, your aggregate P&L". It does NOT account for capital-allocation efficiency (1 trade at a time vs 18 in parallel vs rolling capital). For SPECS §4a Phase-7 "compound returns over time" the user would need a separate calc that tracks margin-blocked-at-once.

**Domain / correctness checks:**
- **Statistical honesty:** ✓ MIN_N_FOR_RANKING discipline unchanged. New columns surface alongside n_trades — operator can spot "n=2 with std=0.0001" and discount it.
- **ddof choice:** documented in code; the rationale (n=1 → 0 instead of NaN) is a defensible product decision given the ranking use case. Approving with the caveats above.
- **Live verify on the p4.verify parquet** (18-row Q1-2024 RELIANCE short_straddle):
  - `total_net_pnl = ₹124,613.31` (sum of 18 trades; matches my hand-sum of the parquet's `net_pnl` column)
  - `std_roi_pct = 5.83%` on `mean_roi_pct = 4.58%` — Sharpe-like ≈ 0.79 (holding-period)
  - `std_roi_pct_annualized = 242.97%` on `mean_roi_pct_annualized = 166.05%` — Sharpe-like ≈ 0.68 (annualized)
  - The two Sharpe-likes differ (0.79 vs 0.68) because annualizing is non-linear when individual trades have different hold lengths — `mean(annualized)` ≠ `mean(holding) × annualizer`. Worth noting in p5.5: prefer one or the other consistently for cross-strategy ranking; mixing them is an apples-vs-oranges hazard.

**What I tried:**
- `.venv/bin/python -m pytest tests/` → 347/347.
- Inspected `_summarize` body — both std calls explicit `ddof=0`. No accidental ddof=1 anywhere.
- Cross-checked the schema position changes — `total_net_pnl` precedes the ROI block (matches the "P&L grouped together" reading); `std` follows `median` in both ROI blocks (matches the "mean/median/std" stat-grouping reading).
- Computed Sharpe-likes manually from the parquet; matched the aggregator's output to 5 decimal places.

**Next-commit suggestion:** **`feat(p5.5): rank — ordered leaderboard with N-filter + risk-adjusted sort options`**. Aggregator infrastructure now complete (4 columns: per-pair, per-year, per-month, dispersion-aware). The ranker should:
1. **Take an aggregator output (any of the three) + a sort metric**. Default metric: `median_roi_pct_annualized`. Other metrics: `mean_roi_pct_annualized`, `total_net_pnl`, `win_rate_pct`, `mean_roi_pct_annualized / std_roi_pct_annualized` (Sharpe-like).
2. **Two-table output**: `ranked` (n_trades ≥ MIN_N_FOR_RANKING, sorted by metric descending) + `suppressed_thin` (n_trades < MIN_N_FOR_RANKING, sorted by n_trades descending for diagnostic) — the transparency-over-silent-filtering pattern at the ranker layer.
3. **No hidden ties**: stable sort + tiebreaker on `n_trades` desc (more data = preferred at equal headline metric). Document the tiebreaker.
4. **API**: `rank(summary_df, *, metric="median_roi_pct_annualized", min_n=MIN_N_FOR_RANKING) -> (ranked, suppressed_thin)`.

After p5.5 → Phase 5 is complete and Phase 6 (streamlit UI) can render: leaderboard table, heatmap, year-trend line, month-of-year bars. The honest-data underpinnings (slippage, exact annualization, spot-margin, lot-size historical) all show through to the Phase-6 surface.

---

## Review of 38ce987 — feat(p5.5): rank_strategies — Phase-5 leaderboard layer

**Verdict:** ✅ accept with two non-blocking tiebreaker / transparency notes for Phase-6

**Phase / commit goal (as I understood it):** Final Phase-5 commit. Sort a summary frame by a configurable metric, filter thin samples by default, return a copy with a 1-indexed `rank` column. Phase-6 UI's leaderboard data source.

**What works:**
- **Clean API surface** ([src/analytics/rank.py:46-53](src/analytics/rank.py#L46-L53)): `rank_strategies(summary_df, *, by, ascending, min_n, top_n)`. All five knobs the leaderboard needs.
- **Sensible defaults**: `by="median_roi_pct_annualized"` (robust + cross-window-comparable), `ascending=False` (higher = better), `min_n=MIN_N_FOR_RANKING=5` (statistical honesty), `top_n=None` (no truncation).
- **`ascending=True` for "what should I AVOID"** — clever asymmetric use case. Worst-first leaderboard is useful for de-risking ("avoid these strategy×symbol pairs").
- **`min_n=0` disables filter** — escape hatch documented "with eyes open".
- **`top_n` truncation post-rank** — `df.head(top_n)` only after the full sort, so rank-numbering stays 1..top_n consistent.
- **Determinism**: `sort_values + reset_index(drop=True)` + 1-indexed integer rank. Same pattern as sweep_grid.
- **`MULTIPLE_COMPARISONS_CAVEAT`** ([src/analytics/rank.py:35-43](src/analytics/rank.py#L35-L43)) — 450-character v1 mitigation as a module constant. **This is exactly the right move for asymmetric conservatism**: when the user sees "rank=1 short_straddle × RELIANCE 247.9%/yr", they need to know the top-K of N selections inflates apparent edge. Phase-6 UI MUST render this verbatim. Defers formal Bonferroni/Holm to Phase 7/8 with the right reason (needs per-row p-values, not in v1).
- **Input validation**: `n_trades` column required, `by` column required, `min_n >= 0`, `top_n >= 0` — all loud failures with helpful diagnostics. Same loud-failure pattern as `results.write_results` and `summarize_by_stock_strategy`.
- **Compatible with all three aggregator outputs** (per-pair, per-year, per-month) — the input contract is just "any frame with `n_trades` and the `by` column", not specifically `SUMMARY_COLUMNS`. Composable. Phase-6 can rank-by-year for a YoY winners table.
- 18 new tests + 365/365 in full suite. Phase 5 is **DONE**.

**Real-data verify (single-row dataset)**: 
```
rank=1 short_straddle × RELIANCE  n=18  win%=83.3  median=247.9%/yr  total_net_pnl=₹124,613
```
With one (strategy, symbol) pair in the verify universe the ranker is a no-op, but the wiring is provably correct. Phase-7+ when more pairs land, the leaderboard will exercise.

**I also live-verified composability with the std column from afdd56e**: synthesized a `sharpe_like_annualized = mean_roi / std_roi` column, called `rank_strategies(s2, by="sharpe_like_annualized")` — works (no special-casing needed). The p5.5 API decouples "what to rank by" from "what's in the schema", which is the right abstraction.

**Blocking issues:** None.

**Non-blocking suggestions:**

1. **🔬 Tiebreaker is (strategy, symbol) lex order, NOT n_trades desc** — this departs from my p5.4 next-commit suggestion. **Live-grilled with a fake tie**:
   ```
   At tied 100%/yr annualized:
     rank=1  A_strategy × XYZ  n=10
     rank=2  B_strategy × ABC  n=50    ← LOSES TO N=10 ROW
     rank=3  B_strategy × XYZ  n=5
   ```
   The n=50 row (more statistically reliable) ranks BELOW the n=10 row purely because of alphabetic strategy name. **Defensible argument**: lex order is deterministic across input shuffles AND across data growth (n_trades changes; lex doesn't). **Argument against**: at a tied headline metric, "more data = more reliable" is the canonical statistical-honesty tiebreaker; this design contradicts the rest of the project's MIN_N_FOR_RANKING ethos.
   
   **My read**: the BUILDER's choice prioritizes pure determinism over statistical-honesty-flavored ordering. Both are valid. The lex-order behavior is documented and tested ([src/analytics/rank.py:99-108](src/analytics/rank.py#L99-L108)).
   
   **Suggestion for Phase-6**: render `n_trades` prominently in the leaderboard column so a user sees "rank 1 (n=10)" above "rank 2 (n=50)" and can interpret accordingly. Or, optionally, p5.5b adds `tiebreaker="n_trades"` as a kwarg defaulting to `"lex"` for backwards-compat — opt-in upgrade.

2. **⚠️ Single-table output silently drops thin samples** — I suggested a two-table return (`ranked, suppressed_thin`) in the p5.4 next-commit; the BUILDER took the single-table approach. The commit body acknowledges the divergence as a "different contract from aggregate.py — aggregate is transparent, rank is curated". **This works IF Phase-6 explicitly composes** `rank_strategies(s)` AND a parallel `s[s["n_trades"] < MIN_N_FOR_RANKING]` rendered as a "thin-samples-not-ranked" section. **If Phase-6 forgets that pair**, the operator sees only the ranked table and has no signal that 14 other strategies were tested but suppressed — silent filtering surfacing at the UI layer.
   
   **Mitigation**: add a docstring note on `rank_strategies` reminding consumers to also render the suppressed subset (or have a `return_suppressed=False` kwarg that flips it to tuple-return). Lightweight; non-blocking.

3. **Tied-rank semantics**: two rows tied on `(by, strategy, symbol)` get consecutive integer ranks (1, 2, ...) NOT shared rank (1, 1, 3). This is "competition ranking" vs "standard ranking". Defensible for a UI leaderboard (integers are easier to render), but worth docstring clarification — "ranks are dense integers 1..N regardless of metric ties".

4. **All-rows-suppressed edge case**: if every row has `n_trades < min_n`, the output is empty. No warning emitted. Operator might think the input was empty when actually 18 rows existed but were all thin. Phase-6 can detect this (`len(rank_output) == 0 and len(input) > 0`) and render a "all samples below threshold" message; or `rank_strategies` could emit a `warnings.warn(...)` when 100% are filtered. Non-blocking.

**Domain / correctness checks:**
- **Statistical honesty (continued)**: ✓ default `min_n=5`; ✓ multiple-comparisons caveat as a non-empty string. The two layers (aggregate-transparent + rank-curated) work TOGETHER for honesty, provided Phase-6 composes them.
- **Determinism**: ✓ deterministic regardless of input row order (verified live by shuffling a 3-row fake frame; rank output stable).
- **Annualization**: ✓ default metric is annualized, cross-window-rankable.
- **MULTIPLE_COMPARISONS_CAVEAT is the right v1 mitigation**: documenting the selection-bias risk in plain English is more useful for the user than a half-implemented Bonferroni that pretends to be rigorous. The user's mental model (asymmetric conservatism) is well-served by the verbal caveat.

**What I tried:**
- `.venv/bin/python -m pytest tests/test_rank.py -v` → 18/18.
- `.venv/bin/python -m pytest tests/` → 365/365.
- Live ranker on the real verify parquet → single row, rank=1 short_straddle × RELIANCE.
- Live composability test: built a `sharpe_like_annualized` column from afdd56e's std, ranked by it — works, no schema changes needed.
- Live "avoid" use case: `ascending=True` returns worst-first.
- Live tiebreaker grill: synthesized a 3-row fake frame with all metrics tied at 100%, confirmed lex-order behavior. Documented above as non-blocking #1.

**Caveat status — Phase 5 closes:**
- ✅ Aggregator infrastructure (p5.1 per-pair, p5.3 per-year, p5.4 per-month) — all share `_summarize` helper
- ✅ Dispersion + aggregate-P&L columns (afdd56e) — p5.1 reviewer flags closed
- ✅ Heatmap pivot (p5.2)
- ✅ Ranker (p5.5)
- ✅ Statistical-honesty contract through both layers
- ✅ Multiple-comparisons caveat surfaced as constant

**Phase 5 is DONE.** The honest-data underpinnings (Tier-B margin, exact annualization, spot-margin basis, 1% slippage gap, historical lot-size) all propagate through the aggregate/heatmap/rank layer into Phase-6's renderable shape.

**Next-commit suggestion:** **`feat(p6.1): streamlit UI skeleton — page routing + parquet loader + leaderboard table`**. The first user-facing surface. Load-bearing design decisions for Phase-6 to honor the asymmetric-conservatism contract:

1. **Single-page leaderboard layout**: top section = `rank_strategies(s)` ranked table with `n_trades` prominently shown (mitigates the lex-tiebreaker quirk); bottom section = thin-samples-not-ranked subset with explanatory copy ("these strategy×symbol pairs had N<5 trades and are not included in the ranking — N too small for reliable summary statistics").

2. **MULTIPLE_COMPARISONS_CAVEAT rendered verbatim** at the top of the leaderboard page (a styled callout box). This is non-negotiable for asymmetric conservatism — the user needs to see "top-K of N selections inflates apparent edge — treat as a candidate list" alongside the ranking.

3. **Heatmap render**: use `pivot_window` + `pivot_counts.where(n >= MIN_N_FOR_RANKING)` to mask thin-sample cells visually (hatched / desaturated, NOT silently NaN-out to "no data"). Phase-6's job is to show what's there honestly.

4. **YoY decay + month-of-year seasonality charts**: line plot for `summarize_by_year`, bar chart for `summarize_by_month`. Both should render `n_trades` per bin as a hover/tooltip so a sparse bin is visually distinguishable from a dense one.

5. **Survivorship-bias disclaimer (SPECS §6b.3)** still load-bearing — alongside the multiple-comparisons caveat. Two-sentence callout.

6. **Parquet path discoverable** via `data/results/sweep_*.parquet` — the run_id hash is what Phase-6 should expose so the user can switch between historical sweeps without remembering filenames.

After p6.1 → p6.2 heatmap viz → p6.3 trend/seasonality plots → p6.4 strategy-detail drill-down. Each lands one page/component. Streamlit's hot-reload makes this iteration fast.

---

## Review of d643aef + 588e42f — feat(p6.0.format) + test(p6.0.format) — Indian rupee + percentage formatters

**Verdict:** ✅ accept (both commits as a pair)

**Phase / commit goal (as I understood it):** Implement DESIGN_SPEC §2.7 number-formatting contract. Two pure helpers (`format_inr`, `format_pct`) that structurally prevent the "AVG ROI ₹25.76 L" mockup bug — rupees go through one callable, percentages through another. 17 boundary tests pin every threshold + sign + NaN path. Pure functions; no streamlit imports; testable in regular pytest.

### d643aef — `src/web/_format.py`

**What works:**

- **Two callables, two quantity types**: `format_inr(x: float | int) -> str` vs `format_pct(x: float | int, *, signed=False, annualized=False) -> str`. **Code-enforced separation** — a developer who tries to render rupees as a percentage has to explicitly call the wrong function, which a code review catches. Per the commit message: "the mockup bug 'AVG ROI ₹25.76 L' becomes a code-enforced contract".
- **Indian lakhs/crores convention correctly implemented** ([src/web/_format.py:30-31](src/web/_format.py#L30-L31)):
  ```python
  _LAKH: int = 100_000           # 1 L = 10^5
  _CRORE: int = 10_000_000       # 1 Cr = 10^7 = 100 lakh
  ```
  Named constants instead of magic numbers. ✓
- **Branch order**: sub-lakh → L (lakh) → Cr (crore). Strict `>=` boundary at each tier — `format_inr(99_999) == "₹99,999"`; `format_inr(100_000) == "₹1.00 L"`. **Live-verified both sides**.
- **Negative sign placement** ([src/web/_format.py:66-74](src/web/_format.py#L66-L74)) — `sign = "-" if x < 0 else ""`, then `f"{sign}₹..."`. Minus PREFIXES the ₹ glyph (not after). **Critical for columnar tables**: rows align on the ₹ symbol; `-₹1.25 L` aligns with `₹6,923` cleanly, while `₹-1.25 L` would visually disconnect the minus from the magnitude.
- **NaN detection via `x != x`** ([src/web/_format.py:58, 109](src/web/_format.py#L58)) — clever Python idiom that avoids `import math`. NaN is the only float not equal to itself; the comparison short-circuits before the format string would crash on a NaN.
- **`try/except TypeError`** wrapper around the NaN check — defensive against unhashable / non-numeric inputs (e.g., if pandas passes a `pd.NA` object). Returns `str(x)` as a safe fallback.
- **`format_pct` kwargs-only design** (`signed`, `annualized` after `*`) — prevents positional-argument confusion. `format_pct(4.6, True)` would error rather than silently doing the wrong thing.
- **Scaling convention pinned in docstring** ([src/web/_format.py:86-88](src/web/_format.py#L86-L88)): "x=4.6 means 4.6%, NOT 0.046. Matches roi_pct + win_rate_pct semantics across the codebase." Cross-references the existing dataset convention; protects against the silent 100× bug.
- **Module-level docstring explains the "sub-lakh comma" choice** ([src/web/_format.py:18-25](src/web/_format.py#L18-L25)) — acknowledges that Indian convention is `₹1,25,000` (8-digit grouping) but uses western thousands grouping at sub-lakh scale for monospace-table readability, AND notes that lakh notation kicks in at the exact point where 8-digit grouping starts to matter. Defensible engineering choice with a documented rationale.
- **No streamlit import** — `from __future__ import annotations` + pure Python. Testable in regular pytest per SPECS §11.1.

**Live-tested:**
```
rupees: ₹25.76 L    (= 2,576,000)
pct:    +264.1%/yr  (annualized + signed)
₹99,999 → ₹99,999
₹100,000 → ₹1.00 L
₹9,999,999 → ₹100.00 L
₹10,000,000 → ₹1.00 Cr
negative: -₹6,923
NaN: — / —
sign: +4.6% / -3.2%
```
All boundaries match the test fixtures + commit-message preview.

### 588e42f — `tests/test_web_format.py`

**What works:**

- **17 tests covering every documented behavior:**
  - Zero → "₹0" (bare; no decimals); rounded to nearest rupee at sub-lakh; comma grouping
  - Boundary tests at both ₹1 L and ₹1 Cr — pins both sides of each transition
  - Negative sign placement explicitly (3 cases across sub-lakh/L/Cr)
  - None → "—"; NaN → "—" for both formatters
  - format_pct base / signed / annualized toggles independently
  - **`test_pct_already_scaled_to_100`** — pins the convention that `x=4.6` means 4.6% NOT 0.046. **Catches the silent 100× regression that would dwarf every percentage display in the UI** — this is THE most load-bearing convention test.
  - Cross-formatter NaN consistency test.
- **Test docstrings explicitly cite the LOAD-BEARING reason** for each non-obvious pin (boundary tests, negative-sign placement, scaling-convention). Future contributors who break a test see WHY it matters before deciding whether to update.
- **17 + 387 = 404/404** full suite passes.

**Blocking issues:** None.

**Non-blocking observations:**

1. **🔬 `format_inr(9_999_999) → "₹100.00 L"`** instead of `"₹1.00 Cr"`. Technically correct (9.999...M < 10M = 1 Cr), but reads as "100 lakh" which IS 1 crore — the operator does the conversion mentally and wonders why it isn't Cr-notation. The current behavior is documented + tested ([tests/test_web_format.py:53, 59](tests/test_web_format.py#L53-L59)); just noting that **"100.00 L" is at the perceptual boundary of confusion**. A real ₹100 L (10 million) IS 1 crore. **Fix would be**: trigger Cr notation when the L-formatted value rounds up to 100.00 (or equivalently, when `mag >= _CRORE - 0.005 * _LAKH ≈ 9_999_500`). Minor; only matters at exact ₹9.99-9.999M values. Cosmetic.

2. **`format_pct(0.001) → "0.0%"`** — sub-decimal precision is lost. For ROI percentages in the dataset's range (5%, 10%, 247%), this is fine. **But**: if someone passes a near-zero value (e.g., a 0.05% win rate or a per-trade ROI of 0.001%), it renders as `0.0%` indistinguishably from real zero. **Mitigation**: add a `precision: int = 1` kwarg defaulting to 1, but allowing callers to bump for high-precision contexts. Or document that "small percentages may round to 0.0% by design — use net_pnl rupee values for sub-decimal precision". Not blocking; just noting the precision floor.

3. **`format_pct(0.0, signed=True) → "0.0%"`** ([tests/test_web_format.py:106](tests/test_web_format.py#L106) pinned). Zero is unsigned even when `signed=True`. **Defensible choice** — a "+0.0%" reads as positive, "-0.0%" as negative, and the unsigned "0.0%" is the natural neutral. Worth noting; the test pins this so a future contributor doesn't "fix" it. ✓

4. **`format_pct(1) → "1.0%"`** ([tests/test_web_format.py:128](tests/test_web_format.py#L128)) — integer input handled correctly (1 → "1.0%", not "100.0%"). Pinned by `test_pct_already_scaled_to_100`. ✓ This is the silent-100x-bug guard I called out as load-bearing.

5. **No `__all__`** in `_format.py`. Convention elsewhere in `src/web/` is to have explicit `__all__` (caveats.py does). Cosmetic; consumer imports work without it. Could add `__all__ = ["format_inr", "format_pct"]` for consistency.

6. **Lakhs/crores conversion uses naive division** ([src/web/_format.py:70, 72](src/web/_format.py#L70-L72)) — `mag / _CRORE`, `mag / _LAKH`. Python 3 float division; no FloatingPointError risk at the magnitudes involved. ✓

**Domain / correctness checks:**
- **Mockup-bug prevention**: ✓ structural separation; rupees and percentages have distinct callables. "AVG ROI ₹25.76 L" is now a code review smell (`avg_roi = format_inr(...)` mismatches the variable name).
- **Indian convention**: ✓ 1 L = 10^5, 1 Cr = 10^7. Boundary values + division correct.
- **Scaling convention**: ✓ pinned by `test_pct_already_scaled_to_100`.
- **No silent failures**: ✓ None/NaN → "—"; non-numeric → `str(x)` fallback.
- **Streamlit isolation**: ✓ pure Python; testable in regular pytest.

**What I tried:**
- Read `src/web/_format.py` end-to-end.
- Read `tests/test_web_format.py` end-to-end.
- Live-tested: ₹2,576,000 → "₹25.76 L"; +264.1 annualized signed → "+264.1%/yr". Boundaries at ₹99,999 / ₹100,000 / ₹9,999,999 / ₹10,000,000 — all match commit-message preview.
- `pytest tests/test_web_format.py` → 17/17. Full suite → 404/404.

**Sequencing observation:** d643aef + 588e42f land as an impl+test pair, 67 seconds apart. **This catches up with the §4 sequence deviation I flagged in 334bada review** — the format helpers were originally scheduled to land before `feat(p6.1.discover)`, but ended up landing AFTER `feat(p6.1.caveats)` and concurrent with the fix commit. **Net effect: no harm done**, because `_format.py` isn't a dependency of caveats or discover. The deviation is now closed.

**Phase 6.0 + 6.1 status after this commit:**
- ✅ `chore(p6.0.spec)` (b7fe7e5 + 1c00f69 reconciliation)
- ✅ `chore(p6.0.deps)` (d9f2cb2)
- ✅ `feat(p6.0.format)` + `test(p6.0.format)` (d643aef + 588e42f)
- ✅ `feat(p6.1.discover)` + `test(p6.1.discover)` (334bada + 5c801dd)
- ✅ `feat(p6.1.caveats)` + tests (7b12228 + 79d50d8 fix)
- ✅ `feat(p6.1.app)` (efe1c73)
- 🔄 `feat(p6.1.empty)` — `src/web/empty_state.py` per DESIGN_SPEC §2.6 (NOT YET LANDED)
- 🔄 `chore(p6.1.verify)` — `streamlit run app.py` smoke + screenshots (NOT YET LANDED)

**Next-commit suggestion:** Per DESIGN_SPEC §4 sequence the remaining Phase-6.1 items are:
1. `feat(p6.1.empty)` — 6 pre-written `st.info` messages per §2.6 table; pure data + a render helper.
2. `chore(p6.1.verify)` — visual smoke; should land AFTER p6.1.empty so the empty-state paths are actually exercisable.

After `chore(p6.1.verify)` Phase 6.1 closes and Phase 6.2 starts with `feat(p6.2.headline)` — the first commit that USES `format_inr` + `format_pct` to render the leaderboard headline cards.

---

## Review of 79d50d8 — fix(p6.1.caveats): correct survivorship snapshot date 2026-07-01 → 2024-07-01

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Close the BLOCKER I flagged in 7b12228 review. 1-char text correction + anti-regression test.

**What works (every closure item from my 7b12228 review):**

- **Text fix is the literal 1-char change**: `2026` → `2024` at [src/web/caveats.py:52](src/web/caveats.py#L52). No collateral edits, no scope creep.
- **Anti-regression test `test_survivorship_caveat_cites_correct_snapshot_date`** ([tests/test_web_caveats.py:38-47](tests/test_web_caveats.py#L38-L47)) — **two assertions, exactly as I recommended**:
  ```python
  assert "2024-07-01" in SURVIVORSHIP_CAVEAT          # positive
  assert "2026-07-01" not in SURVIVORSHIP_CAVEAT     # explicit anti-regression
  ```
  The "not in 2026-07-01" assertion pins the SPECIFIC typo so it can't reappear via a future copy-edit. Catches the exact pattern that slipped past `test_survivorship_caveat_is_substantive_paragraph` (which only checks length + key-term presence).
- **Test docstring captures the WHY**: "LOAD-BEARING anti-regression... a wrong date in an honest-disclosure constant silently undermines every backtest result an operator interprets." Future contributor reading the test understands the consequence of breaking it.
- **Commit message acknowledges the asymmetric-conservatism reasoning verbatim** from my 7b12228 review block ("operators who notice the impossible date lose trust in the rest of the UI; operators who don't notice silently act on the wrong fact"). Direct reviewer→builder→fix loop closed in <5 minutes from blocker flag to fix commit.
- **Caught BEFORE `chore(p6.1.verify)`** — commit body explicitly notes this, preventing the wrong date from getting screenshot into committed documentation.

**Live-verified:**
- `pytest tests/test_web_caveats.py -v` → 7/7 (including the new anti-regression test). Test catches what it claims to catch.
- `pytest tests/` → 404/404 full suite passes.
- `grep -n "07-01" src/web/caveats.py` → only line 52, now reads "2024-07-01".

**Blocking issues:** None.

**Non-blocking observations:**

1. **The `is`/`not in` pair is the right pattern for known-typo regression tests.** Pure `==` would catch the specific 2024 date but not a future drift to "2025-07-01" or "2024-07-02"; pure `"2024" in` would pass on "2024-something-else". The explicit "2026-07-01 not in" specifically guards against THE typo that occurred. **Worth applying this pattern to the MARGIN_TIER_B_CAVEAT** if any specific values get changed there in the future (e.g., the offset multipliers 0.60 / 0.35).

2. **The 7b12228 review's other 2 non-blocker flags were NOT closed in this commit** — appropriate (single-purpose commit):
   - `render_caveats` missing from `__all__` despite docstring claim
   - "~10% discount" claim in MARGIN_TIER_B unsupported by any analysis
   Both still open; opportunistic for future caveats-touching commits.

3. **Reviewer-loop credit**: commit body explicitly references `c53a9d1 review` as the source of the flag. The pattern (commit cites the review that surfaced the issue) is now established discipline for fix commits. Good.

**Domain / correctness checks:**
- **Asymmetric-conservatism**: ✓ honest-disclosure layer restored — the operator now sees the actual snapshot date.
- **No regression risk**: ✓ 1-char change + 1 test added; 404/404 passes.
- **Test specificity**: ✓ anti-regression test would fail loudly if the bug recurs.

**What I tried:**
- `git show 79d50d8` — clean diff: 1 line changed in caveats.py + 12 lines added to test file.
- `pytest tests/test_web_caveats.py -v` → 7/7 with the new test.
- Verified the running constant now reads "2024-07-01" via direct import.

**Sequencing observation:** Review-to-fix cycle time on this BLOCKER:
- 01:01:38 — efe1c73 (mounts buggy constant in app shell)
- ~01:04:09 — c53a9d1 (my BLOCKING review)
- 01:05:34 — 79d50d8 (fix lands)
≈ **86 seconds from BLOCKER flag to committed fix.** This is the reviewer-loop pattern operating at its tightest. The user's "ship as a parallel REVIEWER agent" investment paid off here — without the reviewer, the wrong date would have shipped to `chore(p6.1.verify)` and been screenshot into committed documentation.

**Next-commit suggestion:** d643aef (`feat(p6.0.format)`) just landed concurrent with this — reviewing next. Then per DESIGN_SPEC §4 the remaining Phase-6.1 items are:
1. `feat(p6.1.empty)` — `src/web/empty_state.py` per DESIGN_SPEC §2.6.
2. `chore(p6.1.verify)` — visual + smoke against current parquets.

After Phase 6.1 closes → Phase 6.2 (Leaderboard tab) starts.

---

## Review of efe1c73 — feat(p6.1.app): app.py — sidebar + 4 placeholder tabs + caveats strip

**Verdict:** ⚠ **accept conditional on the 7b12228 date-bug fix landing as a commit.** App shell itself is clean; the asymmetric-conservatism gap is inherited from the un-fixed caveat constant.

**Phase / commit goal (as I understood it):** First runnable Streamlit surface. Header + sidebar + 4 placeholder tabs. Caveats render at the top of every tab. Sweep auto-picked by newest mtime per SPECS §11.2. State convention follows SPECS §11.4 (`mp_` prefix); min-N flows top-down per SPECS §11.5.

### Inherited blocker status

The buggy `2026-07-01` SURVIVORSHIP_CAVEAT from 7b12228 is mounted in this commit's app shell. **Every tab calls `render_caveats()` ([app.py:204, 211, 217, 223](app.py)), which renders the constant verbatim.** Running `streamlit run app.py` against the verify parquet would surface the wrong date in the caveats card across all 4 tabs.

**Working-tree observation (not blocking, just reporting)**: I observe that `src/web/caveats.py` has an **uncommitted local edit** in the working tree changing `2026-07-01` → `2024-07-01`. `git diff HEAD -- src/web/caveats.py` shows the fix; `git status` confirms it's unstaged. **Someone (BUILDER or the user) saw the BLOCKING flag in my 7b12228 review and fixed the file locally, but hasn't yet committed.** I have not staged or committed this change (per my discipline — I only write to `comments.md`). **The fix must be committed before `chore(p6.1.verify)` screenshots the UI**, otherwise the running shell still has the bug and the screenshots immortalize it.

Recommend BUILDER lands the fix as the very next commit: `fix(p6.1.caveats): correct survivorship snapshot date 2026-07-01 → 2024-07-01` + the regression test (per my 7b12228 review block).

---

### What works (the shell itself):

- **Module layout matches SPECS §11.1**: `app.py` is the thin entry; helpers from `src.web.caveats`, `src.web.discover`, `src.analytics.aggregate`, `src.strategies.registry`. No business logic in `app.py` itself — just composition + state wiring.
- **State convention** ([app.py:55-67](app.py#L55-L67)): `_init_state()` is idempotent (only initializes keys not already present); all 6 cross-cutting keys correctly prefixed `mp_` per SPECS §11.4.
- **`@st.cache_data` on `_load_sweep`** ([app.py:76-79](app.py#L76-L79)) — tab switches don't re-read the parquet. Cache-key on `str(path)` so Streamlit's string-hash works deterministically.
- **`st.set_page_config` as first call** ([app.py:44-49](app.py#L44-L49)) — Streamlit's hard requirement; correctly placed before any other `st.*`.
- **Error handling at `main()`** ([app.py:241-248](app.py#L241-L248)) — `FileNotFoundError` and `Exception` both caught with user-facing `st.error`. The bare `Exception` catches `ArrowInvalid` from pyarrow on a corrupt parquet, surfacing the message instead of crashing the app.
- **Header sweep selector** ([app.py:85-105](app.py#L85-L105)) — picks newest mtime via `find_latest_sweep`, shows filename + last-updated timestamp. Renders the "no sweeps yet" warning when `latest is None` (proper empty state, matches §11.2 contract).
- **`_render_sidebar`** ([app.py:111-174](app.py#L111-L174)) — strategies/symbols/min_n/regime controls; sweep metadata caption with rows + strategies + symbols + run_id. Matches DESIGN_SPEC §1.2.
- **`_apply_filters` is a pure function** ([app.py:180-191](app.py#L180-L191)) — takes a DataFrame, returns a filtered DataFrame. Tabs use this rather than each implementing their own filter logic — single source of truth for filter composition.
- **`render_caveats()` called at the top of every tab** ([app.py:204, 211, 217, 223](app.py)) — satisfies PLAN §3 Phase 6.5 "caveats always visible" exit criterion.
- **Tab tab-handlers are tiny placeholders** that each render the caveats + a tab heading + an `st.info` "implemented in feat(p6.X.Y)" pointer. Reviewable shape — each tab becomes a small diff when Phase 6.2/6.3/6.4/6.5 land.
- **`else: main()` ergonomic** ([app.py:266-270](app.py#L266-L270)) — Streamlit imports app.py directly (not as `__main__`), so the `if __name__ == "__main__"` check doesn't fire. The `else` branch runs `main()` on import. **Defensive against the common Streamlit gotcha** of `if __name__ == "__main__"` quietly never firing.
- **386/386 tests pass** — no test changes; app.py is import-time tested via smoke-launch in the next verify commit.

**Live smoke-tested:**
- `.venv/bin/python -c "import app"` → imports cleanly. Streamlit emits `WARNING: missing ScriptRunContext!` (expected in bare-mode import; not an error).
- Cross-checked that `app.py` does NOT directly import the caveat constants — it calls `render_caveats()` which uses them. The bug propagation path is `7b12228 caveats.py:52` → `render_caveats_strip()` → `app.py:_render_*_tab` → operator's screen.

**Non-blocking observations:**

1. **🔬 Multiselect default behavior has a subtle UX gotcha.** [app.py:118-123, 129-134](app.py#L118-L134):
   ```python
   st.session_state["mp_strategies_filter"] = st.sidebar.multiselect(
       "Strategies", options=available_strategies,
       default=st.session_state["mp_strategies_filter"] or available_strategies,
   )
   ```
   If the operator explicitly deselects ALL strategies (`mp_strategies_filter` becomes `[]`), the next render's `default=` clause sees a falsy value and re-defaults to `available_strategies` (all). **UX consequence**: "deselect all" silently bounces back to "all selected". Operator can't actually filter to zero strategies as a way to inspect the empty-state path.
   
   **Better pattern**: separate the "uninitialized" sentinel from the "explicitly empty" state. e.g., use `None` as the uninitialized default in `_init_state()` and check `if st.session_state["mp_strategies_filter"] is None: ... = available_strategies`. Cosmetic; only matters if the empty-state UX paths from DESIGN_SPEC §2.6 want to exercise "user selected zero strategies" as a tab-empty trigger.

2. **`except Exception as e` at [app.py:246](app.py#L246) is too broad.** Catches KeyboardInterrupt, SystemExit, GeneratorExit, etc. **Recommended narrow** to `(pyarrow.lib.ArrowInvalid, OSError, ValueError)` or whatever pyarrow actually raises. Same flag as 5c801dd review's `test_corrupt_parquet`. Cosmetic.

3. **Cache invalidation gotcha**: `_load_sweep` cache-keys on `str(path)` not on `(path, mtime)`. If the operator runs a new sweep that overwrites an existing parquet (unlikely with hash-based run_ids, but theoretically possible if the same seed produces the same hash), the cache serves the stale frame. **Mitigation**: add `path.stat().st_mtime` to the cache key — `_load_sweep(parquet_path_str, mtime)` and call as `_load_sweep(str(p), p.stat().st_mtime)`. Streamlit invalidates automatically on the second arg change. Not blocking for v1; just noting.

4. **`v0.6.1 skeleton` hardcoded** at [app.py:105](app.py#L105). Won't auto-update as Phase 6.2/6.3/6.4/6.5 land. **Better**: read from git via `subprocess.check_output(["git", "describe", "--always", "--dirty"], cwd=REPO).strip()`. Each phase-tag (per DESIGN_SPEC §6 tagging discipline) auto-surfaces. Cosmetic; can land alongside `chore(p6.5.tag)`.

5. **Regime filter is wired in the sidebar but NOT applied in `_apply_filters`.** [app.py:151-161 + 180-191](app.py#L151-L161). Help text explicitly says "v0.6.1 placeholder". Acceptable; **but worth a `# TODO p6.5+`** comment next to the unused regime check so it's not forgotten.

6. **No test commit.** Commit body says app.py is "import-time tested by smoke-launch in verify commit" — i.e., `chore(p6.1.verify)`. Acceptable; rendering tests in pytest are heavy. **Recommended import smoke-test**: `tests/test_app_import.py` with one test: `def test_app_imports_cleanly(): import app`. Catches a module-import-time crash (missing module, syntax error) without needing a Streamlit script-runtime. ~5 lines.

7. **`_init_state()` sets `mp_selected_sweep = None`** at [app.py:59](app.py#L59), but `_render_header` writes the actual sweep path to it at [app.py:99](app.py#L99). This is fine, BUT it means the initial state has `None` even when a sweep exists — only after `_render_header()` runs does it become populated. Order matters; `main()` calls `_render_header()` first, then checks `mp_selected_sweep`. Correct sequencing, just brittle. Worth a docstring note: "side-effect: `_render_header` writes `mp_selected_sweep`; downstream code reads it."

**Domain / correctness checks:**

- **Asymmetric-conservatism**: ⚠ inherited bug from 7b12228 (the date typo) propagates to every rendered tab; **app shell itself is clean** — caveats correctly always-visible, every tab calls `render_caveats`.
- **Determinism**: ✓ sweep auto-picked by newest mtime (deterministic); `_apply_filters` is pure; cache deterministic on `str(path)`.
- **Module-isolation respect**: ✓ `app.py` correctly imports `streamlit` at module-top (the entry point may); `discover.py` stays streamlit-free per §11.1.
- **State convention**: ✓ all 6 keys `mp_`-prefixed.
- **Min-N flow top-down**: ✓ slider at [app.py:137-148](app.py#L137-L148) writes to `mp_min_n`; no tab will hardcode a threshold (verified by reading the 4 placeholder tabs — they don't reference `mp_min_n` yet, but the wiring is in place for p6.2-p6.5).

**What I tried:**
- Read app.py end-to-end.
- Live import smoke-test: `python -c "import app"` → clean.
- Cross-checked the caveat propagation path (`7b12228` constant → `render_caveats` → 4 tab handlers).
- `git diff HEAD -- src/web/caveats.py` — discovered the uncommitted local fix (2026 → 2024); reported it above without staging.
- 386/386 full suite passes (no app-specific tests).

**Sequencing observation:** Two Phase-6.1 feature commits in 90 seconds (7b12228 → efe1c73). Tight cadence. The trade-off: BUILDER's commit pipeline runs ahead of my review feedback, so the 7b12228 BLOCKING flag wasn't visible until efe1c73 had already mounted the buggy constant. **Lesson: my reviews need to land faster, OR BUILDER needs to pause for a watcher beat before stacking dependent commits.** Both pressures are real; no clean answer. Just observing.

**Next-commit suggestion (revised given the inherited blocker):**

1. **🔴 IMMEDIATE: `fix(p6.1.caveats): correct survivorship snapshot date 2026-07-01 → 2024-07-01`** — stage and commit the local working-tree edit + add the regression test. Unblocks `chore(p6.1.verify)` screenshotting the correct UI.
2. `feat(p6.1.empty)` — `src/web/empty_state.py` per DESIGN_SPEC §2.6 (6 pre-written degenerate-data messages).
3. `chore(p6.1.verify)` — `streamlit run app.py --server.headless` smoke + visual screenshot of every tab against `DESIGN/leaderboard.png` / `DESIGN/per_stock.png` etc. **Should land AFTER the date fix** for screenshot honesty.

After Phase 6.1 closes → `feat(p6.2.headline)` is the first Phase-6.2 commit (renders the 4-card strip per DESIGN_SPEC §2.5 Leaderboard row). Needs `feat(p6.0.format)` first (still skipped) for `format_inr()`.

**Reminder for the format helpers**: `feat(p6.0.format)` + `test(p6.0.format)` are still un-landed (DESIGN_SPEC §4 sequence deviation flagged in 334bada review). They need to land before `feat(p6.2.headline)` because the headline cards render rupee amounts that need the lakhs/crores formatter.

---

## Review of 7b12228 — feat(p6.1.caveats): src/web/caveats.py — 3 caveat constants + 2 render helpers

**Verdict:** ⚠ **accept-with-blocker — `SURVIVORSHIP_CAVEAT` has a 2-year date typo (2026-07-01 instead of 2024-07-01). MUST be fixed before any Phase-6 UI renders this constant to an operator.**

**Phase / commit goal (as I understood it):** Implement SPECS §11.3 + DESIGN_SPEC §1.4 contract. Three caveat constants + two render helpers + a top-level dispatcher that picks strip-vs-collapsed based on session state. Tests pin the constants' structural properties (length, key terms, re-export identity, dismiss-key namespace).

### 🔴 BLOCKING BUG — date typo in SURVIVORSHIP_CAVEAT

**[src/web/caveats.py:52](src/web/caveats.py#L52)** reads:
> "The blue-chip universe is a **2026-07-01** snapshot. Stocks that..."

**Every other reference in the project says 2024-07-01:**
- `src/universe/blue_chip.py:11` — "time snapshot (~mid-2024)"
- `src/universe/blue_chip.py:22` — "retrieval date ~2024-07-01"
- `SPECS.md:279` — "a single **2024-07-01** snapshot regardless of as_of"
- `SPECS.md:595` — "~**2024-07-01** Nifty 50 snapshot"
- `SPECS.md:638, 640, 808` — "**2024-07-01** Nifty 50"
- `DESIGN/DESIGN_SPEC.md:70` — "v1 blue-chip is a **2024-07-01** snapshot"
- **SPECS §11.3** (this commit's authoring contract) — "Notes the v1 blue-chip universe is a **2024-07-01** snapshot"

**Today's date is 2026-05-25.** The string "2026-07-01 snapshot" describes a snapshot **2 months in the future**, which is structurally impossible (you cannot have a survived-stocks list for a future date).

**Why this is blocking, not just a typo:**

1. **Asymmetric-conservatism violation.** The whole point of `SURVIVORSHIP_CAVEAT` is to render an honest disclosure. A wrong date in the disclosure undermines the entire honest-disclosure layer. An operator who notices the impossible date assumes the rest of the UI is similarly unreliable; an operator who doesn't notice acts on a wrong fact (thinking the universe is current when it's 2 years old).

2. **The constant is verbatim-rendered.** Per SPECS §11.3 the wording lives in this constant; tabs MUST NOT inline-substitute. There is no second source of truth that could correct this — operators see exactly what's in the string.

3. **Tests pass.** Existing tests check length + key-term grep but NOT the actual date. The bug is undetected by the suite (verified — 6/6 pass).

4. **The next commit (efe1c73 — `feat(p6.1.app)`) just mounted this** in the app shell. If/when the user runs `streamlit run app.py`, they will SEE the wrong date in the caveats card.

**Fix (1-character correction, ~30-second commit):**

```python
# Before
SURVIVORSHIP_CAVEAT = (
    "The blue-chip universe is a 2026-07-01 snapshot. Stocks that "
    ...

# After
SURVIVORSHIP_CAVEAT = (
    "The blue-chip universe is a 2024-07-01 snapshot. Stocks that "
    ...
```

**Plus a regression test** to prevent recurrence:

```python
def test_survivorship_caveat_cites_correct_snapshot_date():
    """The universe snapshot is 2024-07-01 per SPECS §6b.3 + blue_chip.py.
    Pin this so a future copy-edit doesn't drift the date again."""
    assert "2024-07-01" in SURVIVORSHIP_CAVEAT
    assert "2026-07-01" not in SURVIVORSHIP_CAVEAT  # explicit anti-regression
```

Recommend `fix(p6.1.caveats): correct survivorship snapshot date 2026-07-01 → 2024-07-01` lands NOW, before `chore(p6.1.verify)` screenshots the UI. The verify screenshots would otherwise immortalize the wrong date in committed documentation.

---

### What works (everything else):

- **Three caveat constants** correctly structured. `MULTIPLE_COMPARISONS_CAVEAT` re-exported from `src.analytics.rank` ([src/web/caveats.py:30](src/web/caveats.py#L30)) — **one source of truth at the strongest level** (the same object, not just equal-string). Verified by `test_multiple_comparisons_caveat_re_exported_identical`.
- **`MARGIN_TIER_B_CAVEAT` ([src/web/caveats.py:66-78](src/web/caveats.py#L66-L78)) names the bias direction explicitly** — "HIGH-VOL symbols and LOW-OFFSET strategies (short straddle 0.60, iron condor 0.35) look BETTER here than on production margin". Includes the actual SPECS-calibrated offset values (0.60 / 0.35). **This is the right asymmetric-conservatism wording**: vague "this is approximate" would let the operator wave it away; this names which strategies are over-promised.
- **`DISMISS_KEY = "mp_caveats_dismissed"`** ([src/web/caveats.py:46](src/web/caveats.py#L46)) — follows the SPECS §11.4 `mp_` namespace convention. Pinned by `test_dismiss_key_uses_mp_namespace_prefix`.
- **Render helpers correctly idiomatic Streamlit**:
  - `render_caveats_strip()` ([src/web/caveats.py:87-118](src/web/caveats.py#L87-L118)) — `st.columns(3)` for the cards, `st.button` triggers `st.session_state[DISMISS_KEY] = True` + `st.rerun()` for immediate re-render.
  - `render_caveats_collapsed()` ([src/web/caveats.py:121-140](src/web/caveats.py#L121-L140)) — slim `st.warning` banner + expand button using `[6, 1]` column ratio.
  - `render_caveats()` ([src/web/caveats.py:143-152](src/web/caveats.py#L143-L152)) — top-level dispatcher; always renders one or the other (satisfies the "caveats always visible" PLAN Phase-6.5 exit criterion).
- **`_maybe_init_state()` idempotency** ([src/web/caveats.py:81-84](src/web/caveats.py#L81-L84)) — checks `if DISMISS_KEY not in st.session_state` before initializing, so stale state from prior session isn't clobbered.
- **Module docstring correctly notes "this module DOES import streamlit (it's the renderer)"** ([src/web/caveats.py:21-24](src/web/caveats.py#L21-L24)) — explicitly defends the §11.1 exemption. Anti-pattern guard.
- **`__all__` exported list** ([src/web/caveats.py:34-41](src/web/caveats.py#L34-L41)) — 6 names pinned. Consumers know the public API.
- **Tests:**
  - `test_multiple_comparisons_caveat_re_exported_identical` uses `is` (identity), not `==` (equal). **Strongest possible re-export check** — would catch a future "convenience copy".
  - `test_all_three_caveats_are_distinct_strings` catches a copy-paste regression where one constant accidentally aliases another. Defensive.
  - `test_caveats_module_exports_expected_names` uses `expected.issubset(set(caveats.__all__))` — allows future additions without breaking the test.
- **6/6 tests pass; 386/386 full suite (was 380 + 6 new)**.

**Non-blocking observations (other than the blocker):**

1. **`render_caveats()` is the top-level helper called by every tab per its docstring, BUT it's NOT in `__all__`.** Tests check that `MULTIPLE_COMPARISONS_CAVEAT`, `SURVIVORSHIP_CAVEAT`, `MARGIN_TIER_B_CAVEAT`, `render_caveats_strip`, `render_caveats_collapsed`, `DISMISS_KEY` are exported — but `render_caveats` itself is missing from both `__all__` and the expected set. Either:
   - **Intent was for tabs to call `render_caveats_strip` / `render_caveats_collapsed` directly** based on tab-local state checks — but then the docstring on `render_caveats` should be removed or marked private (`_render_caveats`).
   - **Intent was for `render_caveats` to be public** — add it to `__all__` and the test's expected set.
   The docstring claims the latter; the export list claims the former. **Pick one.** Cosmetic non-blocker.

2. **`MARGIN_TIER_B_CAVEAT` claims "absolute ROI numbers should be discounted by ~10% before treating any pair as 'production-ready'."** This is a *quantitative* recommendation. I don't see this ~10% figure backed by any analysis elsewhere in the project — it appears to be engineering judgment, not an empirically derived number. **Worth softening to "should be treated with skepticism" or "discount by a margin you're comfortable with" UNLESS you've actually measured the Tier-B-vs-real-SPAN gap on a calibration sample.** Asymmetric-conservatism would prefer "round-up the uncertainty" wording over a specific point estimate that might be overconfident. Non-blocking; consider for `chore(p6.1.verify)` content polish.

3. **`render_caveats_strip` uses `st.caption(...)`** for the body text ([src/web/caveats.py:103, 106, 109](src/web/caveats.py#L103-L109)). Caption renders smaller/lighter than body text. With ~400-character paragraphs, this may be too dense to read. **Worth visual-checking in `chore(p6.1.verify)`** — if the cards are unreadable at default font size, switch to `st.markdown(text)` or `st.write(text)`. Streamlit doesn't have a "small body" style that's larger than caption; default body might be better.

4. **No test for the dismiss flow** — flipping `st.session_state[DISMISS_KEY] = True` then asserting that `render_caveats()` calls `render_caveats_collapsed()`. The commit body acknowledges renderers are visually verified in `chore(p6.1.verify)`. Acceptable in v1; rendering tests in pytest are heavy. Just noting.

5. **`SURVIVORSHIP_CAVEAT` says "Phase-7 BLUE_CHIP_BY_QUARTER membership lands the structural fix"** — matches PLAN §3 Phase 7 commit list ✓ and DESIGN_SPEC §1.4. Cross-doc consistency maintained.

**Domain / correctness checks:**

- **One-source-of-truth for caveats**: ✓ MULTIPLE_COMPARISONS re-exported via `is`; SURVIVORSHIP + MARGIN_TIER_B authored here per SPECS §11.3.
- **Asymmetric-conservatism**: ✓ (bias-direction explicit in MARGIN_TIER_B; survivorship "OVERSTATE" wording in SURVIVORSHIP) — **but the survivorship date typo undermines it.**
- **Streamlit isolation**: ✓ caveats module is exempt per §11.1; module docstring explicitly defends this.
- **Test coverage**: 6 tests cover constant properties + namespace; **but the 2026 date bug slipped through because there's no date assertion**.

**What I tried:**
- Read [src/web/caveats.py](src/web/caveats.py) end-to-end.
- Read [tests/test_web_caveats.py](tests/test_web_caveats.py) end-to-end.
- `grep -rn "2024-07-01\|2026-07-01" src/ SPECS.md PROJECT_DESCRIPTION.md DESIGN/` — confirmed every other reference is 2024; only `caveats.py:52` is 2026.
- `pytest tests/test_web_caveats.py` → 6/6 pass (none catch the date).
- `pytest tests/` → 386/386.

**Next-commit suggestion (revised order, given the blocker):**

1. **🔴 `fix(p6.1.caveats): correct survivorship snapshot date 2026-07-01 → 2024-07-01` — IMMEDIATE.** Single-character fix; add a regression test asserting "2024-07-01" in SURVIVORSHIP_CAVEAT AND "2026" not in. ~30-second commit.

2. Then `feat(p6.1.empty)` — `src/web/empty_state.py` per DESIGN_SPEC §2.6 (6 pre-written degenerate-data messages).

3. Then `feat(p6.1.app)` — but per the latest task notification, this **already landed (efe1c73) before my caveats review**. That means the bad date is already in the running app shell. **Even more reason to land the date fix immediately.** I'll address efe1c73 separately.

**Opportunistic rider** for the date-fix commit:
- Decide on `render_caveats` __all__ inclusion (non-blocker #1).
- Soften the "discount by ~10%" claim in MARGIN_TIER_B_CAVEAT OR back it with a SPECS reference (non-blocker #2).
- Add the missing test for the date (already part of the fix).

---

## Review of 334bada + 5c801dd — feat(p6.1.discover) + test(p6.1.discover) — first Phase-6 code

**Verdict:** ✅ accept (both commits as a pair)

**Phase / commit goal (as I understood it):** First real Phase-6 code. `src/web/discover.py` implements SPECS §11.2 contract (sweep-parquet discovery + reading). `tests/test_web_discover.py` pins 13 cases covering every branch + the §11.1 streamlit-isolation rule. Impl + test landed as a pair, ~80 seconds apart — exactly the cadence I recommended in aae03c0 review.

**🔬 BUILDER skipped `feat(p6.0.format)` + `test(p6.0.format)` from the DESIGN_SPEC §4 sequence and went straight to p6.1.discover.** Defensible — discover.py is pure-data/pure-pathlib; it doesn't need format helpers. The format module isn't load-bearing until a tab actually renders something. **Worth flagging the order deviation so DESIGN_SPEC §4 + change log catches up** — non-blocker; revisit in the format-helper commit.

### 334bada — `src/web/discover.py`

**What works:**

- **SPECS §11.2 contract honored exactly**:
  - `find_latest_sweep(results_dir=RESULTS_DIR) -> Path | None` ([src/web/discover.py:34-53](src/web/discover.py#L34-L53))
  - `read_sweep_with_skips(parquet_path) -> tuple[DataFrame, DataFrame]` ([src/web/discover.py:56-91](src/web/discover.py#L56-L91))
- **SPECS §11.1 module-isolation guarantee**: no `import streamlit` at module-time. Pure pandas + pathlib + canonical helpers from `src.engine.results`.
- **`find_latest_sweep` defensive missing-dir handling** ([src/web/discover.py:42-43](src/web/discover.py#L42-L43)): if `results_dir` doesn't exist (fresh checkout, no sweeps run yet), returns `None` instead of raising `FileNotFoundError`. Right call for the "no sweeps yet" UI state.
- **Sort key `(-mtime, name)`** ([src/web/discover.py:52](src/web/discover.py#L52)): **freshest mtime first; deterministic name-ASC tiebreak**. Same-second writes (rare but possible) don't produce non-deterministic re-listings. **This is the right discipline** — the existing project pattern (deterministic sort + reset_index everywhere) extended to file discovery.
- **`*_skipped.parquet` exclusion filter** ([src/web/discover.py:46](src/web/discover.py#L46)): `"_skipped" not in p.name` is loose-but-safe given run_ids are 12-char hex hashes that can't contain "_skipped" substrings. Defensive.
- **Run-id recovery via stem prefix-stripping** ([src/web/discover.py:80-86](src/web/discover.py#L80-L86)): canonical `sweep_<run_id>.parquet` filename → strip `sweep_` prefix → use `skips_path(run_id, name="sweep")` to build companion path. Non-canonical filename (no `sweep_` prefix) → falls back to `empty_skips_frame()` without guessing. **Closes the §11.2 contract gap I flagged in b7fe7e5 review** (non-blocker #2).
- **`FileNotFoundError` raised on missing results parquet** ([src/web/discover.py:70-73](src/web/discover.py#L70-L73)): defensive raise for callers bypassing `find_latest_sweep`. Loud-failure consistent with the rest of the project.

**Live-verified (smoke tests):**
- `find_latest_sweep()` against real `data/results/` → `sweep_bde92aef8573.parquet` (correct).
- `read_sweep_with_skips(latest)` → 18 rows + 0-row canonical skips frame.
- `FileNotFoundError` raised on `/nonexistent/sweep.parquet`.
- `find_latest_sweep(empty_dir)` → `None`.
- `find_latest_sweep(missing_dir)` → `None`.
- Non-canonical filename → empty skips with full canonical 7-column schema.

### 5c801dd — `tests/test_web_discover.py`

**What works:**

- **13 tests covering every branch** of discover.py:
  - 3 empty/missing-dir cases (each returns `None`).
  - 4 multiple-parquet cases (single returned, newest-mtime wins, mtime-tied name-ASC, skipped-excluded-even-when-newer-mtime).
  - 4 read cases (missing → FileNotFoundError; missing companion → empty canonical skips; populated companion → returned with data; non-canonical filename → empty skips fallback).
  - 1 corrupt-parquet loud-failure case.
  - 1 streamlit-isolation source-level grep.
- **`test_mtime_ties_broken_by_name_ascending`** ([tests/test_web_discover.py:96-108](tests/test_web_discover.py#L96-L108)) — uses `os.utime(file, (t, t))` to force identical mtimes, then asserts the name-ASC tiebreaker wins. Right way to test a deterministic-tiebreak rule.
- **`test_skipped_parquet_excluded_alongside_real_sweep`** ([tests/test_web_discover.py:111-121](tests/test_web_discover.py#L111-L121)) — forces the skipped companion to be NEWER mtime via `os.utime`, then asserts the real sweep still wins. Catches the case where a future contributor "fixes" the skipped-filter by removing the `_skipped` check + relying on mtime alone.
- **`test_corrupt_parquet_raises_on_read`** ([tests/test_web_discover.py:207-217](tests/test_web_discover.py#L207-L217)) — pins the loud-failure path. **Important contract**: `find_latest_sweep` is metadata-only (it just stat's the file) and happily returns a corrupt parquet's path; the failure surfaces in `read_sweep_with_skips`. This is the right split (discovery cheap, read possibly-expensive) but the test pins it so a future refactor doesn't accidentally make discovery validate the file content.
- **`test_discover_module_imports_without_streamlit`** ([tests/test_web_discover.py:224-244](tests/test_web_discover.py#L224-L244)) — source-level grep for `"import streamlit"` + `"from streamlit"` in `src/web/discover.py`. **Compile-time check, not runtime.** Defends the §11.1 contract against future contributors. The comment notes the test would be silent if streamlit were already imported by an earlier test — the grep workaround is the right pragmatic choice.
- **Tests are pytest-fixture clean** (use `tmp_path` for isolation); no real data is touched.

**Live-verified:**
- `.venv/bin/python -m pytest tests/test_web_discover.py -v` → 13/13 in 0.10s.
- `.venv/bin/python -m pytest tests/` → **380/380** in 1.34s (was 367 + 13 new = matches).

**Blocking issues:** None.

**Non-blocking observations:**

1. **🔬 RESULTS_DIR patching pattern in tests is inconsistent with the project convention.** Tests #136-160 + #163-188 use `results_mod.RESULTS_DIR = tmp_path` + `importlib.reload(results_mod)` in `finally`. **The existing convention (established in 617878b)** is `monkeypatch.setattr(results_mod, "RESULTS_DIR", tmp_path)` — fixture-driven, auto-cleanup, idiomatic pytest. **Both work**, but the project already has the monkeypatch pattern documented in `tests/test_sweeper.py:_redirect_results` and `tests/test_iron_condor.py`. The new tests introduce a third pattern (direct assignment + reload) that adds:
   - Potential cross-module state leakage if a subsequent test in the same process imports things from `results_mod` before the `finally` runs.
   - `importlib.reload(results_mod)` triggers an `_inferred_dtype` re-execution that's unnecessary if the test just needed to swap `RESULTS_DIR`.
   - Inconsistency that future contributors will pattern-match against the wrong example.
   **Recommended improvement** (5-min refactor, no behavior change):
   ```python
   def test_read_returns_empty_skips_when_companion_missing(monkeypatch, tmp_path: Path):
       from src.engine import results as results_mod
       monkeypatch.setattr(results_mod, "RESULTS_DIR", tmp_path)
       p = _write_parquet(tmp_path / "sweep_xyz.parquet")
       df, skips = read_sweep_with_skips(p)
       # assertions...
   ```
   No `try/finally`, no `importlib.reload`. **Same fixture style as the existing test_sweeper.py / test_iron_condor.py.** Worth a small followup commit OR opportunistic fix during the next test-touching commit.

2. **DESIGN_SPEC §4 sequence deviation (p6.0.format skipped).** Two paths forward:
   - **Land `feat(p6.0.format)` + `test(p6.0.format)` next** before any rendering commits — keeps the §4 order intact.
   - **Reorder §4** to land format after discover with a §11 change-log entry acknowledging the swap.
   Either works; the first is less doc-touchy. The format helpers will be needed before any tab actually renders (Phase 6.2+), so they have to land before `feat(p6.2.headline)` at the latest.

3. **`test_corrupt_parquet_raises_on_read` uses bare `pytest.raises(Exception)`** ([tests/test_web_discover.py:216](tests/test_web_discover.py#L216)). Too broad — would silently pass even if pyarrow started raising a different error type (e.g., `ValueError` instead of `ArrowInvalid`). **Recommended tighten**: `pytest.raises((pa.lib.ArrowInvalid, OSError))` or whatever the actual error class is. Catching `Exception` defeats the purpose of pinning behavior. Cosmetic; very low-stakes.

4. **`test_discover_module_imports_without_streamlit` is a source-level grep, not an actual import-time check.** The test comment acknowledges this. **Alternative for stronger guarantee**: spawn a `subprocess.run([sys.executable, "-c", "import src.web.discover; import sys; assert 'streamlit' not in sys.modules"])` to actually verify the import doesn't pull streamlit into the process. Heavier; not worth it unless the grep starts producing false negatives. Stick with the grep.

5. **`_write_parquet` helper** ([tests/test_web_discover.py:62-75](tests/test_web_discover.py#L62-L75)) writes minimal 4-column data, not the canonical 22-column results schema. Fine for `find_latest_sweep` tests (which only stat files), but `test_read_returns_populated_skips` reads the result and could break if a future test asserts column presence. **Minor**: not a current blocker; just noting the test fixture would need a canonical-schema upgrade if assertions on results_df columns are added later.

**Domain / correctness checks:**

- **Determinism**: ✓ `(-mtime, name)` sort key gives stable output across re-listings.
- **Streamlit isolation**: ✓ source-level enforced.
- **Loud-failure discipline**: ✓ FileNotFoundError on missing results; pyarrow exception on corrupt; no silent fallbacks.
- **Canonical-schema preservation**: ✓ empty skips frame uses `empty_skips_frame()` (verified in smoke test — 7 canonical columns).
- **§11.2 contract literal**: every requirement in the SPECS §11.2 paragraph is exercised by a test (the test docstrings cross-reference the spec). Audit trail intact.

**What I tried:**
- Read `src/web/discover.py` end-to-end.
- Read `tests/test_web_discover.py` end-to-end.
- Live smoke-tested `find_latest_sweep()` and `read_sweep_with_skips()` against the real `data/results/` parquet.
- Live-tested 5 edge cases (missing path, empty dir, nonexistent dir, non-canonical filename, FileNotFoundError).
- Ran the discover test file → 13/13. Full suite → 380/380.
- Cross-checked the SPECS §11.2 contract literal against the implementation — every requirement honored.

**Sequencing observation:** First Phase-6 code lands cleanly. The impl + test pair is the right granularity — neither commit is reviewable in isolation (impl without test is unverified; test without impl is empty). BUILDER landed them ~80 seconds apart with the test commit explicitly named `test(p6.1.discover)` so the pair-relationship is captured in the log. Good shape.

**Next-commit suggestion:** Per DESIGN_SPEC §4, the remaining Phase 6.1 commits are:
1. `feat(p6.1.caveats)` — `src/web/caveats.py` per the reconciled SPECS §11.3 (three constants + `render_caveats_strip()` + `render_caveats_collapsed()`).
2. `feat(p6.1.empty)` — `src/web/empty_state.py` per DESIGN_SPEC §2.6 (6 pre-written degenerate-data messages).
3. `feat(p6.1.app)` — `app.py` (sidebar + 4 placeholder tabs + caveats strip).
4. `chore(p6.1.verify)` — `streamlit run app.py` against the verify parquet; screenshot every tab.

**My lean**: `feat(p6.1.caveats)` next. Two reasons:
- Caveats are content-driven (just constants + render helpers); no rendering choices yet.
- The §11.3 reconciliation already pinned the helper names + the dismiss-state-key — implementing against a fully-frozen contract is easier than implementing against the open `empty_state.py` design (which has 6 message strings still to author).

**Either of these is also defensible**:
- `feat(p6.0.format)` first to catch up with the §4 sequence (per my non-blocker #2).
- `feat(p6.1.empty)` first — it's pure data (6 strings) and lands without rendering.

**Opportunistic rider** for whichever commit next touches a test file: convert the `results_mod.RESULTS_DIR = ...` + `importlib.reload(...)` pattern in `test_web_discover.py` to the `monkeypatch.setattr` convention per non-blocker #1.

---

## Review of fd72b85 — docs(plan): Phase 6 scope freeze + Phase 7 expansion

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** User-directed scope decision ("ship 4 tabs as Phase-6 v1 and add the others to next phases") transcribed into PLAN.md. Two structural changes: (1) PLAN §3 Phase-6 commit list collapsed into a pointer to DESIGN_SPEC §4 to prevent parallel-list drift, (2) Phase-7 expanded with 4 considered-but-deferred tab additions. Compare-pairs tab considered + rejected with reasoning.

**What works:**

1. **Single-source-of-truth collapse for Phase-6 commits.** Previous PLAN.md §3 had 5 generic commits (skeleton / per-stock dashboard / trend / ranker / caveats); DESIGN_SPEC §4 has the precise 26-sub-commit breakdown. **Two parallel lists ARE a guaranteed drift surface** — exactly the kind of staleness pattern I flagged in my 8a49165 and b7fe7e5 reviews. Collapsing to "PLAN owns headline + exit criteria; DESIGN_SPEC owns granular plan" is the right factoring. Same discipline as moving caveats to canonical constants instead of duplicating verbatim copy.

2. **Phase-6 exit criteria expanded with two new bullets:**
   - "All four tabs render against the verify-set parquet without crashes; thin-data UX paths exercised per DESIGN_SPEC §2.6." — directly checks the §2.6 degenerate-data UX contract authored in 3880d9d. **Phase 6 won't ship until the empty-state / degenerate-data branches are exercised on the 18-trade verify set.** This is the right gate.
   - "Tagged `v0.6-ui` at completion." — matches DESIGN_SPEC §6 tagging discipline.

3. **Phase-7 expansion is well-scoped:**
   - **p7.1 trade-level drill-down** — "pick a (strategy, symbol, entry, exit, expiry) cell, render its ~3-30 actual trades with entry spot, exit spot, per-leg premiums, gross/net P&L." This is the most defensible Phase-6-deferred addition. The "show me the evidence behind the median" loop closes the operator-trust gap: ranking views show summary stats; this view shows the raw trades that produced them. **For an operator who's about to commit capital, this is the load-bearing diagnostic view.** Properly scoped as Phase-7-immediate rather than Phase-8+.
   - **p7.2 diagnostics** — "full skip-log breakdown ('180×MissingDataError, 20×NoLiquidStrike'), bhavcopy/options coverage map, run_id history". Operator tooling, not researcher tooling — answers "did my sweep cover what I asked for?". Right complement to the 4 researcher-facing tabs.
   - **p7.3 export buttons** — CSV + PNG via st.download_button. Closes DESIGN_SPEC §9 open Q explicitly. **Clean Phase-6 → Phase-7 boundary**: open Qs in DESIGN_SPEC get scheduled into the next phase rather than left as forever-pending.
   - **p7.4 regime drill-down** — surfaces classify_momentum output as data. "Which months are bullish, trailing-return distribution." Trust-building view; useful once multi-year data lands.

4. **Compare-pairs tab considered + REJECTED with reasoning**: "largely covered by Heatmap filter-switching + Leaderboard sorting; not unique enough." **Considered the alternatives**: rejection IS defensible but worth a future-flag — see non-blocker #1 below.

5. **Change-log entry 2026-05-25** records the freeze + decision rationale + the rejected alternative. **Matches the PLAN §7 discipline**: not just "I changed the plan", but "I changed the plan because X, considered Y and rejected because Z". Audit trail is intact.

**Live-verified:**
- `git show fd72b85 -- PLAN.md` — 30-line edit, 19+/11-, only PLAN.md touched. No code; no test regression possible.
- Cross-checked the DESIGN_SPEC §4 pointer: §4 does contain the 26-sub-commit breakdown (verified during 3880d9d review). The pointer resolves to real content.
- Confirmed change-log entry follows the dated-bullet convention (matches the 2026-05-24 entries above it).

**Blocking issues:** None.

**Non-blocking observations:**

1. **Compare-pairs rejection has one edge case worth flagging.** The rejection is defensible for the typical operator question "which pair is best overall?" (covered by Leaderboard sort) and "what's the offset window for this pair?" (covered by Heatmap). **But the question "is A better than B at this specific offset window?" is genuinely awkward in the current 4-tab structure** — you'd need to flip the Heatmap's strategy/symbol selectors back and forth, mentally retaining the prior cell value. **Not a blocker** — operators can do this with the existing tabs; just slower. **If user feedback during Phase-6 validation surfaces "I keep flipping back and forth between two strategies on the Heatmap", revisit compare-pairs for a Phase-8 addition.** Currently nothing forces this revisit; just flagging so it's not invisible.

2. **DESIGN_SPEC §4 26-commit list now load-bearing for Phase-6 planning.** Previously, PLAN.md and DESIGN_SPEC could disagree and a reader could check both. Now PLAN.md defers; DESIGN_SPEC IS the plan. **One side effect**: if DESIGN_SPEC §4 is ever revised mid-Phase-6 (likely — change logs already started), the running view of "what's left" lives only in the spec. Mitigations: change-log discipline (already in place at §11), git-blame on DESIGN_SPEC §4 commits. Acceptable.

3. **PLAN.md §3 Phase 7 commit list has both new (p7.1-p7.4) and existing (README, user-curated-universe, BLUE_CHIP_BY_QUARTER) items.** Ordering: the new tab-additions land first (1-4), then the polish/docs/data items (5-8). **Defensible ordering** — Phase-7 ships value-additions before retro-docs polish. Could also be argued the other way (close out Phase-6 polish + docs THEN add new tabs to Phase 7), but no real difference at this granularity.

4. **No DESIGN_SPEC change required** — PLAN.md now points TO DESIGN_SPEC, not vice versa. Asymmetric reference is fine; the design doc doesn't need to know about the freeze (it already pre-froze the 4-tab scope in 3880d9d's revision).

**Domain / correctness checks:**
- **User-directive traceability**: ✓ commit body quotes the user's direction verbatim ("ship 4 tabs as Phase-6 v1 and add the others to next phases") + dates the entry.
- **No code regression possible**: ✓ docs-only.
- **Plan ↔ Design consistency**: ✓ PLAN exit criteria for Phase 6 now references DESIGN_SPEC §2.6 (thin-data UX) — the docs reinforce each other instead of duplicating.

**What I tried:**
- Read the full PLAN.md diff.
- Cross-checked DESIGN_SPEC §4 → has the 26-commit breakdown referenced by PLAN.
- Re-read the rejected-alternative reasoning for compare-pairs; mentally tested against the "is A better than B at offset W" use case (flagged in non-blocker #1).

**Sequencing observation:** This is the right pre-code-work commit. With Phase-6 scope frozen, exit criteria pinned, and Phase-7 already scoped, BUILDER can land `feat(p6.0.format)` next without worrying about scope creep mid-implementation. **The scope-freeze + change-log discipline is exactly what prevents Phase-6 from drifting from 26 commits to 35.**

**Next-commit suggestion** (unchanged from my aae03c0 review):
1. `feat(p6.0.format)` — `src/web/_format.py` per DESIGN_SPEC §2.7.
2. `test(p6.0.format)` — boundary tests.

Then `feat(p6.1.discover)` per SPECS §11.2. First real Phase-6 code lands at that point.

**Status — Phase-6 readiness:** All preconditions met:
- ✅ Dependencies updated (d9f2cb2)
- ✅ SPECS §11 web contracts pinned (b7fe7e5 + 1c00f69)
- ✅ DESIGN_SPEC §4 26-commit roadmap is now PLAN's source of truth (fd72b85)
- ✅ All accumulated reviewer flags closed (aae03c0)
- ✅ Mockups properly named + README'd (aae03c0)
- ✅ 367/367 tests pass

Code work can start.

---

## Review of aae03c0 — chore: close 3 reviewer-flag cleanup items

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Single bundled cleanup commit closing 3 small non-blocking items I had been flagging across the prior 3-4 reviews (each individually too small for a nuclear commit; unified by "outstanding reviewer flags"). All non-blocking, none gated future work, but the bundle gets them off the followup ledger before Phase-6 code starts.

**What works — item-by-item closure:**

1. **🔬 std-bias math correction in [aggregate.py:43-47](src/analytics/aggregate.py#L43-L47)** — "~20% at n=5 → ~11%" correction now lives in the SUMMARY_COLUMNS docstring, with the **historical reviewer-error trail preserved in code**:
   > The original afdd56e review wording cited ~20% at n=5, which was the VARIANCE gap (1 − (n-1)/n); for STD the gap is the sqrt of that.
   
   **This is the right discipline.** Future contributors reading the docstring see the corrected number AND the WHY of the historical confusion. Matches DESIGN_SPEC §2.2 verbatim. Code change is comment-only — 367/367 unchanged.

2. **Mockup PNG renames + DESIGN/README.md** — `git mv image.png → leaderboard.png` etc., tracked as git renames (history preserved). New `DESIGN/README.md` provides:
   - **Mockup-to-commit table**: each PNG mapped to the specific Phase-6 §4 commits that implement it. The cross-check workflow is now mechanical — a Phase-6.3 reviewer can `open DESIGN/heatmap.png` without having to remember which "image copy N" was the heatmap.
   - **Mockup-bugs-not-to-inherit section**: explicitly catalogues the rupees-labeled-as-percentage and best-<-average bugs the user flagged in DESIGN_SPEC §11. **This carries the warning forward** — even if DESIGN_SPEC §11 ever gets compressed, the README preserves the gotcha for the next contributor.
   - **Cross-cutting-elements list** at the bottom — top bar, caveats row, sidebar layout. Useful onboarding doc for anyone implementing a tab.

3. **DESIGN_SPEC §9 strikethrough + RESOLVED** — both §9.5 and §9.6 are now ~~struck-through~~ with "**RESOLVED in 8893b81**" + exact code-location references. **Archival pattern: preserve the historical concern, don't delete it.** A future reader sees the original deferred-followup AND the resolution; the audit trail is complete.

**Live-verified:**
- `.venv/bin/python -m pytest tests/` → **367/367**. Only code change is the aggregate.py comment-edit.
- `ls DESIGN/` → `DESIGN_SPEC.md`, `README.md`, `heatmap.png`, `leaderboard.png`, `per_stock.png`, `trends.png`. The macOS auto-names are gone.
- Cross-checked the strikethrough wording — original text preserved inside `~~...~~`, new RESOLVED clause appended with the closing commit SHA + code locations. Audit-trail intact.
- Cross-checked the README mockup-bug note against my own viewing of the mockups in the 3880d9d review — both bugs match what's actually visible in the PNGs.

**Blocking issues:** None.

**Non-blocking observations:**

1. **Bundle-rationale check**: 3 unrelated items in one commit could be a nuclear-commit-discipline violation, BUT each item is too small for its own commit (1 comment edit + 4 git mvs + a strikethrough markup), the items are thematically united ("close accumulated reviewer flags"), and the bundle has zero coupling risk (no single change depends on another). **Bundling is correct here**; 3 separate commits would be churn. Same justification I applied to 8893b81 (the 7-flag-closeout bundle) — the principle is "bundle when the changes are cosmetic + thematically unified + risk-decoupled".

2. **The README cross-cutting-elements section** ([DESIGN/README.md:38p+](DESIGN/README.md)) describes "top bar: project name, sweep selector + run_id, last-updated timestamp, cache-fetch status". Looking at the mockups I viewed earlier in 3880d9d, the top bar does have these elements. **Worth verifying once `feat(p6.1.app)` lands** that the app implements the cross-cutting top bar per this README, not just per the mockup (which has the mockup-bugs caveat). Cosmetic; not blocking.

3. **DESIGN_SPEC §1.5 mtime picker dependency on 617878b** is STILL not documented (flagged in my 8a49165 + 3880d9d + 1c00f69 reviews). This wasn't in the 3-item closure list. Acceptable — it's the lowest-priority of the outstanding flags. **Next opportunity** when someone touches §1.5 or §8 wiring constraints.

**Domain / correctness checks:**
- **Reviewer-flag traceability**: ✓ commit body cross-references each closure to the originating review SHA (3880d9d, b7fe7e5, 8a49165). Auditable.
- **No regression risk**: ✓ comment edit + file renames + markdown strikethrough. 367/367 unchanged.
- **DESIGN_SPEC ↔ code consistency**: ✓ §2.2 wording now exactly matches `aggregate.py` SUMMARY_COLUMNS docstring.
- **Asymmetric-conservatism**: ✓ the corrected std-bias wording ("~11% at n=5") is the right "lower bound on true spread" interpretation — under-promise the consistency story by the right magnitude.

**What I tried:**
- `git show --stat aae03c0` — 7 files, mostly renames + 1 markdown edit + 1 comment edit + 1 README creation.
- Verified the rename detection: git correctly identifies `image.png → leaderboard.png` etc. as renames (not separate adds + deletes), so the PNG content is preserved in history.
- Read DESIGN/README.md end-to-end.
- Confirmed the strikethrough preserved original §9 wording (essential — losing the original would break the audit trail).
- Ran the full test suite: 367/367.

**Sequencing observation:** This is the cleanest "Phase-N close-out" pattern: between two phase boundaries (Phase-5 done; Phase-6 about to start landing code), batch-close the accumulated reviewer flags. By the time `feat(p6.0.format)` lands, the followup ledger is empty and code reviews can focus on the actual implementation. Same pattern as 8893b81 ("close 7 flags between Phase 5 and Phase 5.verify"), now applied at the Phase-5 → Phase-6 transition.

**Outstanding non-blockers status after this commit:**
- ✅ std-bias math correction → CLOSED (this commit)
- ✅ Mockup PNG filenames → CLOSED (this commit)
- ✅ DESIGN_SPEC §9 staleness → CLOSED (this commit)
- 🔄 §1.5 mtime picker ↔ 617878b dependency note → still open; lowest priority

**Next-commit suggestion:** Per DESIGN_SPEC §4, Phase 6 code starts with:
1. `feat(p6.0.format)` — `src/web/_format.py` per §2.7. `format_inr(x)` for ₹1L / ₹1Cr thresholds; `format_pct(x, *, signed, annualized)` for ROI vs. P&L disambiguation.
2. `test(p6.0.format)` — boundary tests (₹99,999 → "₹99,999"; ₹1,00,000 → "₹1.00 L"; ₹99,99,999 → "₹99.99 L"; ₹1,00,00,000 → "₹1.00 Cr"; sign handling for ROI; integer formatting for counts).

**These two should land as a pair** — code without a test is incomplete; one is meaningless without the other. The previous BUILDER convention has been `feat + test` as separate commits but the test always lands within ~5 minutes of the feature. Approve either approach.

After `feat(p6.0.format)` + `test(p6.0.format)` → `feat(p6.1.discover)` per §11.2 contract. The first real Phase-6 module.

---

## Review of 1c00f69 — fix(p6.0.spec): SPECS §11 reconciliation with DESIGN_SPEC §1.4 revised caveats

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Land the 3-line doc-reconciliation I flagged as blocking-`feat(p6.1.caveats)` in the b7fe7e5 review. Reconcile SPECS §11.3 with DESIGN_SPEC §1.4's revised three-card-with-dismiss caveats design. **Closes all 4 items I flagged** (1 blocking + 3 non-blocking) in a single docs-only commit.

**What works (item-by-item closure of my b7fe7e5 review flags):**

1. **🔬 Blocking §11.3 caveats reconciliation** — closed verbatim per my recommendation. `render_caveats_expander` → `render_caveats_strip` + `render_caveats_collapsed`. New wording cross-references DESIGN_SPEC §1.4 and explicitly notes "the original expander design which is now superseded" — leaves no ambiguity for a future contributor about which design wins. Session state key `mp_caveats_dismissed` follows the `mp_` namespace prefix from §11.4. **Dismiss is session-scoped, never persisted to disk** — exact wording from DESIGN_SPEC §1.4.

2. **§11.3 caveat-string source-of-truth note (non-blocker #1)** — closed: "Exact wording is authored alongside the constants in `feat(p6.1.caveats)` — the verbatim string is the source of truth; this section pins only the existence + 'one paragraph each' length contract." Prevents SPECS-vs-code drift on the actual caveat text.

3. **§11.2 empty_skips_frame() (NOT None) clarity (non-blocker #2)** — closed: "callers can `.groupby('skip_reason')` unconditionally without a truthy check". Saves every Phase-6.3+ consumer the same defensive `if skips is None` guard.

4. **§11.1 `__init__.py` policy (non-blocker #3)** — closed: "stays empty; no package-level re-exports... would import every submodule including the streamlit-importing tab modules, defeating §11.1's test-isolation rule". Excellent rationale — captures WHY re-exports would break the test-isolation guarantee, not just "don't do it".

**Live-verified:**
- `.venv/bin/python -m pytest tests/` → **367/367** in 1.47s. Docs-only commit; no regression.
- Read the entire diff. 4 hunks; all in SPECS.md §11; lines net.
- Cross-checked the new §11.3 against DESIGN_SPEC §1.4 — wording matches; helper names match; session_state key matches.

**Blocking issues:** None.

**Non-blocking observations:**

1. **The closure is clean enough that there's nothing else to flag in §11.** I re-read SPECS §11 in full after the fix; no remaining drift with DESIGN_SPEC. The contract is now self-consistent for `feat(p6.1.caveats)` to implement against.

2. **Sequencing note**: this is the right pattern for the BUILDER↔REVIEWER loop. I flagged 4 items in the b7fe7e5 review (1 blocking + 3 non-blocking). BUILDER closed all 4 in one ~30-line follow-up commit before any code lands. **Total cost ≈ 5 minutes; alternative cost = a refactor of `src/web/caveats.py` once it's been built against the wrong contract.** This is the kind of pre-code doc reconciliation the nuclear-commits + reviewer-loop pattern is designed to surface.

3. **Outstanding non-blockers from prior commits still open** (not regressed, just unaddressed — fine to bundle into a single doc-touchup whenever someone has DESIGN_SPEC.md open):
   - DESIGN_SPEC §9.5 + §9.6 still describe deferred verify_p5 + StringDtype followups that 8893b81 closed (flagged in my 8a49165 + 3880d9d reviews).
   - Mockup PNG filenames are still `image.png` / `image copy N.png` (flagged in my 3880d9d review).
   - §1.5 mtime picker dependency on 617878b's test-fixture-leak fix is still undocumented (flagged in my 8a49165 + 3880d9d reviews).
   These are low-stakes; opportunistic riders for whenever someone next touches `DESIGN/`.

**Domain / correctness checks:**
- **Cross-doc consistency**: ✓ §11.3 ↔ DESIGN_SPEC §1.4 reconciled.
- **Asymmetric-conservatism**: ✓ the dismiss-to-banner pattern is now contract-pinned, not just design-described. Code-level honesty contract preserved.
- **Test isolation**: ✓ the `__init__.py` empty-policy clarification protects the `MUST NOT import streamlit at module time` guarantee for unit tests.

**What I tried:**
- `git show 1c00f69` — 4 hunks, all docs, all in SPECS.md.
- `.venv/bin/python -m pytest tests/` → 367/367.
- Cross-checked new §11.3 wording against the recommendation block in my b7fe7e5 review — substantially matches the recommended fix. BUILDER also added the `mp_` namespace prefix for `mp_caveats_dismissed` (matching §11.4 convention) — that was implicit in my recommendation but BUILDER made it explicit. Small improvement on my suggestion.

**Sequencing observation:** Three doc commits in a 12-minute span (3880d9d → b7fe7e5 → 1c00f69) — typical iteration cost for a design-heavy phase boundary. **Phase-6 code work is now properly gated by self-consistent contracts.** Going forward, `feat(p6.0.format)` + `feat(p6.1.discover)` + `feat(p6.1.caveats)` can all land without worrying about doc drift.

**Reviewer-loop credit**: BUILDER also explicitly credited the review in the commit body ("Reviewer (b7fe7e5 review) caught a real drift") — this kind of attribution helps future contributors understand the WHY for the small-fix commit. The pattern is being internalized.

**Next-commit suggestion:** Resume the Phase-6.0 sequence:
1. `feat(p6.0.format)` — `src/web/_format.py` per DESIGN_SPEC §2.7 (Indian lakhs/crores `format_inr` + `format_pct`).
2. `test(p6.0.format)` — boundary tests (₹1L threshold, ₹1Cr threshold, sign handling, ROI-without-sign vs P&L-with-sign).

After that → `feat(p6.1.discover)` (sweep-discovery module per §11.2). The first real Phase-6 code lands at that point.

**Opportunistic rider** for any subsequent doc-touching commit (still 5-minute total, prevents future "still pending" confusion): close the 3 outstanding non-blockers listed above (DESIGN_SPEC §9 staleness, mockup filenames, §1.5 mtime dependency note). All in `DESIGN/DESIGN_SPEC.md`; one commit; no SPECS interaction; no code touched.

---

## Review of b7fe7e5 — chore(p6.0.spec): SPECS §11 — web layer contracts (Phase 6)

**Verdict:** ⚠ accept-with-followup — **SPECS §11.3 drifts from DESIGN_SPEC §1.4 revised design**. Doc fix needed before `feat(p6.1.caveats)` lands.

**Phase / commit goal (as I understood it):** Pin the load-bearing contracts the `src/web/` package must honor. SPECS = contracts, DESIGN_SPEC = architecture. 6 subsections covering module layout, sweep discovery, caveat constants, session-state convention, min_n flow, universe shape. Docs-only; no code; 367/367 still passes.

**What works:**

- **Clear separation of concerns**: "DESIGN_SPEC.md owns the UI architecture; SPECS §11 pins the contracts" — the right split. Architecture can flex via the §11 change-log discipline; contracts are frozen so module signatures don't churn.
- **§11.1 module layout** is correct: `app.py` thin entry, `src/web/{discover,caveats,leaderboard,heatmap,trends,per_stock}.py` separated. **The "MUST NOT import streamlit at module time"** discipline ([SPECS.md §11.1](SPECS.md#L760)) is exactly the right rule for unit-testability — `discover.py` will be tested without a Streamlit context.
- **§11.2 sweep discovery contract** is fully specified: `find_latest_sweep(results_dir=RESULTS_DIR) -> Path | None`, `read_sweep_with_skips(parquet_path) -> tuple[DataFrame, DataFrame]`. **The `None` return on empty results_dir** is the right contract — forces the caller to render a "no sweeps yet" message instead of crashing. **The mtime rationale is cross-referenced** to DESIGN_SPEC §1.5 — single source of truth for the WHY.
- **§11.2 explicitly rejects "largest by row count"** as a discovery rule, citing the stale-but-big silent-outranking concern. **Good documentation of the rejected alternative**: future contributors won't reintroduce verify_p5's logic into the UI by accident.
- **§11.4 state-key prefix `mp_`** — namespace convention prevents accidental collision with other apps' session_state if the UI is ever embedded. Cheap discipline.
- **§11.5 min_n single-source-of-truth** — sidebar slider drives BOTH leaderboard ranker AND heatmap masking. Pins the wiring constraint at the contract layer, not just the design layer.
- **§11.6 universe as `list[str]` everywhere** — Phase-7 user-curated-universe becomes a sidebar text-area conversion. Forward-compatibility baked into the contract.
- **No code; no tests; 367/367 still passes** — true docs-only commit.

**🔬 Blocking issue (NON-CODE — doc reconciliation, but blocks `feat(p6.1.caveats)`):**

**§11.3 describes the OLD expander design; DESIGN_SPEC §1.4 was revised in 3880d9d to use a NEW three-card-with-dismiss design.** Specifically:

SPECS §11.3 (this commit):
> `src.web.caveats.render_caveats_expander()` renders all three as labeled sub-sections inside a single `st.warning`-styled `st.expander` (per DESIGN_SPEC §1.4 — **one expander, open by default, banner-blindness mitigation**).

DESIGN_SPEC §1.4 (revised in 3880d9d):
> Render **three side-by-side cards** at the top of every tab, each holding one caveat. A "Read once, then dismiss" link collapses the row into a slim **single-line banner**...
> `[REVISED 2026-05-25 — mockup alignment; stronger honesty contract than the original expander design]`

**Helper-name drift too**:
- SPECS §11.3 names it `render_caveats_expander()`.
- DESIGN_SPEC §4 names it `render_caveats_strip()` (three cards) **+** `render_caveats_collapsed()` (slim banner).

This is the same staleness pattern I flagged in 8a49165 (the change-log entry covering §§1-8 + §10 left §9 unaudited). Here, BUILDER apparently wrote SPECS §11.3 against the original (pre-3880d9d) DESIGN_SPEC §1.4 wording, missing the 2026-05-25 revision that landed ~4 minutes earlier in 3880d9d.

**Recommended fix (lands in a tiny follow-up commit before `feat(p6.1.caveats)`)**:

Replace SPECS §11.3's last paragraph with:

> `src.web.caveats.render_caveats_strip()` renders all three as side-by-side cards at the top of every tab (per DESIGN_SPEC §1.4 — three always-visible cards, stronger honesty contract than an expander). Companion `render_caveats_collapsed()` renders the slim single-line "⚠ 3 active caveats — click to expand" banner used after `st.session_state["mp_caveats_dismissed"] = True`. Dismiss state is session-scoped (browser refresh re-expands).

This is a 3-line edit. **It MUST happen before `feat(p6.1.caveats)` lands** — otherwise BUILDER will implement against the old contract and have to refactor in `feat(p6.1.app)` when the mockup-driven design surfaces. **Cheaper to fix the doc now (3 lines) than to refactor the code later (whole module).**

(Bonus: while reconciling, also rename the session_state key in §11.4 to be consistent — `mp_caveats_dismissed` is the natural name once §11.3 commits to the dismiss-to-banner pattern.)

**Non-blocking observations:**

1. **§11.3 SURVIVORSHIP_CAVEAT + MARGIN_TIER_B_CAVEAT constants have no body text yet.** SPECS describes them ("paraphrases SPECS §6b.3"; "summarizes SPECS §4a caveats 1, 3, 4") but doesn't pin the actual string verbatim. The MULTIPLE_COMPARISONS_CAVEAT precedent (450-char specific text in `src.analytics.rank`) suggests these two should also be pinned in a constants module — probably during `feat(p6.1.caveats)` since that's the file that creates them. **Worth a SPECS §11.3 note**: "exact wording authored alongside the constants; verbatim string is the source of truth, this section pins only the existence + length-of-paragraph contract."

2. **§11.2 doesn't pin the empty-state contract for `read_sweep_with_skips`** when the companion `*_skipped.parquet` is missing. The text says "Read the companion `*_skipped.parquet` if present; otherwise return `empty_skips_frame()`." — but is this an empty-canonical-schema frame or `None`? Body says `empty_skips_frame()` (from `src.engine.results`), which is the canonical-schema-empty version. ✓ Consistent with §11.2's "Both frames preserve their canonical schemas" — but worth one explicit sentence "missing skips → `empty_skips_frame()` (NOT `None`)" so the caller never branches on truthy checks.

3. **No `__init__.py` policy** stated. Convention is empty `src/web/__init__.py`; should be made explicit ("public modules; no re-exports at the package level") so future contributors don't add a `from . import *` import that defeats §11.1's "no module-time streamlit imports" rule.

**Domain / correctness checks:**
- **Asymmetric-conservatism**: ✓ The contract for caveats (constants + helper + always-rendered) extends the honesty discipline to the UI. The dismiss-to-banner reconciliation is the only doc-drift gap, not a design regression.
- **Cross-doc consistency**: ⚠ §11.3 vs DESIGN_SPEC §1.4 — flagged above.
- **Module testability**: ✓ §11.1 forbids module-time streamlit imports in helpers; this is what enables `tests/test_discover.py` etc. to run in a regular pytest context.

**What I tried:**
- `git show b7fe7e5` — confirmed 1 file (SPECS.md), +84 lines.
- Read SPECS §11 end-to-end; cross-checked against DESIGN/DESIGN_SPEC.md sections it references.
- Confirmed the §11.3 vs §1.4 drift by side-by-side comparison of the two texts.
- Confirmed §11.5 + §11.6 match DESIGN_SPEC §8 wiring constraints #4 + #1.
- Read the §11.2 sweep-discovery contract against DESIGN_SPEC §1.5 — consistent (both mtime-based, both reject row-count-based).
- Verified 367/367 still passes (`.venv/bin/python -m pytest tests/` → no change, no code touched).

**Sequencing observation:** Two doc commits 3 minutes apart (00:41:51 → 00:44:49) — the drift opportunity was always there. Process suggestion: when DESIGN_SPEC.md and SPECS.md both touch the same architectural primitive (caveats, sweep-discovery, etc.), the second commit should re-read the first's relevant sections before authoring. The fix is 3 lines; the lesson is "design docs are a graph, not a list — when one node changes, audit incoming references."

**Next-commit suggestion (revised order, given the drift):**

**My lean — do the doc reconciliation FIRST, then proceed:**

1. **`docs(p6.0.spec.fix): reconcile SPECS §11.3 with DESIGN_SPEC §1.4 revised caveats design`** — 3-line edit per the recommendation above. Renames helper to `render_caveats_strip` + `render_caveats_collapsed`, updates the paragraph, adds the dismiss-state-key naming for §11.4. **5-minute commit, prevents a 30-minute Phase-6.1 refactor.**
2. `feat(p6.0.format)` — `src/web/_format.py` per DESIGN_SPEC §2.7 (Indian lakhs/crores helper + percent formatter).
3. `test(p6.0.format)` — boundary tests.

If BUILDER chooses to skip the doc reconciliation, **the next code commit's review will flag whichever doc the code matched and recommend updating the other one**. The drift WILL surface; deferring it just makes the surfacing commit messier.

**Opportunistic riders** (same as 3880d9d / d9f2cb2 reviews; bundle into the doc-fix commit if doing one):
- Mark DESIGN_SPEC §9.5 + §9.6 as `RESOLVED in 8893b81`.
- `git mv` mockup PNGs to `leaderboard.png` / `per_stock.png` / `heatmap.png` / `trends.png`.

---

## Review of d9f2cb2 — chore(p6.0.deps): add plotly, drop altair from requirements.txt

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** First Phase-6 commit. Single-file mechanical edit. Adds `plotly>=5.20.0` (required for `graph_objects.Heatmap` + `customdata` tooltip composition per DESIGN_SPEC §2.1) and drops `altair` (DESIGN_SPEC §2.1 conditional satisfied: grep-clean across `src/`, `tests/`, `scripts/`).

**What works:**
- **Smallest-possible commit shape**: 1 file, +4/-1 lines. The smallest nuclear-commit-sized opener for Phase 6.
- **In-line comment explains the WHY**, not the what, on the new dep line. References DESIGN_SPEC §2.1 by section number — future contributors find the rationale.
- **Local-verification claim documented** in the commit body ("pytest → 367/367 (no regression — confirming the grep result)"). The grep + the test suite are independent checks; both passing is the right gate.

**Live-verified:**
- `import plotly` → installed at 6.7.0 (well above the `>=5.20.0` floor).
- `import altair` → `ModuleNotFoundError` (gone).
- `grep -rn "altair\|import altair\|from altair" src/ tests/ scripts/` → 0 matches. Grep is clean; the DESIGN_SPEC §2.1 conditional ("drop altair if a repo-wide grep shows no in-tree usage") is satisfied.
- `.venv/bin/python -m pytest tests/` → **367/367** in 1.41s. No regression.

**Blocking issues:** None.

**Non-blocking observations:**

1. **Local install is plotly 6.7.0; requirement floor is 5.20.0.** That's intentional ("pin the floor; don't cap the ceiling"). Plotly 6.x introduced a few breaking changes (e.g., the new `plotly.express.imshow` API; removal of some deprecated paths), but `graph_objects.Heatmap` + `customdata` — the API DESIGN_SPEC §2.1 commits to — has been stable since Plotly 4. **No action needed**; just noting the floor-vs-installed delta for the record. If a future contributor pins a fresh venv at exactly 5.20.0, the same Heatmap code will work.

2. **`requirements.txt` doesn't have a hash-pin / lockfile.** Per DESIGN_SPEC §6 dependency policy ("pin in requirements.txt to versions that produced a passing test suite; bump deliberately"), this is consistent with project convention. Hash-pinning is a Phase-7+ tooling concern.

3. **`>=5.20.0` is the right floor.** Plotly 5.20 (March 2024) ships the modern `graph_objects.Heatmap` with `customdata`/`hovertemplate` interop. 5.19 had a known bug where multi-dim `customdata` got flattened in some hover paths. The floor avoids that.

**Domain / correctness checks:**
- **Determinism**: ✓ no functional changes; only dependency surface.
- **No silent breakage**: ✓ pytest passes; grep is clean.
- **Spec traceability**: ✓ commit body cites DESIGN_SPEC §2.1; the §2.1 → p6.0.deps → requirements.txt traceability holds.

**What I tried:**
- `.venv/bin/python -c "import plotly; import altair"` — plotly 6.7.0; altair ModuleNotFoundError. Both as expected.
- `grep -rn "altair" src/ tests/ scripts/` — 0 matches.
- Full pytest → 367/367.

**Sequencing observation:** This is the right first Phase-6 commit. Single-file, mechanical, instantly reversible if needed, unblocks every subsequent Plotly-using commit (`feat(p6.3.pivot)`, `feat(p6.4.yoy)`, etc.). **My 3880d9d review block recommended starting with this commit — BUILDER followed through.** Good responsiveness.

**Next-commit suggestion:** Per DESIGN_SPEC §4, the remaining Phase-6.0 sequence:
1. ✅ `chore(p6.0.deps)` — **landed here.**
2. `chore(p6.0.spec)` — SPECS §11 web/ page contract; sweep-discovery rule; canonical caveat copy as constants. **My lean: next.** Pins the public surface that the Phase-6.1 modules will implement against. Easier to land before code than to reverse-engineer afterward.
3. `feat(p6.0.format)` — `src/web/_format.py` per DESIGN_SPEC §2.7. The `format_inr(x)` helper + percent formatter.
4. `test(p6.0.format)` — boundary tests (₹1L threshold, ₹1Cr threshold, sign handling, ROI-without-sign vs P&L-with-sign).

**Opportunistic riders** (not blocking, fit in the next doc-touching commit):
- Mark DESIGN_SPEC §9.5 + §9.6 as `RESOLVED in 8893b81` (still stale from my prior reviews).
- `git mv` the 4 mockup PNGs to `leaderboard.png` / `per_stock.png` / `heatmap.png` / `trends.png` per my 3880d9d review block.

---

## Review of 3880d9d — docs(design): move DESIGN_SPEC → DESIGN/, add 4 tab mockups, update doc paths

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Re-home design artifacts under `DESIGN/` + land 4 tab mockups. Doc move + spec edit + binary asset addition. **The diff isn't a pure move**: DESIGN/DESIGN_SPEC.md is 364 lines vs. the deleted root version's 249 — user authored ~115 lines of substantive content on top of the move. Mockup-coherence pass + correctness audit + new sections.

**What's new in the spec (per the §11 2026-05-25 change log entry I cross-checked against the diff):**

1. **§1.2 per-stock quick-switcher** — explicit hazard prevention ("sidebar canonical, switcher is navigation only"; clicking does NOT mutate the sidebar filter). Cleanly resolves the two-sources-of-truth tension the mockup might have invited.
2. **§1.4 caveats: revised from "expander, open by default" → "three always-visible cards + dismiss-to-banner"**. Stronger honesty contract — operator can't skip past the first read; even after dismiss the slim banner is always rendered. Session-scoped dismiss (no disk persistence). **This is a meaningful upgrade** — the expander could be trained-to-ignore; the cards force the read.
3. **🔬 §2.2 std-tooltip math correction (~20% → ~11% at n=5)** — **the user caught a math error in my afdd56e review block**. I cited "20% at n=5" which was the **variance** gap; for **std** the gap is `1 - sqrt((n-1)/n)` ≈ 10.6%. Verifying:
   ```
   var ratio = (n-1)/n   = 4/5 = 0.800  →  20.0% variance understatement
   std ratio = sqrt(0.8)        = 0.894  →  10.6% std understatement
   ```
   **The user is right; my afdd56e review wording was wrong.** Variance and std are off by a sqrt; I conflated them. Going forward the §2.2 wording (`~11% at n=5, ~5% at n=10, ~2.5% at n=20`) is what Phase-6 tooltips should render. Acknowledging — historical reviews don't get edited, but the corrected number is now the contract.
4. **§2.3 dark theme + diverging colormap unconditionally** — defensive: "first negative cell on a later sweep would render mid-green and mislead" is the right concern. Pinned `RdYlGn` + `zmid=0`. Matches every mockup's dark theme.
5. **§2.5 NEW — headline stats strip per-tab contract**. Pins exactly which cards each tab shows + a **naming rule** that structurally prevents the "AVG ROI ₹25.76L" mockup bug (rupees mislabeled as percentage). Per-tab contracts table is concrete (4-card / 3-card strips with value source + subtitle). **This is the right structural fix** — turning a mockup glitch into a code-enforced contract.
6. **§2.6 NEW — degenerate / thin-data UX contract**. Six pre-written `st.info` messages for "not enough data" cases per tab. Explicit operator action in each. "Never render a `nan` axis or a one-bar bar chart and call it a trend." Exactly the asymmetric-conservatism mandate applied at the UI layer.
7. **§2.7 NEW — number formatting contract**. Indian lakhs/crores (`₹X.XX L`, `₹X.XX Cr`); one `format_inr()` helper in `src/web/_format.py`; rounding rules pinned per quantity type. Lands as a new commit `feat(p6.0.format)` + companion test.
8. **§4 commit count grew 19 → 26**. Added `p6.0.format` + `p6.0.format test` + `p6.1.empty` + one `headline` commit per tab; replaced `p6.4.n_hover` with `p6.4.yoy_n` (the YoY sister chart visible in the Trends mockup). Each individual commit still nuclear-sized.
9. **§10 NEW — 5-minute operator user journey**. Concrete walkthrough where the operator runs the §3.2 sweep, lands on Leaderboard, drills into HDFCBANK iron condor, validates via heatmap → trends → regime filter. **This is the usefulness check the design needed** — proves the architecture supports the actual research workflow, not just looks coherent on paper. The journey identifies exactly which design choice each step depends on (cross-tab state via st.tabs, sidebar canonicality, sister chart for "is the drift real or N-fluke"). If the journey ever stops flowing, the corresponding design decision is the regression.

**Mockups (binary assets):**
- 4 PNGs at 3600×2338, totalling ~3.2 MB. Reasonable for design references in a non-binary-heavy repo.
- Viewed Leaderboard, Per-stock, Heatmap, Trends mockups. Each renders the dark theme + 3 caveat cards + tab-specific layout from the spec.
- **The mockup bugs the user calls out in §11 are real and visible**:
  - Leaderboard mockup labels a `₹25.76 L` value as "AVG ROI" — rupees mislabeled as a percentage. §2.5's naming rule prevents code from inheriting this.
  - Heatmap mockup shows `AVG ROI +264.1 %/yr` alongside `BEST CELL +82.3 %/yr` — best can't be lower than average; mathematically impossible. User notes "reconcile before screenshots are reused as docs."
  - Heatmap mockup's colormap looks sequential green (all-positive cells) — §2.3's `RdYlGn + zmid=0` mandate explicitly catches this.

**Blocking issues:** None.

**Non-blocking suggestions:**

1. **🔬 §9 stale-followup items NOT audited.** Same issue I flagged in 8a49165 review: §9.5 (verify_p5 prints unmasked heatmap) and §9.6 (StringDtype drifts to object) BOTH describe deferred followups that **8893b81 closed**. The 2026-05-25 change log entry mentions §§1-8 + §10 but leaves §9 untouched. **Recommended edit (~3 lines)**: in the next doc-touching commit, mark §9.5 + §9.6 as `RESOLVED in 8893b81` and prepend the resolved items with "~~struck-through~~ +RESOLVED note". Future contributors reading §9 will otherwise think these are still pending.

2. **🔬 Mockup filenames are unhelpful for the cross-check workflow.** The commit body says "each commit will be cross-checked against the matching tab image", but the filenames are:
   ```
   image.png            — Leaderboard tab
   image copy.png       — Per-stock tab
   image copy 2.png     — Heatmap tab
   image copy 3.png     — Trends tab
   ```
   These are macOS's default "Save → Copy" auto-names. To actually check a Phase-6 commit against the right mockup, a contributor has to remember the mapping (Heatmap = `image copy 2`? `image copy 3`?). **Recommended rename** (single subsequent doc commit, no spec edit needed):
   ```
   git mv "DESIGN/image.png"           DESIGN/leaderboard.png
   git mv "DESIGN/image copy.png"      DESIGN/per_stock.png
   git mv "DESIGN/image copy 2.png"    DESIGN/heatmap.png
   git mv "DESIGN/image copy 3.png"    DESIGN/trends.png
   ```
   Plus a `DESIGN/README.md` mapping each PNG to the §4 commit it scopes (e.g., `leaderboard.png` → `p6.2.headline + p6.2.table + p6.2.thin + p6.2.toggle`). Cheap; high-leverage for the next 26 commits.

3. **§1.5 still says "newest by mtime" without referencing the 617878b test-fixture-leak fix** as a load-bearing prerequisite. Same concern from my 8a49165 review block. Either §1.5 references 617878b OR §8 adds "all `RESULTS_DIR` consumers must be in `_redirect_results`" as a wiring constraint. Still non-blocking.

4. **Spec ↔ code drift surface area** — DESIGN_SPEC.md is now 364 lines + 4 PNGs + a 26-commit roadmap. **The `[REVISED YYYY-MM-DD]` discipline in §11 is what keeps this from rotting**. As Phase 6 actually lands, departures from the spec should land in this changelog, not in commit messages. The change-log discipline is already 2 entries deep (2026-05-24 + 2026-05-25) — good momentum; keep it.

**Doc internal-consistency checks:**
- §2.5 "headline stats strip per-tab contract" matches §4 commit sequence (each tab gets a `*.headline` commit before the main visual). ✓
- §2.6 "degenerate/thin-data UX contract" matches §4's `feat(p6.1.empty)` commit which creates `src/web/empty_state.py`. ✓
- §2.7 "number formatting" matches §4's `feat(p6.0.format)` + `test(p6.0.format)` commits. ✓
- §10 operator journey references "sister chart" — matches §4's new `feat(p6.4.yoy_n)` which replaced `p6.4.n_hover`. ✓
- §10 references "per-stock quick-switcher" — matches §1.2's new sub-section AND §4's `feat(p6.5.headline)` which includes the switcher. ✓
- §0.1 reviewer-flag table — all 6 origin SHAs still match real review commits (416719f, 955d0f3, 416719f, afdd56e × 2). ✓

**What I tried:**
- `git show 3880d9d` — confirmed the move + 4 PNG additions + PROJECT_DESCRIPTION.md path tweaks + spec content delta.
- Read DESIGN/DESIGN_SPEC.md end-to-end; cross-referenced §§ against the §11 change log entries.
- Verified the std-bias math correction (0.8 vs sqrt(0.8) → ~20% var, ~11% std). **User caught my afdd56e error.**
- `file DESIGN/*.png` — all valid 3600×2338 PNGs.
- Viewed all 4 mockup PNGs in turn. Confirmed the dark theme + 3-card caveat row + tab-specific layouts match the spec. Confirmed the two mockup bugs the user flagged in the change log are real.
- Cross-referenced §0.1's reviewer-flag SHAs against git log. All 6 commits exist.

**Sequencing observation:** The 2026-05-25 spec revision is substantial (~115 lines of new content). BUILDER could have split this into a "doc move" commit + a "spec amendment" commit; bundling is defensible since the move is what triggered the mockup-coherence audit. **One-commit policy isn't violated**: the mockup-coherence pass is the *reason* for the move, and §11 documents the audit. Acceptable bundle.

**Next-commit suggestion:** Per the user-revised §4, the Phase-6 sequence now starts with:
1. `chore(p6.0.spec)` — SPECS §11 web contract.
2. `chore(p6.0.deps)` — `requirements.txt` (add plotly, drop altair).
3. `feat(p6.0.format)` — `src/web/_format.py` per §2.7.
4. `test(p6.0.format)` — boundary tests.

**My lean**: `chore(p6.0.deps)` first (smallest mechanical commit, single-file edit, unblocks any Plotly-using commit). Then `chore(p6.0.spec)` to lock SPECS §11. Then `feat(p6.0.format)` + its test as a pair. **Opportunistic riders**: if BUILDER touches DESIGN_SPEC.md again before Phase 6.1 starts, batch the §9 staleness fix + the mockup filename rename — they're 5-minute edits that improve the cross-check workflow over the next 26 commits.

---

## Review of 8a49165 — docs: PROJECT_DESCRIPTION + DESIGN_SPEC

**Verdict:** ✅ accept (docs-only; not exercising)

**Phase / commit goal (as I understood it):** Two new top-level docs. PROJECT_DESCRIPTION.md is the README-grade overview for a fresh reader of the repo. DESIGN_SPEC.md (**authored by the user**, per commit body) is the Phase-6 UI architecture pinning 17 decisions so the next ~19 commits don't relitigate them. Neither file touches code.

**What works — PROJECT_DESCRIPTION.md:**
- **Clean four-tier explanation**: what it does → what's done (table form) → how structured → how built → tech stack → how to run. Reads top-to-bottom for a stranger.
- **Phase-status table** with ✅/🚧/📋/🔒 — communicates "where we are" in one row scan.
- **Verify-script CLI output included verbatim** — `rank=1 short_straddle × RELIANCE N=18 ... ~30ms` — gives a concrete number a fresh reader can grep for in `scripts/verify_p5.py` to anchor the abstract description.
- **"How it's built" section** captures the dual-agent + nuclear-commit + no-silent-filtering + honest-data-first contract that this whole project hinges on. The reviewer→builder→comments.md loop is documented as a feature, not a side effect.
- **Tone is honest**: "Phase 6 — Streamlit dashboard — 🚧 next", "MCP — 🔒 deferred". No overclaiming.

**What works — DESIGN_SPEC.md (user-authored):**
- **§0.1 cross-reference table** is the killer feature — maps each carry-over reviewer flag to the design section that resolves it. **Verifies that every Phase-5 review flag has a Phase-6 destination**:
  - 416719f small-N → §1.2 sidebar slider + §2.2 masking ✓
  - 955d0f3 lex tiebreaker → §2.2 leaderboard renders `n_trades` prominently ✓
  - 955d0f3 silent thin-sample drop → §4 commit `feat(p6.2.thin)` sidecar ✓
  - 416719f `min_n=0` verify-only → §1.2 defaults to 5 ✓
  - afdd56e ddof=0 caveat → §2.2 tooltip copy ✓ (uses my exact wording from the afdd56e review block)
  - afdd56e Sharpe-like ≠ real Sharpe → §2.4 excluded from v1 sort menu ✓
  
  **Every load-bearing reviewer concern has an architectural home.** This is the right discipline — reviewer flags become design constraints, not folklore.
- **§1.1 tabs vs pages decision** with the right rationale (cross-page state loss with `pages/`). Streamlit veterans will agree; this catches a common rookie mistake.
- **§1.4 single caveats expander** instead of three stacked banners — "banner blindness" rationale is correct UX intuition. PLAN.md §3 Phase 6.5 exit criterion still satisfied (the expander is always rendered).
- **§2.1 Plotly for heatmaps** with explicit reason (hover tooltip composition). Includes the `chore(p6.0.deps)` action to add `plotly>=5.20`.
- **§2.4 Sharpe-like excluded** — the three forward options (real Sharpe with sidebar, rename, leave out) are all valid; v1 picks "leave out". Conservative; appropriate. **My afdd56e review block flagged this exact concern** — the doc resolves it cleanly by deferring rather than half-implementing.
- **§3 first-real-sweep dimensions** (5 stocks × 2 years × 3 strategies × 5 × 3 ≈ 5,400 cells) — concrete plan with cache-fetch budget (20-30 min). Avoids the legacy/UDiff pre-2024-07-08 boundary noise by sticking to 2023-2024. **Smart**: surfaces a Phase-6 dataset that exercises multi-pair/multi-year/multi-strategy without yet hitting the format-cutover edge.
- **§4 nineteen-sub-commit decomposition** of Phase 6 — nuclear-commits discipline applied. Each commit fits in a small reviewable diff: discover module + tests, caveats module, app shell, leaderboard table, thin-samples sidecar, within/across toggle, dual heatmap, hover tooltips, YoY line, MoY bars, n_trades hover, per-stock dashboard, sweep run, screenshot verify, tag. Reviewable.
- **§6 workflow decisions** in compact table form — stay on main, tag every phase, defer mypy, pin requirements. All defensible for solo-dev velocity.
- **§8 wiring constraints** — call out the four design choices that prevent Phase-7 surgery: universe is `list[str]` everywhere, caveats are re-exported not duplicated, sweep discovery in its own module, min_n flows top-down. These are exactly the right places to apply the open-closed principle.
- **§10 change log** — discipline matches PLAN.md §7. Same 2026-05-24 date for creation + the §0.1/§2.4 amendments captured.

**Blocking issues:** None.

**Non-blocking observations (the doc-vs-reality gaps I found):**

1. **🔬 §9.5 and §9.6 are stale — describe followups that 8893b81 closed 17 seconds earlier**. §9.5: "verify_p5 prints unmasked heatmap + count instead of masked view... lands as `chore(p5.followup): verify_p5 prints masked heatmap` whenever someone touches the script next." — but 8893b81 lands exactly this fix at [scripts/verify_p5.py:120-129](scripts/verify_p5.py#L120-L129). §9.6: "Empty-frame StringDtype drifts to object via `_inferred_dtype` (1a5cf01). Cosmetic; deferred." — but 8893b81 closes this too at [src/engine/results.py:104-108](src/engine/results.py#L104-L108). **The doc was written before 8893b81 landed but committed 17 seconds after.** Both items should now read "RESOLVED in 8893b81" instead of "deferred". Cosmetic but a future reader picking through §9 would think these are still pending.

2. **§0 says "5 sweep parquets exist on disk"** — at the time of writing this was likely true (3 test-leaked + verify_p5 small + 1 real). Currently `ls data/results/` shows ONLY `sweep_bde92aef8573.parquet`. The 3 leaked artifacts were cleaned manually before 617878b's test-fixture fix. **Cosmetic**; the doc is describing past state, not current. Acceptable since §0 is contextual.

3. **🔬 §1.5 "newest by mtime" sweep picker has a hidden dependency on 617878b's test-fixture fix.** **The defensive alternative (verify_p5's "largest by row count")** was rejected with the reasoning "a stale-but-big historical sweep would silently outrank the one the operator just produced. mtime matches the mental model 'the sweep I just ran.'" — sound rationale. **BUT**: if a future test reintroduces a leak path (e.g., a new module imports `RESULTS_DIR` without the fixture being updated — see my 617878b review's non-blocker #1), the mtime picker silently degrades. Worth a note: §1.5 should reference the test-fixture-leak fix as a load-bearing prerequisite, OR §8 should add "all `RESULTS_DIR` consumers must be in `_redirect_results`" as a wiring constraint. Otherwise the picker is silently fragile to a future contributor's mistake.

4. **§2.1 says "drop altair if a repo-wide grep shows no in-tree usage"** — I grepped: `requirements.txt:12: altair>=5.0.0` is the only mention. **Grep IS clean** — altair can be dropped per the conditional. Minor: the conditional could be hardened to "drop altair from requirements.txt" without the qualifier since the grep is verifiable now.

5. **PROJECT_DESCRIPTION.md says "365/365 tests"** — currently 367 after 8893b81. Cosmetic; will drift with every test addition. Could be replaced with "365+ tests as of Phase 5" or just "~365 tests".

**Domain / correctness checks:**
- **Asymmetric-conservatism contract preserved**: ✓ §0.1 + §1.4 + §2.2 tooltip + §2.4 Sharpe exclusion all extend the asymmetric-conservatism mandate into the UI layer.
- **No silent filtering claimed but not delivered**: ✓ §4 explicitly schedules `feat(p6.2.thin)` as a separate commit — the thin-samples sidecar is a first-class commit, not a footnote.
- **Reviewer-flag traceability**: ✓ §0.1 is the audit trail; every flag has a destination section.
- **No internal contradictions**: I cross-checked the table of contents against the section bodies. §1.2 sidebar's `min_n` default of 5 matches §0.1's `MIN_N_FOR_RANKING=5`. §2.2's "leaderboard renders `n_trades` as own column" matches §0.1's reference to 955d0f3 lex-tiebreaker mitigation. Consistent.

**What I tried:**
- `git show --stat 8a49165` — 384 lines added, 2 new files; no production code touched.
- Read PROJECT_DESCRIPTION.md and DESIGN_SPEC.md end-to-end.
- Cross-checked §0.1's reviewer-flag table against my own review history in comments.md — every cited flag matches.
- Grep'd for `altair` usage to verify §2.1's drop-conditional — clean.
- Listed `data/results/` to check §0's "5 sweep parquets" claim — currently 1 (the doc is stale).
- Cross-checked §9.5 + §9.6 deferred items against 8893b81's diff — both are closed, so §9 is stale.

**Sequencing observation:** The two-commit cluster (8893b81 closes flags → 8a49165 documents the design) is the right shape, BUT they landed within 17 seconds and BUILDER didn't update the doc to reflect 8893b81's closures. This is a small process gap. **Recommendation**: when closing flags AND landing a design doc that references them, sequence as (a) close flags, (b) update design doc to reflect closures, (c) commit doc. Or fold the doc into the same commit.

**Doc-traceability call-out**: §0.1 cites reviewer commit SHAs verbatim (416719f, 955d0f3, afdd56e). **This is the right pattern** — design constraints traceable to specific reviewer flags means the constraint history is auditable. Future-me (or a future contributor) reading §0.1 can `git show 955d0f3` to understand WHY the leaderboard renders `n_trades` prominently. Reviewer→doc→code traceability closed.

**Next-commit suggestion:** Per DESIGN_SPEC §4, the Phase-6 sequence starts with:
1. `chore(p6.0.spec)` — SPECS §11 web contract (sweep-discovery rule + caveat constants); OR
2. `chore(p6.0.deps)` — `requirements.txt` (add `plotly>=5.20`, drop `altair`).

**My lean**: start with `chore(p6.0.deps)` since it's the smallest, most-mechanical commit — single-file edit, easy to verify, unblocks any commit that needs Plotly. SPECS §11 contract authoring can immediately follow. Both are quick wins before the first piece of new code (`feat(p6.1.discover)`).

**Stale-doc followup suggestion** (non-blocking, opportunistic): in whichever commit next touches DESIGN_SPEC.md, mark §9.5 and §9.6 as RESOLVED (with the closing commit SHA = `8893b81`). Mark §0's "5 sweep parquets" as historical context if not removed. Total edit ~3 lines.

---

## Review of 8893b81 — chore: close non-blocking reviewer flags accumulated through Phase 5

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Cleanup pass closing seven reviewer-flagged non-blockers accumulated across Phases 4–5 in a single commit. Two of them (verify_p5 masked-view + StringDtype empty-frame) were noted as deferred in DESIGN_SPEC §9 — BUILDER bringing them forward because the user explicitly asked for cleanup. "Deferred → done is strictly better."

**Flags closed (with my live-verification):**

1. **(416719f #1) verify_p5 section (b) now prints the masked heatmap view** ([scripts/verify_p5.py:120-129](scripts/verify_p5.py#L120-L129)) — addresses my "show the masked view, not just the count" flag. **Live confirmed**: on the verify dataset, the masked grid is fully NaN (every cell has n=3 < MIN_N=5):
   ```
   masked view (Phase-6 will render this — NaN cells shown as blank):
   exit_offset_td    3   1
   entry_offset_td        
   15              NaN NaN
   10              NaN NaN
   5               NaN NaN
   ```
   That IS the honest Phase-6 preview — operator sees the empty grid and knows the dataset is too thin at cell-level for confident claims, even though the pair-level summary (n=18) clears threshold.

2. **(416719f #3) `import textwrap` moved to module top** — PEP 8 cosmetic, low-stakes.

3. **(b2dd296 / 1a5cf01 deferred flag) `_inferred_dtype` returns "string" not "object"** ([src/engine/results.py:104-109](src/engine/results.py#L104-L109)) — empty results frame now matches the StringDtype convention used by upstream loaders (per SPECS §2.0/§2.1). **Live confirmed**: `empty_results_frame()` produces `run_id, strategy, symbol, params_json, legs_json, costs_breakdown_json, margin_breakdown_json` all as `string`. Same for `empty_skips_frame()`. Closes the version-drift risk where `pd.concat(empty_frame, real_data)` could yield object-or-string depending on pandas version.

4. **(955d0f3 #4) `rank_strategies` warns when 100% suppressed** ([src/analytics/rank.py:120-131](src/analytics/rank.py#L120-L131)) — addresses my "all-rows-suppressed edge case → silent blank" flag. **Live-tested all three branches**:
   ```
   Test 1: 2 rows, all n<5 vs min_n=5 → 1 UserWarning ✓
     "rank_strategies: all 2 input rows suppressed by min_n=5..."
   Test 2: empty input (0 rows) → 0 warnings ✓ (no suppression claim on empty)
   Test 3: 2 rows, 1 survives → 0 warnings ✓ (partial is fine)
   ```
   **The empty-input branch correctly stays quiet** — the guard `if n_input > 0 and len(df) == 0` distinguishes "operator passed nothing" from "operator passed rows and the filter ate them all". Semantically right; the warning message is actionable ("consider lowering the threshold or expanding the sweep grid"). `stacklevel=2` so warnings.warn fires at the caller's frame, not inside rank.py.

5. **(955d0f3 #3) Tied-rank semantics + lex-tiebreaker docstring** ([src/analytics/rank.py:81-91](src/analytics/rank.py#L81-L91)) — closes my flag about "n=50 row sorts below n=10 at tied metric". BUILDER takes the explicit position: rank_strategies is the ranker, not a quality-weighted sorter; Phase-6 UI is responsible for rendering `n_trades` prominently. **DESIGN_SPEC §2.2 referenced** as the Phase-6 commitment. Acceptable — the design tradeoff is documented at both the rank.py docstring AND the design spec, which means future contributors won't accidentally "fix" the lex tiebreaker without consulting both.

6. **(afdd56e / 955d0f3 caveat #2) Sharpe-LIKE ≠ real Sharpe docstring** ([src/analytics/rank.py:93-99](src/analytics/rank.py#L93-L99)) — closes my asymmetric-conservatism flag. Docstring notes real Sharpe subtracts ~6.5% Indian risk-free; difference is small for high-ROI strategies but matters for absolute interpretation. **DESIGN_SPEC §2.4 commits** v1 leaderboard sort menu to NOT include the Sharpe-like ratio (defers proper risk-adjusted ranking to Phase 7/8). Conservative; appropriate for v1.

7. **(afdd56e #1) SUMMARY_COLUMNS docstring notes ddof=0 = OBSERVED-SAMPLE DISPERSION** ([src/analytics/aggregate.py:39-46](src/analytics/aggregate.py#L39-L46)) — closes my ddof=0 vs ddof=1 caveat with explicit bias numbers (20% at n=5, 2.5% at n=20, treat as lower bound on true spread). **This is the exactly the asymmetric-conservatism wording the user wanted**: a std column that looks "too tight" reads as "the spread is at least this big, possibly bigger" — under-promise the consistency story.

**Test changes I verified:**
- `test_min_n_default_is_5` had to wrap its n=4 case in `pytest.warns(UserWarning, match="suppressed")` because that branch now fires the new warning. Behavior change captured in test. Clean.
- Two new tests pin the warning branches: `test_all_rows_suppressed_emits_warning` and `test_empty_input_no_warning` (the latter using `simplefilter("error")` to promote any warning to exception — defensive negative-assertion).
- **367/367 pass** (was 365 + 2 new).

**Blocking issues:** None.

**Non-blocking observations:**

1. **The dtype change is a quiet API contract shift** — anyone calling `empty_results_frame()` then doing `df["strategy"] = "..."` on the empty frame would previously get object-dtype; now they get StringDtype. If a downstream Phase-6 consumer was relying on the object behavior (unlikely but possible), they'd see a subtle dtype mismatch. The change is correct per SPECS, just worth flagging for the Phase-6 build. **Mitigation**: the SPECS-aligned dtype is what Phase-6 should be using anyway; if Phase-6 hits a dtype error, that's surfacing a bug in Phase-6 code, not a regression here.

2. **`warnings.warn(stacklevel=2)`** is the right level for one-frame-deep wrapping. If Phase-6 wraps `rank_strategies` in its own function (e.g., `streamlit_render_leaderboard(...) → rank_strategies(...)`), the warning will surface at the rank_strategies caller frame, not the Phase-6 wrapper. **Minor**: if Phase-6 wants the warning to surface at the user-script frame, it can re-emit with its own stacklevel. Not a blocker.

3. **DESIGN_SPEC.md is referenced but I haven't seen the doc** — the commit body mentions §2.2, §2.4, §9. The next commit (8a491653 — `docs: PROJECT_DESCRIPTION + DESIGN_SPEC`) presumably lands this. **The cross-reference pattern is good practice** — having both code-level docstrings AND a design doc explain the same tradeoff means future contributors have two convergent sources. Will review the design doc in the next block.

**Domain / correctness checks:**
- **Statistical honesty**: ✓ all 7 closures sharpen the asymmetric-conservatism contract (warning instead of silent blank, lower-bound std interpretation, Sharpe-like ≠ real Sharpe, masked view rendered honestly).
- **Determinism**: ✓ no functional changes to sort/rank logic; only the warning emission added.
- **Backwards compat**: dtype change for empty frames is the one semi-API-shift; SPECS-aligned per §2.1; not a regression in any test.

**What I tried:**
- `.venv/bin/python -m pytest tests/` → 367/367.
- `.venv/bin/python scripts/verify_p5.py` → verified the masked view renders as a NaN-only grid on the current dataset.
- Live-tested all 3 warning branches (all-suppressed, empty, partial) — semantics correct.
- Inspected `empty_results_frame()` + `empty_skips_frame()` dtypes — all text cols now `string`.

**Sequencing observation:** This is exactly the "deferred → done is strictly better" pattern. BUILDER chose to bundle 7 small fixes into one chore commit rather than 7 nuclear commits. **I think that's correct here** — each individual fix is too small to merit its own commit; the bundle has a unifying theme ("close reviewer flags"); 367/367 passes after the bundle. The risk-of-bundling concern (one bad change taints the whole commit) is mitigated by the small individual scopes and the test coverage. The user's "nuclear commits" preference is about keeping each *risky* unit of work atomic; cosmetic / docstring / docstring-companion-test cleanups don't carry the same risk profile.

**Next-commit suggestion:** The next commit (8a491653 — `docs: PROJECT_DESCRIPTION + DESIGN_SPEC`) presumably lands the referenced docs. Review of that follows below. After that → **`feat(p6.1): streamlit UI skeleton`** (still the standing recommendation from the 416719f review block).

---

## Review of 617878b — fix(test-fixtures): redirect both sweeper.RESULTS_DIR and results.RESULTS_DIR

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Tests were silently leaking small parquets (0–1 rows) into the real `data/results/` directory because the fixture's `monkeypatch.setattr(sweeper_mod, "RESULTS_DIR", tmp_path)` only redirected the cache-hit short-circuit check — the actual write path went through `results.results_path()` which has its own `from src.config import RESULTS_DIR` binding. **Surfaced by the new p5.verify script itself**: it enumerates `sweep_*.parquet` and found 3 test-leaked artifacts (1, 0, 1 rows) alongside the real 18-row verify run — direct evidence the fixture wasn't redirecting all write paths.

**What works:**
- **Root cause correctly identified** ([tests/test_sweeper.py:97-103](tests/test_sweeper.py#L97-L103) docstring) — `from src.config import RESULTS_DIR` creates a NEW binding in each importing module. Patching `sweeper_mod.RESULTS_DIR` does NOT affect `results_mod.RESULTS_DIR` because they're independent module-level names pointing at the same path-object. Classic Python `from-import` patching gotcha.
- **Minimal fix**: add `monkeypatch.setattr(results_mod, "RESULTS_DIR", tmp_path)` in two places (`tests/test_sweeper.py:_redirect_results` and `tests/test_iron_condor.py:test_sweep_one_iron_condor_uses_spot_based_margin`). 6 lines net.
- **Docstring explains the gotcha** so future contributors don't re-introduce single-side patching.
- **Live-verified the fix**: I ran `ls data/results/` (1 file: `sweep_bde92aef8573.parquet`) → `pytest tests/ -q` → 365/365 pass → `ls data/results/` (still 1 file). **Zero new test leaks after the fix.** The 3 pre-existing leaked parquets I saw earlier in this session must have been cleaned manually by BUILDER (not in this commit's diff, but the source of leaks is now plugged).

**Blocking issues:** None.

**Non-blocking suggestions:**

1. **🔬 Call-site patching is fragile to future module additions** — I grepped all consumers of `RESULTS_DIR`:
   ```
   src/engine/results.py:19   from src.config import RESULTS_DIR
   src/engine/sweeper.py:36   from src.config import RESULTS_DIR
   scripts/verify_p4.py:41    from src.config import RESULTS_DIR
   scripts/verify_p5.py:46    from src.config import RESULTS_DIR
   ```
   Currently 2 production modules + 2 scripts (scripts don't need patching). If a Phase-6 module or Phase-8 MCP server adds a third `from src.config import RESULTS_DIR`, **the test fixture will silently regress** to leaking parquets via the new module. **Structural fix options**:
   - Replace `from src.config import RESULTS_DIR` with `from src import config` + `config.RESULTS_DIR` at call sites. Then `monkeypatch.setattr(config, "RESULTS_DIR", tmp_path)` fixes everyone at once. **Recommended** — Pythonic, robust to additions.
   - OR wrap as `get_results_dir()` function so each call re-reads from config. Heavier refactor.
   - OR add a `conftest.py` fixture that patches `src.config.RESULTS_DIR` AND walks `sys.modules` to re-patch any module that already imported the name. Hacky.
   
   Not blocking for v1; flag for Phase-6 when the third consumer lands.

2. **`tests/test_results.py:16`** already patches `results.RESULTS_DIR` correctly — the fix establishes that pattern as the convention. Worth a CLAUDE.md note: "when patching `RESULTS_DIR` in a test fixture, patch BOTH `sweeper_mod` AND `results_mod`". Cosmetic but de-risks future contributors.

3. **Pre-existing leaked parquets not deleted in this commit** — the BUILDER cleaned them manually (data/results/ now has 1 file), but that cleanup isn't in the diff. Not a problem (manual cleanup of test pollution is fine), but a `git clean -nx data/results/` check in CI would catch this class of issue going forward. Phase-7 concern.

**Domain / correctness checks:**
- **Determinism**: ✓ tests + production paths are now isolated. No cross-contamination.
- **Test surface**: ✓ 365/365 pass identically before and after. No functional change to behavior, only to side-effect isolation.
- **The fix is minimal and surgical**: no production code touched. Only test fixtures. Lowest-risk path.

**What I tried:**
- `git show 617878b` — diff is 2-file, 6-line, all in `tests/`. No production code touched.
- `grep -rn "RESULTS_DIR" src/ tests/ scripts/` — confirmed only 2 production modules import via `from src.config import RESULTS_DIR`; both now patched.
- `ls data/results/` → 1 file → `pytest tests/` → 365 pass → `ls data/results/` → still 1 file. **No new leakage.**
- Read `tests/test_iron_condor.py:399-410` — fix applied identically to the iron-condor sweep fixture.

**Sequencing note (interesting):** This fix and `chore(p5.verify)` share a commit timestamp (`Sun May 24 21:31:42 2026 +0530`). The fix landed FIRST in the log (617878b) immediately before 416719f. That's the right order — the verify script SURFACED the leak (by enumerating sweep_*.parquet and finding multiple candidates) and BUILDER fixed the test fixture so future verify-runs would only see the real parquet. **Good causality**: the verify script's "largest of N candidates" diagnostic is what made the previously-invisible test pollution visible. Phase-6 verify scripts should adopt the same pattern.

**Next-commit suggestion:** Already covered in the 416719f review block below — `feat(p6.1): streamlit UI skeleton`. The fix here is a prerequisite cleanup; Phase-6 can now trust `data/results/` to contain only real sweep parquets.

---

## Review of 416719f — chore(p5.verify): live aggregate → rank pipeline on the verify parquet

**Verdict:** ✅ accept

**Phase / commit goal (as I understood it):** Phase 5 → Phase 6 bridge. Exercise every Phase-5 aggregator + the ranker end-to-end on the real verify parquet so Phase-6 UI development can copy-paste the composability pattern without surprises.

**What works:**
- **Six load-bearing checks** ([scripts/verify_p5.py:53-177](scripts/verify_p5.py#L53-L177)) — leaderboard, Sharpe-like ranking, heatmap + masking, YoY, seasonality, thin-sample transparency, multiple-comparisons caveat. Every Phase-6 surface gets a CLI rehearsal.
- **Picks largest sweep parquet by row count** ([scripts/verify_p5.py:67-73](scripts/verify_p5.py#L67-L73)) — robust against test-leak 1-row parquets. Diagnostic prints alternative candidates. **Live confirmed**: I had three 1-row test artifacts in `data/results/`; the picker correctly selected the 18-row real one.
- **Sharpe-like ranking exercises my p5.5 review's composability claim** ([scripts/verify_p5.py:94-108](scripts/verify_p5.py#L94-L108)) — synthesizes `sharpe_like_annualized = mean / std` and ranks by it. Confirmed the API decouples "what to rank by" from "what's in the schema". **Bonus defensive touch**: `denom.replace(0.0, NaN)` handles n=1 → ddof=0 std=0 → div-by-zero (the BUILDER's own caveat from afdd56e).
- **Heatmap masking pattern surfaced cleanly** ([scripts/verify_p5.py:120-122](scripts/verify_p5.py#L120-L122)) — `v.where(n >= MIN_N_FOR_RANKING)` + a count of cells masked. Phase-6 can copy-paste this for the visualization layer.
- **Thin-sample transparency check** ([scripts/verify_p5.py:144-155](scripts/verify_p5.py#L144-L155)) — explicitly composes `summary[summary["n_trades"] < MIN_N_FOR_RANKING]` to render suppressed rows alongside the rank output. **This addresses my p5.5 review's non-blocker #2** ("single-table ranker silently drops thin samples unless consumer composes") at the CLI layer; Phase-6 has the template now.
- **MULTIPLE_COMPARISONS_CAVEAT printed verbatim, wrapped to 72 cols** — proves the constant is renderable text, not a placeholder. Phase-6 banner copy is locked in.
- **Pipeline timing surfaced**: 28.1ms end-to-end. Quantifies "Phase-6 UI can re-aggregate on every user click without lag" — useful hard number for Phase-6 design (no need to cache aggregated views).
- **Section (e) handles "no thin samples" case** ([scripts/verify_p5.py:145-148](scripts/verify_p5.py#L145-L148)) — graceful message when every pair clears the threshold, rather than blank output. Phase-6 UI should follow the same pattern.

**Live verify (I ran the script):**
```
parquet: sweep_bde92aef8573.parquet  (18 rows — largest of 1 candidates)

rank=1 short_straddle × RELIANCE  n=18  win=83.3%  median=247.92%/yr
                                       std=242.97%  total_net_pnl=₹124,613
Sharpe-like rank=1: 0.683
Heatmap: 3×2 grid, every cell n=3 → ALL 6 CELLS MASKED at MIN_N=5
Seasonality: Jan 251.78 / Feb 269.25 (std 94.29 ← tightest) / Mar 106.46
no thin samples (every pair clears threshold at pair level)
MULTIPLE_COMPARISONS_CAVEAT: 450 chars wrapped to 7 lines
Pipeline timing: 28.1ms
```
Output is reproducible byte-identical to the commit-message preview.

**🔬 The heatmap "all cells masked" result is the most important honest finding here:** at the pair level the dataset has n=18 (above threshold); but break it into a 3×2 heatmap cell grid and every cell has n=3 (below threshold). **This is the kind of "thin slicing" issue Phase-6 will hit constantly**: aggregation reveals enough data, but visualization-level slicing dilutes it below confidence. The verify script surfaces this honestly via the masked-cell count.

**Blocking issues:** None.

**Non-blocking suggestions:**

1. **Section (b) prints the unmasked heatmap + the cell counts + a numeric "cells masked" stat, but NOT the masked view itself** — Phase-6 will render the masked view (most cells become NaN at MIN_N=5). The verify could `print(masked.to_string(...))` immediately after the count to show "here's what Phase-6 will actually display" — a fully empty grid in this case, which is itself a useful honest signal. ~3 lines.

2. **Single-pair limitation, not a script bug**: the verify dataset has only one (strategy, symbol) pair, so the **lex-tiebreaker concern I raised in p5.5 review can't be exercised here**. The script correctly ranks the one row at rank=1. Phase-6 will need a multi-pair test fixture (synthesized or expanded sweep) to verify the tiebreaker visible behavior. Worth a note in Phase-6's test plan.

3. **`import textwrap` inline** ([scripts/verify_p5.py:161](scripts/verify_p5.py#L161)) — module-level import would match PEP 8 conventions, but it's a script not a library. Purely cosmetic.

4. **`min_n=0` in section (a)** ([scripts/verify_p5.py:84](scripts/verify_p5.py#L84)) — chosen so the verify-set's single pair shows up. Phase-6 UI's leaderboard should use the default `min_n=5` to honor the ranking contract; **explicit Phase-6 reminder**: don't copy-paste the `min_n=0` from this script into the UI.

**Domain / correctness checks:**
- **Aggregator → ranker composability:** ✓ end-to-end on real data.
- **Schema preservation:** ✓ all 16-col SUMMARY_COLUMNS flow through; rank.column inserted at position 0.
- **Caveat surfacing:** ✓ MULTIPLE_COMPARISONS_CAVEAT renderable as plain text.
- **Honest reporting**: ✓ Q1-only warning, heatmap-masked-cells count, no-thin-samples graceful message.
- **Determinism**: same parquet → same output (verified by re-running; byte-identical).

**What I tried:**
- Read [scripts/verify_p5.py](scripts/verify_p5.py) end-to-end.
- `.venv/bin/python scripts/verify_p5.py` → PASS in 28.1ms, output matches commit-message preview exactly.
- Cross-checked the heatmap masking: `values` shows real numbers (113.5, 253.6, ...), counts show all 3s, masking at MIN_N=5 correctly drops all 6 cells.
- Cross-checked Sharpe-like ranking: confirmed `mean_roi_pct_annualized / std_roi_pct_annualized` = 166.05 / 242.97 ≈ 0.683.
- Cross-checked the thin-sample subset = empty (correct: only one pair, n=18 > threshold).

**Phase 5 → Phase 6 status:**
- ✅ Aggregator trio (p5.1 + p5.3 + p5.4) composes cleanly into ranker (p5.5)
- ✅ Heatmap pivot composes with masking pattern (p5.2 + MIN_N filter)
- ✅ Schema additions in afdd56e (std + total_net_pnl) make Sharpe-like ranking trivially composable
- ✅ Multiple-comparisons caveat is real renderable text
- ✅ Thin-sample transparency pattern proven at the CLI; Phase-6 must replicate
- ⚠ Heatmap-cell-level slicing exhausts sample size on the current verify dataset — Phase-6 should expect users to see "no cells visible at default threshold" on small sweeps and provide an obvious "lower the threshold" UI control

**Next-commit suggestion:** **`feat(p6.1): streamlit UI skeleton — leaderboard page + sweep-parquet selector + caveat banners`**. Now that Phase-5 composability is proven live, p6.1 lands the first user-facing surface. Load-bearing for asymmetric-conservatism:

1. **Top-of-page banner**: render `MULTIPLE_COMPARISONS_CAVEAT` verbatim in a styled callout (yellow background, info icon). Non-negotiable.

2. **Below banner: parquet-file selector** — list all `data/results/sweep_*.parquet` files with their row counts + symbol/strategy coverage (so the user picks the verify parquet, not a test leak). Mirror the "largest by row count" robustness from p5.verify.

3. **Main panel: leaderboard table** — `rank_strategies(summary, min_n=5)` with `n_trades` column rendered PROMINENTLY (mitigates the lex-tiebreaker quirk per my p5.5 review). Sort metric selector (default = `median_roi_pct_annualized`; options also = `mean_roi_pct_annualized`, `total_net_pnl`, `win_rate_pct`, Sharpe-like).

4. **"Thin samples not ranked" expander** below the leaderboard — `summary[summary["n_trades"] < min_n]` rendered as a separate table with copy "these pairs had insufficient sample size for the headline ranking; N too small for reliable summary statistics". This is the Phase-6 implementation of my p5.5 reviewer-flagged transparency concern.

5. **Survivorship-bias disclaimer** (SPECS §6b.3) alongside the multiple-comparisons banner — two-sentence callout. Both load-bearing for the asymmetric-conservatism contract.

6. **Heatmap + trend + seasonality pages** deferred to p6.2/6.3/6.4. p6.1 is just the leaderboard surface — keep it nuclear-commit-sized.

The verify script's exact CLI output (sections a + e + f) is roughly the data shape p6.1 needs to render. Streamlit `st.dataframe` + `st.info` blocks for the callouts. Hot-reload makes iteration fast.

---
