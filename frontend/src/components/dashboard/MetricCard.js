import { createElement } from "react";
import { ArrowDownRight, ArrowUpRight, FileText } from "lucide-react";

export default function MetricCard({ card }) {
  if (!card) return null;

  const isAvailable = card.value !== null && card.value !== undefined;
  const hasYoY = card.yoy_change !== null && card.yoy_change !== undefined;
  const isPositiveYoY = hasYoY && card.yoy_change >= 0;

  return createElement(
    "article",
    {
      "data-testid": `metric-card-${card.label.toLowerCase().replace(/\s+/g, "-")}`,
      className:
        "group relative flex flex-col justify-between rounded-2xl border border-white/10 bg-white/[0.035] p-5 transition hover:border-teal-400/30 hover:bg-white/[0.05]",
    },
    createElement(
      "div",
      null,
      createElement(
        "div",
        { className: "flex items-center justify-between gap-2" },
        createElement(
          "p",
          { className: "text-xs font-medium uppercase tracking-wider text-slate-400" },
          card.label,
        ),
        card.period
          ? createElement(
              "span",
              {
                className:
                  "rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] font-semibold text-teal-300",
              },
              card.period,
            )
          : null,
      ),
      createElement(
        "div",
        { className: "mt-3 flex items-baseline gap-2" },
        createElement(
          "p",
          { className: "text-2xl font-bold tracking-tight text-white lg:text-3xl" },
          card.formatted_value,
        ),
        card.scale
          ? createElement("span", { className: "text-xs text-slate-400" }, `(${card.scale})`)
          : null,
      ),
    ),
    createElement(
      "div",
      {
        className:
          "mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-white/5 pt-3 text-xs",
      },
      hasYoY
        ? createElement(
            "span",
            {
              className: `inline-flex items-center gap-1 font-medium ${
                isPositiveYoY ? "text-emerald-400" : "text-rose-400"
              }`,
            },
            createElement(isPositiveYoY ? ArrowUpRight : ArrowDownRight, {
              size: 14,
              className: "shrink-0",
            }),
            (() => {
              const isPp =
                card.yoy_change_unit === "pp" ||
                (card.yoy_change_formatted && card.yoy_change_formatted.endsWith("pp"));
              if (isPp) {
                return ` ${card.yoy_change_formatted || `${card.yoy_change > 0 ? "+" : ""}${card.yoy_change} pp`}`;
              }
              return ` ${card.yoy_change_formatted || `${card.yoy_change > 0 ? "+" : ""}${card.yoy_change}%`} YoY`;
            })(),
          )
        : createElement(
            "span",
            { className: "text-slate-500" },
            isAvailable ? "Base period" : "Metric unavailable",
          ),
      card.source_citation
        ? createElement(
            "span",
            {
              className:
                "flex items-center gap-1 text-[11px] text-slate-500 group-hover:text-slate-400",
              title: card.source_citation,
            },
            createElement(FileText, { size: 12, className: "text-teal-400/70" }),
            ` ${card.source_citation}`,
          )
        : null,
    ),
  );
}
