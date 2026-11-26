import { useState } from 'react'
import { ArrowRight, LoaderCircle } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'

import AuthShell from '../components/AuthShell'
import FormField from '../components/FormField'
import useAuth from '../context/useAuth'
import { getApiError } from '../lib/api'

function validate(form) {
  const errors = {}
  if (form.fullName.trim().length < 2) errors.fullName = 'Enter your full name.'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) errors.email = 'Enter a valid email address.'
  if (form.password.length < 12) errors.password = 'Use at least 12 characters.'
  else {
    const groups = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((pattern) => pattern.test(form.password)).length
    if (groups < 3) errors.password = 'Include three of: lowercase, uppercase, number, special character.'
  }
  if (form.confirmPassword !== form.password) errors.confirmPassword = 'Passwords do not match.'
  return errors
}

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ fullName: '', email: '', password: '', confirmPassword: '' })
  const [fieldErrors, setFieldErrors] = useState({})
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const update = (event) => {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }))
    setFieldErrors((current) => ({ ...current, [event.target.name]: '' }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    const errors = validate(form)
    if (Object.keys(errors).length) {
      setFieldErrors(errors)
      return
    }
    setIsSubmitting(true)
    try {
      await register({ full_name: form.fullName.trim(), email: form.email.trim(), password: form.password })
      navigate('/login', { replace: true, state: { registered: true } })
    } catch (requestError) {
      setError(getApiError(requestError, 'Unable to create your account.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthShell eyebrow="Create your account" title="Start with a secure workspace" description="Your account controls access to every document, conversation, and citation.">
      {error && <div role="alert" className="mb-5 rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div>}
      <form className="space-y-4" onSubmit={handleSubmit} noValidate>
        <FormField label="Full name" name="fullName" autoComplete="name" placeholder="Mihir Sharma" value={form.fullName} onChange={update} error={fieldErrors.fullName} disabled={isSubmitting} />
        <FormField label="Email address" name="email" type="email" autoComplete="email" placeholder="you@company.com" value={form.email} onChange={update} error={fieldErrors.email} disabled={isSubmitting} />
        <FormField label="Password" name="password" type="password" autoComplete="new-password" placeholder="At least 12 characters" hint="Use 12–128 characters and include at least three character groups." value={form.password} onChange={update} error={fieldErrors.password} disabled={isSubmitting} />
        <FormField label="Confirm password" name="confirmPassword" type="password" autoComplete="new-password" placeholder="Repeat your password" value={form.confirmPassword} onChange={update} error={fieldErrors.confirmPassword} disabled={isSubmitting} />
        <button type="submit" disabled={isSubmitting} aria-busy={isSubmitting} className="flex w-full items-center justify-center gap-2 rounded-xl bg-teal-400 px-4 py-3 font-semibold text-[#061512] transition hover:bg-teal-300 disabled:cursor-not-allowed disabled:opacity-60">
          {isSubmitting ? <><LoaderCircle className="animate-spin" size={18} /> Creating account…</> : <>Create account <ArrowRight size={18} /></>}
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-400">Already registered? <Link className="font-medium text-teal-300 hover:text-teal-200" to="/login">Sign in</Link></p>
    </AuthShell>
  )
}

