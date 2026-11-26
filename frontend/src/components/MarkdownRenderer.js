import { createElement } from "react";
import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";

function cleanProps(props) {
  const rest = { ...props };
  delete rest.node;
  return rest;
}

const components = {
  table: (props) =>
    createElement(
      "div",
      {
        className:
          "my-3 w-full overflow-x-auto rounded-xl border border-white/10 bg-white/[0.02]",
      },
      createElement("table", {
        className:
          "w-full min-w-full divide-y divide-white/10 text-xs text-slate-200",
        ...cleanProps(props),
      }),
    ),
  thead: (props) =>
    createElement("thead", {
      className:
        "bg-white/[0.06] font-semibold tracking-wider text-slate-300 uppercase",
      ...cleanProps(props),
    }),
  tbody: (props) =>
    createElement("tbody", {
      className: "divide-y divide-white/5",
      ...cleanProps(props),
    }),
  tr: (props) =>
    createElement("tr", {
      className: "transition-colors hover:bg-white/[0.03]",
      ...cleanProps(props),
    }),
  th: (props) => {
    const clean = cleanProps(props);
    const textAlign = clean.style?.textAlign || clean.align;
    delete clean.align;
    const alignClass =
      textAlign === "right"
        ? "text-right"
        : textAlign === "center"
          ? "text-center"
          : "text-left";
    return createElement("th", {
      scope: "col",
      className: `px-3.5 py-2.5 font-semibold whitespace-nowrap text-slate-200 ${alignClass}`,
      ...clean,
    });
  },
  td: (props) => {
    const clean = cleanProps(props);
    const textAlign = clean.style?.textAlign || clean.align;
    delete clean.align;
    const alignClass =
      textAlign === "right"
        ? "text-right font-mono"
        : textAlign === "center"
          ? "text-center"
          : "text-left";
    return createElement("td", {
      className: `px-3.5 py-2.5 text-slate-300 ${alignClass}`,
      ...clean,
    });
  },
  p: (props) =>
    createElement("p", {
      className: "mb-2 break-words leading-6 text-slate-200 last:mb-0",
      ...cleanProps(props),
    }),
  ul: (props) =>
    createElement("ul", {
      className: "my-2 ml-4 list-disc space-y-1 text-slate-200",
      ...cleanProps(props),
    }),
  ol: (props) =>
    createElement("ol", {
      className: "my-2 ml-4 list-decimal space-y-1 text-slate-200",
      ...cleanProps(props),
    }),
  li: (props) =>
    createElement("li", {
      className: "leading-6",
      ...cleanProps(props),
    }),
  strong: (props) =>
    createElement("strong", {
      className: "font-semibold text-white",
      ...cleanProps(props),
    }),
  code: (props) =>
    createElement("code", {
      className:
        "rounded bg-white/10 px-1 py-0.5 font-mono text-xs text-teal-300",
      ...cleanProps(props),
    }),
  h1: (props) =>
    createElement("h1", {
      className: "mb-2 text-base font-bold text-white",
      ...cleanProps(props),
    }),
  h2: (props) =>
    createElement("h2", {
      className: "mb-2 text-sm font-bold text-white",
      ...cleanProps(props),
    }),
  h3: (props) =>
    createElement("h3", {
      className:
        "mb-1 text-xs font-semibold tracking-wider text-teal-300 uppercase",
      ...cleanProps(props),
    }),
};

export default function MarkdownRenderer({ content }) {
  if (!content) return null;
  return createElement(
    ReactMarkdown,
    {
      remarkPlugins: [remarkGfm, remarkBreaks],
      components,
    },
    content,
  );
}
