// Plausible sweep dataset for morenseprofits Phase 6 mockup.
// 5 symbols × 3 strategies × 2 years (2023-2024). Numbers are tuned to feel real
// (heavy-tailed short-vol RoIs, condor smaller std, occasional flat years).

const SWEEPS = [
  { run_id: "swp_20260524_2103",  rows: 3812, mtime: "2026-05-24 21:03", note: "2023-24 / 5x3", current: true },
  { run_id: "swp_20260524_1418",  rows: 3640, mtime: "2026-05-24 14:18", note: "2023-24 / 5x3 (rerun)" },
  { run_id: "swp_20260519_2244",  rows: 1064, mtime: "2026-05-19 22:44", note: "2024 / 5x3" },
  { run_id: "swp_20260507_p4",    rows:   18, mtime: "2026-05-07 11:02", note: "verify · RELIANCE Q1 2024" },
];

const STRATEGIES = [
  { key: "short_straddle",  short: "SS",  label: "Short Straddle",  cls: "ss"  },
  { key: "short_strangle",  short: "SST", label: "Short Strangle",  cls: "sst" },
  { key: "iron_condor",     short: "IC",  label: "Iron Condor",     cls: "ic"  },
  { key: "long_straddle",   short: "LS",  label: "Long Straddle",   cls: "ls"  },
  { key: "long_strangle",   short: "LST", label: "Long Strangle",   cls: "lst" },
];

const SYMBOLS = [
  { sym: "RELIANCE",   name: "Reliance Industries",     regime: "bull",    lot: 250 },
  { sym: "HDFCBANK",   name: "HDFC Bank",               regime: "neutral", lot: 550 },
  { sym: "INFY",       name: "Infosys",                 regime: "neutral", lot: 400 },
  { sym: "ICICIBANK",  name: "ICICI Bank",              regime: "bull",    lot: 700 },
  { sym: "TCS",        name: "Tata Consultancy",        regime: "bear",    lot: 175 },
];

// Per-pair summary (current sweep, 2023-24, 5×3).
// Columns mirror analytics.aggregate.summarize_by_stock_strategy.
const LEADERBOARD = [
  { strategy: "short_straddle", symbol: "RELIANCE",  n: 72, win: 77.8, median: 189.4, mean: 204.1, std: 287.6, total: 421250 },
  { strategy: "short_strangle", symbol: "HDFCBANK",  n: 78, win: 82.1, median: 164.2, mean: 178.5, std: 198.4, total: 298100 },
  { strategy: "short_straddle", symbol: "TCS",       n: 70, win: 71.4, median: 152.0, mean: 171.3, std: 312.2, total: 312890 },
  { strategy: "iron_condor",    symbol: "INFY",      n: 84, win: 86.9, median: 139.7, mean: 144.2, std:  86.1, total: 201400 },
  { strategy: "short_strangle", symbol: "ICICIBANK", n: 76, win: 79.0, median: 128.6, mean: 141.8, std: 174.0, total: 243800 },
  { strategy: "short_straddle", symbol: "HDFCBANK",  n: 72, win: 73.6, median: 121.3, mean: 139.4, std: 224.7, total: 248600 },
  { strategy: "iron_condor",    symbol: "HDFCBANK",  n: 80, win: 84.4, median:  98.2, mean: 108.6, std:  72.4, total: 156900 },
  { strategy: "short_strangle", symbol: "RELIANCE",  n: 74, win: 75.6, median:  94.7, mean: 107.2, std: 189.3, total: 187200 },
  { strategy: "short_strangle", symbol: "INFY",      n: 72, win: 73.6, median:  78.4, mean:  91.5, std: 183.7, total: 128400 },
  { strategy: "iron_condor",    symbol: "RELIANCE",  n: 76, win: 81.5, median:  72.1, mean:  84.4, std:  78.6, total:  98200 },
  { strategy: "short_straddle", symbol: "INFY",      n: 68, win: 66.1, median:  58.3, mean:  64.2, std: 298.4, total:  76300 },
  { strategy: "iron_condor",    symbol: "TCS",       n: 78, win: 79.4, median:  51.4, mean:  62.7, std:  82.0, total:  71800 },
  { strategy: "short_strangle", symbol: "TCS",       n: 70, win: 68.5, median:  43.2, mean:  51.1, std: 204.6, total:  62400 },
  { strategy: "iron_condor",    symbol: "ICICIBANK", n: 82, win: 82.9, median:  38.6, mean:  45.0, std:  68.4, total:  54300 },
  { strategy: "short_straddle", symbol: "ICICIBANK", n: 68, win: 64.7, median:  21.4, mean:  12.8, std: 341.2, total:  14600 },
];

// Thin samples — n < min_n (we treat 5 as default; some pairs slip in/out depending on slider)
const THIN_SAMPLES = [
  { strategy: "iron_condor",    symbol: "ICICIBANK", regime: "bear-only",     n: 4, median:   "—", note: "regime: bear (1 of 24 expiries)" },
  { strategy: "short_strangle", symbol: "TCS",       regime: "bear-only",     n: 3, median:   "—", note: "regime: bear (1 of 24 expiries)" },
  { strategy: "long_straddle",  symbol: "RELIANCE",  regime: "all",           n: 2, median:   "—", note: "skip: NoLiquidStrike on 70/72 cells" },
  { strategy: "long_strangle",  symbol: "HDFCBANK",  regime: "all",           n: 1, median:   "—", note: "skip: NoLiquidStrike on 71/72 cells" },
];

// Entry × Exit heatmap for short_straddle × RELIANCE (the deep-dive pair).
// Rows = entry_offset (trading days before expiry), cols = exit_offset (TD before expiry, 0 = on expiry).
// Cells store [n_trades, median_roi_pct_ann, win_rate_pct, std, total_net_pnl_lakhs]
const HEATMAP_ENTRIES = [15, 12, 9, 6, 3];
const HEATMAP_EXITS   = [3, 1, 0];

const HEATMAP_CELLS = {
  // entry_offset: { exit_offset: {...} }
  15: { 3: { n: 24, roi:  82.3, win: 70.8, std: 156.4, pnl: 0.61 }, 1: { n: 24, roi: 121.6, win: 75.0, std: 188.2, pnl: 1.02 }, 0: { n: 24, roi: 144.7, win: 79.2, std: 224.0, pnl: 1.31 } },
  12: { 3: { n: 24, roi: 118.9, win: 75.0, std: 174.1, pnl: 0.96 }, 1: { n: 24, roi: 168.4, win: 79.2, std: 211.7, pnl: 1.42 }, 0: { n: 24, roi: 196.2, win: 83.3, std: 248.3, pnl: 1.71 } },
   9: { 3: { n: 24, roi: 142.1, win: 75.0, std: 197.2, pnl: 1.18 }, 1: { n: 24, roi: 207.5, win: 79.2, std: 256.4, pnl: 1.78 }, 0: { n: 24, roi: 247.9, win: 83.3, std: 287.6, pnl: 2.04 } },
   6: { 3: { n: 24, roi: 154.7, win: 70.8, std: 224.8, pnl: 1.04 }, 1: { n: 24, roi: 228.4, win: 75.0, std: 291.0, pnl: 1.62 }, 0: { n: 24, roi: 264.1, win: 79.2, std: 318.4, pnl: 1.88 } },
   3: { 3: { n: 24, roi: 102.6, win: 62.5, std: 296.1, pnl: 0.41 }, 1: { n: 24, roi: 166.7, win: 70.8, std: 341.2, pnl: 0.74 }, 0: { n: 24, roi: 184.2, win: 75.0, std: 372.4, pnl: 0.92 } },
};

// Per-year summary for the selected (strategy, symbol) = (short_straddle, RELIANCE)
const YOY = [
  { year: 2022, n: 36, median: 224.7, mean: 234.1, win: 80.5, total: 198400, regime: "neutral" },
  { year: 2023, n: 36, median: 218.3, mean: 226.8, win: 80.5, total: 212840, regime: "bull"    },
  { year: 2024, n: 36, median: 247.9, mean: 282.4, win: 83.3, total: 208410, regime: "bull"    },
];

// Per-month summary (Jan-Dec), same pair, across 2 years (so n=6 per bucket)
const MOY = [
  { m: "Jan", n: 6, median: 251.8, mean: 268.3, std: 142.1 },
  { m: "Feb", n: 6, median: 269.2, mean: 282.4, std:  94.3 },
  { m: "Mar", n: 6, median: 106.4, mean: 132.7, std: 248.6 },
  { m: "Apr", n: 6, median: 198.4, mean: 211.2, std: 167.3 },
  { m: "May", n: 6, median: 314.7, mean: 342.1, std: 188.4 },
  { m: "Jun", n: 6, median: 178.2, mean: 201.6, std: 222.0 },
  { m: "Jul", n: 6, median: 224.1, mean: 248.8, std: 154.7 },
  { m: "Aug", n: 6, median:  86.4, mean:  94.2, std: 271.8 },
  { m: "Sep", n: 6, median: 142.7, mean: 168.4, std: 198.6 },
  { m: "Oct", n: 6, median: 312.6, mean: 338.4, std: 124.1 },
  { m: "Nov", n: 6, median: 264.8, mean: 287.3, std: 142.4 },
  { m: "Dec", n: 6, median:  74.2, mean:  82.6, std: 304.2 },
];

// ---------- Heatmap "lens" datasets ----------
// Same pair (short_straddle × RELIANCE), different 2D slices through the sweep.
// Cells = { n, roi, win, std, pnl (in lakhs), mean, byYear: [{y, n, roi}], skips }

function _enrich(c, seed = 0) {
  if (typeof c.roi !== "number") {
    // thin / unpriced cell — keep as is but ensure byYear/skips exist
    return { ...c, mean: c.roi, byYear: [], skips: [] };
  }
  // Plausible mean given heavy short-vol tail (mean usually drifts above or below median)
  const mean = c.roi + ((seed % 7) - 3) * (c.std / 24);
  // year split (assume 24 trades = 12+12)
  const half = Math.floor(c.n / 2);
  const noise = ((seed * 31) % 11 - 5) * 0.04;
  const yA = c.roi * (1 + noise);
  const yB = c.roi * (1 - noise);
  const byYear = [
    { y: 2023, n: half,           roi: +yA.toFixed(1) },
    { y: 2024, n: c.n - half,     roi: +yB.toFixed(1) },
  ];
  // Skipped expiries — handful when entry is near expiry (illiquid strikes hunt)
  const skips = (seed % 5 === 0) ? [{ reason: "NoLiquidStrike", n: 1 }] : [];
  return { ...c, mean: +mean.toFixed(1), byYear, skips };
}

// Lens A · entry × exit  (the default; what HEATMAP_CELLS already covers, re-enriched)
const LENS_ENTRY_EXIT = {
  id: "entry_exit",
  label: "Entry × Exit",
  hint: "Which holding window is best for this strike rule?",
  rowKey: "entry_offset_td",
  rowLabel: "ENTRY OFFSET (TD before expiry)",
  rowFmt: (v) => `−${v}`,
  colKey: "exit_offset_td",
  colLabel: "EXIT OFFSET (TD before expiry)",
  colFmt: (v) => v === 0 ? "0 (expiry)" : `−${v}`,
  rows: [15, 12, 9, 6, 3],
  cols: [3, 1, 0],
  cells: {
    15: { 3: _enrich({ n: 24, roi:  82.3, win: 70.8, std: 156.4, pnl: 0.61 }, 1),
          1: _enrich({ n: 24, roi: 121.6, win: 75.0, std: 188.2, pnl: 1.02 }, 2),
          0: _enrich({ n: 24, roi: 144.7, win: 79.2, std: 224.0, pnl: 1.31 }, 3) },
    12: { 3: _enrich({ n: 24, roi: 118.9, win: 75.0, std: 174.1, pnl: 0.96 }, 4),
          1: _enrich({ n: 24, roi: 168.4, win: 79.2, std: 211.7, pnl: 1.42 }, 5),
          0: _enrich({ n: 24, roi: 196.2, win: 83.3, std: 248.3, pnl: 1.71 }, 6) },
     9: { 3: _enrich({ n: 24, roi: 142.1, win: 75.0, std: 197.2, pnl: 1.18 }, 7),
          1: _enrich({ n: 24, roi: 207.5, win: 79.2, std: 256.4, pnl: 1.78 }, 8),
          0: _enrich({ n: 24, roi: 247.9, win: 83.3, std: 287.6, pnl: 2.04 }, 9) },
     6: { 3: _enrich({ n: 24, roi: 154.7, win: 70.8, std: 224.8, pnl: 1.04 }, 10),
          1: _enrich({ n: 24, roi: 228.4, win: 75.0, std: 291.0, pnl: 1.62 }, 11),
          0: _enrich({ n: 24, roi: 264.1, win: 79.2, std: 318.4, pnl: 1.88 }, 12) },
     3: { 3: _enrich({ n: 22, roi: 102.6, win: 62.5, std: 296.1, pnl: 0.41 }, 13),
          1: _enrich({ n: 22, roi: 166.7, win: 70.8, std: 341.2, pnl: 0.74 }, 14),
          0: _enrich({ n: 22, roi: 184.2, win: 75.0, std: 372.4, pnl: 0.92 }, 15) },
  },
};

// Lens B · strike × entry  (fixed exit = 0 / expiry)
const LENS_STRIKE_ENTRY = {
  id: "strike_entry",
  label: "Strike × Entry",
  hint: "Which strike rule is best at this exit offset?",
  rowKey: "strike_offset_pct",
  rowLabel: "STRIKE OFFSET (% OTM)",
  rowFmt: (v) => `${v}% OTM`,
  colKey: "entry_offset_td",
  colLabel: "ENTRY OFFSET (TD before expiry)",
  colFmt: (v) => `−${v}`,
  fixed: { exit_offset_td: 0 },
  phase: "phase-7-preview",
  rows: [0, 1, 2, 3, 5],   // ATM, 1%, 2%, 3%, 5%
  cols: [15, 12, 9, 6, 3],
  cells: {
    0: { 15: _enrich({ n: 24, roi: 178.4, win: 75.0, std: 312.6, pnl: 1.42 }, 21),
         12: _enrich({ n: 24, roi: 242.1, win: 79.2, std: 358.4, pnl: 1.94 }, 22),
          9: _enrich({ n: 24, roi: 318.7, win: 83.3, std: 422.6, pnl: 2.64 }, 23),
          6: _enrich({ n: 24, roi: 286.4, win: 75.0, std: 458.1, pnl: 2.08 }, 24),
          3: _enrich({ n: 22, roi: 192.3, win: 66.7, std: 521.4, pnl: 0.84 }, 25) },
    1: { 15: _enrich({ n: 24, roi: 156.2, win: 79.2, std: 224.1, pnl: 1.38 }, 26),
         12: _enrich({ n: 24, roi: 212.4, win: 83.3, std: 268.7, pnl: 1.82 }, 27),
          9: _enrich({ n: 24, roi: 264.8, win: 87.5, std: 298.4, pnl: 2.18 }, 28),
          6: _enrich({ n: 24, roi: 234.6, win: 79.2, std: 324.2, pnl: 1.74 }, 29),
          3: _enrich({ n: 22, roi: 138.2, win: 70.8, std: 384.6, pnl: 0.62 }, 30) },
    2: { 15: _enrich({ n: 24, roi: 144.7, win: 79.2, std: 224.0, pnl: 1.31 }, 31),
         12: _enrich({ n: 24, roi: 196.2, win: 83.3, std: 248.3, pnl: 1.71 }, 32),
          9: _enrich({ n: 24, roi: 247.9, win: 83.3, std: 287.6, pnl: 2.04 }, 33),
          6: _enrich({ n: 24, roi: 264.1, win: 79.2, std: 318.4, pnl: 1.88 }, 34),
          3: _enrich({ n: 22, roi: 184.2, win: 75.0, std: 372.4, pnl: 0.92 }, 35) },
    3: { 15: _enrich({ n: 24, roi:  98.4, win: 75.0, std: 184.6, pnl: 0.84 }, 36),
         12: _enrich({ n: 24, roi: 142.8, win: 79.2, std: 218.1, pnl: 1.18 }, 37),
          9: _enrich({ n: 24, roi: 184.6, win: 79.2, std: 254.8, pnl: 1.48 }, 38),
          6: _enrich({ n: 24, roi: 198.4, win: 75.0, std: 296.2, pnl: 1.32 }, 39),
          3: _enrich({ n: 18, roi: 124.2, win: 66.7, std: 362.1, pnl: 0.42 }, 40) },
    5: { 15: _enrich({ n: 18, roi:  42.6, win: 72.2, std: 142.4, pnl: 0.38 }, 41),
         12: _enrich({ n: 18, roi:  68.4, win: 77.8, std: 168.2, pnl: 0.62 }, 42),
          9: _enrich({ n: 16, roi:  82.1, win: 75.0, std: 196.4, pnl: 0.74 }, 43),
          6: _enrich({ n: 14, roi:  64.8, win: 71.4, std: 248.6, pnl: 0.41 }, 44),
          3: _enrich({ n:  4, roi:    "—", win:  "—", std:   "—", pnl: "—" }, 45) }, // thin
  },
};

// Lens C · year × entry  (fixed exit = 0, strike = 2%)
const LENS_YEAR_ENTRY = {
  id: "year_entry",
  label: "Year × Entry",
  hint: "Which entry offset is robust across years?",
  rowKey: "year",
  rowLabel: "YEAR",
  rowFmt: (v) => String(v),
  colKey: "entry_offset_td",
  colLabel: "ENTRY OFFSET (TD before expiry)",
  colFmt: (v) => `−${v}`,
  fixed: { exit_offset_td: 0, strike_offset_pct: 2 },
  rows: [2022, 2023, 2024],
  cols: [15, 12, 9, 6, 3],
  cells: {
    2022: { 15: _enrich({ n: 12, roi: 124.6, win: 75.0, std: 218.4, pnl: 0.62 }, 51),
            12: _enrich({ n: 12, roi: 176.8, win: 75.0, std: 248.2, pnl: 0.84 }, 52),
             9: _enrich({ n: 12, roi: 224.7, win: 83.3, std: 287.4, pnl: 1.04 }, 53),
             6: _enrich({ n: 12, roi: 248.2, win: 75.0, std: 312.6, pnl: 0.94 }, 54),
             3: _enrich({ n: 11, roi: 162.4, win: 72.7, std: 358.4, pnl: 0.42 }, 55) },
    2023: { 15: _enrich({ n: 12, roi: 142.8, win: 83.3, std: 198.4, pnl: 0.71 }, 56),
            12: _enrich({ n: 12, roi: 192.6, win: 83.3, std: 224.7, pnl: 0.86 }, 57),
             9: _enrich({ n: 12, roi: 218.3, win: 83.3, std: 268.4, pnl: 0.98 }, 58),
             6: _enrich({ n: 12, roi: 248.4, win: 83.3, std: 298.1, pnl: 1.04 }, 59),
             3: _enrich({ n: 11, roi: 168.2, win: 72.7, std: 348.2, pnl: 0.46 }, 60) },
    2024: { 15: _enrich({ n: 12, roi: 168.4, win: 83.3, std: 224.6, pnl: 0.84 }, 61),
            12: _enrich({ n: 12, roi: 214.2, win: 83.3, std: 248.1, pnl: 0.98 }, 62),
             9: _enrich({ n: 12, roi: 282.4, win: 91.7, std: 278.6, pnl: 1.14 }, 63),
             6: _enrich({ n: 12, roi: 274.6, win: 83.3, std: 322.4, pnl: 1.06 }, 64),
             3: _enrich({ n: 11, roi: 196.4, win: 72.7, std: 364.8, pnl: 0.48 }, 65) },
  },
};

// Lens D · strike × exit  (fixed entry = 9 TD)
const LENS_STRIKE_EXIT = {
  id: "strike_exit",
  label: "Strike × Exit",
  hint: "Which (strike, exit) pair wins at this entry offset?",
  rowKey: "strike_offset_pct", rowLabel: "STRIKE OFFSET (% OTM)", rowFmt: (v) => `${v}% OTM`,
  colKey: "exit_offset_td",    colLabel: "EXIT OFFSET (TD before expiry)", colFmt: (v) => v === 0 ? "0 (expiry)" : `−${v}`,
  fixed: { entry_offset_td: 9 },
  phase: "phase-7-preview",
  rows: [0, 1, 2, 3, 5], cols: [3, 1, 0],
  cells: {
    0: { 3: _enrich({ n: 24, roi: 184.6, win: 70.8, std: 268.4, pnl: 1.42 }, 71),
         1: _enrich({ n: 24, roi: 262.4, win: 75.0, std: 348.1, pnl: 2.18 }, 72),
         0: _enrich({ n: 24, roi: 318.7, win: 83.3, std: 422.6, pnl: 2.64 }, 73) },
    1: { 3: _enrich({ n: 24, roi: 162.8, win: 79.2, std: 198.4, pnl: 1.34 }, 74),
         1: _enrich({ n: 24, roi: 218.4, win: 87.5, std: 244.6, pnl: 1.86 }, 75),
         0: _enrich({ n: 24, roi: 264.8, win: 87.5, std: 298.4, pnl: 2.18 }, 76) },
    2: { 3: _enrich({ n: 24, roi: 142.1, win: 75.0, std: 197.2, pnl: 1.18 }, 77),
         1: _enrich({ n: 24, roi: 207.5, win: 79.2, std: 256.4, pnl: 1.78 }, 78),
         0: _enrich({ n: 24, roi: 247.9, win: 83.3, std: 287.6, pnl: 2.04 }, 79) },
    3: { 3: _enrich({ n: 24, roi: 116.4, win: 75.0, std: 174.6, pnl: 0.94 }, 80),
         1: _enrich({ n: 24, roi: 168.2, win: 79.2, std: 224.1, pnl: 1.42 }, 81),
         0: _enrich({ n: 24, roi: 184.6, win: 79.2, std: 254.8, pnl: 1.48 }, 82) },
    5: { 3: _enrich({ n: 16, roi:  52.4, win: 75.0, std: 124.6, pnl: 0.48 }, 83),
         1: _enrich({ n: 16, roi:  72.8, win: 75.0, std: 158.4, pnl: 0.68 }, 84),
         0: _enrich({ n: 16, roi:  82.1, win: 75.0, std: 196.4, pnl: 0.74 }, 85) },
  },
};

// Lens E · strike × year  (fixed entry=9, exit=0) — answers "has the optimal strike drifted?"
const LENS_STRIKE_YEAR = {
  id: "strike_year",
  label: "Strike × Year",
  hint: "Has the optimal strike rule drifted across years?",
  rowKey: "strike_offset_pct", rowLabel: "STRIKE OFFSET (% OTM)", rowFmt: (v) => `${v}% OTM`,
  colKey: "year",              colLabel: "YEAR",                  colFmt: (v) => String(v),
  fixed: { entry_offset_td: 9, exit_offset_td: 0 },
  phase: "phase-7-preview",
  rows: [0, 1, 2, 3, 5], cols: [2022, 2023, 2024],
  cells: {
    0: { 2022: _enrich({ n: 8, roi: 268.4, win: 75.0, std: 388.4, pnl: 0.84 }, 91),
         2023: _enrich({ n: 8, roi: 312.6, win: 87.5, std: 412.2, pnl: 0.94 }, 92),
         2024: _enrich({ n: 8, roi: 374.8, win: 87.5, std: 458.6, pnl: 1.04 }, 93) },
    1: { 2022: _enrich({ n: 8, roi: 244.2, win: 87.5, std: 268.4, pnl: 0.78 }, 94),
         2023: _enrich({ n: 8, roi: 268.4, win: 87.5, std: 296.1, pnl: 0.84 }, 95),
         2024: _enrich({ n: 8, roi: 281.6, win: 87.5, std: 318.4, pnl: 0.88 }, 96) },
    2: { 2022: _enrich({ n: 8, roi: 224.7, win: 75.0, std: 268.4, pnl: 0.68 }, 97),
         2023: _enrich({ n: 8, roi: 248.6, win: 87.5, std: 287.4, pnl: 0.72 }, 98),
         2024: _enrich({ n: 8, roi: 264.2, win: 87.5, std: 312.6, pnl: 0.76 }, 99) },
    3: { 2022: _enrich({ n: 8, roi: 168.4, win: 75.0, std: 224.6, pnl: 0.46 }, 101),
         2023: _enrich({ n: 8, roi: 184.6, win: 87.5, std: 248.1, pnl: 0.52 }, 102),
         2024: _enrich({ n: 8, roi: 198.4, win: 75.0, std: 268.4, pnl: 0.58 }, 103) },
    5: { 2022: _enrich({ n: 6, roi:  72.4, win: 66.7, std: 168.4, pnl: 0.21 }, 104),
         2023: _enrich({ n: 6, roi:  84.6, win: 83.3, std: 184.2, pnl: 0.24 }, 105),
         2024: _enrich({ n: 4, roi:  82.1, win: 75.0, std: 196.4, pnl: 0.21 }, 106) }, // thin in 2024
  },
};

const LENSES = [LENS_ENTRY_EXIT, LENS_STRIKE_ENTRY, LENS_STRIKE_EXIT, LENS_YEAR_ENTRY, LENS_STRIKE_YEAR];

// Strike rule descriptions per strategy (rendered under the strategy selector)
const STRIKE_RULES = {
  short_straddle:  { text: "ATM each side, nearest listed strike", param: "strike_offset_pct=0.00" },
  short_strangle:  { text: "2% OTM each side, nearest listed strike", param: "strike_offset_pct=0.02" },
  iron_condor:     { text: "2% OTM short legs · 4% OTM long legs", param: "short=0.02 / long=0.04" },
  long_straddle:   { text: "ATM each side, nearest listed strike", param: "strike_offset_pct=0.00" },
  long_strangle:   { text: "2% OTM each side, nearest listed strike", param: "strike_offset_pct=0.02" },
};

// Per-cell synthesized trades (deterministic) — used by drill-down
function tradesForCell(cell, entryLabel, exitLabel, strategyKey, symbol, year) {
  if (cell.roi === "—" || cell.n < 1) return [];
  const out = [];
  const expMonths = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
  const sigma = cell.std / 100; // approximate
  const median = cell.roi / 100;
  let seed = (cell.n * 13 + median * 100) | 0;
  function rand() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }
  for (let i = 0; i < cell.n; i++) {
    const y = year ?? (2023 + (i < cell.n / 2 ? 0 : 1));
    const m = expMonths[i % 12];
    // Long-tail: positive-skewed mixture (winners cluster, losers fat tail)
    const u = rand();
    let z = u < 0.78
      ? median * (0.5 + rand() * 1.2)            // typical winner
      : -median * (0.5 + rand() * 2.5);          // tail loser
    z = +(z * 100).toFixed(1);
    const pnl = Math.round(z * 1200);            // ~₹1200 per 1% per lot
    out.push({
      expiry: `${y}-${m}`,
      roi: z,
      pnl,
      iv_entry: +(14 + rand() * 14).toFixed(1),
      iv_exit: +(8 + rand() * 12).toFixed(1),
    });
  }
  return out.sort((a, b) => b.roi - a.roi);
}

// Skipped expiries (per cell, fixed for short_straddle x RELIANCE)
const SKIPPED = {
  // key entry-exit
  "3-0": [
    { exp: "2023-AUG", reason: "NoLiquidStrike", note: "min OI below 50 on ATM call leg" },
    { exp: "2024-NOV", reason: "MissingData",    note: "L1 quotes gap >90s at intended entry" },
  ],
  "6-1": [
    { exp: "2023-MAR", reason: "NoLiquidStrike", note: "wide spread on put leg, >1.5%" },
  ],
};

// Per-stock cards (all strategies for one symbol) — used in Per-stock tab
const PER_STOCK = {
  RELIANCE: [
    { strategy: "short_straddle", n: 72, median: 189.4, win: 77.8, std: 287.6, total: 421250, sparkY: [120,140,165,190,155,210,232,225,247,238,265,210] },
    { strategy: "short_strangle", n: 74, median:  94.7, win: 75.6, std: 189.3, total: 187200, sparkY: [78, 92, 105, 88, 112, 124, 96, 118, 134, 102, 128, 96] },
    { strategy: "iron_condor",    n: 76, median:  72.1, win: 81.5, std:  78.6, total:  98200, sparkY: [62, 68, 72, 78, 82, 74, 86, 81, 76, 84, 79, 72] },
    { strategy: "long_straddle",  n: 68, median: -42.6, win: 26.4, std: 124.8, total: -98400, sparkY: [-40,-32,-48,-55,-22,-38,-42,-65,-38,-44,-52,-28] },
    { strategy: "long_strangle",  n: 64, median: -58.3, win: 21.8, std: 142.4, total: -112800,sparkY: [-50,-58,-62,-48,-72,-55,-44,-65,-58,-72,-48,-60] },
  ],
  HDFCBANK: [
    { strategy: "short_strangle", n: 78, median: 164.2, win: 82.1, std: 198.4, total: 298100, sparkY: [142,158,168,174,182,156,178,184,164,172,168,158] },
    { strategy: "short_straddle", n: 72, median: 121.3, win: 73.6, std: 224.7, total: 248600, sparkY: [98,118,124,142,108,132,124,128,148,118,124,108] },
    { strategy: "iron_condor",    n: 80, median:  98.2, win: 84.4, std:  72.4, total: 156900, sparkY: [82,88,94,98,102,96,104,102,98,104,96,92] },
    { strategy: "long_straddle",  n: 70, median: -28.4, win: 31.4, std: 102.4, total: -56400, sparkY: [-22,-32,-28,-44,-18,-32,-26,-38,-28,-32,-18,-26] },
    { strategy: "long_strangle",  n: 68, median: -41.2, win: 27.9, std: 124.2, total: -72400, sparkY: [-38,-42,-38,-52,-28,-44,-38,-48,-42,-46,-38,-44] },
  ],
};

window.MORENSE_DATA = {
  SWEEPS, STRATEGIES, SYMBOLS, LEADERBOARD, THIN_SAMPLES,
  HEATMAP_ENTRIES, HEATMAP_EXITS, HEATMAP_CELLS, YOY, MOY, PER_STOCK,
  LENSES, STRIKE_RULES, SKIPPED, tradesForCell,
};
