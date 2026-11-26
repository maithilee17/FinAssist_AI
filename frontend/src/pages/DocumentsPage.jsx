import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Database,
  FileText,
  LoaderCircle,
  LogOut,
  RefreshCw,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";

import useAuth from "../context/useAuth";
import api, { getApiError } from "../lib/api";
import {
  describeDocumentProcessingResult,
  documentStatusLabels,
} from "../lib/documentStatus";

const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_SIZE_MB ?? 50);
const PROCESSING_TIMEOUT_MS = Number(
  import.meta.env.VITE_PROCESSING_TIMEOUT_MS ?? 600000,
);

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 1) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

const statusStyles = {
  uploaded: "border-sky-400/20 bg-sky-400/10 text-sky-200",
  processing: "border-amber-400/20 bg-amber-400/10 text-amber-200",
  indexing: "border-violet-400/20 bg-violet-400/10 text-violet-200",
  completed: "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
  failed: "border-rose-400/20 bg-rose-400/10 text-rose-200",
};

function validateFile(file) {
  if (!file) return "Choose a PDF to upload.";
  if (!file.name.toLowerCase().endsWith(".pdf"))
    return "Only files with a .pdf extension are accepted.";
  if (
    file.type &&
    !["application/pdf", "application/x-pdf"].includes(file.type)
  )
    return "The selected file does not have a PDF MIME type.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024)
    return `PDFs must be ${MAX_UPLOAD_MB} MB or smaller.`;
  if (file.size === 0) return "The selected file is empty.";
  return "";
}

export default function DocumentsPage() {
  const { user, logout } = useAuth();
  const inputRef = useRef(null);
  const [documents, setDocuments] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [notice, setNotice] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const loadDocuments = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const { data } = await api.get("/documents", {
        params: { page: 1, page_size: 100 },
      });
      setDocuments(data.items);
    } catch (requestError) {
      setError(getApiError(requestError, "Unable to load your documents."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!deleteTarget) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && busyId !== deleteTarget.id) setDeleteTarget(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [busyId, deleteTarget]);

  useEffect(() => {
    let active = true;
    api
      .get("/documents", { params: { page: 1, page_size: 100 } })
      .then(({ data }) => {
        if (active) setDocuments(data.items);
      })
      .catch((requestError) => {
        if (active)
          setError(getApiError(requestError, "Unable to load your documents."));
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function uploadFile(file) {
    const validationError = validateFile(file);
    setUploadError(validationError);
    setNotice("");
    if (validationError) return;

    const formData = new FormData();
    formData.append("file", file);
    setUploadProgress(0);
    try {
      const { data } = await api.post("/documents/upload", formData, {
        timeout: PROCESSING_TIMEOUT_MS,
        onUploadProgress(event) {
          if (event.total)
            setUploadProgress(Math.round((event.loaded / event.total) * 100));
        },
      });
      const outcome = describeDocumentProcessingResult(data);
      if (outcome.level === "error") setUploadError(outcome.message);
      else setNotice(outcome.message);
      await loadDocuments();
    } catch (requestError) {
      setUploadError(
        getApiError(requestError, "The PDF could not be uploaded."),
      );
    } finally {
      setUploadProgress(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function retryDocument(document) {
    setBusyId(document.id);
    setError("");
    setNotice("");
    try {
      const { data } = await api.post(`/documents/${document.id}/retry`, null, {
        timeout: PROCESSING_TIMEOUT_MS,
      });
      if (data.processing_status === "completed") {
        setNotice(`${data.filename} was indexed successfully.`);
      } else if (data.processing_status === "failed") {
        setError(
          data.processing_error ??
            "Indexing failed again. Review the document error before retrying.",
        );
      }
      await loadDocuments();
    } catch (requestError) {
      setError(getApiError(requestError, "The document could not be retried."));
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setBusyId(deleteTarget.id);
    setError("");
    try {
      await api.delete(`/documents/${deleteTarget.id}`);
      setDeleteTarget(null);
      await loadDocuments();
    } catch (requestError) {
      setError(getApiError(requestError, "The document could not be deleted."));
    } finally {
      setBusyId(null);
    }
  }

  function handleDrop(event) {
    event.preventDefault();
    setIsDragging(false);
    uploadFile(event.dataTransfer.files?.[0]);
  }

  return (
    <main className="min-h-screen bg-[#071512] text-slate-100">
      <header className="border-b border-white/10 bg-[#071512]/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5 lg:px-8">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-teal-400 text-[#061512]">
              <Database size={20} />
            </span>
            <div>
              <p className="font-semibold">FinAssist AI</p>
              <p className="text-xs text-slate-500">Private document library</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link
              to="/dashboard"
              className="hidden text-sm text-slate-400 hover:text-white sm:inline"
            >
              Dashboard
            </Link>
            <Link
              to="/documents"
              className="hidden text-sm font-semibold text-teal-300 sm:inline"
            >
              Library
            </Link>
            <Link
              to="/chat"
              className="hidden text-sm text-slate-400 hover:text-white sm:inline"
            >
              AI assistant
            </Link>
            <span className="hidden text-sm text-slate-400 md:inline">
              {user.full_name}
            </span>
            <button
              onClick={logout}
              className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-300 hover:bg-white/10"
            >
              <LogOut size={16} /> Logout
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-6 py-10 lg:px-8">
        <Link
          to="/dashboard"
          className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white"
        >
          <ArrowLeft size={16} /> Dashboard
        </Link>
        <div className="mt-6">
          <p className="text-sm font-medium text-teal-300">
            Document management
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.035em]">
            Financial document library
          </h1>
          <p className="mt-3 max-w-2xl text-slate-400">
            Upload private PDFs for page-aware extraction, chunking, and private
            semantic indexing.
          </p>
        </div>

        <section
          aria-busy={uploadProgress !== null}
          aria-describedby="upload-requirements"
          onDragEnter={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget))
              setIsDragging(false);
          }}
          onDrop={handleDrop}
          className={`mt-9 rounded-2xl border-2 border-dashed p-8 text-center transition ${isDragging ? "border-teal-300 bg-teal-300/10" : "border-white/15 bg-white/[0.03]"}`}
        >
          <UploadCloud className="mx-auto text-teal-300" size={32} />
          <h2 className="mt-4 font-semibold">Drop a financial PDF here</h2>
          <p id="upload-requirements" className="mt-2 text-sm text-slate-400">
            PDF only · Maximum {MAX_UPLOAD_MB} MB · Encrypted files are not
            supported
          </p>
          <input
            ref={inputRef}
            className="sr-only"
            type="file"
            accept="application/pdf,.pdf"
            onChange={(event) => uploadFile(event.target.files?.[0])}
          />
          <button
            disabled={uploadProgress !== null}
            onClick={() => inputRef.current?.click()}
            className="mt-5 rounded-xl bg-teal-400 px-5 py-2.5 text-sm font-semibold text-[#061512] hover:bg-teal-300 disabled:opacity-60"
          >
            Browse files
          </button>
          {uploadProgress !== null && (
            <div
              role="progressbar"
              aria-label="PDF upload and processing progress"
              aria-valuemin="0"
              aria-valuemax="100"
              aria-valuenow={uploadProgress}
              className="mx-auto mt-5 max-w-md"
            >
              <div className="mb-2 flex justify-between text-xs text-slate-400">
                <span>
                  {uploadProgress < 100
                    ? "Uploading…"
                    : "Extracting, embedding, and indexing…"}
                </span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-teal-400 transition-all"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          )}
          {uploadError && (
            <div
              role="alert"
              className="mx-auto mt-5 flex max-w-lg items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-left text-sm text-rose-200"
            >
              <AlertCircle className="mt-0.5 shrink-0" size={16} />{" "}
              {uploadError}
            </div>
          )}
          {notice && (
            <div role="status" aria-live="polite" className="mx-auto mt-5 flex max-w-lg items-start gap-2 rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-left text-sm text-emerald-200">
              <CheckCircle2 className="mt-0.5 shrink-0" size={16} /> {notice}
            </div>
          )}
        </section>

        <section className="mt-10">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold">Your documents</h2>
              <p className="mt-1 text-sm text-slate-500">
                {documents.length} document{documents.length === 1 ? "" : "s"}
              </p>
            </div>
            <button
              onClick={loadDocuments}
              disabled={isLoading}
              className="rounded-lg border border-white/10 p-2 text-slate-400 hover:bg-white/5 hover:text-white"
              aria-label="Refresh documents"
            >
              <RefreshCw className={isLoading ? "animate-spin" : ""} size={17} />
            </button>
          </div>
          {error && (
            <div
              role="alert"
              className="mt-5 rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200"
            >
              {error}
            </div>
          )}

          {isLoading ? (
            <div className="mt-8 flex items-center gap-3 text-sm text-slate-400">
              <LoaderCircle className="animate-spin" size={18} /> Loading
              documents…
            </div>
          ) : documents.length === 0 ? (
            <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.025] px-6 py-14 text-center">
              <FileText className="mx-auto text-slate-600" size={36} />
              <h3 className="mt-4 font-medium">No documents uploaded</h3>
              <p className="mt-2 text-sm text-slate-500">
                Your private financial reports will appear here after upload.
              </p>
            </div>
          ) : (
            <div className="mt-6 overflow-hidden rounded-2xl border border-white/10">
              {documents.map((document) => (
                <article
                  key={document.id}
                  className="flex flex-col gap-4 border-b border-white/10 bg-white/[0.025] p-5 last:border-b-0 md:flex-row md:items-center"
                >
                  <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-white/5 text-teal-300">
                    <FileText size={21} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-white" title={document.filename}>
                      {document.filename}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatFileSize(document.file_size)} ·{" "}
                      {document.page_count} page
                      {document.page_count === 1 ? "" : "s"} ·{" "}
                      {document.indexed_chunk_count} indexed chunks ·{" "}
                      {formatDate(document.upload_date)}
                    </p>
                    {document.processing_error && (
                      <p className="mt-2 text-xs text-rose-300">
                        {document.processing_error}
                      </p>
                    )}
                  </div>
                  <span
                    aria-label={`Processing status: ${document.processing_status}`}
                    className={`inline-flex self-start rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${statusStyles[document.processing_status] ?? statusStyles.uploaded}`}
                  >
                    {document.processing_status === "completed" && (
                      <CheckCircle2 className="mr-1" size={13} />
                    )}
                    {documentStatusLabels[document.processing_status] ??
                      document.processing_status}
                  </span>
                  <div className="flex gap-2">
                    {document.processing_status === "failed" && (
                      <button
                        disabled={busyId === document.id}
                        onClick={() => retryDocument(document)}
                        className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50"
                      >
                        <RefreshCw size={14} /> Retry
                      </button>
                    )}
                    <button
                      disabled={busyId === document.id}
                      onClick={() => setDeleteTarget(document)}
                      className="rounded-lg border border-rose-400/15 p-2 text-rose-300 hover:bg-rose-400/10 disabled:opacity-50"
                      aria-label={`Delete ${document.filename}`}
                    >
                      {busyId === document.id ? (
                        <LoaderCircle className="animate-spin" size={16} />
                      ) : (
                        <Trash2 size={16} />
                      )}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      {deleteTarget && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 px-5 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-title"
            className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0b211c] p-6 shadow-2xl"
          >
            <div className="flex items-start justify-between">
              <div>
                <p id="delete-title" className="font-semibold">
                  Delete document?
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  This permanently removes{" "}
                  <span className="break-all text-slate-200">
                    {deleteTarget.filename}
                  </span>
                  , its extracted pages, and prepared chunks.
                </p>
              </div>
              <button
                onClick={() => setDeleteTarget(null)}
                aria-label="Close delete confirmation"
                className="text-slate-500 hover:text-white"
              >
                <X size={19} />
              </button>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                autoFocus
                onClick={() => setDeleteTarget(null)}
                disabled={busyId === deleteTarget.id}
                className="rounded-xl border border-white/10 px-4 py-2 text-sm text-slate-300 hover:bg-white/5"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={busyId === deleteTarget.id}
                className="rounded-xl bg-rose-500 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-400 disabled:opacity-60"
              >
                {busyId === deleteTarget.id ? "Deleting…" : "Delete permanently"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
