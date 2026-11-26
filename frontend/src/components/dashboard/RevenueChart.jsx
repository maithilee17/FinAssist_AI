import { useState } from "react";
import { TrendingUp } from "lucide-react";

export default function RevenueChart({ data }) {
  const [hoveredIdx, setHoveredIdx] = useState(null);

  if (!data || data.length === 0) {
    return (
      <div className="flex h-64 flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.025] p-6 text-center">
        <TrendingUp className="size-8 text-slate-600" />
        <p className="mt-2 text-sm text-slate-400">Revenue trend unavailable</p>
        <p className="mt-1 text-xs text-slate-500">No multi-period revenue figures were found.</p>
      </div>
    );
  }

  // Calculate scaling
  const revenues = data.map((d) => d.revenue);
  const maxRevenue = Math.max(...revenues, 1);

  // SVG dimensions
  const width = 500;
  const height = 240;
  const padding = { top: 30, right: 30, bottom: 45, left: 60 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  const barCount = data.length;
  const barWidth = Math.min(48, Math.max(24, chartWidth / (barCount * 2.2)));
  const step = chartWidth / barCount;

  return (
    <div
      data-testid="chart-revenue-trend"
      className="flex flex-col justify-between rounded-2xl border border-white/10 bg-white/[0.035] p-5"
    >
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white">Revenue Trend</h3>
          <p className="text-xs text-slate-400">Verified top-line revenue over fiscal periods</p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-teal-400/20 bg-teal-400/10 px-2.5 py-1 text-[11px] font-medium text-teal-300">
          <TrendingUp size={13} /> Top-Line
        </span>
      </div>

      <div className="relative mt-4 w-full">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full overflow-visible"
          role="img"
          aria-label="Revenue Trend Chart"
        >
          <defs>
            <linearGradient id="revenueBarGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#0d9488" stopOpacity="0.4" />
            </linearGradient>
            <linearGradient id="revenueBarHover" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5eead4" stopOpacity="1" />
              <stop offset="100%" stopColor="#14b8a6" stopOpacity="0.7" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((pct) => {
            const y = padding.top + chartHeight * (1 - pct);
            const val = maxRevenue * pct;
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

          {/* Bars */}
          {data.map((item, idx) => {
            const barHeight = Math.max(4, (item.revenue / maxRevenue) * chartHeight);
            const x = padding.left + idx * step + (step - barWidth) / 2;
            const y = padding.top + chartHeight - barHeight;
            const isHovered = hoveredIdx === idx;

            return (
              <g
                key={item.period}
                onMouseEnter={() => setHoveredIdx(idx)}
                onMouseLeave={() => setHoveredIdx(null)}
                className="cursor-pointer transition-all duration-200"
              >
                <rect
                  x={x}
                  y={y}
                  width={barWidth}
                  height={barHeight}
                  rx="6"
                  fill={isHovered ? "url(#revenueBarHover)" : "url(#revenueBarGradient)"}
                  stroke={isHovered ? "#5eead4" : "rgba(45,212,191,0.4)"}
                  strokeWidth={isHovered ? "1.5" : "0.5"}
                />

                {/* Bar Value on top */}
                <text
                  x={x + barWidth / 2}
                  y={y - 8}
                  textAnchor="middle"
                  fontSize="11"
                  fontWeight="600"
                  fill={isHovered ? "#5eead4" : "#94a3b8"}
                >
                  {item.formatted}
                </text>

                {/* X Axis Label */}
                <text
                  x={x + barWidth / 2}
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
          <div className="pointer-events-none absolute right-4 top-2 rounded-lg border border-teal-400/20 bg-slate-900/95 px-3 py-1.5 text-xs text-white shadow-lg backdrop-blur">
            <span className="font-semibold text-teal-300">
              {data[hoveredIdx].fiscal_year}:
            </span>{" "}
            {data[hoveredIdx].formatted} {data[hoveredIdx].currency || "USD"}
          </div>
        )}
      </div>
    </div>
  );
}
