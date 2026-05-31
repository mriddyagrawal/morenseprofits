// Trends tab — YoY line + MoY bar for one (strategy, symbol)
function TrendsTab({ filters }) {
  const { YOY, MOY, STRATEGIES } = window.MORENSE_DATA;
  const { LineChart, BarChart } = window.Charts;
  const [pair, setPair] = React.useState({ strategy: "short_straddle", symbol: "RELIANCE" });
  const stratLabel = STRATEGIES.find(s => s.key === pair.strategy)?.label;

  // Identify tightest / widest months
  const stds = MOY.map(m => m.std);
  const tightestIdx = stds.indexOf(Math.min(...stds));
  const widestIdx   = stds.indexOf(Math.max(...stds));
  const bestMedian  = MOY.reduce((a, b) => a.median > b.median ? a : b);
  const worstMedian = MOY.reduce((a, b) => a.median < b.median ? a : b);

  return (
    <>
      <div className="page-h">
        <h1><em>The</em>Trend</h1>
        <span className="sub">summarize_by_year · summarize_by_month</span>
        <div className="right">
          <window.PairPicker pair={pair} setPair={setPair} />
        </div>
      </div>

      <div className="trends-row">
        <div className="chart-card">
          <div className="hd">
            <div className="ttl">YoY · {stratLabel} × {pair.symbol}</div>
            <div className="sub">median + mean RoI per year</div>
            <div className="right">trailing 3 years</div>
          </div>
          <LineChart data={YOY} xKey="year" yKey="median" secondaryKey="mean" width={520} />
          <div style={{ display: "flex", gap: 18, marginTop: 6, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)" }}>
            <span><span style={{ display: "inline-block", width: 16, height: 2, background: "var(--accent)", verticalAlign: "middle", marginRight: 6 }}></span>median ROI/yr</span>
            <span><span style={{ display: "inline-block", width: 16, height: 1.5, borderTop: "1.5px dashed var(--text-3)", verticalAlign: "middle", marginRight: 6 }}></span>mean ROI/yr</span>
            <span style={{ marginLeft: "auto" }}>"Is this strategy decaying?"</span>
          </div>
        </div>

        <div className="chart-card">
          <div className="hd">
            <div className="ttl">YoY · win rate &amp; sample size</div>
            <div className="sub">win_rate_pct</div>
          </div>
          <LineChart
            data={YOY.map(d => ({ ...d, val: d.win }))}
            xKey="year" yKey="win" width={520}
            fmt={(v) => `${v.toFixed(0)}%`}
          />
        </div>
      </div>

      <div className="chart-card" style={{ marginBottom: 14 }}>
        <div className="hd">
          <div className="ttl">Month-of-year seasonality · {pair.symbol}</div>
          <div className="sub">median ROI/yr · n=6 per bin (2 years × 3 expiries... here verify-set extended)</div>
          <div className="right">
            <span style={{ color: "var(--pos)" }}>● best</span>
            <span style={{ margin: "0 8px", color: "var(--text-3)" }}>·</span>
            <span style={{ color: "var(--warn)" }}>● tightest std</span>
          </div>
        </div>
        <BarChart data={MOY} xKey="m" yKey="median" nKey="n" width={1040} height={260} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        <SeasonReadout label="Best month" v={`+${bestMedian.median.toFixed(1)}%/yr`} sub={`${bestMedian.m} · n=${bestMedian.n}`} tone="pos" />
        <SeasonReadout label="Worst month" v={`+${worstMedian.median.toFixed(1)}%/yr`} sub={`${worstMedian.m} · n=${worstMedian.n}`} tone="dim" />
        <SeasonReadout label="Tightest std" v={`${MOY[tightestIdx].std.toFixed(1)}`} sub={`${MOY[tightestIdx].m} · median ${MOY[tightestIdx].median.toFixed(1)}%`} tone="warn" />
        <SeasonReadout label="Widest std" v={`${MOY[widestIdx].std.toFixed(1)}`} sub={`${MOY[widestIdx].m} · median ${MOY[widestIdx].median.toFixed(1)}%`} tone="neg" />
      </div>

      <div style={{
        marginTop: 18, padding: "12px 14px",
        border: "1px solid var(--border)", borderRadius: 6,
        background: "var(--surface)", fontSize: 12, color: "var(--text-2)",
        display: "flex", gap: 14, alignItems: "flex-start",
      }}>
        <span style={{ fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-3)", fontSize: 10.5 }}>READ</span>
        <span>
          October pays best (<strong className="up">+312.6%/yr</strong>, std 124.1) and Feb is the tightest distribution
          (<strong style={{ color: "var(--warn)" }}>std 94.3</strong>) — both candidates for further drill-down.
          Dec and Aug medians sit near zero with wide std — likely noise, not signal at n=6.
        </span>
      </div>
    </>
  );
}

function SeasonReadout({ label, v, sub, tone }) {
  const color = tone === "pos" ? "var(--pos)" : tone === "neg" ? "var(--neg)" : tone === "warn" ? "var(--warn)" : "var(--text)";
  return (
    <div style={{
      padding: "12px 14px", border: "1px solid var(--border)",
      background: "var(--surface)", borderRadius: 6,
    }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--text-3)",
                    letterSpacing: "0.06em", textTransform: "uppercase" }}>{label}</div>
      <div className="mono" style={{ fontSize: 19, fontWeight: 500, marginTop: 4, color, fontFeatureSettings: '"tnum"' }}>{v}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{sub}</div>
    </div>
  );
}

window.TrendsTab = TrendsTab;
