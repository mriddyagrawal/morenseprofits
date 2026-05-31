// Sidebar — filters & cross-cutting state
function Sidebar({ filters, setFilters }) {
  const { STRATEGIES, SYMBOLS } = window.MORENSE_DATA;

  function toggle(key, value) {
    setFilters(f => {
      const cur = f[key];
      const next = cur.includes(value) ? cur.filter(v => v !== value) : [...cur, value];
      return { ...f, [key]: next };
    });
  }

  return (
    <aside className="sidebar">

      <div className="sb-section">
        <div className="sb-label">
          Strategies
          <span className="hint">{filters.strategies.length}/{STRATEGIES.length}</span>
        </div>
        <div className="chip-grid">
          {STRATEGIES.map(s => (
            <button key={s.key}
                    className={`chip ${filters.strategies.includes(s.key) ? "active" : ""}`}
                    onClick={() => toggle("strategies", s.key)}>
              {s.short}
            </button>
          ))}
        </div>
      </div>

      <div className="sb-section">
        <div className="sb-label">
          Symbols
          <span className="hint">{filters.symbols.length}/{SYMBOLS.length}</span>
        </div>
        <div className="chip-grid">
          {SYMBOLS.map(s => (
            <button key={s.sym}
                    className={`chip ${filters.symbols.includes(s.sym) ? "active" : ""}`}
                    onClick={() => toggle("symbols", s.sym)}>
              {s.sym}
            </button>
          ))}
        </div>
      </div>

      <div className="sb-section">
        <div className="sb-label">
          min_N for ranking
          <span className="hint mono">{filters.minN}</span>
        </div>
        <div className="slider-row">
          <input type="range" min="0" max="30" step="1"
                 value={filters.minN}
                 onChange={(e) => setFilters(f => ({ ...f, minN: parseInt(e.target.value) }))} />
          <span className="slider-val mono">{filters.minN}</span>
        </div>
        <div style={{ fontSize: 10.5, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>
          MIN_N_FOR_RANKING default = 5
        </div>
      </div>

      <div className="sb-section">
        <div className="sb-label">Regime filter</div>
        <div className="radio-stack">
          {[
            { v: "all",         l: "All",         c: 360 },
            { v: "bull",        l: "Bullish",     c: 142 },
            { v: "neutral",     l: "Neutral",     c: 158 },
            { v: "non_bullish", l: "Non-bullish", c: 218 },
          ].map(r => (
            <button key={r.v}
                    className={`radio ${filters.regime === r.v ? "checked" : ""}`}
                    onClick={() => setFilters(f => ({ ...f, regime: r.v }))}>
              <span className="radio-bullet"></span>
              {r.l}
              <span className="count mono">{r.c}</span>
            </button>
          ))}
        </div>
        <div style={{ fontSize: 10.5, color: "var(--text-3)", marginTop: 6, lineHeight: 1.4 }}>
          classify_momentum · trailing 126-TD return tercile
        </div>
      </div>

      <div className="sb-foot">
        Filters propagate to every tab below.<br/>
        <span style={{ color: "var(--text-2)" }}>v0.6-ui</span>
        <span style={{ color: "var(--text-4)" }}> · </span>
        <span className="mono">src/web/</span>
      </div>
    </aside>
  );
}

window.Sidebar = Sidebar;
