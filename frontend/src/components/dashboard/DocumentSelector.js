import { createElement } from "react";
import { ChevronDown, FileSpreadsheet, RefreshCw } from "lucide-react";

export default function DocumentSelector({
  documents = [],
  selectedId = null,
  onSelect = () => {},
  isLoading = false,
  onRefresh = () => {},
}) {
  const completedDocs = documents.filter((d) => d.processing_status === "completed");

  return createElement(
    "div",
    {
      "data-testid": "document-selector-container",
      className: "flex flex-wrap items-center gap-3",
    },
    createElement(
      "div",
      { className: "relative min-w-[280px] max-w-md flex-1" },
      createElement(FileSpreadsheet, {
        size: 16,
        className:
          "pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-teal-400",
      }),
      createElement(
        "select",
        {
          "data-testid": "document-select",
          value: selectedId || "",
          onChange: (e) => onSelect(e.target.value),
          disabled: isLoading || completedDocs.length === 0,
          className:
            "w-full appearance-none rounded-xl border border-white/10 bg-white/[0.04] py-2.5 pl-10 pr-10 text-xs font-medium text-white transition hover:border-teal-400/40 focus:border-teal-400 focus:outline-none disabled:opacity-50",
        },
        completedDocs.length === 0
          ? createElement(
              "option",
              { value: "", disabled: true },
              isLoading ? "Loading documents..." : "No indexed documents found",
            )
          : completedDocs.map((doc) =>
              createElement(
                "option",
                {
                  key: doc.id,
                  value: doc.id,
                  className: "bg-[#071512] text-white",
                },
                doc.company_name
                  ? `${doc.company_name} — ${doc.filename}`
                  : doc.filename,
              ),
            ),
      ),
      createElement(ChevronDown, {
        size: 15,
        className:
          "pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400",
      }),
    ),
    createElement(
      "button",
      {
        type: "button",
        onClick: onRefresh,
        disabled: isLoading,
        title: "Refresh documents",
        className:
          "flex size-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-slate-400 transition hover:bg-white/10 hover:text-white disabled:opacity-50",
      },
      createElement(RefreshCw, {
        size: 14,
        className: isLoading ? "animate-spin text-teal-400" : "",
      }),
    ),
  );
}
