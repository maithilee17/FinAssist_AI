import { useState } from 'react'
import { ArrowRight, LoaderCircle } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import AuthShell from '../components/AuthShell'
import FormField from '../components/FormField'
import useAuth from '../context/useAuth'
import { getApiError } from '../lib/api'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const successMessage = location.state?.registered ? 'Account created. Sign in to continue.' : ''

  const update = (event) => setForm((current) => ({ ...current, [event.target.name]: event.target.value }))

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (!form.email.trim() || !form.password) {
      setError('Enter both your email address and password.')
      return
    }
    setIsSubmitting(true)
    try {
      await login({ email: form.email.trim(), password: form.password })
      navigate(location.state?.from ?? '/dashboard', { replace: true })
    } catch (requestError) {
      setError(getApiError(requestError, 'Unable to sign in.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthShell eyebrow="Welcome back" title="Sign in to your workspace" description="Continue to your private financial document workspace.">
      {successMessage && <div role="status" aria-live="polite" className="mb-5 rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-200">{successMessage}</div>}
      {error && <div role="alert" className="mb-5 rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}
      <form className="space-y-5" onSubmit={handleSubmit} noValidate>
        <FormField label="Email address" name="email" type="email" autoComplete="email" placeholder="you@company.com" value={form.email} onChange={update} disabled={isSubmitting} />
        <FormField label="Password" name="password" type="password" autoComplete="current-password" placeholder="Enter your password" value={form.password} onChange={update} disabled={isSubmitting} />
        <button type="submit" disabled={isSubmitting} aria-busy={isSubmitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-teal-400 px-4 py-3 font-semibold text-[#061512] transition hover:bg-teal-300 disabled:cursor-not-allowed disabled:opacity-60">
          {isSubmitting ? <><LoaderCircle className="animate-spin" size={18} /> Signing in…</> : <>Sign in <ArrowRight size={18} /></>}
        </button>
      </form>
      <p className="mt-7 text-center text-sm text-slate-400">New to FinAssist AI? <Link className="font-medium text-teal-300 hover:text-teal-200" to="/register">Create an account</Link></p>
    </AuthShell>
  )
}

