import { useId } from 'react'

export default function FormField({ label, error, hint, id: suppliedId, ...inputProps }) {
  const generatedId = useId()
  const inputId = suppliedId ?? generatedId
  const errorId = `${inputId}-error`
  const hintId = `${inputId}-hint`
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined

  return (
    <div className="block">
      <label htmlFor={inputId} className="mb-2 block text-sm font-medium text-slate-200">{label}</label>
      <input
        {...inputProps}
        id={inputId}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        className={`w-full rounded-xl border bg-white/[0.045] px-4 py-3 text-sm text-white outline-none transition placeholder:text-slate-600 focus:ring-2 focus:ring-teal-400/20 ${error ? 'border-rose-400/70 focus:border-rose-400' : 'border-white/12 focus:border-teal-300/70'}`}
      />
      {hint && <p id={hintId} className="mt-1.5 text-xs leading-5 text-slate-500">{hint}</p>}
      {error && <p id={errorId} className="mt-1.5 text-xs text-rose-300">{error}</p>}
    </div>
  )
}

