// Top bar — brand, sweep picker, status
const { useState: useStateTopbar, useRef: useRefTopbar, useEffect: useEffectTopbar } = React;

function TopBar({ sweep, setSweep, sweeps }) {
  const [open, setOpen] = useStateTopbar(false);
  const ref = useRefTopbar(null);

  useEffectTopbar(() => {
    function onDoc(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-glyph">m</div>
        <div className="brand-name">morenseprofits <span>· phase 6</span></div>
      </div>

      <div className="topbar-divider" />

      <div ref={ref} style={{ position: "relative" }}>
        <button className="sweep-pill" onClick={() => setOpen(o => !o)}>
          <span className="tag mono">SWEEP</span>
          <span className="mono">{sweep.run_id}</span>
          <span className="meta mono">· {sweep.rows.toLocaleString()} rows · {sweep.mtime}</span>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
        {open && (
          <div style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0,
            background: "var(--surface)", border: "1px solid var(--border-strong)",
            borderRadius: 6, padding: 4, minWidth: 360, zIndex: 50,
            boxShadow: "var(--shadow)",
          }}>
            <div style={{ padding: "8px 10px", fontSize: 10.5, color: "var(--text-3)",
                          textTransform: "uppercase", letterSpacing: "0.08em", fontFamily: "var(--font-mono)" }}>
              data/results/sweep_*.parquet
            </div>
            {sweeps.map(s => (
              <button key={s.run_id}
                      onClick={() => { setSweep(s); setOpen(false); }}
                      style={{
                        display: "flex", alignItems: "center", gap: 10, width: "100%",
                        padding: "8px 10px", borderRadius: 4,
                        background: s.run_id === sweep.run_id ? "var(--accent-bg)" : "transparent",
                        color: "var(--text)", textAlign: "left", cursor: "pointer",
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.background = s.run_id === sweep.run_id ? "var(--accent-bg)" : "var(--surface-2)"}
                      onMouseLeave={(e) => e.currentTarget.style.background = s.run_id === sweep.run_id ? "var(--accent-bg)" : "transparent"}>
                <span className="mono" style={{ fontSize: 11, color: s.run_id === sweep.run_id ? "var(--accent)" : "var(--text)" }}>
                  {s.run_id}
                </span>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--text-3)" }}>
                  {s.rows.toLocaleString()} rows
                </span>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--text-3)", marginLeft: "auto" }}>
                  {s.mtime}
                </span>
                {s.current && <span style={{ fontSize: 10, color: "var(--accent)", marginLeft: 6 }}>● latest</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="topbar-status">
        <div><span className="dot"></span>cache hot · 8.2GB</div>
        <div className="sep" />
        <div>365 tests passing</div>
        <div className="sep" />
        <div className="row" style={{ gap: 5 }}>
          <span className="kbd">⌘</span><span className="kbd">K</span>
        </div>
      </div>
    </header>
  );
}

window.TopBar = TopBar;
