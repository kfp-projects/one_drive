import { useEffect, useMemo, useState } from 'react'
import { api, basename, dirname } from '../api'
import { Card, Stat, Badge, Spinner, Empty } from '../components/ui'

const PROBLEM_LABELS = {
  PATH_TOO_LONG: 'Caminho longo',
  FILENAME_TOO_LONG: 'Nome longo',
  FORBIDDEN_CHARS: 'Caractere proibido',
  RESERVED_NAME: 'Nome reservado',
  INVALID_EDGE_CHARS: 'Espaço/ponto nas bordas',
  SUSPICIOUS_DOUBLE_EXT: 'Extensão dupla',
}

function problemsOf(rec) {
  return (rec.detected_problems || '')
    .split(';')
    .map((s) => s.trim())
    .filter(Boolean)
}

export default function Overview({ refreshKey }) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  const [filter, setFilter] = useState('')

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true }))
    api
      .latestReport()
      .then((r) => alive && setState({ loading: false, data: r, error: null }))
      .catch((e) => alive && setState({ loading: false, data: null, error: e.message }))
    return () => {
      alive = false
    }
  }, [refreshKey])

  const issues = state.data?.data?.issues || []

  const counts = useMemo(() => {
    const c = { total: issues.length, byCode: {}, shared: 0 }
    for (const r of issues) {
      if (r.is_shared) c.shared++
      for (const code of problemsOf(r)) c.byCode[code] = (c.byCode[code] || 0) + 1
    }
    return c
  }, [issues])

  const filtered = useMemo(() => {
    const q = filter.toLowerCase().trim()
    if (!q) return issues.slice(0, 500)
    return issues
      .filter((r) => (r.original_name || '').toLowerCase().includes(q))
      .slice(0, 500)
  }, [issues, filter])

  if (state.loading) {
    return (
      <div className="flex items-center gap-2 text-slate-500">
        <Spinner /> Carregando relatório…
      </div>
    )
  }

  if (state.error || state.data?.status === 'no_reports' || counts.total === 0) {
    return (
      <Empty
        title="Nenhum problema no último scan"
        hint="Rode um scan acima para analisar a conformidade dos seus arquivos."
      />
    )
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Stat label="Itens com problema" value={counts.total} tone="amber" />
        {Object.entries(counts.byCode)
          .sort((a, b) => b[1] - a[1])
          .map(([code, n]) => (
            <Stat key={code} label={PROBLEM_LABELS[code] || code} value={n} />
          ))}
        {counts.shared > 0 && <Stat label="Bloqueados (compartilhados)" value={counts.shared} />}
      </div>

      <Card>
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 p-4">
          <h2 className="text-base font-semibold text-slate-800">Arquivos com problema</h2>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filtrar por nome…"
            className="w-56 max-w-[50vw] rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-500"
          />
        </div>
        <div className="max-h-[60vh] divide-y divide-slate-100 overflow-auto">
          {filtered.map((r, i) => (
            <div key={i} className="flex flex-col gap-1 px-4 py-2.5 hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-800">
                  {r.is_dir ? '📁 ' : ''}
                  {r.original_name}
                </div>
                <div className="truncate text-xs text-slate-400" title={dirname(r.full_path)}>
                  {dirname(r.full_path)}
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-1.5">
                {r.is_shared && <Badge tone="slate">Bloqueado</Badge>}
                {problemsOf(r).map((code) => (
                  <Badge key={code} tone="red">
                    {PROBLEM_LABELS[code] || code}
                  </Badge>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
