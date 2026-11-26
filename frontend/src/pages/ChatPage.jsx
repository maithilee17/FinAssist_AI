import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  ChevronDown,
  Database,
  FileText,
  History,
  LoaderCircle,
  LogOut,
  MessageSquarePlus,
  Send,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";

import useAuth from "../context/useAuth";
import api, { getApiError } from "../lib/api";
import MarkdownRenderer from "../components/MarkdownRenderer";

function SourceCard({ source }) {
  const pages = source.page_numbers?.length ? source.page_numbers.join(", ") : "Unavailable";
  return (
    <details className="group rounded-xl border border-teal-300/15 bg-teal-300/[0.045] p-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs">
        <span className="flex min-w-0 items-center gap-2 text-teal-100">
          <FileText size={14} className="shrink-0 text-teal-300" />
          <span className="truncate" title={source.filename}>{source.filename}</span>
          <span className="shrink-0 text-slate-500">
            {source.page_numbers?.length === 1 ? "Page" : "Pages"} {pages}
          </span>
        </span>
        <ChevronDown
          size={14}
          className="shrink-0 text-slate-500 transition group-open:rotate-180"
        />
      </summary>
      <p className="mt-3 border-t border-white/5 pt-3 text-xs leading-5 text-slate-400">
        {source.excerpt}
      </p>
    </details>
  );
}

function MessageBubble({ message }) {
  const assistant = message.role === "assistant";
  const retrieval = message.retrieval;
  const verification = message.verification;
  const confidence = message.confidence;
  const strategyLabel = retrieval?.selected_strategy
    ? retrieval.selected_strategy[0].toUpperCase() +
      retrieval.selected_strategy.slice(1)
    : null;
  return (
    <article aria-label={assistant ? "FinAssist answer" : "Your question"} className={`flex gap-3 ${assistant ? "" : "justify-end"}`}>
      {assistant && (
        <span className="mt-1 grid size-8 shrink-0 place-items-center rounded-lg bg-teal-400 text-[#061512]">
          <Bot size={16} />
        </span>
      )}
      <div
        className={`max-w-3xl rounded-2xl px-4 py-3 ${assistant ? "border border-white/10 bg-white/[0.04]" : "bg-teal-400 text-[#061512]"}`}
      >
        {assistant && (
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-teal-300">
            {verification?.missing_aspects?.some((m) => m.includes("clarification"))
              ? "Clarification requested"
              : verification?.overall_status === "abstained"
                ? "Answer withheld"
                : "Answer"}
          </p>
        )}
        {assistant ? (
          <div className="text-sm leading-6 text-slate-200">
            <MarkdownRenderer content={message.message} />
          </div>
        ) : (
          <p className="break-words whitespace-pre-wrap text-sm font-medium leading-6">
            {message.message}
          </p>
        )}
        {assistant && retrieval && (
          <div className="mt-4 rounded-xl border border-sky-300/15 bg-sky-300/[0.04] p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-sky-300/10 px-2.5 py-1 font-medium text-sky-200">
                <SlidersHorizontal size={12} /> {strategyLabel} retrieval
              </span>
              <span className="text-slate-500">
                {retrieval.retrieved_chunks_count} passages
              </span>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-400">
              {retrieval.selection_reason}
            </p>
            <details className="group mt-2 text-[11px] text-slate-500">
              <summary className="cursor-pointer list-none text-sky-300/70 hover:text-sky-200">
                Technical details
              </summary>
              <div className="mt-2 grid gap-1 border-t border-white/5 pt-2 sm:grid-cols-2">
                <span>Query type: {retrieval.query_analysis?.query_type}</span>
                <span>Latency: {retrieval.retrieval_time_ms} ms</span>
                <span>Keyword results: {retrieval.keyword_result_count}</span>
                <span>Semantic results: {retrieval.semantic_result_count}</span>
                <span>Fused results: {retrieval.selected_strategy === 'hybrid' ? retrieval.fusion_result_count : 'Not executed'}</span>
              </div>
            </details>
          </div>
        )}
        {assistant && verification && (
          <div
            className={`mt-3 rounded-xl border p-3 ${verification.overall_status === "verified" ? "border-emerald-300/20 bg-emerald-300/[0.05]" : verification.overall_status === "abstained" ? "border-amber-300/20 bg-amber-300/[0.05]" : "border-sky-300/20 bg-sky-300/[0.05]"}`}
          >
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span
                className={`inline-flex items-center gap-1.5 font-medium ${verification.overall_status === "verified" ? "text-emerald-200" : verification.overall_status === "abstained" ? "text-amber-200" : "text-sky-200"}`}
              >
                {verification.overall_status === "verified" ? (
                  <ShieldCheck size={14} />
                ) : (
                  <ShieldAlert size={14} />
                )}
                {verification.overall_status === "verified"
                  ? "Verified"
                  : verification.overall_status === "partially_supported"
                    ? "Partially supported"
                    : verification.overall_status === "abstained"
                      ? "Abstained"
                      : "Unsupported"}
              </span>
              <span className="text-slate-500">
                {verification.evidence_status} evidence
              </span>
              {confidence && (
                <span className="text-slate-500">
                  · {confidence.level} evidence confidence
                </span>
              )}
            </div>
            <details className="group mt-2 text-[11px] text-slate-500">
              <summary className="cursor-pointer list-none text-slate-400 hover:text-slate-200">
                Verification details
              </summary>
              <div className="mt-2 space-y-2 border-t border-white/5 pt-2">
                <div className="grid gap-1 sm:grid-cols-2">
                  <span>Claims checked: {verification.claims_checked}</span>
                  <span>Supported claims: {verification.supported_claims}</span>
                  <span>
                    Supporting citations: {verification.supporting_citations}
                  </span>
                  <span>
                    Retrieval attempts: {verification.retrieval_attempts}
                  </span>
                </div>
                {verification.missing_aspects?.length > 0 && (
                  <p className="text-amber-200/70">
                    Missing: {verification.missing_aspects.join(", ")}
                  </p>
                )}
                {confidence && (
                  <p>
                    Evidence score: {Number(confidence.score).toFixed(2)}/1.00. {" "}
                    {confidence.explanation}
                  </p>
                )}
              </div>
            </details>
          </div>
        )}
        {assistant && message.sources?.length > 0 && (
          <div className="mt-4 space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-slate-500">
              Cited evidence
            </p>
            {message.sources.map((source) => (
              <SourceCard key={source.chunk_id} source={source} />
            ))}
          </div>
        )}
        {assistant && message.model_name && (
          <p className="mt-3 text-[10px] text-slate-600">
            {message.model_name} · {message.retrieved_chunks_count ?? 0}{" "}
            retrieved chunks
          </p>
        )}
      </div>
      {!assistant && (
        <span className="mt-1 grid size-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/5">
          <UserRound size={15} />
        </span>
      )}
    </article>
  );
}

export default function ChatPage() {
  const { user, logout } = useAuth();
  const endRef = useRef(null);
  const [documents, setDocuments] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [selectedDocuments, setSelectedDocuments] = useState([]);
  const [question, setQuestion] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deletingSessionId, setDeletingSessionId] = useState(null);

  const indexedDocuments = useMemo(
    () =>
      documents.filter(
        (document) => document.processing_status === "completed",
      ),
    [documents],
  );

  async function refreshSessions() {
    const { data } = await api.get("/chat/sessions", {
      params: { page: 1, page_size: 100 },
    });
    setSessions(data.items);
  }

  useEffect(() => {
    let active = true;
    Promise.all([
      api.get("/documents", { params: { page: 1, page_size: 100 } }),
      api.get("/chat/sessions", { params: { page: 1, page_size: 100 } }),
    ])
      .then(([documentResponse, sessionResponse]) => {
        if (active) {
          setDocuments(documentResponse.data.items);
          setSessions(sessionResponse.data.items);
        }
      })
      .catch((requestError) => {
        if (active)
          setError(getApiError(requestError, "Unable to load the assistant."));
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  useEffect(() => {
    if (!deleteTarget) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape" && deletingSessionId !== deleteTarget.id) setDeleteTarget(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [deleteTarget, deletingSessionId]);

  async function openSession(sessionId) {
    setError("");
    try {
      const { data } = await api.get(`/chat/sessions/${sessionId}`);
      setActiveSessionId(sessionId);
      setMessages(data.messages);
    } catch (requestError) {
      setError(getApiError(requestError, "Unable to load this conversation."));
    }
  }

  function newConversation() {
    setActiveSessionId(null);
    setMessages([]);
    setQuestion("");
    setError("");
  }

  function toggleDocument(documentId) {
    setSelectedDocuments((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    );
  }

  async function sendQuestion(event) {
    event.preventDefault();
    const value = question.trim();
    if (!value || isSending) return;
    setMessages((current) => [
      ...current,
      { id: `local-${Date.now()}`, role: "user", message: value, sources: [] },
    ]);
    setQuestion("");
    setError("");
    setIsSending(true);
    try {
      const { data } = await api.post(
        "/chat/ask",
        {
          question: value,
          document_ids: selectedDocuments,
          ...(activeSessionId ? { session_id: activeSessionId } : {}),
        },
        { timeout: 360000 },
      );
      setActiveSessionId(data.session_id);
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          message: data.answer,
          sources: data.sources,
          model_name: data.model_name,
          retrieved_chunks_count: data.retrieved_chunks_count,
          retrieval: data.retrieval,
          verification: data.verification,
          confidence: data.confidence,
        },
      ]);
      await refreshSessions();
    } catch (requestError) {
      setError(
        getApiError(requestError, "FinAssist could not answer this question."),
      );
    } finally {
      setIsSending(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeletingSessionId(deleteTarget.id);
    try {
      await api.delete(`/chat/sessions/${deleteTarget.id}`);
      if (activeSessionId === deleteTarget.id) newConversation();
      setDeleteTarget(null);
      await refreshSessions();
    } catch (requestError) {
      setError(
        getApiError(requestError, "The conversation could not be deleted."),
      );
    } finally {
      setDeletingSessionId(null);
    }
  }

  return (
    <main className="min-h-screen bg-[#071512] text-slate-100">
      <header className="border-b border-white/10 bg-[#071512]/95">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-teal-400 text-[#061512]">
              <Database size={20} />
            </span>
            <div>
              <p className="font-semibold">FinAssist AI</p>
              <p className="text-xs text-slate-500">
                Grounded financial assistant
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <Link
              to="/dashboard"
              className="hidden text-sm text-slate-400 hover:text-white sm:inline"
            >
              Dashboard
            </Link>
            <Link
              to="/documents"
              className="hidden text-sm text-slate-400 hover:text-white sm:inline"
            >
              Library
            </Link>
            <Link
              to="/chat"
              className="hidden text-sm font-semibold text-teal-300 sm:inline"
            >
              AI assistant
            </Link>
            <span className="hidden text-sm text-slate-500 md:inline">
              {user.full_name}
            </span>
            <button
              onClick={logout}
              className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/5"
            >
              <LogOut size={16} /> Logout
            </button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-[1500px] lg:grid-cols-[280px_minmax(0,1fr)_280px]">
        <aside className="border-b border-white/10 p-4 lg:min-h-[calc(100vh-73px)] lg:border-b-0 lg:border-r">
          <button
            onClick={newConversation}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-teal-400 px-4 py-3 text-sm font-semibold text-[#061512] hover:bg-teal-300"
          >
            <MessageSquarePlus size={17} /> New conversation
          </button>
          <div className="mt-6 flex items-center gap-2 px-1 text-xs font-medium uppercase tracking-[0.16em] text-slate-600">
            <History size={14} /> History
          </div>
          <div className="mt-3 max-h-52 space-y-1 overflow-y-auto lg:max-h-[calc(100vh-190px)]">
            {sessions.length === 0 ? (
              <p className="px-2 py-6 text-sm text-slate-600">
                No conversations yet.
              </p>
            ) : (
              sessions.map((session) => (
                <div
                  key={session.id}
                  className={`group flex items-center rounded-xl ${activeSessionId === session.id ? "bg-white/[0.08]" : "hover:bg-white/[0.04]"}`}
                >
                  <button
                    onClick={() => openSession(session.id)}
                    className="min-w-0 flex-1 px-3 py-3 text-left"
                  >
                    <p className="truncate text-sm text-slate-300">
                      {session.title}
                    </p>
                    <p className="mt-1 text-[10px] text-slate-600">
                      {session.message_count} messages
                    </p>
                  </button>
                  <button
                    onClick={() => setDeleteTarget(session)}
                    aria-label={`Delete ${session.title}`}
                    className="mr-2 p-1.5 text-slate-700 opacity-0 hover:text-rose-300 focus:opacity-100 group-hover:opacity-100"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))
            )}
          </div>
        </aside>

        <section className="flex min-h-[68vh] min-w-0 flex-col lg:h-[calc(100vh-73px)]">
          <div className="flex-1 overflow-y-auto px-5 py-8 lg:px-10">
            {isLoading ? (
              <div className="flex h-full items-center justify-center gap-3 text-sm text-slate-500">
                <LoaderCircle className="animate-spin" size={18} /> Loading
                assistant…
              </div>
            ) : messages.length === 0 ? (
              <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center text-center">
                <span className="grid size-14 place-items-center rounded-2xl border border-teal-300/20 bg-teal-300/10 text-teal-300">
                  <Bot size={27} />
                </span>
                <h1 className="mt-5 text-2xl font-semibold">
                  Ask your financial documents
                </h1>
                <p className="mt-3 text-sm leading-6 text-slate-500">
                  Each question is routed to keyword, semantic, or hybrid
                  retrieval. Source excerpts and original page numbers appear
                  beneath each response.
                </p>
                {indexedDocuments.length === 0 && (
                  <Link
                    to="/documents"
                    className="mt-5 rounded-xl bg-teal-400 px-4 py-2.5 text-sm font-semibold text-[#061512]"
                  >
                    Upload an indexed PDF
                  </Link>
                )}
              </div>
            ) : (
              <div role="log" aria-live="polite" aria-relevant="additions" className="mx-auto max-w-4xl space-y-6">
                {messages.map((message) => (
                  <MessageBubble key={message.id} message={message} />
                ))}
                {isSending && (
                  <div role="status" className="flex items-center gap-3 text-sm text-slate-500">
                    <LoaderCircle className="animate-spin" size={17} />{" "}
                    Retrieving evidence and generating a grounded answer…
                  </div>
                )}
                <div ref={endRef} />
              </div>
            )}
          </div>
          <div className="border-t border-white/10 bg-[#071512] px-5 py-4 lg:px-10">
            {error && (
              <div
                role="alert"
                className="mx-auto mb-3 max-w-4xl rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200"
              >
                {error}
              </div>
            )}
            <form
              onSubmit={sendQuestion}
              className="mx-auto flex max-w-4xl items-end gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-2 focus-within:border-teal-300/40"
            >
              <textarea
                aria-label="Ask a question about your financial documents"
                aria-describedby="question-help"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    sendQuestion(event);
                  }
                }}
                rows={1}
                maxLength={2000}
                disabled={isSending || indexedDocuments.length === 0}
                placeholder={
                  indexedDocuments.length
                    ? "Ask about revenue, profit, risks, or another document fact…"
                    : "Upload and index a PDF first"
                }
                className="max-h-32 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-slate-600 disabled:cursor-not-allowed"
              />
              <button
                type="submit"
                disabled={
                  isSending || !question.trim() || indexedDocuments.length === 0
                }
                className="grid size-11 shrink-0 place-items-center rounded-xl bg-teal-400 text-[#061512] hover:bg-teal-300 disabled:opacity-40"
                aria-label="Send question"
              >
                {isSending ? (
                  <LoaderCircle className="animate-spin" size={18} />
                ) : (
                  <Send size={18} />
                )}
              </button>
            </form>
            <p id="question-help" className="mx-auto mt-2 max-w-4xl text-xs text-slate-600">
              Enter sends · Shift+Enter adds a new line · Answers may abstain when evidence is insufficient.
            </p>
          </div>
        </section>

        <aside className="border-t border-white/10 p-5 lg:min-h-[calc(100vh-73px)] lg:border-l lg:border-t-0">
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-slate-600">
            Search scope
          </p>
          <button
            onClick={() => setSelectedDocuments([])}
            aria-pressed={selectedDocuments.length === 0}
            className={`mt-4 flex w-full items-center gap-3 rounded-xl border p-3 text-left text-sm ${selectedDocuments.length === 0 ? "border-teal-300/30 bg-teal-300/10 text-teal-100" : "border-white/10 text-slate-400"}`}
          >
            <Database size={16} /> All indexed documents
          </button>
          <div className="mt-3 space-y-2">
            {indexedDocuments.map((document) => {
              const selected = selectedDocuments.includes(document.id);
              return (
                <label
                  key={document.id}
                  className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${selected ? "border-teal-300/30 bg-teal-300/10" : "border-white/10 bg-white/[0.02]"}`}
                >
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => toggleDocument(document.id)}
                    className="mt-0.5 accent-teal-400"
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-slate-300">
                      {document.filename}
                    </span>
                    <span className="mt-1 block text-[10px] text-slate-600">
                      {document.page_count} pages ·{" "}
                      {document.indexed_chunk_count} chunks
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
          <p className="mt-5 text-xs leading-5 text-slate-600">
            An empty selection searches every completed document. Document
            ownership is enforced again by the backend.
          </p>
        </aside>
      </div>

      {deleteTarget && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 px-5">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-chat-title"
            className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0b211c] p-6"
          >
            <div className="flex justify-between gap-4">
              <div>
                <p id="delete-chat-title" className="font-semibold">
                  Delete conversation?
                </p>
                <p className="mt-2 text-sm leading-6 text-slate-400">
                  This permanently removes “{deleteTarget.title}” and its saved
                  messages.
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
                disabled={deletingSessionId === deleteTarget.id}
                className="rounded-xl border border-white/10 px-4 py-2 text-sm"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                disabled={deletingSessionId === deleteTarget.id}
                className="rounded-xl bg-rose-500 px-4 py-2 text-sm font-semibold disabled:opacity-60"
              >
                {deletingSessionId === deleteTarget.id ? "Deleting…" : "Delete permanently"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
