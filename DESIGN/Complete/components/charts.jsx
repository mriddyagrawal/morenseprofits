// Small chart primitives — built in SVG so they inherit theme tokens cleanly.

const { useState, useRef, useMemo } = React;

// Diverging color scale anchored at 0. Returns CSS color string.
function divergingColor(v, vMax) {
  const t = Math.max(-1, Math.min(1, v / vMax));
  if (t >= 0) {
    // white -> green
    const alpha = 0.18 + 0.62 * t;
    return `rgba(93, 211, 158, ${alpha.toFixed(3)})`;
  } else {
    const alpha = 0.18 + 0.62 * Math.abs(t);
    return `rgba(255, 118, 118, ${alpha.toFixed(3)})`;
  }
}

function sequentialColor(t) {
  // 0 -> faint, 1 -> accent
  const a = 0.06 + 0.55 * t;
  return `rgba(212, 255, 58, ${a.toFixed(3)})`;
}

// ---------- HEATMAP ----------
// Generic 2D heatmap. Takes row labels (rows), col labels (cols), a getCell(r, c) -> {n, roi, win, ...},
// a min_n threshold for masking, render mode ("value" | "density"), and optional selection array
// with numbered badges.
function Heatmap({
  rows, cols, getCell, minN, mode = "value",
  rowLabel = "", colLabel = "", rowFmt = (v) => v, colFmt = (v) => v,
  onHover, onClick, selected = [], cellW = 96, cellH = 60,
  noiseFloor = false,
}) {
  const padL = 56;
  const padT = 32;
  const padR = 14;
  const padB = 22;
  const w = padL + cellW * cols.length + padR;
  const h = padT + cellH * rows.length + padB;

  const flat = [];
  rows.forEach(r => cols.forEach(c => {
    const cell = getCell(r, c);
    if (cell && typeof cell.roi === "number" && cell.n >= minN) flat.push(cell.roi);
  }));
  const vMax = Math.max(...flat.map(Math.abs), 1);

  const counts = rows.flatMap(r => cols.map(c => getCell(r, c)?.n || 0));
  const cMax = Math.max(...counts, 1);

  function selectionIndex(r, c) {
    const idx = selected.findIndex(s => s.r === r && s.c === c);
    return idx >= 0 ? idx + 1 : null;
  }

  // selection colors (badges in numbered order)
  const BADGE_COLORS = ["#d4ff3a", "#7cd6ff", "#ffaa4d", "#ff9ec7"];

  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <text x={padL + (cellW * cols.length) / 2} y={14}
            textAnchor="middle"
            style={{ fontFamily: "var(--font-mono)", fontSize: 10, fill: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
        {colLabel}
      </text>
      <text x={14} y={padT + (cellH * rows.length) / 2}
            textAnchor="middle"
            transform={`rotate(-90, 14, ${padT + (cellH * rows.length) / 2})`}
            style={{ fontFamily: "var(--font-mono)", fontSize: 10, fill: "var(--text-3)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
        {rowLabel}
      </text>

      {cols.map((c, i) => (
        <text key={`hc${c}`} x={padL + cellW * i + cellW / 2} y={padT - 10}
              textAnchor="middle"
              style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, fill: "var(--text-2)" }}>
          {colFmt(c)}
        </text>
      ))}
      {rows.map((r, i) => (
        <text key={`hr${r}`} x={padL - 10} y={padT + cellH * i + cellH / 2 + 4}
              textAnchor="end"
              style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, fill: "var(--text-2)" }}>
          {rowFmt(r)}
        </text>
      ))}

      {rows.map((r, i) => cols.map((c, j) => {
        const cell = getCell(r, c);
        if (!cell) return null;
        const noRoi = typeof cell.roi !== "number";
        const masked = cell.n < minN;
        const fill = mode === "density"
          ? (noiseFloor && cell.n < minN
              ? "rgba(255,255,255,0.025)"
              : sequentialColor(cell.n / cMax))
          : ((masked || noRoi) ? "rgba(255,255,255,0.025)" : divergingColor(cell.roi, vMax));
        const x0 = padL + cellW * j + 3;
        const y0 = padT + cellH * i + 3;
        const cw = cellW - 6;
        const ch = cellH - 6;
        const selIdx = selectionIndex(r, c);
        const badgeColor = selIdx ? BADGE_COLORS[(selIdx - 1) % 4] : null;
        return (
          <g key={`${r}-${c}`} style={{ cursor: onClick ? "pointer" : "default" }}>
            <rect
              x={x0} y={y0} width={cw} height={ch}
              rx={4}
              fill={fill}
              stroke="var(--border)"
              strokeWidth="1"
              onMouseEnter={(ev) => onHover && onHover({ r, c, cell, masked, mx: x0 + cw, my: y0 })}
              onMouseLeave={() => onHover && onHover(null)}
              onClick={(ev) => onClick && onClick({ r, c, cell, shift: ev.shiftKey })}
            />

            {mode === "value" && (
              <>
                <text x={x0 + cw / 2} y={y0 + ch / 2 - 4}
                      textAnchor="middle"
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 14,
                        fontWeight: 500,
                        fill: (masked || noRoi) ? "var(--text-4)" : "var(--text)",
                        fontFeatureSettings: '"tnum"',
                        pointerEvents: "none",
                      }}>
                  {noRoi ? "—" : (masked ? "·" : `${cell.roi.toFixed(0)}%`)}
                </text>
                <text x={x0 + cw / 2} y={y0 + ch / 2 + 11}
                      textAnchor="middle"
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 9.5,
                        fill: "var(--text-3)",
                        pointerEvents: "none",
                      }}>
                  {masked || noRoi ? `n=${cell.n}` : `n=${cell.n} · ${cell.win.toFixed(0)}%w`}
                </text>
              </>
            )}

            {mode === "density" && (
              <text x={x0 + cw / 2} y={y0 + ch / 2 + 4}
                    textAnchor="middle"
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 13,
                      fontWeight: 500,
                      fill: cell.n < minN ? "var(--text-4)" : "var(--text)",
                      pointerEvents: "none",
                    }}>
                {cell.n}
              </text>
            )}

            {/* Selection border + numbered badge */}
            {selIdx && (
              <>
                <rect x={x0 - 1} y={y0 - 1} width={cw + 2} height={ch + 2}
                      rx={5} fill="none" stroke={badgeColor} strokeWidth="2"
                      style={{ pointerEvents: "none" }} />
                <circle cx={x0 + cw - 8} cy={y0 + 8} r={8} fill={badgeColor} style={{ pointerEvents: "none" }} />
                <text x={x0 + cw - 8} y={y0 + 11.5} textAnchor="middle"
                      style={{ fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 700, fill: "#0a0c10", pointerEvents: "none" }}>
                  {selIdx}
                </text>
              </>
            )}
          </g>
        );
      }))}

      {/* noise floor marker on density colorbar — drawn inline as a thin tick on rightmost edge */}
      {noiseFloor && mode === "density" && (
        <g>
          <line x1={w - padR + 2} x2={w - padR + 2}
                y1={padT} y2={padT + cellH * rows.length}
                stroke="var(--warn)" strokeWidth="2" strokeDasharray="3 3" opacity="0.6" />
        </g>
      )}
    </svg>
  );
}

// ---------- LINE CHART (YoY) ----------
function LineChart({ data, xKey, yKey, secondaryKey, height = 220, width = 520, fmt = (v) => `${v.toFixed(0)}%` }) {
  const padL = 44, padR = 14, padT = 14, padB = 28;
  const W = width, H = height;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const ys = data.map(d => d[yKey]).concat(secondaryKey ? data.map(d => d[secondaryKey]) : []);
  const yMin = Math.min(0, Math.min(...ys));
  const yMax = Math.max(...ys) * 1.1;
  const xN = data.length;

  const xPos = (i) => padL + (innerW / Math.max(1, xN - 1)) * i;
  const yPos = (v) => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;

  const linePath = data.map((d, i) => `${i === 0 ? "M" : "L"} ${xPos(i)} ${yPos(d[yKey])}`).join(" ");
  const areaPath = `${linePath} L ${xPos(xN - 1)} ${padT + innerH} L ${xPos(0)} ${padT + innerH} Z`;
  const sndPath  = secondaryKey ? data.map((d, i) => `${i === 0 ? "M" : "L"} ${xPos(i)} ${yPos(d[secondaryKey])}`).join(" ") : null;

  // gridlines
  const ticks = 4;
  const gridY = Array.from({ length: ticks + 1 }, (_, i) => yMin + (yMax - yMin) * (i / ticks));

  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      {gridY.map((g, i) => (
        <g key={`g${i}`}>
          <line className="grid-line" x1={padL} x2={W - padR} y1={yPos(g)} y2={yPos(g)} />
          <text className="axis-tick" x={padL - 8} y={yPos(g) + 3} textAnchor="end">{fmt(g)}</text>
        </g>
      ))}
      <defs>
        <linearGradient id="ln-area" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%"   stopColor="var(--accent)" stopOpacity="0.30" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill="url(#ln-area)" />
      {sndPath && <path d={sndPath} stroke="var(--text-3)" strokeWidth="1.25" strokeDasharray="3 4" fill="none" />}
      <path d={linePath} stroke="var(--accent)" strokeWidth="1.75" fill="none" strokeLinecap="round" />
      {data.map((d, i) => (
        <g key={`p${i}`}>
          <circle cx={xPos(i)} cy={yPos(d[yKey])} r={3.5} fill="var(--bg)" stroke="var(--accent)" strokeWidth="1.5" />
          <text className="axis-tick" x={xPos(i)} y={H - 10} textAnchor="middle">{d[xKey]}</text>
          <text x={xPos(i)} y={yPos(d[yKey]) - 10} textAnchor="middle"
                style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, fill: "var(--text-2)" }}>
            n={d.n}
          </text>
        </g>
      ))}
    </svg>
  );
}

// ---------- BAR CHART (MoY) ----------
function BarChart({ data, xKey, yKey, nKey, height = 220, width = 520, fmt = (v) => `${v.toFixed(0)}%` }) {
  const padL = 44, padR = 14, padT = 14, padB = 28;
  const W = width, H = height;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const ys = data.map(d => d[yKey]);
  const yMin = Math.min(0, Math.min(...ys));
  const yMax = Math.max(...ys) * 1.15;
  const xN = data.length;
  const bw = innerW / xN * 0.66;

  const yPos = (v) => padT + innerH - ((v - yMin) / (yMax - yMin)) * innerH;
  const zeroY = yPos(0);

  const ticks = 4;
  const gridY = Array.from({ length: ticks + 1 }, (_, i) => yMin + (yMax - yMin) * (i / ticks));

  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      {gridY.map((g, i) => (
        <g key={`g${i}`}>
          <line className="grid-line" x1={padL} x2={W - padR} y1={yPos(g)} y2={yPos(g)} />
          <text className="axis-tick" x={padL - 8} y={yPos(g) + 3} textAnchor="end">{fmt(g)}</text>
        </g>
      ))}
      <line className="axis-line" x1={padL} x2={W - padR} y1={zeroY} y2={zeroY} />
      {data.map((d, i) => {
        const cx = padL + (innerW / xN) * (i + 0.5);
        const v = d[yKey];
        const y0 = Math.min(yPos(v), zeroY);
        const h = Math.abs(yPos(v) - zeroY);
        const color = v >= 0 ? "var(--accent)" : "var(--neg)";
        return (
          <g key={`b${i}`}>
            <rect x={cx - bw / 2} y={y0} width={bw} height={h}
                  fill={color} opacity={0.72} rx={2}>
              <title>{`${d[xKey]} · median ${v.toFixed(1)}%/yr · n=${d[nKey]} · std ${d.std?.toFixed(1) ?? "—"}`}</title>
            </rect>
            <text className="axis-tick" x={cx} y={H - 10} textAnchor="middle">{d[xKey]}</text>
            {nKey && (
              <text x={cx} y={(v >= 0 ? y0 - 6 : y0 + h + 12)}
                    textAnchor="middle"
                    style={{ fontFamily: "var(--font-mono)", fontSize: 9.5, fill: "var(--text-3)" }}>
                n={d[nKey]}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ---------- SPARK BAR (per-stock cards) ----------
function Sparkbar({ values, width = 200, height = 36 }) {
  const W = width, H = height;
  const max = Math.max(...values.map(Math.abs), 1);
  const bw = W / values.length;
  const midY = H / 2;
  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      <line x1="0" x2={W} y1={midY} y2={midY} className="grid-line" />
      {values.map((v, i) => {
        const h = (Math.abs(v) / max) * (H / 2 - 2);
        const y0 = v >= 0 ? midY - h : midY;
        const color = v >= 0 ? "var(--pos)" : "var(--neg)";
        return <rect key={i} x={i * bw + 1} y={y0} width={bw - 2} height={h} fill={color} opacity="0.75" rx="1" />;
      })}
    </svg>
  );
}

window.Charts = { Heatmap, LineChart, BarChart, Sparkbar, divergingColor, sequentialColor };
