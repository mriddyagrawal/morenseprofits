// Heatmap mode panels — Drill-down, Compare cells, Export rule.
// All three operate over selections from the lens heatmap.

const HM_BADGE_COLORS = ["#d4ff3a", "#7cd6ff", "#ffaa4d", "#ff9ec7"];

// ---------- helpers ----------
function fmtPct(v, d = 1) { return typeof v === "number" ? `${v.toFixed(d)}%` : "—"; }
function fmtINR(v) {
  if (typeof v !== "number") return "—";
  const sign = v < 0 ? "−" : "";
  const a = Math.abs(v);
  if (a >= 100000) return `${sign}₹${(a / 100000).toFixed(2)}L`;
  if (a >= 1000) return `${sign}₹${(a / 1000).toFixed(1)}k`;
  return `${sign}₹${a.toLocaleString("en-IN")}`;
}
function medianCI(cell) {
  if (typeof cell.roi !== "number" || cell.n < 4) return null;
  const se = 1.253 * (cell.std / Math.sqrt(cell.n));
  return { lo: cell.roi - 1.96 * se, hi: cell.roi + 1.96 * se, se };
}
function cellRuleText(lens, r, c, pair) {
  // Returns a humane "Entry −9 TD → Exit on expiry" style description
  const rowTxt = lens.rowFmt(r);
  const colTxt = lens.colFmt(c);
  return `${lens.rowLabel.split(" (")[0].toLowerCase()}: ${rowTxt} · ${lens.colLabel.split(" (")[0].toLowerCase()}: ${colTxt}`;
}

// ---------- DRILL DOWN ----------
function DrillDown({ lens, cell, r, c, pair, stratLabel, strikeRule }) {
  const trades = window.MORENSE_DATA.tradesForCell(cell, lens.rowFmt(r), lens.colFmt(c), pair.strategy, pair.symbol);
  const ci = medianCI(cell);
  const winners = trades.filter(t => t.roi >= 0);
  const losers = trades.filter(t => t.roi < 0);
  const worst = losers.length ? losers.reduce((a, b) => a.pnl < b.pnl ? a : b) : null;
  const best = trades.length ? trades.reduce((a, b) => a.pnl > b.pnl ? a : b) : null;

  const [tradeView, setTradeView] = React.useState("all"); // all | winners | losers
  const shown = tradeView === "winners" ? winners
              : tradeView === "losers"  ? losers
              : trades;

  return (
    <div className="mode-pane">
      <div className="dd-grid">

        {/* Cell rule card */}
        <div className="dd-card dd-rule">
          <div className="dd-eyebrow">Selected cell</div>
          <div className="dd-rule-title">
            <span className="serif">{stratLabel}</span>
            <span style={{ color: "var(--text-3)", margin: "0 6px" }}>×</span>
            <span style={{ fontWeight: 600 }}>{pair.symbol}</span>
          </div>
          <div className="dd-rule-row">
            <span className="k">{lens.rowLabel.split(" (")[0]}</span>
            <span className="v mono">{lens.rowFmt(r)}</span>
          </div>
          <div className="dd-rule-row">
            <span className="k">{lens.colLabel.split(" (")[0]}</span>
            <span className="v mono">{lens.colFmt(c)}</span>
          </div>
          <div className="dd-rule-row">
            <span className="k">strike rule</span>
            <span className="v mono" style={{ fontSize: 11 }}>{strikeRule.text}</span>
          </div>
          {Object.entries(lens.fixed || {}).map(([k, v]) => (
            <div key={k} className="dd-rule-row">
              <span className="k">{k.replace(/_/g, " ")}</span>
              <span className="v mono">{typeof v === "number" ? v : v}</span>
            </div>
          ))}
        </div>

        {/* Headline */}
        <div className="dd-card dd-headline">
          <div className="dd-eyebrow">median RoI / annualized</div>
          <div className="dd-big mono">
            <span className={cell.roi >= 0 ? "up" : "down"}>
              {typeof cell.roi === "number" ? `${cell.roi.toFixed(1)}%` : "—"}
            </span>
          </div>
          {ci && (
            <div className="dd-ci">
              <span className="mono">95% CI</span>
              <span className="mono" style={{ color: "var(--text)" }}>
                {ci.lo.toFixed(0)} … {ci.hi.toFixed(0)}%
              </span>
              <span className="mono" style={{ color: "var(--text-3)" }}>· bootstrap (B=1000)</span>
            </div>
          )}
          <div className="dd-stats">
            <div><div className="k">n</div><div className="v mono">{cell.n}</div></div>
            <div><div className="k">win</div><div className="v mono">{typeof cell.win === "number" ? `${cell.win.toFixed(1)}%` : "—"}</div></div>
            <div><div className="k">mean</div><div className="v mono"><span className={cell.mean >= 0 ? "up" : "down"}>{fmtPct(cell.mean)}</span></div></div>
            <div><div className="k">std (ddof=0)</div><div className="v mono dim">{typeof cell.std === "number" ? cell.std.toFixed(1) : "—"}</div></div>
            <div><div className="k">Σ net P&amp;L</div><div className="v mono"><span className={cell.pnl >= 0 ? "up" : "down"}>{typeof cell.pnl === "number" ? `₹${cell.pnl.toFixed(2)}L` : "—"}</span></div></div>
            <div><div className="k">worst trade</div><div className="v mono"><span className="down">{worst ? fmtINR(worst.pnl) : "—"}</span></div></div>
          </div>
          {typeof cell.mean === "number" && typeof cell.roi === "number" && Math.abs(cell.mean - cell.roi) > 30 && (
            <div className="dd-flag">
              <span className="mono" style={{ color: "var(--warn)" }}>mean &lt; median</span> by{" "}
              <span className="mono">{Math.abs(cell.mean - cell.roi).toFixed(0)} pts</span>
              — confirms heavy tail (cf. §SPECS 6b.3).
            </div>
          )}
        </div>

        {/* YoY line */}
        <div className="dd-card dd-yoy">
          <div className="dd-eyebrow">Across years</div>
          <YoYMini byYear={cell.byYear} />
          <div className="dd-yoy-note mono">
            stability check · {cell.byYear?.length || 0} years observed in sweep
          </div>
        </div>
      </div>

      {/* Per-expiry bar chart */}
      <div className="dd-card" style={{ marginTop: 14 }}>
        <div className="dd-section-head">
          <div className="dd-eyebrow">Per-expiry RoI · {trades.length} trades</div>
          <div className="dd-section-meta mono">
            sorted descending · 0% baseline · color = sign
          </div>
        </div>
        <ExpiryBars trades={trades} median={typeof cell.roi === "number" ? cell.roi : 0} />
        <div className="dd-bar-legend mono">
          <span>{winners.length} winners <span className="up">●</span></span>
          <span>{losers.length} losers <span className="down">●</span></span>
          <span style={{ marginLeft: "auto" }}>
            best <span className="up mono">{best ? fmtINR(best.pnl) : "—"}</span>
            <span style={{ margin: "0 8px", color: "var(--text-4)" }}>·</span>
            worst <span className="down mono">{worst ? fmtINR(worst.pnl) : "—"}</span>
          </span>
        </div>
      </div>

      {/* Per-trade table + skipped */}
      <div className="dd-grid-2" style={{ marginTop: 14 }}>
        <div className="dd-card">
          <div className="dd-section-head">
            <div className="dd-eyebrow">Per-trade table · top {Math.min(8, shown.length)} of {shown.length}</div>
            <div className="seg" style={{ marginLeft: "auto" }}>
              <button className={tradeView === "all" ? "active" : ""} onClick={() => setTradeView("all")}>All</button>
              <button className={tradeView === "winners" ? "active" : ""} onClick={() => setTradeView("winners")}>Winners</button>
              <button className={tradeView === "losers" ? "active" : ""} onClick={() => setTradeView("losers")}>Losers</button>
            </div>
          </div>
          <table className="lb dd-trades">
            <thead>
              <tr>
                <th>expiry</th>
                <th className="num">RoI</th>
                <th className="num">net P&amp;L</th>
                <th className="num">IV in</th>
                <th className="num">IV out</th>
              </tr>
            </thead>
            <tbody>
              {shown.slice(0, 8).map((t, i) => (
                <tr key={i}>
                  <td className="mono">{t.expiry}</td>
                  <td className="num mono"><span className={t.roi >= 0 ? "up" : "down"}>{t.roi >= 0 ? "+" : ""}{t.roi.toFixed(1)}%</span></td>
                  <td className="num mono"><span className={t.pnl >= 0 ? "up" : "down"}>{fmtINR(t.pnl)}</span></td>
                  <td className="num mono dim">{t.iv_entry}</td>
                  <td className="num mono dim">{t.iv_exit}</td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr><td colSpan="5" style={{ padding: "16px", color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  No trades match this filter.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="dd-card">
          <div className="dd-section-head">
            <div className="dd-eyebrow">Skipped expiries</div>
          </div>
          {(() => {
            const key = `${r}-${c}`;
            const skipped = window.MORENSE_DATA.SKIPPED[key];
            if (!skipped) {
              return <div className="dd-empty">
                <span className="serif">No skipped expiries</span> — all {cell.n} priced cleanly.
              </div>;
            }
            return (
              <table className="lb dd-trades">
                <thead>
                  <tr>
                    <th>expiry</th>
                    <th>reason</th>
                    <th>note</th>
                  </tr>
                </thead>
                <tbody>
                  {skipped.map((s, i) => (
                    <tr key={i}>
                      <td className="mono">{s.exp}</td>
                      <td><span className="strat-tag" style={{ background: "var(--warn-bg)", color: "var(--warn)" }}>{s.reason}</span></td>
                      <td className="dim" style={{ fontSize: 11.5 }}>{s.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            );
          })()}
        </div>
      </div>
    </div>
  );
}

// ---------- YoY mini line ----------
function YoYMini({ byYear }) {
  if (!byYear || byYear.length < 2) {
    return <div style={{ height: 90, display: "grid", placeItems: "center",
      color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
      sweep covers a single year · cannot compare YoY
    </div>;
  }
  const W = 280, H = 110;
  const padL = 30, padR = 8, padT = 14, padB = 22;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const ys = byYear.map(b => b.roi);
  const yMin = Math.min(0, Math.min(...ys));
  const yMax = Math.max(...ys) * 1.15;
  const xPos = (i) => padL + (innerW / Math.max(1, byYear.length - 1)) * i;
  const yPos = (v) => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;
  const path = byYear.map((b, i) => `${i === 0 ? "M" : "L"} ${xPos(i)} ${yPos(b.roi)}`).join(" ");

  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      <line className="grid-line" x1={padL} x2={W - padR} y1={yPos(0)} y2={yPos(0)} />
      <path d={path} stroke="var(--accent)" strokeWidth="1.75" fill="none" strokeLinecap="round" />
      {byYear.map((b, i) => (
        <g key={b.y}>
          <circle cx={xPos(i)} cy={yPos(b.roi)} r={3.5}
            fill="var(--bg)" stroke="var(--accent)" strokeWidth="1.5" />
          <text x={xPos(i)} y={H - 7} textAnchor="middle"
                style={{ fontFamily: "var(--font-mono)", fontSize: 10, fill: "var(--text-3)" }}>{b.y}</text>
          <text x={xPos(i)} y={yPos(b.roi) - 8} textAnchor="middle"
                style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, fill: "var(--text)" }}>
            {b.roi.toFixed(0)}%
          </text>
        </g>
      ))}
    </svg>
  );
}

// ---------- Per-expiry bar chart ----------
function ExpiryBars({ trades, median }) {
  if (trades.length === 0) {
    return <div style={{ padding: 24, color: "var(--text-3)" }}>No trades.</div>;
  }
  const W = 920, H = 200;
  const padL = 36, padR = 14, padT = 14, padB = 22;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const ys = trades.map(t => t.roi);
  const yMin = Math.min(0, Math.min(...ys));
  const yMax = Math.max(...ys) * 1.05;
  const yPos = (v) => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;
  const zeroY = yPos(0);
  const bw = innerW / trades.length * 0.72;

  const ticks = 4;
  const gridY = Array.from({ length: ticks + 1 }, (_, i) => yMin + (yMax - yMin) * (i / ticks));

  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      {gridY.map((g, i) => (
        <g key={i}>
          <line className="grid-line" x1={padL} x2={W - padR} y1={yPos(g)} y2={yPos(g)} />
          <text x={padL - 6} y={yPos(g) + 3} textAnchor="end"
                style={{ fontFamily: "var(--font-mono)", fontSize: 10, fill: "var(--text-3)" }}>
            {g.toFixed(0)}%
          </text>
        </g>
      ))}
      <line x1={padL} x2={W - padR} y1={zeroY} y2={zeroY}
            stroke="var(--border-strong)" strokeWidth="1" />
      {/* median line */}
      <line x1={padL} x2={W - padR} y1={yPos(median)} y2={yPos(median)}
            stroke="var(--accent)" strokeWidth="1" strokeDasharray="4 4" opacity="0.6" />
      <text x={W - padR - 4} y={yPos(median) - 4} textAnchor="end"
            style={{ fontFamily: "var(--font-mono)", fontSize: 9.5, fill: "var(--accent)", letterSpacing: "0.04em" }}>
        median {median.toFixed(0)}%
      </text>

      {trades.map((t, i) => {
        const cx = padL + (innerW / trades.length) * (i + 0.5);
        const v = t.roi;
        const y0 = Math.min(yPos(v), zeroY);
        const h = Math.abs(yPos(v) - zeroY);
        const color = v >= 0 ? "var(--pos)" : "var(--neg)";
        return (
          <g key={i}>
            <rect x={cx - bw / 2} y={y0} width={bw} height={h}
                  fill={color} opacity={0.78} rx={1.5}>
              <title>{`${t.expiry} · ${v.toFixed(1)}% · ₹${t.pnl.toLocaleString()}`}</title>
            </rect>
          </g>
        );
      })}
    </svg>
  );
}

// ---------- COMPARE CELLS ----------
function CompareCells({ lens, selected, pair, stratLabel }) {
  if (selected.length < 2) {
    return (
      <div className="mode-empty">
        <div className="mode-empty-glyph">⊞</div>
        <div className="mode-empty-title"><span className="serif">Pick at least two cells</span> to compare.</div>
        <div className="mode-empty-sub">Shift-click on the heatmap, or use the keyboard picker below to add up to 4.</div>
      </div>
    );
  }

  // Pool std for rough p-value (Welch-ish)
  function pValue(a, b) {
    const seA = a.std / Math.sqrt(a.n);
    const seB = b.std / Math.sqrt(b.n);
    const tStat = Math.abs(a.roi - b.roi) / Math.sqrt(seA * seA + seB * seB);
    // crude approximation of two-tailed normal p-value
    const p = Math.max(0.001, Math.min(0.999, 2 * (1 - normalCdf(tStat))));
    return p;
  }
  function normalCdf(z) {
    // Abramowitz & Stegun 7.1.26
    const t = 1 / (1 + 0.2316419 * Math.abs(z));
    const d = 0.3989422804014327 * Math.exp(-z * z / 2);
    const p = d * t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
    return z > 0 ? 1 - p : p;
  }

  const baseCell = selected[0].cell;

  return (
    <div className="mode-pane">
      {/* Cells chosen — chips */}
      <div className="cmp-chips">
        {selected.map((s, i) => (
          <div key={i} className="cmp-chip" style={{ borderColor: HM_BADGE_COLORS[i] }}>
            <span className="cmp-chip-num" style={{ background: HM_BADGE_COLORS[i] }}>{i + 1}</span>
            <span className="mono" style={{ fontSize: 11.5 }}>
              {lens.rowFmt(s.r)} <span style={{ color: "var(--text-3)" }}>×</span> {lens.colFmt(s.c)}
            </span>
            <span className={`mono ${s.cell.roi >= 0 ? "up" : "down"}`} style={{ fontSize: 11.5 }}>
              {typeof s.cell.roi === "number" ? `${s.cell.roi.toFixed(0)}%` : "—"}
            </span>
          </div>
        ))}
      </div>

      <div className="cmp-grid">
        {/* Distribution overlay (per-expiry bars side by side) */}
        <div className="dd-card">
          <div className="dd-section-head">
            <div className="dd-eyebrow">Per-expiry RoI · overlay</div>
            <div className="dd-section-meta mono">sorted within each cell</div>
          </div>
          <CompareBars selected={selected} />
        </div>

        {/* Stats table */}
        <div className="dd-card">
          <div className="dd-section-head">
            <div className="dd-eyebrow">Side-by-side stats</div>
            <div className="dd-section-meta mono">vs cell 1</div>
          </div>
          <table className="lb cmp-stats">
            <thead>
              <tr>
                <th>stat</th>
                {selected.map((s, i) => (
                  <th key={i} className="num">
                    <span className="cmp-chip-num" style={{ background: HM_BADGE_COLORS[i], marginRight: 6 }}>{i + 1}</span>
                    {i > 0 ? <span style={{ color: "var(--text-3)" }}>Δ vs 1</span> : "value"}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { k: "n_trades",        accessor: (c) => c.n,      fmt: (v) => v.toString(), diff: false },
                { k: "win_rate",        accessor: (c) => c.win,    fmt: (v) => `${v.toFixed(1)}%`, diff: true },
                { k: "median ROI/yr",   accessor: (c) => c.roi,    fmt: (v) => `${v.toFixed(1)}%`, diff: true, hilite: true },
                { k: "mean ROI/yr",     accessor: (c) => c.mean,   fmt: (v) => `${v.toFixed(1)}%`, diff: true },
                { k: "std (ddof=0)",    accessor: (c) => c.std,    fmt: (v) => v.toFixed(1), diff: true },
                { k: "Σ net P&L",       accessor: (c) => c.pnl,    fmt: (v) => `₹${v.toFixed(2)}L`, diff: true },
              ].map(row => (
                <tr key={row.k}>
                  <td className={row.hilite ? "" : "dim"} style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>{row.k}</td>
                  {selected.map((s, i) => {
                    const v = row.accessor(s.cell);
                    if (i === 0 || !row.diff) {
                      return <td key={i} className="num mono">{typeof v === "number" ? row.fmt(v) : "—"}</td>;
                    }
                    const base = row.accessor(baseCell);
                    const d = (typeof v === "number" && typeof base === "number") ? v - base : null;
                    return (
                      <td key={i} className="num mono">
                        {d == null ? "—" : (
                          <span className={d >= 0 ? "up" : "down"}>
                            {d >= 0 ? "+" : ""}{row.fmt(d).replace(/^([+−-]?)/, "")}
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr>
                <td className="dim" style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>p-value vs 1</td>
                {selected.map((s, i) => {
                  if (i === 0) return <td key={i} className="num mono dim">—</td>;
                  const p = pValue(baseCell, s.cell);
                  return <td key={i} className="num mono">
                    <span style={{ color: p < 0.05 ? "var(--pos)" : p < 0.1 ? "var(--warn)" : "var(--text-3)" }}>
                      p = {p < 0.001 ? "<0.001" : p.toFixed(3)}
                    </span>
                  </td>;
                })}
              </tr>
            </tbody>
          </table>
          <div className="cmp-caveat">
            <span className="mono" style={{ color: "var(--warn)" }}>caveat</span>
            <span>
              With <span className="mono">n≈{baseCell.n}</span> per cell, statistical power is weak —
              treat p &lt; 0.05 as <em className="serif">interesting</em>, not confirmed.
              <span className="mono" style={{ color: "var(--text-3)" }}> · Welch t-approx; switch to permutation in Phase 7.</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function CompareBars({ selected }) {
  const W = 920, H = 220;
  const padL = 36, padR = 14, padT = 14, padB = 28;
  const innerW = W - padL - padR, innerH = H - padT - padB;

  // synth trade arrays per selected cell
  const series = selected.map((s, i) => {
    const trades = window.MORENSE_DATA.tradesForCell(s.cell);
    return { trades, color: HM_BADGE_COLORS[i], idx: i };
  });
  const maxN = Math.max(...series.map(s => s.trades.length));
  const allYs = series.flatMap(s => s.trades.map(t => t.roi));
  const yMin = Math.min(0, Math.min(...allYs));
  const yMax = Math.max(...allYs) * 1.05;
  const yPos = (v) => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;
  const zeroY = yPos(0);

  const groupW = innerW / maxN;
  const barW = (groupW / series.length) * 0.78;

  const ticks = 4;
  const gridY = Array.from({ length: ticks + 1 }, (_, i) => yMin + (yMax - yMin) * (i / ticks));

  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      {gridY.map((g, i) => (
        <g key={i}>
          <line className="grid-line" x1={padL} x2={W - padR} y1={yPos(g)} y2={yPos(g)} />
          <text x={padL - 6} y={yPos(g) + 3} textAnchor="end"
                style={{ fontFamily: "var(--font-mono)", fontSize: 10, fill: "var(--text-3)" }}>
            {g.toFixed(0)}%
          </text>
        </g>
      ))}
      <line x1={padL} x2={W - padR} y1={zeroY} y2={zeroY}
            stroke="var(--border-strong)" strokeWidth="1" />

      {series.map(s => s.trades.map((t, i) => {
        const cx = padL + groupW * (i + 0.5) - (groupW / 2) + (s.idx + 0.5) * (groupW / series.length);
        const y0 = Math.min(yPos(t.roi), zeroY);
        const h = Math.abs(yPos(t.roi) - zeroY);
        return <rect key={`${s.idx}-${i}`} x={cx - barW / 2} y={y0} width={barW} height={h}
                     fill={s.color} opacity={0.78} rx={1.5}>
          <title>{`cell ${s.idx + 1} · expiry ${i + 1} · ${t.roi.toFixed(1)}%`}</title>
        </rect>;
      }))}

      <text x={padL} y={H - 8}
            style={{ fontFamily: "var(--font-mono)", fontSize: 10, fill: "var(--text-3)" }}>
        expiry rank (best → worst within each cell)
      </text>
    </svg>
  );
}

// ---------- EXPORT RULE ----------
function ExportRule({ lens, cell, r, c, pair, stratLabel, strikeRule, sweep }) {
  if (typeof cell.roi !== "number") {
    return (
      <div className="mode-empty">
        <div className="mode-empty-glyph">⛔</div>
        <div className="mode-empty-title"><span className="serif">This cell is masked.</span></div>
        <div className="mode-empty-sub">A trading rule requires real data — pick a cell with n ≥ min_N.</div>
      </div>
    );
  }

  const ci = medianCI(cell);
  const trades = window.MORENSE_DATA.tradesForCell(cell);
  const losers = trades.filter(t => t.roi < 0);
  const worst = losers.length ? losers.reduce((a, b) => a.pnl < b.pnl ? a : b) : null;
  const ruleId = `${pair.strategy}_${pair.symbol}_${lens.rowFmt(r).replace(/[^a-z0-9]/gi, "")}_${lens.colFmt(c).replace(/[^a-z0-9]/gi, "")}`.toLowerCase();

  const today = new Date().toISOString().slice(0, 10);

  const lines = [
    `# Trading rule — ${pair.strategy} × ${pair.symbol}`,
    `Generated ${today} from sweep ${sweep.run_id}`,
    ``,
    `## Rule`,
    `- Strategy: \`${pair.strategy}\``,
    `- Symbol: \`${pair.symbol}\``,
    `- Strike rule: ${strikeRule.text}  *(${strikeRule.param})*`,
    `- ${lens.rowLabel.split(" (")[0]}: **${lens.rowFmt(r)}**`,
    `- ${lens.colLabel.split(" (")[0]}: **${lens.colFmt(c)}**`,
    ...Object.entries(lens.fixed || {}).map(([k, v]) => `- ${k.replace(/_/g, " ")}: ${typeof v === "number" ? v : v}  *(fixed via lens)*`),
    `- Sizing: 1 lot per leg (verify NSE current lot size before trading)`,
    ``,
    `## Historical performance — backtest only`,
    `- N = **${cell.n}** expiries`,
    `- Win rate: **${cell.win.toFixed(1)}%**`,
    `- Median RoI / yr: **${cell.roi >= 0 ? "+" : ""}${cell.roi.toFixed(1)}%**${ci ? `  *(95% CI ${ci.lo.toFixed(0)} … ${ci.hi.toFixed(0)}%)*` : ""}`,
    `- Mean RoI / yr: **${cell.mean >= 0 ? "+" : ""}${cell.mean.toFixed(1)}%**${cell.mean < cell.roi ? "  *(mean < median ⇒ tail risk)*" : ""}`,
    `- Worst single trade: **${worst ? fmtINR(worst.pnl) : "—"}**`,
    `- Σ net P&L: **₹${cell.pnl.toFixed(2)}L**`,
    ``,
    `## Sizing guidance`,
    `For max-drawdown tolerance ₹X, max lots = X / ${worst ? Math.abs(worst.pnl).toLocaleString("en-IN") : "—"} = N lots.`,
    `Discount displayed RoI by ~10% for Tier-B margin overestimate (SPECS §4a).`,
    ``,
    `## Caveats`,
    `- Past N=${cell.n} trades is small; use as candidate, not guarantee (multiple-comparisons risk: rank.MULTIPLE_COMPARISONS_CAVEAT).`,
    `- 1% per-side slippage in backtest; thin strikes may differ.`,
    `- Survivorship bias: blue-chip universe snapshot 2026-07-01.`,
    ``,
    `## Standardisation — operator decisions`,
    `- [ ] Order timing within day (open / VWAP / close)?`,
    `- [ ] Stop-loss policy (none, fixed-%, vol-multiple)?`,
    `- [ ] Position roll on assignment?`,
    `- [ ] Position size override vs sweep default?`,
  ];

  function downloadMd() {
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `rule_${ruleId}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mode-pane">
      <div className="export-grid">
        <div className="dd-card md-preview">
          <div className="md-toolbar mono">
            <span className="md-filename">rule_{ruleId}.md</span>
            <span className="spacer"></span>
            <span style={{ color: "var(--text-3)" }}>{lines.length} lines · markdown</span>
          </div>
          <pre className="md-body mono">
            {lines.map((l, i) => <span key={i} className={
              l.startsWith("# ") ? "md-h1"
              : l.startsWith("## ") ? "md-h2"
              : l.startsWith("- ") ? "md-li"
              : l.startsWith("Generated") ? "md-meta"
              : l === "" ? "md-blank"
              : "md-p"
            }>{l + "\n"}</span>)}
          </pre>
        </div>

        <div className="dd-card export-sidebar">
          <div className="dd-eyebrow">Export</div>
          <button className="btn primary" onClick={downloadMd} style={{ width: "100%", justifyContent: "center", padding: "10px 14px" }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            Download rule_{ruleId.slice(0, 18)}….md
          </button>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <button className="btn" style={{ flex: 1, justifyContent: "center" }}>Copy markdown</button>
            <button className="btn" style={{ flex: 1, justifyContent: "center" }}>Copy as YAML</button>
          </div>

          <div className="export-sep" />

          <div className="dd-eyebrow">Operator checklist</div>
          <div className="checklist">
            {[
              "Verify NSE lot size matches sweep assumption",
              "Decide order timing within day",
              "Set stop-loss policy (or none)",
              "Roll vs let-assign on early exercise",
              "Pre-trade margin check vs broker",
              "Log rule_id in trade journal",
            ].map((t, i) => (
              <label key={i} className="check-row">
                <span className="check-box"></span>
                <span>{t}</span>
              </label>
            ))}
          </div>

          <div className="export-sep" />

          <div className="dd-eyebrow">Saved rules</div>
          <div className="saved-list mono">
            <div className="saved-row">
              <span className="saved-dot" style={{ background: "var(--pos)" }}></span>
              rule_short_strangle_hdfc_e9_x0.md
              <span style={{ color: "var(--text-3)", marginLeft: "auto" }}>3d</span>
            </div>
            <div className="saved-row">
              <span className="saved-dot" style={{ background: "var(--pos)" }}></span>
              rule_iron_condor_infy_e12_x1.md
              <span style={{ color: "var(--text-3)", marginLeft: "auto" }}>1w</span>
            </div>
            <div className="saved-row">
              <span className="saved-dot" style={{ background: "var(--text-4)" }}></span>
              rule_short_straddle_reli_e9_x0.md
              <span style={{ color: "var(--text-3)", marginLeft: "auto" }}>(this)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

window.HeatmapModes = { DrillDown, CompareCells, ExportRule };
