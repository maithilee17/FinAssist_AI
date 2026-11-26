import { useEffect, useState } from 'react'
import { ArrowRight, CheckCircle2, Database, FileSearch, HeartPulse, ShieldCheck, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'

import api, { apiBaseUrl } from '../lib/api'

const features = [
  { icon: FileSearch, title: 'Adaptive retrieval', text: 'Keyword, semantic, and hybrid search selected for each question.' },
  { icon: ShieldCheck, title: 'Evidence first', text: 'Claims are tied to retrieved passages, page numbers, and document ownership.' },
  { icon: Sparkles, title: 'Confidence aware', text: 'The assistant retrieves more context or abstains when support is insufficient.' },
]

export default function SetupPage() {
  const [apiStatus, setApiStatus] = useState('checking')

  useEffect(() => {
    let active = true
    api.get('/health/live')
      .then(() => active && setApiStatus('online'))
      .catch(() => active && setApiStatus('offline'))
    return () => { active = false }
  }, [])

  return (
    <main className="min-h-screen overflow-hidden bg-[#061512] text-slate-100">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(20,184,166,0.17),transparent_32%),radial-gradient(circle_at_15%_55%,rgba(59,130,246,0.10),transparent_30%)]" />
      <div className="relative mx-auto max-w-7xl px-6 pb-16 pt-7 lg:px-8">
        <nav className="flex items-center justify-between border-b border-white/10 pb-6">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-teal-400 text-[#061512] shadow-lg shadow-teal-400/20">
              <Database size={21} strokeWidth={2.4} />
            </div>
            <div>
              <p className="font-semibold tracking-tight">FinAssist AI</p>
              <p className="hidden text-xs text-slate-400 sm:block">Evidence-aware financial intelligence</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div aria-live="polite" className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300 sm:flex">
              <span className={`size-2 rounded-full ${apiStatus === 'online' ? 'bg-emerald-400' : apiStatus === 'offline' ? 'bg-rose-400' : 'animate-pulse bg-amber-300'}`} />
              API {apiStatus}
            </div>
            <Link to="/login" className="text-sm font-medium text-slate-300 hover:text-white">Sign in</Link>
            <Link to="/register" className="rounded-lg bg-white/10 px-3 py-2 text-sm font-medium text-white hover:bg-white/15">Register</Link>
          </div>
        </nav>

        <section className="grid items-center gap-14 py-20 lg:grid-cols-[1.1fr_0.9fr] lg:py-28">
          <div>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-teal-300/20 bg-teal-300/10 px-3 py-1.5 text-sm text-teal-200">
              <HeartPulse size={15} /> Evidence-aware document analysis
            </div>
            <h1 className="max-w-3xl text-5xl font-semibold leading-[1.05] tracking-[-0.045em] text-white sm:text-6xl">
              Ask financial documents. Get answers you can verify.
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-300">
              FinAssist AI combines adaptive retrieval, evidence checks, and page-level citations so useful answers remain grounded in your own reports.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link to="/register" className="inline-flex items-center gap-2 rounded-xl bg-teal-400 px-5 py-3 font-semibold text-[#061512] transition hover:bg-teal-300">
                Create secure workspace <ArrowRight size={18} />
              </Link>
              <a href={`${apiBaseUrl}/health/ready`} className="rounded-xl border border-white/15 bg-white/5 px-5 py-3 font-medium text-white transition hover:bg-white/10">
                Check infrastructure
              </a>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-white/[0.055] p-4 shadow-2xl shadow-black/30 backdrop-blur-xl">
            <div className="rounded-2xl border border-white/10 bg-[#091d19] p-6">
              <div className="mb-6 flex items-center justify-between">
                <div>
                  <p className="text-sm text-slate-400">System overview</p>
                  <p className="mt-1 text-xl font-semibold">RAG service foundation</p>
                </div>
                <CheckCircle2 className="text-teal-300" />
              </div>
              {['React + Vite client', 'FastAPI REST service', 'PostgreSQL metadata store', 'ChromaDB vector store'].map((item, index) => (
                <div key={item} className="flex items-center gap-4 border-t border-white/8 py-4 first:border-t-0">
                  <span className="grid size-8 place-items-center rounded-lg bg-white/7 text-xs font-semibold text-teal-200">0{index + 1}</span>
                  <span className="text-sm text-slate-200">{item}</span>
                  <span className="ml-auto text-xs text-slate-500">architecture</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-3">
          {features.map(({ icon: Icon, title, text }) => (
            <article key={title} className="rounded-2xl border border-white/10 bg-white/[0.035] p-6">
              <Icon className="mb-5 text-teal-300" size={24} />
              <h2 className="font-semibold text-white">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-slate-400">{text}</p>
            </article>
          ))}
        </section>
      </div>
    </main>
  )
}

