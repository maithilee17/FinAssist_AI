import { useState } from "react";
import { Percent } from "lucide-react";

export default function MarginChart({ data }) {
  const [hoveredIdx, setHoveredIdx] = useState(null);

  if (!data || data.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.025] p-6 text-center">
        <Percent className="size-8 text-slate-600" />
        <p className="mt-2 text-sm text-slate-400">Margin trend unavailable</p>
        <p className="mt-1 text-xs text-slate-500">No gross margin or net margin figures were found.</p>
      </div>
    );
  }

  // Margin values range (typically 0% to 50% or dynamic max)
  const allMargins = data.flatMap((d) => [d.gross_profit_margin, d.net_profit_margin].filter((m) => m !== null));
  const maxMargin = Math.max(40, Math.ceil((Math.max(...allMargins, 30) + 5) / 10) * 10);

  // SVG dimensions
  const width = 500;
  const height = 240;
  const padding = { top: 30, right: 30, bottom: 45, left: 55 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  const count = data.length;
  const step = count > 1 ? chartWidth / (count - 1) : chartWidth / 2;

  // Build SVG path points
  const gpPoints = data.map((d, idx) => {
    const x = count > 1 ? padding.left + idx * step : padding.left + chartWidth / 2;
    const yVal = d.gross_profit_margin !== null ? d.gross_profit_margin : 0;
    const y = padding.top + chartHeight - (yVal / maxMargin) * chartHeight;
    return { x, y, val: d.gross_profit_margin };
  });

  const niPoints = data.map((d, idx) => {
    const x = count > 1 ? padding.left + idx * step : padding.left + chartWidth / 2;
    const yVal = d.net_profit_margin !== null ? d.net_profit_margin : 0;
    const y = padding.top + chartHeight - (yVal / maxMargin) * chartHeight;
    return { x, y, val: d.net_profit_margin };
  });

  const gpPath = gpPoints.reduce((acc, pt, i) => `${acc} ${i === 0 ? "M" : "L"} ${pt.x} ${pt.y}`, "");
  const niPath = niPoints.reduce((acc, pt, i) => `${acc} ${i === 0 ? "M" : "L"} ${pt.x} ${pt.y}`, "");

  return (
    <div
      data-testid="chart-margin-trend"
      className="flex flex-col justify-between rounded-2xl border border-white/10 bg-white/[0.035] p-5 lg:col-span-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-white">Profit Margin Trend</h3>
          <p className="text-xs text-slate-400">Gross profit margin vs Net profit margin across periods</p>
        </div>
        <div className="flex items-center gap-4 text-[11px]">
          <span className="flex items-center gap-1.5 text-emerald-300">
            <span className="size-2 rounded-full bg-emerald-400 ring-2 ring-emerald-400/30" /> Gross Margin (%)
          </span>
          <span className="flex items-center gap-1.5 text-amber-300">
            <span className="size-2 rounded-full bg-amber-400 ring-2 ring-amber-400/30" /> Net Margin (%)
          </span>
        </div>
      </div>

      <div className="relative mt-4 w-full">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full overflow-visible"
          role="img"
          aria-label="Profit Margin Trend Chart"
        >
          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((pct) => {
            const y = padding.top + chartHeight * (1 - pct);
            const val = maxMargin * pct;

            return (
              <g key={pct}>
                <line
                  x1={padding.left}
                  y1={y}
                  x2={width - padding.right}
                  y2={y}
                  stroke="rgba(255,255,255,0.08)"
                  strokeDasharray="4 4"
                />
                <text
                  x={padding.left - 8}
                  y={y + 3.5}
                  textAnchor="end"
                  fontSize="10"
                  fill="#64748b"
                >
                  {val.toFixed(0)}%
                </text>
              </g>
            );
          })}

          {/* Paths */}
          {count > 1 && (
            <>
              <path
                d={gpPath}
                fill="none"
                stroke="#10b981"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d={niPath}
                fill="none"
                stroke="#f59e0b"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray="5 3"
              />
            </>
          )}

          {/* Points & Interactive Nodes */}
          {data.map((item, idx) => {
            const gpPt = gpPoints[idx];
            const niPt = niPoints[idx];
            const isHovered = hoveredIdx === idx;

            return (
              <g
                key={item.period}
                onMouseEnter={() => setHoveredIdx(idx)}
                onMouseLeave={() => setHoveredIdx(null)}
                className="cursor-pointer"
              >
                {/* Vertical hover guide */}
                {isHovered && (
                  <line
                    x1={gpPt.x}
                    y1={padding.top}
                    x2={gpPt.x}
                    y2={padding.top + chartHeight}
                    stroke="rgba(255,255,255,0.2)"
                    strokeWidth="1"
                    strokeDasharray="2 2"
                  />
                )}

                {/* Gross Margin Dot */}
                {gpPt.val !== null && (
                  <circle
                    cx={gpPt.x}
                    cy={gpPt.y}
                    r={isHovered ? "6" : "4.5"}
                    fill="#10b981"
                    stroke="#071512"
                    strokeWidth="2"
                    className="transition-all"
                  />
                )}

                {/* Net Margin Dot */}
                {niPt.val !== null && (
                  <circle
                    cx={niPt.x}
                    cy={niPt.y}
                    r={isHovered ? "6" : "4.5"}
                    fill="#f59e0b"
                    stroke="#071512"
                    strokeWidth="2"
                    className="transition-all"
                  />
                )}

                {/* X Axis Label */}
                <text
                  x={gpPt.x}
                  y={height - 12}
                  textAnchor="middle"
                  fontSize="11"
                  fontWeight="500"
                  fill="#94a3b8"
                >
                  {item.fiscal_year}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Hover Tooltip Overlay */}
        {hoveredIdx !== null && data[hoveredIdx] && (
          <div className="pointer-events-none absolute right-4 top-2 rounded-lg border border-white/10 bg-slate-900/95 p-2.5 text-xs text-white shadow-xl backdrop-blur">
            <p className="font-semibold text-white">
              {data[hoveredIdx].fiscal_year} Margin Performance
            </p>
            <div className="mt-1 space-y-0.5">
              <p className="text-emerald-300">
                Gross Margin: {data[hoveredIdx].gross_profit_margin !== null ? `${data[hoveredIdx].gross_profit_margin}%` : "—"}
                {(() => {
                  if (hoveredIdx === 0) return null;
                  const prev = data[hoveredIdx - 1]?.gross_profit_margin;
                  const curr = data[hoveredIdx]?.gross_profit_margin;
                  if (prev == null || curr == null) return null;
                  const diff = (curr - prev).toFixed(2);
                  return <span className="ml-1 text-[10px] text-slate-400">({Number(diff) >= 0 ? "+" : ""}{diff} pp)</span>;
                })()}
              </p>
              <p className="text-amber-300">
                Net Margin: {data[hoveredIdx].net_profit_margin !== null ? `${data[hoveredIdx].net_profit_margin}%` : "—"}
                {(() => {
                  if (hoveredIdx === 0) return null;
                  const prev = data[hoveredIdx - 1]?.net_profit_margin;
                  const curr = data[hoveredIdx]?.net_profit_margin;
                  if (prev == null || curr == null) return null;
                  const diff = (curr - prev).toFixed(2);
                  return <span className="ml-1 text-[10px] text-slate-400">({Number(diff) >= 0 ? "+" : ""}{diff} pp)</span>;
                })()}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
