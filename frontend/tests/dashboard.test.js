import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToString } from "react-dom/server";

import DocumentSelector from "../src/components/dashboard/DocumentSelector.js";
import MetricCard from "../src/components/dashboard/MetricCard.js";
import PerformanceSummary from "../src/components/dashboard/PerformanceSummary.js";

test("MetricCard renders percentage point ('pp') badge without '% YoY' for margin changes", () => {
  const card = {
    label: "Gross Margin",
    value: 35.0,
    formatted_value: "35.00%",
    period: "FY2025",
    scale: null,
    yoy_change: 1.32,
    yoy_change_formatted: "+1.32 pp",
    yoy_change_unit: "pp",
    source_citation: "Derived (1)",
  };

  const html = renderToString(createElement(MetricCard, { card }));

  assert.ok(html.includes("Gross Margin"), "Must render Gross Margin label");
  assert.ok(html.includes("35.00%"), "Must render 35.00% formatted value");
  assert.ok(html.includes("+1.32 pp"), "Must render percentage points (+1.32 pp)");
  assert.ok(!html.includes("+1.32%"), "Must NOT render as +1.32%");
  assert.ok(!html.includes("pp YoY"), "Must NOT append YoY after pp");
  assert.ok(html.includes("text-emerald-400"), "Must have positive green indicator styling");
});

test("MetricCard renders formatted value, scale, period, citation, and positive YoY badge", () => {
  const card = {
    label: "Revenue",
    value: 1200000.0,
    formatted_value: "$1,200,000.00 USD",
    currency: "USD",
    period: "FY2025",
    scale: "USD · Exact",
    yoy_change: 26.32,
    yoy_change_formatted: "+26.32%",
    source_citation: "Page 1",
  };

  const html = renderToString(createElement(MetricCard, { card }));

  assert.ok(html.includes("Revenue"), "Must render metric title");
  assert.ok(html.includes("$1,200,000.00 USD"), "Must render formatted value");
  assert.ok(html.includes("FY2025"), "Must render fiscal period");
  assert.ok(html.includes("USD · Exact"), "Must render scale info");
  assert.ok(html.includes("+26.32%"), "Must render positive YoY change");
  assert.ok(html.includes("text-emerald-400"), "Must have positive green styling");
  assert.ok(html.includes("Page 1"), "Must render source citation page");
});

test("MetricCard renders negative YoY badge and handles missing YoY gracefully", () => {
  const cardNegative = {
    label: "Net Income",
    value: -50000.0,
    formatted_value: "-$50,000.00 USD",
    currency: "USD",
    period: "FY2024",
    scale: null,
    yoy_change: -15.5,
    yoy_change_formatted: "-15.50%",
    source_citation: null,
  };

  const htmlNeg = renderToString(createElement(MetricCard, { card: cardNegative }));
  assert.ok(htmlNeg.includes("-15.50%"), "Must render negative YoY change");
  assert.ok(htmlNeg.includes("text-rose-400"), "Must have negative rose styling");

  const cardNoYoY = {
    label: "Revenue",
    value: 800000.0,
    formatted_value: "$800,000.00 USD",
    currency: "USD",
    period: "FY2023",
    scale: null,
    yoy_change: null,
    yoy_change_formatted: null,
    source_citation: null,
  };

  const htmlNoYoY = renderToString(createElement(MetricCard, { card: cardNoYoY }));
  assert.ok(htmlNoYoY.includes("Base period"), "Must display Base period when YoY is null");
  assert.ok(!htmlNoYoY.includes("+"), "Must not display plus sign when YoY is null");
});

test("MetricCard renders unavailable state when metric value is null", () => {
  const cardUnavailable = {
    label: "Operating Income",
    value: null,
    formatted_value: "—",
    currency: null,
    period: "FY2025",
    scale: null,
    yoy_change: null,
    yoy_change_formatted: null,
    source_citation: null,
  };

  const htmlUnavail = renderToString(createElement(MetricCard, { card: cardUnavailable }));
  assert.ok(htmlUnavail.includes("Operating Income"), "Must render label");
  assert.ok(htmlUnavail.includes("—"), "Must render em-dash for unavailable value");
  assert.ok(htmlUnavail.includes("Metric unavailable"), "Must indicate metric unavailable");
});

test("PerformanceSummary renders commentary, observations, limitations, and citations", () => {
  const summary = {
    revenue_performance: "Revenue expanded from $950,000.00 USD in FY2024 to $1,200,000.00 USD in FY2025 (+26.32%).",
    profitability: "Gross profit was $420,000.00 USD (35.00% gross margin). Net income was $91,000.00 USD (7.58% net margin).",
    growth: "Multi-year revenue expanded across FY2023, FY2024, and FY2025.",
    key_observations: [
      "Revenue expanded from $950,000.00 USD (FY2024) to $1,200,000.00 USD (FY2025) (+26.32%).",
      "Gross profit reached $420,000.00 USD (35.00% gross margin).",
    ],
    limitations: [
      "All figures derived strictly from reported table data.",
      "Cash flow metrics unavailable in current table.",
    ],
    citations: ["Page 1", "Page 2"],
  };

  const html = renderToString(createElement(PerformanceSummary, { summary }));

  assert.ok(html.includes("Evidence-Grounded AI Performance Summary"), "Must render title");
  assert.ok(html.includes("Zero Hallucination · Table Grounded"), "Must render Table Grounded badge");
  assert.ok(html.includes("Revenue Trajectory"), "Must render revenue trajectory heading");
  assert.ok(html.includes("+26.32%"), "Must render growth percentage");
  assert.ok(html.includes("Profitability &amp; Margins") || html.includes("Profitability & Margins"), "Must render profitability heading");
  assert.ok(html.includes("35.00%"), "Must render gross margin figure");
  assert.ok(html.includes("Key Financial Observations"), "Must render observations section");
  assert.ok(html.includes("Analytical Scope &amp; Limitations") || html.includes("Analytical Scope & Limitations"), "Must render limitations section");
  assert.ok(html.includes("Cash flow metrics unavailable"), "Must render limitation text");
  assert.ok(html.includes("[Source: Page 1]"), "Must render Page 1 citation");
  assert.ok(html.includes("[Source: Page 2]"), "Must render Page 2 citation");
});

test("DocumentSelector renders completed documents and handles empty states", () => {
  const documents = [
    {
      id: "doc-1",
      filename: "three_year.pdf",
      company_name: "Example Industries",
      processing_status: "completed",
    },
    {
      id: "doc-2",
      filename: "scanned_doc.pdf",
      company_name: null,
      processing_status: "completed",
    },
    {
      id: "doc-3",
      filename: "pending.pdf",
      company_name: null,
      processing_status: "processing",
    },
  ];

  const html = renderToString(
    createElement(DocumentSelector, {
      documents,
      selectedId: "doc-1",
      onSelect: () => {},
      isLoading: false,
    }),
  );

  assert.ok(html.includes("Example Industries — three_year.pdf"), "Must render company name and filename");
  assert.ok(html.includes("scanned_doc.pdf"), "Must render doc without company name");
  assert.ok(!html.includes("pending.pdf"), "Must filter out non-completed documents");
  assert.ok(html.includes("value=\"doc-1\""), "Must contain option value doc-1");

  const emptyHtml = renderToString(
    createElement(DocumentSelector, {
      documents: [],
      selectedId: null,
      isLoading: false,
    }),
  );
  assert.ok(emptyHtml.includes("No indexed documents found"), "Must show empty state when no docs");
});
