import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Card, Stat, Spinner, Empty } from '../components/ui'

function Bars({ data, max, fmt = (v) => v, tone = 'bg-indigo-500' }) {
  const top = Math.max(max || 0, ...Object.values(data || {}), 1)
  return (
    <div className="space-y-2">
      {Object.entries(data || {})
        .sort((a, b) => b[1] - a[1])
        .map(([label, value]) => (
          <div key={label} className="flex items-center gap-2 text-sm">
            <div className="w-40 shrink-0 truncate text-slate-600" title={label}>
              {label}
            </div>
            <div className="h-4 flex-1 overflow-hidden rounded bg-slate-100">
              <div className={`h-full ${tone}`} style={{ width: `${(value / top) * 100}%` }} />
            </div>
            <div className="w-16 shrink-0 text-right tabular-nums text-slate-500">{fmt(value)}</div>
          </div>
        ))}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <Card className="p-4">
      <h2 className="mb-3 text-base font-semibold text-slate-800">{title}</h2>
      {children}
    </Card>
  )
}

export default function Analytics({ refreshKey }) {
  const [state, setState] = useState({ loading: true, data: null })

  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true }))
    api
      .latestAnalytics()
      .then((r) => alive && setState({ loading: false, data: r }))
      .catch(() => alive && setState({ loading: false, data: null }))
    return () => {
      alive = false
    }
  }, [refreshKey])

  const a = state.data?.data
  const pct = useMemo(() => a?.distribuicao_estrutural?.percentual || {}, [a])

  if (state.loading)
    return (
      <div className="flex items-center gap-2 text-slate-500">
        <Spinner /> Carregando analytics…
      </div>
    )

  if (!a || state.data?.status === 'no_analytics')
    return <Empty title="Sem analytics ainda" hint="Rode um scan para gerar a inteligência analítica." />

  const ps = a.path_statistics || {}
  const fd = a.folder_depth || {}
  const da = a.duplicate_analysis || {}
  const cats = a.categorias_de_arquivos || {}
  const deepest = (fd.top_100_deepest_folders || []).slice(0, 15)

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Itens analisados" value={(ps.total_items_analyzed || 0).toLocaleString('pt-BR')} />
        <Stat label="Caminhos críticos" value={(ps.critical_path_length_violations || 0).toLocaleString('pt-BR')} tone="red" />
        <Stat label="Profundidade média" value={fd.average_depth ?? '—'} tone="amber" />
        <Stat label="Profundidade máx." value={fd.max_depth_found ?? '—'} tone="amber" />
        <Stat label="Poluição (cópias)" value={`${da.overall_pollution_rate ?? 0}%`} tone="red" />
        <Stat label="Nomes descritivos" value={a.nomes_descritivos_longos ?? 0} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Categorias de arquivos">
          <Bars data={cats} fmt={(v) => v.toLocaleString('pt-BR')} />
        </Section>

        <Section title="Distribuição estrutural (%)">
          <Bars data={pct} fmt={(v) => `${v}%`} tone="bg-violet-500" />
        </Section>

        <Section title="Padrões de duplicação (%)">
          <Bars data={da.duplication_percentages || {}} fmt={(v) => `${v}%`} tone="bg-rose-500" />
        </Section>

        <Section title="Estruturas de nome mais repetidas">
          <Bars
            data={Object.fromEntries(Object.entries(a.naming_patterns?.top_repetitive_structures || {}).slice(0, 10))}
            tone="bg-amber-500"
          />
        </Section>
      </div>

      <Section title="Pastas mais profundas (top 15)">
        <div className="divide-y divide-slate-100">
          {deepest.map((d, i) => (
            <div key={i} className="flex items-center gap-3 py-1.5 text-sm">
              <span className="w-10 shrink-0 text-right font-semibold text-amber-600">{d.depth}</span>
              <span className="truncate text-slate-600" title={d.path}>
                {d.path}
              </span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  )
}
