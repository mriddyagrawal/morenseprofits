// Leaderboard tab — sortable rank table + thin-samples sidecar + within/across toggle.

function fmtPct(v, decimals = 1) {
  if (v == null || v === "—") return "—";
  return `${v >= 0 ? "" : ""}${v.toFixed(decimals)}%`;
}
function fmtINR(v) {
  if (v == null) return "—";
  const sign = v < 0 ? "−" : "";
  const a = Math.abs(v);
  if (a >= 100000) return `${sign}₹${(a / 100000).toFixed(2)}L`;
  return `${sign}₹${a.toLocaleString("en-IN")}`;
}

const SORT_OPTIONS = [
  { key: "median",  label: "median_roi_pct_annualized",  short: "median ROI/yr" },
  { key: "mean",    label: "mean_roi_pct_annualized",    short: "mean ROI/yr"   },
  { key: "total",   label: "total_net_pnl",              short: "Σ net P&L"     },
  { key: "win",     label: "win_rate_pct",               short: "win rate"      },
];

function Leaderboard({ filters }) {
  const { LEADERBOARD, THIN_SAMPLES, STRATEGIES } = window.MORENSE_DATA;
  const [sortBy, setSortBy] = React.useState("median");
  const [sortDir, setSortDir] = React.useState("desc");
  const [view, setView] = React.useState("across"); // across | within
  const [selected, setSelected] = React.useState(null);

  const minN = filters.minN;

  const stratClass = (key) => STRATEGIES.find(s => s.key === key)?.cls || "";
  const stratShort = (key) => STRATEGIES.find(s => s.key === key)?.short || key;
  const stratLabel = (key) => STRATEGIES.find(s => s.key === key)?.label || key;

  // Filter by sidebar
  let rows = LEADERBOARD.filter(r =>
    filters.strategies.includes(r.strategy) &&
    filters.symbols.includes(r.symbol) &&
    r.n >= minN
  );

  // Sort
  rows = [...rows].sort((a, b) => {
    const av = a[sortBy], bv = b[sortBy];
    if (av === bv) {
      // Stable tiebreak: higher N first
      if (a.n !== b.n) return b.n - a.n;
      return a.symbol.localeCompare(b.symbol);
    }
    return sortDir === "desc" ? bv - av : av - bv;
  });

  // Within-stock: regroup so each symbol's strategies cluster.
  if (view === "within") {
    const bySym = {};
    rows.forEach(r => { (bySym[r.symbol] ||= []).push(r); });
    rows = Object.keys(bySym).flatMap(sym => bySym[sym]);
  }

  const sortInd = (key) => sortBy === key ? (sortDir === "desc" ? "↓" : "↑") : null;

  const onSort = (key) => {
    if (sortBy === key) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortBy(key); setSortDir("desc"); }
  };

  const maxAbsMedian = Math.max(...rows.map(r => Math.abs(r.median)), 1);

  const thin = THIN_SAMPLES.filter(r =>
    filters.strategies.includes(r.strategy) &&
    filters.symbols.includes(r.symbol)
  );

  // KPIs
  const winners = rows.filter(r => r.median > 0);
  const totalNetSum = rows.reduce((s, r) => s + r.total, 0);
  const medianOfMedians = (() => {
    const arr = [...rows.map(r => r.median)].sort((a, b) => a - b);
    if (!arr.length) return 0;
    const mid = Math.floor(arr.length / 2);
    return arr.length % 2 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
  })();

  return (
    <>
      <div className="page-h">
        <h1><em>The</em>Leaderboard</h1>
        <span className="sub">summarize_by_stock_strategy → rank_strategies(min_n={minN})</span>
        <div className="right">
          <button className="btn"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> CSV</button>
          <button className="btn">copy as DataFrame</button>
        </div>
      </div>

      {rows.length > 0 && (() => {
        const top = rows[0];
        const meta = STRATEGIES.find(s => s.key === top.strategy);
        return (
          <div className="hero">
            <div className="hero-left">
              <div className="hero-eyebrow">
                <span className="accent">▲</span> Top of the table
                <span style={{ color: "var(--text-4)" }}>·</span>
                <span>by {SORT_OPTIONS.find(o => o.key === sortBy).short}</span>
                <span style={{ color: "var(--text-4)" }}>·</span>
                <span className="mono">#1 of {rows.length}</span>
              </div>
              <div className="hero-title">
                <span className="strat">{meta.label}</span>
                <span className="x">×</span>
                <span className="sym">{top.symbol}</span>
              </div>
              <div className="hero-headline">
                <span className="big">{top.median.toFixed(1)}<span style={{ fontSize: "0.55em" }}>%</span></span>
                <span className="unit">median RoI / annualized</span>
              </div>
              <div className="hero-readouts">
                <div><div className="k">n_trades</div><div className="v">{top.n}</div></div>
                <div><div className="k">win rate</div><div className="v">{top.win.toFixed(1)}%</div></div>
                <div><div className="k">mean RoI / yr</div><div className="v"><span className={top.mean >= 0 ? "up" : "down"}>{top.mean.toFixed(1)}%</span></div></div>
                <div><div className="k">std (ddof=0)</div><div className="v dim">{top.std.toFixed(1)}</div></div>
                <div><div className="k">Σ net P&amp;L</div><div className="v"><span className={top.total >= 0 ? "up" : "down"}>{fmtINR(top.total)}</span></div></div>
                <div><div className="k">margin (Tier-B)</div><div className="v dim">₹2.41L</div></div>
                <div><div className="k">slippage</div><div className="v dim">1% / side</div></div>
                <div><div className="k">cost / trade</div><div className="v dim">₹287</div></div>
              </div>
            </div>
            <div className="hero-right">
              <div className="label">Reading</div>
              <div className="note">
                <span className="accent">{top.win.toFixed(0)}% win rate</span> on {top.n} expiries,
                heavy-tailed (<span className="mono">std {top.std.toFixed(0)}</span>) — typical
                short-vol distribution. Treat the headline as the <em>hypothesis</em>; drill into
                the (entry × exit) heatmap and YoY trend before sizing.
              </div>
              <div className="hero-actions">
                <button className="btn primary">Open in Heatmap →</button>
                <button className="btn">Year-on-year</button>
              </div>
            </div>
          </div>
        );
      })()}

      <div className="kpi-row">
        <div className="kpi">
          <div className="label">Ranked pairs</div>
          <div className="v">{rows.length}<span style={{ color: "var(--text-3)", fontSize: 14 }}> / {LEADERBOARD.length}</span></div>
          <div className="delta">{LEADERBOARD.length - rows.length} suppressed by filters · {thin.length} thin</div>
        </div>
        <div className="kpi">
          <div className="label">Median of medians</div>
          <div className="v"><span className={medianOfMedians >= 0 ? "up" : "down"}>{medianOfMedians.toFixed(1)}%</span><span style={{ color: "var(--text-3)", fontSize: 13 }}> / yr</span></div>
          <div className="delta">across {rows.length} (strategy × symbol)</div>
        </div>
        <div className="kpi">
          <div className="label">Σ net P&amp;L</div>
          <div className="v"><span className={totalNetSum >= 0 ? "up" : "down"}>{fmtINR(totalNetSum)}</span></div>
          <div className="delta">summed, not compounded · §SPECS 4a</div>
        </div>
        <div className="kpi">
          <div className="label">Profitable cells</div>
          <div className="v">{winners.length}<span style={{ color: "var(--text-3)", fontSize: 14 }}> / {rows.length}</span></div>
          <div className="delta">≥ 0% median annualized RoI</div>
        </div>
      </div>

      <div className="tbl-wrap">
        <div className="tbl-head">
          <span className="title">All (strategy × symbol) pairs</span>
          <span className="meta">· min_N≥{minN} · sorted by {SORT_OPTIONS.find(o => o.key === sortBy).short} {sortDir === "desc" ? "↓" : "↑"}</span>
          <div className="right">
            <div className="seg" role="tablist">
              <button className={view === "across"  ? "active" : ""} onClick={() => setView("across")}>Across stocks</button>
              <button className={view === "within"  ? "active" : ""} onClick={() => setView("within")}>Within stock</button>
            </div>
            <SortMenu sortBy={sortBy} onPick={(k) => onSort(k)} />
          </div>
        </div>

        <table className="lb">
          <thead>
            <tr>
              <th style={{ width: 50 }}>rank</th>
              <th>strategy</th>
              <th>symbol</th>
              <th className="num sortable" onClick={() => onSort("n")}>n_trades {sortInd("n")}</th>
              <th className="num sortable" onClick={() => onSort("win")}>win % {sortInd("win")}</th>
              <th className="num sortable" onClick={() => onSort("median")}>median ROI/yr {sortInd("median")}</th>
              <th className="num sortable" onClick={() => onSort("mean")}>mean ROI/yr {sortInd("mean")}</th>
              <th className="num" title="observed-sample dispersion (ddof=0), not a population estimate">
                std (ddof=0) <span style={{ color: "var(--text-3)" }}>ⓘ</span>
              </th>
              <th className="num sortable" onClick={() => onSort("total")}>Σ net P&amp;L {sortInd("total")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.strategy}-${r.symbol}`}
                  className={selected === `${r.strategy}-${r.symbol}` ? "selected" : ""}
                  onClick={() => setSelected(`${r.strategy}-${r.symbol}`)}>
                <td>
                  <span className="rank-cell mono">
                    <span style={{ color: "var(--text-3)" }}>#</span>
                    <span className="n">{i + 1}</span>
                  </span>
                </td>
                <td>
                  <span className={`strat-tag ${stratClass(r.strategy)}`}>{stratShort(r.strategy)}</span>
                  <span className="dim">{stratLabel(r.strategy).replace("Short ", "").replace("Long ", "")}</span>
                </td>
                <td><span className="sym">{r.symbol}</span></td>
                <td className="num mono">{r.n}</td>
                <td className="num mono">{r.win.toFixed(1)}</td>
                <td className="num mono">
                  <span className="minibar">
                    <span style={{
                      width: `${Math.min(100, (Math.abs(r.median) / maxAbsMedian) * 100)}%`,
                      background: r.median >= 0 ? "var(--pos)" : "var(--neg)",
                    }}/>
                  </span>
                  <span className={r.median >= 0 ? "up" : "down"} style={{ display: "inline-block", minWidth: 60, textAlign: "right" }}>
                    {r.median.toFixed(1)}%
                  </span>
                </td>
                <td className="num mono dim">{r.mean.toFixed(1)}%</td>
                <td className="num mono dim">{r.std.toFixed(1)}</td>
                <td className="num mono"><span className={r.total >= 0 ? "up" : "down"}>{fmtINR(r.total)}</span></td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan="9">
                <div className="empty" style={{ margin: "20px 14px" }}>
                  Every pair was suppressed by filters or min_N ≥ {minN}.<br/>
                  Lower min_N in the sidebar, or widen the symbol/strategy filter.
                </div>
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="thin-sidecar">
        <div className="tbl-head">
          <span className="title">Thin samples — not ranked</span>
          <span className="meta">· n &lt; min_N ({minN}) · surfaced per feat(p6.2.thin)</span>
          <div className="right">
            <span className="suppressed mono">{thin.length} rows suppressed from the ranker</span>
          </div>
        </div>
        <table className="lb">
          <thead>
            <tr>
              <th style={{ width: 50 }}></th>
              <th>strategy</th>
              <th>symbol</th>
              <th className="num">n</th>
              <th>scope</th>
              <th>reason</th>
            </tr>
          </thead>
          <tbody>
            {thin.map((r, i) => (
              <tr key={`${r.strategy}-${r.symbol}-${i}`}>
                <td><span className="mono" style={{ color: "var(--text-4)" }}>—</span></td>
                <td>
                  <span className={`strat-tag ${stratClass(r.strategy)}`}>{stratShort(r.strategy)}</span>
                  <span className="dim">{stratLabel(r.strategy).replace("Short ","").replace("Long ","")}</span>
                </td>
                <td><span className="sym">{r.symbol}</span></td>
                <td className="num mono">{r.n}</td>
                <td className="mono dim">{r.regime}</td>
                <td className="dim">{r.note}</td>
              </tr>
            ))}
            {thin.length === 0 && (
              <tr><td colSpan="6"><div style={{ padding: "18px 14px", color: "var(--text-3)" }}>
                No thin samples at min_N={minN}. ✓
              </div></td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="runmeta">
        <span><b>engine.sweep_grid</b> · 3812 priced cells · 184 skips (NoLiquidStrike: 142, MissingData: 42)</span>
        <span><b>median pipeline</b> · 28ms per (strategy, symbol)</span>
        <span><b>annualization</b> · trading-day-exact (no 252/365 approximation)</span>
      </div>
    </>
  );
}

function SortMenu({ sortBy, onPick }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  React.useEffect(() => {
    function onDoc(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  const current = SORT_OPTIONS.find(o => o.key === sortBy);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="menu" onClick={() => setOpen(o => !o)}>
        <span className="lbl">sort_by</span>
        <span className="val">{current.short}</span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", right: 0,
          background: "var(--surface)", border: "1px solid var(--border-strong)",
          borderRadius: 6, padding: 4, minWidth: 260, zIndex: 30, boxShadow: "var(--shadow)",
        }}>
          {SORT_OPTIONS.map(o => (
            <button key={o.key}
                    onClick={() => { onPick(o.key); setOpen(false); }}
                    style={{
                      display: "flex", flexDirection: "column", gap: 1, width: "100%",
                      padding: "7px 10px", textAlign: "left", borderRadius: 4,
                      background: sortBy === o.key ? "var(--accent-bg)" : "transparent", cursor: "pointer",
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = sortBy === o.key ? "var(--accent-bg)" : "var(--surface-2)"}
                    onMouseLeave={e => e.currentTarget.style.background = sortBy === o.key ? "var(--accent-bg)" : "transparent"}>
              <span className="mono" style={{ fontSize: 12, color: sortBy === o.key ? "var(--accent)" : "var(--text)" }}>{o.label}</span>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--text-3)" }}>{o.short}</span>
            </button>
          ))}
          <div style={{
            padding: "8px 10px", marginTop: 4, borderTop: "1px dashed var(--border)",
            color: "var(--text-3)", fontSize: 10.5, lineHeight: 1.5,
          }}>
            Excluded: <span className="mono">Sharpe-like</span> — risk-free not subtracted (DESIGN_SPEC §2.4)
          </div>
        </div>
      )}
    </div>
  );
}

window.Leaderboard = Leaderboard;
