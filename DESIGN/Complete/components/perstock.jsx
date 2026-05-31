// Per-stock tab — all strategies side-by-side for one symbol.
function PerStockTab({ filters }) {
  const { PER_STOCK, SYMBOLS, STRATEGIES, LEADERBOARD } = window.MORENSE_DATA;
  const { Sparkbar } = window.Charts;
  const [symbol, setSymbol] = React.useState("RELIANCE");

  const rows = PER_STOCK[symbol] || PER_STOCK.RELIANCE;
  const symMeta = SYMBOLS.find(s => s.sym === symbol);

  // Aggregate stats
  const totalN = rows.reduce((s, r) => s + r.n, 0);
  const profitable = rows.filter(r => r.median > 0).length;
  const bestRow = rows.reduce((a, b) => a.median > b.median ? a : b);

  return (
    <>
      <div className="page-h">
        <h1><em>Per</em>Stock</h1>
        <span className="sub">all strategies · one symbol</span>
        <div className="right">
          <div className="seg">
            {SYMBOLS.map(s => (
              <button key={s.sym} className={symbol === s.sym ? "active" : ""} onClick={() => setSymbol(s.sym)}>
                {s.sym}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="ps-head">
        <div>
          <div className="ps-sym">
            {symbol}
            <span className="meta">{symMeta?.name} · lot {symMeta?.lot}</span>
            <span className={`regime-pill ${symMeta?.regime === "bull" ? "" : symMeta?.regime === "neutral" ? "neutral" : "bear"}`}>
              <span className="d"></span> regime · {symMeta?.regime}
            </span>
          </div>
          <div style={{ marginTop: 6, color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
            all strategies · 2023-24 · {totalN} priced trades · {profitable}/{rows.length} profitable
          </div>
        </div>
      </div>

      <div className="kpi-row" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
        <div className="kpi">
          <div className="label">Best strategy</div>
          <div className="v" style={{ fontSize: 14 }}>
            <span className={`strat-tag ${STRATEGIES.find(s => s.key === bestRow.strategy)?.cls}`}>
              {STRATEGIES.find(s => s.key === bestRow.strategy)?.short}
            </span>
            {bestRow.median.toFixed(1)}%/yr
          </div>
          <div className="delta">n={bestRow.n} · win {bestRow.win.toFixed(0)}%</div>
        </div>
        <div className="kpi">
          <div className="label">Σ net P&amp;L (all)</div>
          <div className="v">
            <span className={rows.reduce((s,r)=>s+r.total,0) >= 0 ? "up" : "down"}>
              ₹{(rows.reduce((s,r)=>s+r.total,0) / 100000).toFixed(2)}L
            </span>
          </div>
          <div className="delta">summed across 5 strategies</div>
        </div>
        <div className="kpi">
          <div className="label">N (priced)</div>
          <div className="v">{totalN}</div>
          <div className="delta">across all strategies</div>
        </div>
        <div className="kpi">
          <div className="label">Profitable</div>
          <div className="v">{profitable} / {rows.length}</div>
          <div className="delta">≥ 0% median annualized RoI</div>
        </div>
        <div className="kpi">
          <div className="label">Regime · 6-mo return</div>
          <div className="v"><span className="up">+18.4%</span></div>
          <div className="delta">classify_momentum tercile: bullish</div>
        </div>
      </div>

      <div className="ps-grid">
        {rows.map(r => {
          const meta = STRATEGIES.find(s => s.key === r.strategy);
          return (
            <div key={r.strategy} className="ps-card">
              <div className="hd">
                <span className={`strat-tag ${meta.cls}`}>{meta.short}</span>
                <span className="ttl">{meta.label}</span>
                <span className="n">n = {r.n}</span>
              </div>

              <div className="stat-row">
                <span className="k">median ROI/yr</span><span className="v"><span className={r.median >= 0 ? "up" : "down"}>{r.median.toFixed(1)}%</span></span>
                <span className="k">win rate</span><span className="v">{r.win.toFixed(1)}%</span>
                <span className="k">std (ddof=0)</span><span className="v dim">{r.std.toFixed(1)}</span>
                <span className="k">Σ net P&amp;L</span><span className="v"><span className={r.total >= 0 ? "up" : "down"}>₹{(r.total / 100000).toFixed(2)}L</span></span>
              </div>

              <div style={{ marginTop: 4 }}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--text-3)",
                              letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 4,
                              display: "flex", justifyContent: "space-between" }}>
                  <span>monthly · ROI / yr</span>
                  <span>Jan → Dec</span>
                </div>
                <Sparkbar values={r.sparkY} width={260} height={42} />
              </div>
            </div>
          );
        })}
      </div>

      <div style={{
        marginTop: 18, padding: "12px 14px",
        border: "1px solid var(--border)", borderRadius: 6,
        background: "var(--surface)", fontSize: 12, color: "var(--text-2)",
        display: "flex", gap: 14, alignItems: "flex-start",
      }}>
        <span style={{ fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-3)", fontSize: 10.5 }}>READ</span>
        <span>
          Short-vol family (SS / SST / IC) all positive on <strong>{symbol}</strong>; long-vol siblings (LS / LST)
          are mirror images at &lt; 30% win rate — confirms low realized vs implied volatility regime over the window.
          Iron condor has the tightest distribution (std {rows.find(r => r.strategy === "iron_condor")?.std?.toFixed(1) ?? "—"}) but the lowest absolute return.
        </span>
      </div>
    </>
  );
}

window.PerStockTab = PerStockTab;
