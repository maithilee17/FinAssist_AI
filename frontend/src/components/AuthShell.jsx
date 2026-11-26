import { Database, FileCheck2, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function AuthShell({ eyebrow, title, description, children }) {
  return (
    <main className="min-h-screen bg-[#061512] text-slate-100 lg:grid lg:grid-cols-[0.9fr_1.1fr]">
      <section className="relative hidden overflow-hidden border-r border-white/10 p-12 lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(45,212,191,0.18),transparent_35%),radial-gradient(circle_at_80%_80%,rgba(59,130,246,0.12),transparent_35%)]" />
        <Link to="/" className="relative flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-xl bg-teal-400 text-[#061512]">
            <Database size={22} />
          </span>
          <span>
            <span className="block font-semibold">FinAssist AI</span>
            <span className="text-xs text-slate-400">Evidence-aware intelligence</span>
          </span>
        </Link>
        <div className="relative max-w-lg">
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-teal-300">Trusted by design</p>
          <h2 className="mt-5 text-4xl font-semibold leading-tight tracking-[-0.035em]">Your financial documents stay connected to verifiable evidence.</h2>
          <div className="mt-10 space-y-5">
            <div className="flex gap-3"><ShieldCheck className="mt-0.5 text-teal-300" /><p className="text-sm leading-6 text-slate-300">Argon2 password protection and expiring signed sessions.</p></div>
            <div className="flex gap-3"><FileCheck2 className="mt-0.5 text-teal-300" /><p className="text-sm leading-6 text-slate-300">User ownership forms the boundary for every future document query.</p></div>
          </div>
        </div>
        <p className="relative text-xs text-slate-500">FinAssist AI · Private documents · Verifiable answers</p>
      </section>

      <section className="flex min-h-screen items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-md">
          <Link to="/" className="mb-10 flex items-center gap-2 font-semibold lg:hidden"><Database className="text-teal-300" /> FinAssist AI</Link>
          <p className="text-sm font-medium text-teal-300">{eyebrow}</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-[-0.03em] text-white">{title}</h1>
          <p className="mt-3 text-sm leading-6 text-slate-400">{description}</p>
          <div className="mt-8">{children}</div>
        </div>
      </section>
    </main>
  )
}

