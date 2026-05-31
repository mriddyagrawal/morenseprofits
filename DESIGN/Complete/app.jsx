// morenseprofits — Phase 6 research dashboard

const { useTweaks, TweaksPanel, TweakSection, TweakSlider, TweakToggle,
        TweakRadio, TweakSelect, TweakColor } = window;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "density": "comfortable",
  "accent": "#d4ff3a",
  "minN": 5,
  "showThin": true,
  "sortBy": "median",
  "monoNumerics": true
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [tab, setTab] = React.useState("leaderboard");
  const [sweep, setSweep] = React.useState(window.MORENSE_DATA.SWEEPS[0]);

  // Cross-cutting filter state (sidebar)
  const [filters, setFilters] = React.useState(() => ({
    strategies: ["short_straddle", "short_strangle", "iron_condor", "long_straddle", "long_strangle"],
    symbols: ["RELIANCE", "HDFCBANK", "INFY", "ICICIBANK", "TCS"],
    minN: t.minN,
    regime: "all",
  }));

  // sync min_N with the tweaks panel
  React.useEffect(() => {
    setFilters(f => ({ ...f, minN: t.minN }));
  }, [t.minN]);

  // Apply theme tweaks to root element
  React.useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = t.theme;
    root.dataset.density = t.density;
    root.style.setProperty("--accent", t.accent);
    // derive a dim accent
    root.style.setProperty("--accent-bg", hexToRgba(t.accent, 0.10));
    root.style.setProperty("--accent-dim", shadeColor(t.accent, -25));
  }, [t.theme, t.density, t.accent]);

  const TABS = [
    { key: "leaderboard", label: "Leaderboard", badge: "01", sub: "what's worth investigating" },
    { key: "perstock",    label: "Per-stock",   badge: "02", sub: "one symbol, every strategy" },
    { key: "heatmap",     label: "Heatmap",     badge: "03", sub: "entry × exit window" },
    { key: "trends",      label: "Trends",      badge: "04", sub: "decay & seasonality" },
  ];

  return (
    <div className="app">
      <window.TopBar sweep={sweep} setSweep={setSweep} sweeps={window.MORENSE_DATA.SWEEPS} />
      <window.Sidebar filters={filters} setFilters={setFilters} />

      <main className="main">
        <nav className="tabs" data-screen-label="tabs">
          {TABS.map(t => (
            <button key={t.key} className={`tab ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
              <span className="badge">{t.badge}</span>
              <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                {t.label}
                <span className="sub">— {t.sub}</span>
              </span>
            </button>
          ))}
          <div className="tab-action">
            <button className="btn icon" title="Refresh">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 12a9 9 0 1 1-3-6.7" /><polyline points="21 4 21 10 15 10" />
              </svg>
            </button>
            <button className="btn">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 4h18" /><path d="M3 12h18" /><path d="M3 20h18" />
              </svg>
              {filters.strategies.length}s · {filters.symbols.length}sym · min_N {filters.minN}
            </button>
          </div>
        </nav>

        <div className="tab-content" data-screen-label={`${TABS.find(x=>x.key===tab).badge} ${TABS.find(x=>x.key===tab).label}`}>
          <window.Caveats />

          {tab === "leaderboard" && <window.Leaderboard filters={filters} />}
          {tab === "perstock"    && <window.PerStockTab filters={filters} />}
          {tab === "heatmap"     && <window.HeatmapTab  filters={filters} setFilters={setFilters} />}
          {tab === "trends"      && <window.TrendsTab   filters={filters} />}
        </div>
      </main>

      <TweaksPanel>
        <TweakSection label="Theme" />
        <TweakRadio label="Mode" value={t.theme}
          options={["dark", "light"]}
          onChange={(v) => setTweak("theme", v)} />
        <TweakRadio label="Density" value={t.density}
          options={["compact", "comfortable"]}
          onChange={(v) => setTweak("density", v)} />
        <TweakColor label="Accent" value={t.accent}
          options={["#d4ff3a", "#7cd6ff", "#ff9ec7", "#ffaa4d", "#9affc0", "#c5b3ff"]}
          onChange={(v) => setTweak("accent", v)} />

        <TweakSection label="Data" />
        <TweakSlider label="min_N for ranking" value={t.minN} min={0} max={30} step={1}
          onChange={(v) => setTweak("minN", v)} />
        <TweakToggle label='Show "thin samples"' value={t.showThin}
          onChange={(v) => setTweak("showThin", v)} />
        <TweakSelect label="Default sort" value={t.sortBy}
          options={["median", "mean", "total", "win"]}
          onChange={(v) => setTweak("sortBy", v)} />
      </TweaksPanel>
    </div>
  );
}

// helpers
function hexToRgba(hex, a) {
  const m = hex.replace("#","").match(/^([0-9a-f]{6})$/i);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n>>16)&255}, ${(n>>8)&255}, ${n&255}, ${a})`;
}
function shadeColor(hex, percent) {
  const m = hex.replace("#","").match(/^([0-9a-f]{6})$/i);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  let r = (n>>16)&255, g = (n>>8)&255, b = n&255;
  r = Math.max(0, Math.min(255, Math.round(r * (100 + percent) / 100)));
  g = Math.max(0, Math.min(255, Math.round(g * (100 + percent) / 100)));
  b = Math.max(0, Math.min(255, Math.round(b * (100 + percent) / 100)));
  return `#${((r<<16)|(g<<8)|b).toString(16).padStart(6,"0")}`;
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
