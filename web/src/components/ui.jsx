// Primitivas de UI — pequenas, com Tailwind. Reusadas em todo o app.

export function Button({ variant = 'default', className = '', ...props }) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed'
  const variants = {
    default: 'bg-slate-100 text-slate-700 hover:bg-slate-200',
    primary: 'bg-indigo-600 text-white hover:bg-indigo-700',
    success: 'bg-emerald-600 text-white hover:bg-emerald-700',
    danger: 'bg-rose-50 text-rose-700 hover:bg-rose-100',
    ghost: 'text-slate-600 hover:bg-slate-100',
  }
  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />
}

export function Badge({ tone = 'slate', children }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-700',
    green: 'bg-emerald-100 text-emerald-700',
    amber: 'bg-amber-100 text-amber-700',
    red: 'bg-rose-100 text-rose-700 ring-1 ring-rose-200',
    indigo: 'bg-indigo-100 text-indigo-700',
    violet: 'bg-violet-100 text-violet-700',
  }
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${tones[tone]}`}>
      {children}
    </span>
  )
}

export function Card({ className = '', children }) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {children}
    </div>
  )
}

export function Stat({ label, value, tone = 'slate' }) {
  const tones = {
    slate: 'text-slate-900',
    green: 'text-emerald-600',
    amber: 'text-amber-600',
    red: 'text-rose-600',
    indigo: 'text-indigo-600',
  }
  return (
    <Card className="px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${tones[tone]}`}>{value}</div>
    </Card>
  )
}

export function Spinner({ className = '' }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600 ${className}`}
    />
  )
}

export function Empty({ title, hint }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white py-16 text-center">
      <div className="text-slate-700 font-medium">{title}</div>
      {hint && <div className="mt-1 text-sm text-slate-500">{hint}</div>}
    </div>
  )
}
