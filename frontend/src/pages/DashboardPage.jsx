import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  BarChart3,
  Database,
  FileText,
  LoaderCircle,
  LogOut,
  MessageSquareText,
  PlusCircle,
  ShieldCheck,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import DocumentSelector from "../components/dashboard/DocumentSelector";
import MarginChart from "../components/dashboard/MarginChart";
import MetricCard from "../components/dashboard/MetricCard";
import PerformanceSummary from "../components/dashboard/PerformanceSummary";
import ProfitabilityChart from "../components/dashboard/ProfitabilityChart";
import RevenueChart from "../components/dashboard/RevenueChart";
import useAuth from "../context/useAuth";
import api, { getApiError } from "../lib/api";

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState(searchParams.get("doc") || null);
  const [dashboardData, setDashboardData] = useState(null);

  const [isLoadingDocs, setIsLoadingDocs] = useState(true);
  const [isLoadingDashboard, setIsLoadingDashboard] = useState(false);
  const [error, setError] = useState("");

  // Fetch dashboard data
  const loadDashboard = useCallback((docId) => {
    if (!docId) {
      setDashboardData(null);
      return;
    }
    setIsLoadingDashboard(true);
    setError("");
    api
      .get(`/dashboard/${docId}`)
      .then(({ data }) => {
        setDashboardData(data);
      })
      .catch((requestError) => {
        setError(
          getApiError(requestError, "Unable to load financial analytics for this document.")
        );
        setDashboardData(null);
      })
      .finally(() => {
        setIsLoadingDashboard(false);
      });
  }, []);

  // 1. Initial documents load
  useEffect(() => {
    let active = true;
    api
      .get("/documents", { params: { page: 1, page_size: 100 } })
      .then(({ data }) => {
        if (!active) return;
        const items = data.items || [];
        setDocuments(items);

        const completed = items.filter((d) => d.processing_status === "completed");
        if (completed.length > 0) {
          const currentParam = searchParams.get("doc");
          const match = completed.find((d) => d.id === currentParam);
          const targetId = match ? match.id : completed[0].id;
          setSelectedDocId(targetId);
          setSearchParams({ doc: targetId });
          loadDashboard(targetId);
        }
      })
      .catch((requestError) => {
        if (active) setError(getApiError(requestError, "Unable to load your documents library."));
      })
      .finally(() => {
        if (active) setIsLoadingDocs(false);
      });

    return () => {
      active = false;
    };
  }, [searchParams, setSearchParams, loadDashboard]);

  const refreshDocuments = useCallback(() => {
    setIsLoadingDocs(true);
    api
      .get("/documents", { params: { page: 1, page_size: 100 } })
      .then(({ data }) => {
        setDocuments(data.items || []);
      })
      .catch((requestError) => {
        setError(getApiError(requestError, "Unable to refresh documents."));
      })
      .finally(() => {
        setIsLoadingDocs(false);
      });
  }, []);

  const handleDocumentChange = (docId) => {
    setSelectedDocId(docId);
    setSearchParams({ doc: docId });
    loadDashboard(docId);
  };

  const hasFinancialData = dashboardData?.has_financial_data;

  return (
    <main className="min-h-screen bg-[#071512] text-slate-100">
      {/* Top Navigation */}
      <header className="sticky top-0 z-20 border-b border-white/10 bg-[#071512]/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 lg:px-8">
          <div className="flex items-center gap-6">
            <Link to="/dashboard" className="flex items-center gap-3">
              <span className="grid size-9 place-items-center rounded-xl bg-teal-400 text-[#061512]">
                <Database size={18} />
              </span>
              <div>
                <p className="font-semibold text-white">FinAssist AI</p>
                <p className="text-[11px] text-slate-400">Financial Document Intelligence</p>
              </div>
            </Link>

            <nav className="hidden items-center gap-1 md:flex">
              <Link
                to="/dashboard"
                className="rounded-lg bg-white/10 px-3 py-1.5 text-xs font-semibold text-teal-300"
              >
                Dashboard
              </Link>
              <Link
                to="/documents"
                className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-400 transition hover:bg-white/5 hover:text-white"
              >
                Library
              </Link>
              <Link
                to="/chat"
                className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-400 transition hover:bg-white/5 hover:text-white"
              >
                AI Assistant
              </Link>
            </nav>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium">{user.full_name}</p>
              <p className="text-xs text-slate-500">{user.email}</p>
            </div>
            <button
              onClick={logout}
              className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-slate-300 transition hover:bg-white/10 hover:text-white"
            >
              <LogOut size={15} /> Logout
            </button>
          </div>
        </div>
      </header>

      {/* Main Dashboard Container */}
      <div className="mx-auto max-w-7xl px-6 py-8 lg:px-8">
        {/* Page Title & Context Header */}
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-teal-300">
              <BarChart3 size={15} /> Financial Analytics Dashboard
            </div>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-white lg:text-3xl">
              Financial Intelligence Overview
            </h1>
            <p className="mt-1.5 text-sm text-slate-400">
              Deterministic, evidence-grounded analytics across verified fiscal periods
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Link
              to="/documents"
              className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-medium text-slate-300 transition hover:bg-white/10 hover:text-white"
            >
              <PlusCircle size={14} /> Upload New PDF
            </Link>
            <div className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1.5 text-xs text-emerald-200">
              <ShieldCheck size={14} /> Zero LLM Guessing
            </div>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div
            role="alert"
            className="mt-6 flex items-start gap-2.5 rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200"
          >
            <AlertCircle className="mt-0.5 shrink-0" size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* Document Selector */}
        <div className="mt-6">
          <DocumentSelector
            documents={documents}
            selectedId={selectedDocId}
            onSelect={handleDocumentChange}
            isLoading={isLoadingDocs}
            onRefresh={refreshDocuments}
          />
        </div>

        {/* Loading State */}
        {isLoadingDashboard && (
          <div
            data-testid="dashboard-loading"
            className="mt-12 flex flex-col items-center justify-center py-16"
          >
            <LoaderCircle className="size-10 animate-spin text-teal-400" />
            <p className="mt-4 text-sm font-medium text-slate-300">
              Analyzing financial statements and reconstructing metrics...
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Reconciling verified table cells, currencies, and period margins
            </p>
          </div>
        )}

        {/* Empty State / No Documents */}
        {!isLoadingDashboard && documents.filter((d) => d.processing_status === "completed").length === 0 && (
          <div
            data-testid="dashboard-empty-no-docs"
            className="mt-8 rounded-2xl border border-white/10 bg-white/[0.025] p-12 text-center"
          >
            <FileText className="mx-auto size-12 text-slate-600" />
            <h3 className="mt-4 text-base font-semibold text-white">No Indexed Documents Found</h3>
            <p className="mx-auto mt-2 max-w-md text-sm text-slate-400">
              Upload a financial statement PDF (such as a multi-year income statement or balance sheet) to unlock automated KPI cards and trends.
            </p>
            <Link
              to="/documents"
              className="mt-6 inline-flex items-center gap-2 rounded-xl bg-teal-400 px-5 py-2.5 text-sm font-semibold text-[#061512] transition hover:bg-teal-300"
            >
              <PlusCircle size={16} /> Go to Document Library
            </Link>
          </div>
        )}

        {/* Empty State / Document Has No Tabular Financial Data */}
        {!isLoadingDashboard && selectedDocId && !hasFinancialData && dashboardData && (
          <div
            data-testid="dashboard-no-financial-data"
            className="mt-8 rounded-2xl border border-white/10 bg-white/[0.025] p-10 text-center"
          >
            <BarChart3 className="mx-auto size-10 text-slate-600" />
            <h3 className="mt-3 text-base font-semibold text-white">
              No Structured Multi-Period Tables Detected
            </h3>
            <p className="mx-auto mt-2 max-w-lg text-sm text-slate-400">
              {dashboardData.message ||
                "This document does not contain recognizable multi-year financial statements. You can still ask questions about its text in the AI Assistant."}
            </p>
            <div className="mt-6 flex justify-center gap-3">
              <Link
                to="/chat"
                className="inline-flex items-center gap-2 rounded-xl bg-teal-400 px-4 py-2 text-xs font-semibold text-[#061512] transition hover:bg-teal-300"
              >
                <MessageSquareText size={15} /> Open in AI Assistant
              </Link>
              <Link
                to="/documents"
                className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2 text-xs font-semibold text-slate-300 transition hover:bg-white/5 hover:text-white"
              >
                Select Another PDF
              </Link>
            </div>
          </div>
        )}

        {/* Active Dashboard with Financial Data */}
        {!isLoadingDashboard && hasFinancialData && dashboardData && (
          <div data-testid="dashboard-content" className="mt-8 space-y-8">
            {/* Entity & Provenance Info Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/8 bg-white/[0.02] px-5 py-3 text-xs text-slate-300">
              <div className="flex flex-wrap items-center gap-4">
                {dashboardData.company_name && (
                  <span>
                    <strong className="text-white">Entity:</strong> {dashboardData.company_name}
                  </span>
                )}
                <span>
                  <strong className="text-white">Reporting Currency:</strong>{" "}
                  {dashboardData.currency || "USD"}
                </span>
                {dashboardData.scale && (
                  <span>
                    <strong className="text-white">Scale:</strong> in {dashboardData.scale}
                  </span>
                )}
                <span>
                  <strong className="text-white">Periods Covered:</strong>{" "}
                  {dashboardData.available_years.map((y) => `FY${y}`).join(", ")}
                </span>
              </div>

              {dashboardData.warnings?.length > 0 && (
                <span className="flex items-center gap-1.5 text-amber-300" title={dashboardData.warnings.join("; ")}>
                  <AlertCircle size={14} /> Extraction notices present
                </span>
              )}
            </div>

            {/* Feature A: Financial Summary KPI Cards */}
            <section aria-label="Key Financial Indicators">
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                Key Performance Indicators ({dashboardData.kpi_cards[0]?.period || "Latest Period"})
              </h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {dashboardData.kpi_cards.map((card) => (
                  <MetricCard key={card.label} card={card} />
                ))}
              </div>
            </section>

            {/* Feature B: Financial Trend Charts */}
            <section aria-label="Financial Trends">
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                Longitudinal Financial Trends
              </h2>
              <div className="grid gap-6 lg:grid-cols-2">
                <RevenueChart data={dashboardData.revenue_trend} />
                <ProfitabilityChart data={dashboardData.profitability_trend} />
                <MarginChart data={dashboardData.margin_trend} />
              </div>
            </section>

            {/* Feature C: Verified AI Financial Performance Summary */}
            <PerformanceSummary
              summary={dashboardData.summary}
              companyName={dashboardData.company_name}
            />

            {/* Cross-Link Action Footer */}
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-white/[0.025] p-6">
              <div>
                <h4 className="text-sm font-semibold text-white">Ask specific questions about this document</h4>
                <p className="mt-1 text-xs text-slate-400">
                  Dive into individual line items, citations, or cross-document comparisons using grounded AI.
                </p>
              </div>
              <Link
                to={`/chat`}
                className="inline-flex items-center gap-2 rounded-xl bg-teal-400 px-4 py-2 text-xs font-semibold text-[#061512] transition hover:bg-teal-300"
              >
                <MessageSquareText size={15} /> Ask in AI Assistant
              </Link>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
