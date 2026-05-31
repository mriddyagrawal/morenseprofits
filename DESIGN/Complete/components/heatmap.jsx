// Heatmap tab — bespoke research workspace.
// Selectors → headline strip → dual heatmaps → keyboard fallback → mode tabs.

function HeatmapTab({ filters, setFilters }) {
  const { LENSES, STRATEGIES, SYMBOLS, STRIKE_RULES } = window.MORENSE_DATA;
  const { Heatmap } = window.Charts;
  const { DrillDown, CompareCells, ExportRule } = window.HeatmapModes;

  const [pair, setPair] = React.useState({ strategy: "short_straddle", symbol: "RELIANCE" });
  const [lensId, setLensId] = React.useState("entry_exit");
  const [selected, setSelected] = React.useState([{ r: 9, c: 0 }]); // pre-select RELIANCE × short_straddle × −9 → expiry (the headline cell)
  const [mode, setMode] = React.useState("drill"); // drill | compare | export
  const [hover, setHover] = React.useState(null);

  const lens = LENSES.find(l => l.id === lensId);
  const getCell = (r, c) => lens.cells[r]?.[c];

  // hydrate selection with cell data
  const hydrated = selected
    .map(s => ({ ...s, cell: getCell(s.r, s.c) }))
    .filter(s => s.cell);

  const stratLabel = STRATEGIES.find(s => s.key === pair.strategy)?.label;
  const strikeRule = STRIKE_RULES[pair.strategy];

  const minN = filters.minN;
  const flat = lens.rows.flatMap(r => lens.cols.map(c => getCell(r, c))).filter(Boolean);
  const numericRois = flat.filter(c => typeof c.roi === "number");
  const totalN = flat.reduce((s, c) => s + (c.n || 0), 0);
  const visibleCells = numericRois.filter(c => c.n >= minN);
  const allMasked = visibleCells.length === 0;

  const bestCell = numericRois.length ? numericRois.reduce((a, b) => a.roi > b.roi ? a : b) : null;
  const worstCell = numericRois.length ? numericRois.reduce((a, b) => a.roi < b.roi ? a : b) : null;
  const medianOfMedians = (() => {
    const arr = visibleCells.map(c => c.roi).sort((a, b) => a - b);
    if (!arr.length) return null;
    const mid = Math.floor(arr.length / 2);
    return arr.length % 2 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
  })();
  function findCellLocation(target) {
    if (!target) return null;
    for (const r of lens.rows) for (const c of lens.cols) {
      if (lens.cells[r][c] === target) return { r, c };
    }
    return null;
  }

  // ----- click on heatmap cell -----
  function handleClick({ r, c, cell, shift }) {
    if (!cell) return;
    setSelected(prev => {
      const exists = prev.findIndex(s => s.r === r && s.c === c);
      if (shift) {
        // Toggle in multi-select
        if (exists >= 0) {
          const next = [...prev]; next.splice(exists, 1);
          return next.length ? next : prev; // never go empty via shift
        }
        if (prev.length >= 4) return prev; // max 4
        return [...prev, { r, c }];
      }
      // plain click — replace selection
      return [{ r, c }];
    });
    setMode(m => (shift && selected.length > 0) ? "compare" : "drill");
  }

  // Reset selection when lens changes
  React.useEffect(() => {
    const fallback = lens.rows[Math.floor(lens.rows.length / 2)];
    const fallbackCol = lens.cols[Math.floor(lens.cols.length / 2)];
    setSelected([{ r: fallback, c: fallbackCol }]);
    setMode("drill");
  }, [lensId]);

  // Available modes based on selection count
  const canDrill   = hydrated.length === 1;
  const canCompare = hydrated.length >= 2;
  const canExport  = hydrated.length === 1 && typeof hydrated[0].cell.roi === "number";

  React.useEffect(() => {
    if (mode === "drill"   && !canDrill   && canCompare) setMode("compare");
    if (mode === "compare" && !canCompare && canDrill)   setMode("drill");
    if (mode === "export"  && !canExport)                setMode(canDrill ? "drill" : "compare");
  }, [hydrated.length]);

  return (
    <>
      {/* ----- header ----- */}
      <div className="page-h">
        <h1><em>The</em>Heatmap</h1>
        <span className="sub">pivot_window( {lens.rowKey} × {lens.colKey} )</span>
        <div className="right">
          <button className="btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            Export rule
          </button>
        </div>
      </div>

      {/* ----- selector row ----- */}
      <div className="hm-selectors">
        <Picker label="strategy" value={pair.strategy} fmt={(v) => STRATEGIES.find(s => s.key === v)?.label}
                options={STRATEGIES.map(s => ({ v: s.key, l: s.label }))}
                onChange={(v) => setPair(p => ({ ...p, strategy: v }))} />
        <Picker label="symbol" value={pair.symbol} fmt={(v) => v}
                options={SYMBOLS.map(s => ({ v: s.sym, l: s.sym }))}
                onChange={(v) => setPair(p => ({ ...p, symbol: v }))} />
        <Picker label="lens" value={lensId} fmt={(v) => LENSES.find(l => l.id === v)?.label}
                options={LENSES.map(l => ({ v: l.id, l: l.label, hint: l.hint, phase: l.phase }))}
                onChange={(v) => setLensId(v)} accent />
        <div className="hm-strike-caption">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
          <span className="serif" style={{ color: "var(--text-2)" }}>Strike rule</span>
          <span className="mono">{strikeRule.text}</span>
          <span style={{ color: "var(--text-4)" }}>·</span>
          <span className="mono" style={{ color: "var(--text-3)" }}>{strikeRule.param}</span>
        </div>
      </div>

      {/* ----- headline strip ----- */}
      <div className="hm-headline">
        <HeadlineCell label="best cell" tone="pos"
          v={bestCell && typeof bestCell.roi === "number" ? `+${bestCell.roi.toFixed(1)}%` : "—"}
          sub={(() => {
            const loc = findCellLocation(bestCell);
            if (!loc) return "—";
            return `${lens.rowFmt(loc.r)} × ${lens.colFmt(loc.c)} · n=${bestCell.n}`;
          })()} />
        <HeadlineCell label="worst cell" tone="neg"
          v={worstCell && typeof worstCell.roi === "number" ? `+${worstCell.roi.toFixed(1)}%` : "—"}
          sub={(() => {
            const loc = findCellLocation(worstCell);
            if (!loc) return "—";
            return `${lens.rowFmt(loc.r)} × ${lens.colFmt(loc.c)} · n=${worstCell.n}`;
          })()} />
        <HeadlineCell label="median of medians" tone="neutral"
          v={medianOfMedians != null ? `+${medianOfMedians.toFixed(1)}%` : "—"}
          sub={`across ${visibleCells.length} unmasked cells · range ±${bestCell && worstCell ? (bestCell.roi - worstCell.roi).toFixed(0) : "—"}%`} />
        <HeadlineCell label="selection" tone="accent"
          v={
            <span>
              <span className="mono" style={{ color: "var(--accent)" }}>{hydrated.length}</span>
              <span className="mono" style={{ color: "var(--text-3)", fontSize: 18 }}> / 4</span>
            </span>
          }
          sub={
            hydrated.length === 0
              ? "click a cell to start"
              : hydrated.length === 1
                ? <>cell <span className="mono">{lens.rowFmt(hydrated[0].r)} × {lens.colFmt(hydrated[0].c)}</span> · shift-click to add</>
                : <>{hydrated.length} cells selected · compare mode active</>
          }
          action={hydrated.length > 0
            ? <button className="hm-clear" onClick={() => setSelected([])}>clear</button>
            : null} />
      </div>

      {/* ----- all-masked banner ----- */}
      {allMasked && (
        <div className="hm-banner">
          <span className="mono" style={{ color: "var(--warn)" }}>NOTE</span>
          <span>
            All {flat.length} cells masked at <span className="mono">min_N = {minN}</span>.
            The largest cell has n = <span className="mono">{Math.max(...flat.map(c => c.n))}</span>.
          </span>
          <button className="btn primary" style={{ marginLeft: "auto" }}
            onClick={() => setFilters(f => ({ ...f, minN: Math.max(...flat.map(c => c.n)) }))}>
            Lower min_N to {Math.max(...flat.map(c => c.n))} →
          </button>
        </div>
      )}

      {/* ----- dual heatmaps ----- */}
      <div className="hm-pair">
        <div className="hm-card">
          <div className="hm-card-hd">
            <div className="hm-card-ttl">median RoI / yr <span className="serif" style={{ color: "var(--text-3)" }}>— diverging, anchored at 0</span></div>
            <div className="hm-card-meta mono">{visibleCells.length}/{flat.length} visible · click to drill · shift-click to compare</div>
          </div>
          <div className="hm-svg-wrap">
            <Heatmap
              rows={lens.rows} cols={lens.cols}
              getCell={getCell} minN={minN} mode="value"
              rowLabel={lens.rowLabel} colLabel={lens.colLabel}
              rowFmt={lens.rowFmt} colFmt={lens.colFmt}
              selected={hydrated}
              onHover={setHover}
              onClick={handleClick}
              cellW={96} cellH={64}
            />
            {hover && hover.cell && (
              <div className="hm-tip" style={{ left: hover.mx + 10, top: hover.my }}>
                <div className="hm-tip-ttl">
                  <span className="mono">{lens.rowFmt(hover.r)} × {lens.colFmt(hover.c)}</span>
                  {hover.masked
                    ? <span style={{ color: "var(--warn)", marginLeft: 6 }}>masked</span>
                    : <span className={typeof hover.cell.roi === "number" && hover.cell.roi >= 0 ? "up" : "down"} style={{ marginLeft: 6 }}>
                        {typeof hover.cell.roi === "number" ? `${hover.cell.roi.toFixed(1)}%/yr` : "—"}
                      </span>}
                </div>
                <div className="hm-tip-row"><span>n_trades</span><b className="mono">{hover.cell.n}</b></div>
                <div className="hm-tip-row"><span>win_rate</span><b className="mono">{typeof hover.cell.win === "number" ? `${hover.cell.win.toFixed(1)}%` : "—"}</b></div>
                <div className="hm-tip-row"><span>mean RoI/yr</span><b className="mono">{typeof hover.cell.mean === "number" ? `${hover.cell.mean.toFixed(1)}%` : "—"}</b></div>
                <div className="hm-tip-row"><span>std (ddof=0)</span><b className="mono">{typeof hover.cell.std === "number" ? hover.cell.std.toFixed(1) : "—"}</b></div>
                <div className="hm-tip-row"><span>Σ net P&amp;L</span><b className="mono">{typeof hover.cell.pnl === "number" ? `₹${hover.cell.pnl.toFixed(2)}L` : "—"}</b></div>
                {hover.cell.byYear && (
                  <div className="hm-tip-yoy">
                    {hover.cell.byYear.map(b => (
                      <span key={b.y} className="mono">
                        <span style={{ color: "var(--text-3)" }}>{b.y}</span> {b.roi.toFixed(0)}%
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <ColorbarValue rows={lens.rows} cols={lens.cols} getCell={getCell} />
        </div>

        <div className="hm-card">
          <div className="hm-card-hd">
            <div className="hm-card-ttl">sample density <span className="serif" style={{ color: "var(--text-3)" }}>— sequential</span></div>
            <div className="hm-card-meta mono">Σ n = {totalN} · min_N marker shown</div>
          </div>
          <div className="hm-svg-wrap">
            <Heatmap
              rows={lens.rows} cols={lens.cols}
              getCell={getCell} minN={minN} mode="density"
              rowLabel={lens.rowLabel} colLabel={lens.colLabel}
              rowFmt={lens.rowFmt} colFmt={lens.colFmt}
              selected={hydrated}
              noiseFloor={true}
              onClick={handleClick}
              cellW={96} cellH={64}
            />
          </div>
          <ColorbarDensity counts={flat.map(c => c.n)} minN={minN} />
        </div>
      </div>

      {/* ----- keyboard fallback ----- */}
      <KeyboardFallback lens={lens} selected={hydrated}
        onAdd={(r, c) => setSelected(prev => {
          if (prev.find(s => s.r === r && s.c === c)) return prev;
          if (prev.length >= 4) return [...prev.slice(1), { r, c }];
          return [...prev, { r, c }];
        })}
        onReplace={(r, c) => setSelected([{ r, c }])}
      />

      {/* ----- mode tabs ----- */}
      <div className="mode-tabs">
        <button className={`mode-tab ${mode === "drill" ? "active" : ""}`}
                disabled={!canDrill}
                onClick={() => canDrill && setMode("drill")}>
          <span className="mt-badge">A</span>
          <span className="mt-l">
            <span className="mt-name">Drill-down</span>
            <span className="mt-sub">one cell · per-trade breakdown, YoY, skipped</span>
          </span>
        </button>
        <button className={`mode-tab ${mode === "compare" ? "active" : ""}`}
                disabled={!canCompare}
                onClick={() => canCompare && setMode("compare")}>
          <span className="mt-badge">B</span>
          <span className="mt-l">
            <span className="mt-name">Compare cells</span>
            <span className="mt-sub">2–4 cells · overlay distribution + diff stats</span>
          </span>
        </button>
        <button className={`mode-tab ${mode === "export" ? "active" : ""}`}
                disabled={!canExport}
                onClick={() => canExport && setMode("export")}>
          <span className="mt-badge">C</span>
          <span className="mt-l">
            <span className="mt-name">Export rule</span>
            <span className="mt-sub">deployable .md for the trade journal</span>
          </span>
        </button>
      </div>

      {/* ----- mode content ----- */}
      {hydrated.length === 0 ? (
        <div className="mode-empty">
          <div className="mode-empty-glyph">⊕</div>
          <div className="mode-empty-title"><span className="serif">Pick a cell</span> to start drilling.</div>
          <div className="mode-empty-sub">Click on the heatmap, shift-click to compare up to 4, or use the keyboard picker.</div>
        </div>
      ) : mode === "drill" && canDrill ? (
        <DrillDown
          lens={lens} cell={hydrated[0].cell}
          r={hydrated[0].r} c={hydrated[0].c}
          pair={pair} stratLabel={stratLabel} strikeRule={strikeRule}
        />
      ) : mode === "compare" ? (
        <CompareCells lens={lens} selected={hydrated} pair={pair} stratLabel={stratLabel} />
      ) : mode === "export" && canExport ? (
        <ExportRule
          lens={lens} cell={hydrated[0].cell}
          r={hydrated[0].r} c={hydrated[0].c}
          pair={pair} stratLabel={stratLabel} strikeRule={strikeRule}
          sweep={{ run_id: "swp_20260524_2103" }}
        />
      ) : null}

      {/* ----- footer ----- */}
      <div style={{
        marginTop: 18, padding: "12px 14px",
        border: "1px solid var(--border)", borderRadius: 6,
        background: "var(--surface)", fontSize: 12, color: "var(--text-2)",
        display: "flex", gap: 14, alignItems: "flex-start",
      }}>
        <span style={{ fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-3)", fontSize: 10.5 }}>STD</span>
        <span>
          <strong style={{ color: "var(--text)" }}>std (ddof=0)</strong> is observed-sample dispersion, not a population estimate.
          Treat as a lower bound on true population variance — small-N groups understate spread by
          ~20% at n=5, ~2.5% at n=20.
          <span className="mono" style={{ color: "var(--text-3)" }}> · src: afdd56e</span>
        </span>
      </div>
    </>
  );
}

// ---------- HEADLINE CELL ----------
function HeadlineCell({ label, v, sub, tone = "neutral", action }) {
  const c = tone === "pos" ? "var(--pos)" : tone === "neg" ? "var(--neg)" : tone === "accent" ? "var(--accent)" : "var(--text)";
  return (
    <div className={`hm-headline-cell tone-${tone}`}>
      <div className="hm-h-label">{label}</div>
      <div className="hm-h-v mono" style={{ color: c }}>{v}</div>
      <div className="hm-h-sub">{sub}</div>
      {action}
    </div>
  );
}

// ---------- PICKER ----------
function Picker({ label, value, options, onChange, fmt = (v) => v, accent }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  React.useEffect(() => {
    function onDoc(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className={`hm-picker ${accent ? "accent" : ""}`} onClick={() => setOpen(o => !o)}>
        <span className="hm-picker-l">{label}</span>
        <span className="hm-picker-v">{fmt(value)}</span>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {open && (
        <div className="hm-menu">
          {options.map(o => (
            <button key={o.v} className={`hm-menu-item ${o.v === value ? "active" : ""}`}
                    onClick={() => { onChange(o.v); setOpen(false); }}>
              <div className="hm-menu-main">
                <span>{o.l}</span>
                {o.phase && <span className="hm-phase-tag">PH-7</span>}
              </div>
              {o.hint && <div className="hm-menu-hint">{o.hint}</div>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- KEYBOARD FALLBACK ----------
function KeyboardFallback({ lens, selected, onAdd, onReplace }) {
  const [row, setRow] = React.useState(lens.rows[Math.floor(lens.rows.length / 2)]);
  const [col, setCol] = React.useState(lens.cols[Math.floor(lens.cols.length / 2)]);
  React.useEffect(() => {
    setRow(lens.rows[Math.floor(lens.rows.length / 2)]);
    setCol(lens.cols[Math.floor(lens.cols.length / 2)]);
  }, [lens.id]);

  return (
    <div className="hm-keyboard">
      <span className="hm-keyboard-l mono">keyboard pick</span>
      <div className="hm-kb-select">
        <label className="hm-kb-label">{lens.rowLabel.split(" (")[0]}</label>
        <select value={row} onChange={(e) => setRow(lens.rows.find(v => String(v) === e.target.value) ?? e.target.value)}>
          {lens.rows.map(r => <option key={r} value={r}>{lens.rowFmt(r)}</option>)}
        </select>
      </div>
      <span style={{ color: "var(--text-4)" }}>×</span>
      <div className="hm-kb-select">
        <label className="hm-kb-label">{lens.colLabel.split(" (")[0]}</label>
        <select value={col} onChange={(e) => setCol(lens.cols.find(v => String(v) === e.target.value) ?? e.target.value)}>
          {lens.cols.map(c => <option key={c} value={c}>{lens.colFmt(c)}</option>)}
        </select>
      </div>
      <button className="btn" onClick={() => onReplace(row, col)}>Drill</button>
      <button className="btn" onClick={() => onAdd(row, col)} disabled={selected.length >= 4}>+ Add cell</button>
      <span className="mono" style={{ color: "var(--text-3)", fontSize: 11, marginLeft: "auto" }}>
        click bug fallback · screen-reader friendly · {selected.length}/4 selected
      </span>
    </div>
  );
}

// ---------- COLORBARS ----------
function ColorbarValue({ rows, cols, getCell }) {
  const numericRois = [];
  rows.forEach(r => cols.forEach(c => { const x = getCell(r, c); if (x && typeof x.roi === "number") numericRois.push(x.roi); }));
  const vMax = Math.max(...numericRois.map(Math.abs), 1);
  return (
    <div className="hm-colorbar">
      <span className="mono">−{vMax.toFixed(0)}%</span>
      <div className="hm-cb-bar" style={{
        background: "linear-gradient(90deg, rgba(255,118,118,0.85), rgba(255,255,255,0.05) 50%, rgba(93,211,158,0.85))",
      }}></div>
      <span className="mono">+{vMax.toFixed(0)}%</span>
    </div>
  );
}
function ColorbarDensity({ counts, minN }) {
  const max = Math.max(...counts, 1);
  const threshPct = Math.min(100, Math.max(0, (minN / max) * 100));
  return (
    <div className="hm-colorbar">
      <span className="mono">0</span>
      <div className="hm-cb-bar" style={{ position: "relative",
        background: "linear-gradient(90deg, rgba(212,255,58,0.06), rgba(212,255,58,0.65))",
      }}>
        <div style={{
          position: "absolute", left: `${threshPct}%`, top: -3, bottom: -3, width: 2,
          background: "var(--warn)", boxShadow: "0 0 0 2px rgba(240,198,116,0.18)",
        }}></div>
        <div style={{ position: "absolute", left: `calc(${threshPct}% + 8px)`, top: -18,
          fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--warn)",
          textTransform: "uppercase", letterSpacing: "0.06em",
        }}>min_N {minN}</div>
      </div>
      <span className="mono">{max}</span>
    </div>
  );
}

window.HeatmapTab = HeatmapTab;
window.PairPicker = function PairPicker({ pair, setPair }) {
  // legacy export used by trends.jsx — keep compatible
  const { STRATEGIES, SYMBOLS } = window.MORENSE_DATA;
  return (
    <div className="row" style={{ gap: 6 }}>
      <Picker label="strategy" value={pair.strategy}
              options={STRATEGIES.map(s => ({ v: s.key, l: s.label }))}
              fmt={(v) => STRATEGIES.find(s => s.key === v)?.label}
              onChange={(v) => setPair(p => ({ ...p, strategy: v }))} />
      <Picker label="symbol" value={pair.symbol}
              options={SYMBOLS.map(s => ({ v: s.sym, l: s.sym }))}
              fmt={(v) => v}
              onChange={(v) => setPair(p => ({ ...p, symbol: v }))} />
    </div>
  );
};
