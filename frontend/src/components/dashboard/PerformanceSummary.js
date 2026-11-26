import { createElement } from "react";
import { AlertTriangle, CheckCircle2, FileText, Sparkles } from "lucide-react";

export default function PerformanceSummary({ summary }) {
  if (!summary) return null;

  const hasObservations = summary.key_observations && summary.key_observations.length > 0;
  const hasLimitations = summary.limitations && summary.limitations.length > 0;
  const hasCitations = summary.citations && summary.citations.length > 0;

  return createElement(
    "section",
    {
      "data-testid": "ai-performance-summary",
      className:
        "rounded-2xl border border-teal-400/20 bg-gradient-to-br from-teal-950/20 via-white/[0.02] to-transparent p-6 backdrop-blur",
    },
    createElement(
      "div",
      { className: "flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-4" },
      createElement(
        "div",
        { className: "flex items-center gap-2.5" },
        createElement(
          "span",
          { className: "grid size-8 place-items-center rounded-lg bg-teal-400/10 text-teal-300" },
          createElement(Sparkles, { size: 16 }),
        ),
        createElement(
          "div",
          null,
          createElement(
            "h2",
            { className: "text-sm font-semibold tracking-wide text-white" },
            "Evidence-Grounded AI Performance Summary",
          ),
          createElement(
            "p",
            { className: "text-xs text-slate-400" },
            "Deterministic analysis grounded strictly in extracted financial tables",
          ),
        ),
      ),
      createElement(
        "span",
        {
          className:
            "inline-flex items-center gap-1.5 rounded-full border border-teal-400/30 bg-teal-400/10 px-3 py-1 text-[11px] font-medium text-teal-300",
        },
        createElement(CheckCircle2, { size: 13 }),
        "Zero Hallucination · Table Grounded",
      ),
    ),
    createElement(
      "div",
      { className: "mt-5 space-y-4 text-xs leading-relaxed text-slate-300" },
      summary.revenue_performance
        ? createElement(
            "div",
            { className: "rounded-xl border border-white/5 bg-white/[0.02] p-4" },
            createElement("p", { className: "font-semibold text-teal-200" }, "Revenue Trajectory"),
            createElement("p", { className: "mt-1.5 text-slate-300" }, summary.revenue_performance),
          )
        : null,
      summary.profitability
        ? createElement(
            "div",
            { className: "rounded-xl border border-white/5 bg-white/[0.02] p-4" },
            createElement("p", { className: "font-semibold text-teal-200" }, "Profitability & Margins"),
            createElement("p", { className: "mt-1.5 text-slate-300" }, summary.profitability),
          )
        : null,
      summary.growth
        ? createElement(
            "div",
            { className: "rounded-xl border border-white/5 bg-white/[0.02] p-4" },
            createElement("p", { className: "font-semibold text-teal-200" }, "Multi-Year Growth Dynamics"),
            createElement("p", { className: "mt-1.5 text-slate-300" }, summary.growth),
          )
        : null,
    ),
    hasObservations
      ? createElement(
          "div",
          { className: "mt-5" },
          createElement(
            "h3",
            { className: "text-xs font-semibold uppercase tracking-wider text-slate-400" },
            "Key Financial Observations",
          ),
          createElement(
            "ul",
            { className: "mt-2.5 space-y-2 text-xs text-slate-300" },
            summary.key_observations.map((obs, idx) =>
              createElement(
                "li",
                { key: idx, className: "flex items-start gap-2" },
                createElement(
                  "span",
                  { className: "mt-1 size-1.5 shrink-0 rounded-full bg-teal-400" },
                ),
                createElement("span", null, obs),
              ),
            ),
          ),
        )
      : null,
    hasLimitations
      ? createElement(
          "div",
          {
            className:
              "mt-5 rounded-xl border border-amber-400/20 bg-amber-400/[0.04] p-4 text-xs text-amber-200/90",
          },
          createElement(
            "div",
            { className: "flex items-center gap-2 font-semibold text-amber-300" },
            createElement(AlertTriangle, { size: 14 }),
            "Analytical Scope & Limitations",
          ),
          createElement(
            "ul",
            { className: "mt-2 space-y-1 pl-5 list-disc text-amber-200/80" },
            summary.limitations.map((lim, idx) =>
              createElement("li", { key: idx }, lim),
            ),
          ),
        )
      : null,
    hasCitations
      ? createElement(
          "div",
          { className: "mt-5 flex flex-wrap items-center gap-2 border-t border-white/5 pt-4 text-xs text-slate-400" },
          createElement(
            "span",
            { className: "flex items-center gap-1.5 font-medium text-slate-300" },
            createElement(FileText, { size: 13, className: "text-teal-400" }),
            "Verified Sources:",
          ),
          summary.citations.map((cite, idx) =>
            createElement(
              "span",
              {
                key: idx,
                className:
                  "rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-teal-300",
              },
              `[Source: ${cite}]`,
            ),
          ),
        )
      : null,
  );
}
