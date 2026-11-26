import { useState } from "react";
import { BarChart3 } from "lucide-react";

export default function ProfitabilityChart({ data }) {
  const [hoveredIdx, setHoveredIdx] = useState(null);

  if (!data || data.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.025] p-6 text-center">
        <BarChart3 className="size-8 text-slate-600" />
        <p className="mt-2 text-sm text-slate-400">Profitability trend unavailable</p>
        <p className="mt-1 text-xs text-slate-500">No gross profit or net income figures were found.</p>
      </div>
    );
  }

  // Calculate bounds
  const allValues = data.flatMap((d) => [d.gross_profit, d.net_income].filter((v) => v !== null));
  const maxVal = Math.max(...allValues, 1);

  // SVG dimensions
  const width = 500;
  const height = 240;
  const padding = { top: 30, right: 30, bottom: 45, left: 60 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  const barCount = data.length;
  const groupStep = chartWidth / barCount;
  const singleBarWidth = Math.min(22, Math.max(12, groupStep / 3.2));
  const groupWidth = singleBarWidth * 2 + 4;

  return (
    <div
      data-testid="chart-profitability-trend"
      className="flex flex-col justify-between rounded-2xl border border-white/10 bg-white/[0.035] p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-white">Profitability Breakdown</h3>
          <p className="text-xs text-slate-400">Gross profit vs Net income across reporting periods</p>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <span className="flex items-center gap-1.5 text-teal-300">
            <span className="size-2.5 rounded-sm bg-teal-400" /> Gross Profit
          </span>
          <span className="flex items-center gap-1.5 text-sky-300">
            <span className="size-2.5 rounded-sm bg-sky-400" /> Net Income
          </span>
        </div>
      </div>

      <div className="relative mt-4 w-full">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full overflow-visible"
          role="img"
          aria-label="Profitability Breakdown Chart"
        >
          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((pct) => {
            const y = padding.top + chartHeight * (1 - pct);
            const val = maxVal * pct;
            const formatted =
              val >= 1e9
                ? `$${(val / 1e9).toFixed(1)}B`
                : val >= 1e6
                  ? `$${(val / 1e6).toFixed(1)}M`
                  : val >= 1e3
                    ? `$${(val / 1e3).toFixed(0)}K`
                    : `$${val.toFixed(0)}`;

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
                  {formatted}
                </text>
              </g>
            );
          })}

          {/* Grouped Bars */}
          {data.map((item, idx) => {
            const groupX = padding.left + idx * groupStep + (groupStep - groupWidth) / 2;
            const gpVal = item.gross_profit || 0;
            const niVal = item.net_income || 0;

            const gpHeight = Math.max(3, (gpVal / maxVal) * chartHeight);
            const niHeight = Math.max(3, (niVal / maxVal) * chartHeight);

            const gpY = padding.top + chartHeight - gpHeight;
            const niY = padding.top + chartHeight - niHeight;

            const isHovered = hoveredIdx === idx;

            return (
              <g
                key={item.period}
                onMouseEnter={() => setHoveredIdx(idx)}
                onMouseLeave={() => setHoveredIdx(null)}
                className="cursor-pointer"
              >
                {/* Gross Profit Bar */}
                <rect
                  x={groupX}
                  y={gpY}
                  width={singleBarWidth}
                  height={gpHeight}
                  rx="4"
                  fill={isHovered ? "#2dd4bf" : "#0d9488"}
                  stroke="rgba(45,212,191,0.5)"
                  strokeWidth="0.5"
                />

                {/* Net Income Bar */}
                <rect
                  x={groupX + singleBarWidth + 4}
                  y={niY}
                  width={singleBarWidth}
                  height={niHeight}
                  rx="4"
                  fill={isHovered ? "#38bdf8" : "#0284c7"}
                  stroke="rgba(56,189,248,0.5)"
                  strokeWidth="0.5"
                />

                {/* X Axis Label */}
                <text
                  x={groupX + groupWidth / 2}
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
            <p className="font-semibold text-teal-300">
              {data[hoveredIdx].fiscal_year} Profitability
            </p>
            <div className="mt-1 space-y-0.5">
              <p className="text-teal-200">
                Gross Profit: {data[hoveredIdx].formatted_gross_profit || "—"}
              </p>
              <p className="text-sky-200">
                Net Income: {data[hoveredIdx].formatted_net_income || "—"}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
