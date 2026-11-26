import assert from "node:assert/strict";
import test from "node:test";

import {
  describeDocumentProcessingResult,
  documentStatusLabels,
} from "../src/lib/documentStatus.js";

test("completed documents are presented as successfully indexed", () => {
  assert.deepEqual(
    describeDocumentProcessingResult({
      filename: "report.pdf",
      processing_status: "completed",
    }),
    {
      level: "success",
      message: "report.pdf was uploaded and indexed successfully.",
    },
  );
  assert.equal(documentStatusLabels.completed, "Indexed");
});

test("failed indexing is never presented as upload success", () => {
  const result = describeDocumentProcessingResult({
    filename: "report.pdf",
    processing_status: "failed",
    processing_error: "Embedding step failed (model_load_failed).",
  });

  assert.equal(result.level, "error");
  assert.match(result.message, /model_load_failed/);
});

test("in-progress documents keep an informational state", () => {
  const result = describeDocumentProcessingResult({
    filename: "report.pdf",
    processing_status: "indexing",
  });

  assert.equal(result.level, "info");
  assert.match(result.message, /indexing/);
});
