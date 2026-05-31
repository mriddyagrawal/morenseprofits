// Caveats expander — open by default; renders three load-bearing caveats.
function Caveats() {
  const [open, setOpen] = React.useState(true);

  return (
    <div className={`caveats ${open ? "open" : ""}`}>
      <div className="caveats-head" onClick={() => setOpen(o => !o)}>
        <span className="label">CAVEATS</span>
        <span className="title">Read once, then dismiss.</span>
        <span className="pill mono">3 sections</span>
        <span className="pill mono">SPECS §6b · §4a · rank.py</span>
        <svg className="chev" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </div>

      {open && (
        <div className="caveats-body">

          <div className="caveat">
            <div className="hd">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 9v4M12 17h.01" /><circle cx="12" cy="12" r="10" />
              </svg>
              Multiple comparisons
              <span className="src">rank.MULTIPLE_COMPARISONS_CAVEAT</span>
            </div>
            <p>
              <strong>~15 (strategy, symbol) pairs</strong> were tested. The top-ranked cell is
              not necessarily statistically significant — at <span className="mono">α=0.05</span>,
              expect <span className="mono">~0.75</span> spurious wins by chance alone. Treat the
              leaderboard as <strong>hypotheses to investigate</strong>, not conclusions.
            </p>
          </div>

          <div className="caveat">
            <div className="hd">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 12l6-6 6 6 6-6" /><path d="M3 18l6-6 6 6 6-6" opacity="0.4" />
              </svg>
              Survivorship bias
              <span className="src">SPECS §6b.3</span>
            </div>
            <p>
              v1 blue-chip universe is a <strong>2026-07-01 snapshot</strong>. Names that
              de-listed or fell out of the top 40 mid-window are absent — their bad outcomes
              are not in this dataset. Phase 7 adds per-quarter universe rebalance.
            </p>
          </div>

          <div className="caveat">
            <div className="hd">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <path d="M9 9h6v6H9z" />
              </svg>
              Margin Tier-B asymmetry
              <span className="src">SPECS §4a (1, 3, 4)</span>
            </div>
            <p>
              Margin uses <strong>portfolio SPAN offset + vol-derived per-symbol SPAN%</strong>,
              not a real broker file. Rankings bias toward
              <strong> high-vol symbols</strong> and <strong>low-offset strategies</strong>
              vs. live margin requirements. Read RoIs as relative, not absolute.
            </p>
          </div>

        </div>
      )}
    </div>
  );
}

window.Caveats = Caveats;
