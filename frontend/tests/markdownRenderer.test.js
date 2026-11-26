import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToString } from "react-dom/server";

import MarkdownRenderer from "../src/components/MarkdownRenderer.js";

test("MarkdownRenderer renders GFM financial tables as HTML table elements instead of raw pipes", () => {
  const tableMarkdown = `Verified table financial analysis (normalized amounts in base currency units):
Example Industries (annual, consolidated, reported):

| Financial Metric | FY2023 | FY2024 | FY2025 | Citations |
| :--- | ---: | ---: | ---: | :--- |
| Revenue | 820,000.00 USD | 950,000.00 USD | 1,200,000.00 USD | [Source 2] |
| Cost of Sales | 560,000.00 USD | 630,000.00 USD | 780,000.00 USD | [Source 2] |
| Gross Profit | 260,000.00 USD | 320,000.00 USD | 420,000.00 USD | [Source 2] |`;

  const html = renderToString(
    createElement(MarkdownRenderer, { content: tableMarkdown }),
  );

  // Check required HTML table elements
  assert.ok(html.includes("<table"), "Must produce an HTML <table> element");
  assert.ok(html.includes("<thead"), "Must produce an HTML <thead> element");
  assert.ok(html.includes("<tbody"), "Must produce an HTML <tbody> element");
  assert.ok(html.includes("<tr"), "Must produce HTML <tr> row elements");
  assert.ok(html.includes("<th"), "Must produce HTML <th> header elements");
  assert.ok(html.includes("<td"), "Must produce HTML <td> cell elements");

  // Check that raw markdown syntax is NOT present as visible text
  assert.ok(
    !html.includes("| Financial Metric |"),
    "Raw table pipe header syntax must not be visible",
  );
  assert.ok(
    !html.includes("| :--- |"),
    "Raw markdown delimiter rows must not be visible",
  );

  // Check financial alignment styling
  assert.ok(
    html.includes("text-right"),
    "Right-aligned numeric columns must contain text-right alignment class",
  );
  assert.ok(
    html.includes("overflow-x-auto"),
    "Table must be wrapped in a horizontally scrollable container",
  );

  // Check citation preservation
  assert.ok(
    html.includes("[Source 2]"),
    "Source citations must be preserved inside rendered tables",
  );
});

test("MarkdownRenderer preserves multi-line calculation formatting and citations", () => {
  const calculationMarkdown = `Verified table financial analysis (normalized amounts in base currency units):
Example Industries, FY2024, annual, consolidated, reported: revenue = 950,000.00 USD [Source 2].
Example Industries, FY2025, annual, consolidated, reported: revenue = 1,200,000.00 USD [Source 2].
Revenue growth FY2024 to FY2025: (1200000 - 950000) / 950000 * 100 = 26.32% [Source 2].`;

  const html = renderToString(
    createElement(MarkdownRenderer, { content: calculationMarkdown }),
  );

  assert.ok(html.includes("26.32%"), "Calculation percentage must be present");
  assert.ok(html.includes("[Source 2]"), "Citation must be preserved");
  assert.ok(
    html.includes("<br/>"),
    "Consecutive calculation lines must be separated by line breaks",
  );
});

test("MarkdownRenderer preserves normal chatbot responses, paragraphs, lists and bold text", () => {
  const normalMarkdown = `Northstar Components manufactured industrial electrical components in FY2024 [Source 1]. Its sales model was **distributor-focused** [Source 1].

Key advantages include:
- Scalable distribution
- Strong partner network`;

  const html = renderToString(
    createElement(MarkdownRenderer, { content: normalMarkdown }),
  );

  assert.ok(html.includes("<p"), "Paragraph elements must be produced");
  assert.ok(
    html.includes("<strong") && html.includes("distributor-focused"),
    "Bold text must be rendered in <strong>",
  );
  assert.ok(html.includes("<ul"), "Unordered list element must be produced");
  assert.ok(html.includes("<li"), "List item elements must be produced");
  assert.ok(
    html.includes("[Source 1]"),
    "Source citations must be preserved in prose",
  );
});

test("MarkdownRenderer safely escapes unencoded HTML and ignores dangerous scripts", () => {
  const maliciousInput = `Here is an answer <script>alert("xss")</script> with [Source 1].`;

  const html = renderToString(
    createElement(MarkdownRenderer, { content: maliciousInput }),
  );

  assert.ok(
    !html.includes("<script>"),
    "Script tags must not be rendered into the DOM",
  );
  assert.ok(html.includes("[Source 1]"), "Citations must still be preserved");
});

test("MarkdownRenderer handles empty or null input gracefully", () => {
  assert.equal(
    renderToString(createElement(MarkdownRenderer, { content: "" })),
    "",
  );
  assert.equal(
    renderToString(createElement(MarkdownRenderer, { content: null })),
    "",
  );
});
