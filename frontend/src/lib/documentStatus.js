export const documentStatusLabels = {
  uploaded: "Uploaded",
  processing: "Processing",
  indexing: "Indexing",
  completed: "Indexed",
  failed: "Failed",
};

export function describeDocumentProcessingResult(document) {
  if (document.processing_status === "completed") {
    return {
      level: "success",
      message: `${document.filename} was uploaded and indexed successfully.`,
    };
  }
  if (document.processing_status === "failed") {
    return {
      level: "error",
      message:
        document.processing_error ??
        `${document.filename} was uploaded, but indexing failed. You can retry after resolving the reported issue.`,
    };
  }
  return {
    level: "info",
    message: `${document.filename} was uploaded and is ${document.processing_status}. Refresh to see its latest status.`,
  };
}
