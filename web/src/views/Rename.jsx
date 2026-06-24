import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, dirname } from '../api'
import { Card, Button, Badge, Stat, Spinner, Empty } from '../components/ui'
import { toast } from '../components/toast'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Colisão = mesma pasta + mesmo nome sugerido. Marca cada item.
function annotateCollisions(results) {
  const groups = new Map()
  for (const r of results) {
    r._collision = false
    const name = (r.nome_sugerido || '').trim().toLowerCase()
    if (!name) continue
    const key = dirname(r.full_path).toLowerCase() + '|' + name
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(r)
  }
  for (const g of groups.values())
    if (g.length > 1) g.forEach((r) => (r._collision = true))
  return results
}

const CONF_TONE = { Alta: 'green', Media: 'amber', Baixa: 'red' }

export default function Rename({ onChanged }) {
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null) // texto da ação em curso
  const [progress, setProgress] = useState(null)
  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState(null) // full_path em edição
  const editValue = useRef('')

  const load = useCallback(async () => {
    const d = await api.rename.results()
    setResults(annotateCollisions(d.results || []))
  }, [])

  useEffect(() => {
    load()
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [load])

  const stats = useMemo(() => {
    const s = { total: results.length, pendente: 0, aprovada: 0, recusada: 0, colisao: 0 }
    for (const r of results) {
      s[r.status] = (s[r.status] || 0) + 1
      if (r._collision) s.colisao++
    }
    return s
  }, [results])

  const filtered = useMemo(() => {
    const q = filter.toLowerCase().trim()
    const arr = q
      ? results.filter((r) => (r.original_name || '').toLowerCase().includes(q))
      : results
    return arr.slice(0, 400)
  }, [results, filter])

  async function pollUntilDone(statusFn) {
    for (;;) {
      const s = await statusFn()
      setProgress(s)
      if (!s.running) return s
      await sleep(1500)
    }
  }

  async function generate(mode) {
    try {
      setBusy(mode === 'all' ? 'Gerando todas…' : 'Gerando amostra…')
      await (mode === 'all' ? api.rename.suggestAll() : api.rename.suggestSample())
      await pollUntilDone(api.rename.status)
      await load()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(null)
      setProgress(null)
    }
  }

  async function resolveCollisions() {
    if (!stats.colisao) return toast('Não há nomes repetidos para resolver.', 'info')
    if (!confirm(`Pedir à IA para reescrever ${stats.colisao} arquivo(s) que colidem, com nomes distintos?`)) return
    try {
      setBusy('Resolvendo colisões…')
      const r = await api.rename.resolveCollisions()
      if (r.status === 'noop') return toast('Nenhuma colisão a resolver.', 'info')
      await pollUntilDone(api.rename.resolveStatus)
      await load()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(null)
      setProgress(null)
    }
  }

  async function setStatus(r, status) {
    if (status === 'aprovada' && r._collision)
      return toast('Esse nome colide com outro na mesma pasta. Edite ou resolva as colisões antes de aprovar.', 'error')
    const fn = status === 'aprovada' ? api.rename.approve : api.rename.reject
    await fn(r.full_path)
    setResults((prev) =>
      annotateCollisions(prev.map((x) => (x.full_path === r.full_path ? { ...x, status } : x))),
    )
  }

  async function approveAll() {
    const targets = results.filter((r) => r.status === 'pendente' && !r._collision)
    const blocked = results.filter((r) => r.status === 'pendente' && r._collision).length
    if (!targets.length) return toast('Nada aprovável.' + (blocked ? ` ${blocked} bloqueado(s) por colisão.` : ''))
    if (!confirm(`Aprovar ${targets.length} sugestão(ões)?${blocked ? `\n${blocked} com nome repetido ficam de fora.` : ''}`)) return
    setBusy('Aprovando…')
    try {
      await Promise.all(targets.map((r) => api.rename.approve(r.full_path)))
      await load()
    } finally {
      setBusy(null)
    }
  }

  async function saveEdit(r) {
    const newName = editValue.current.trim()
    if (!newName) return
    try {
      await api.rename.edit(r.full_path, newName)
      setResults((prev) =>
        annotateCollisions(
          prev.map((x) => (x.full_path === r.full_path ? { ...x, nome_sugerido: newName, edited: true } : x)),
        ),
      )
      setEditing(null)
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  async function apply() {
    if (!stats.aprovada) return toast('Nenhuma sugestão aprovada.', 'info')
    if (!confirm(`Renomear ${stats.aprovada} arquivo(s) no disco? (rollback é salvo automaticamente)`)) return
    setBusy('Aplicando…')
    try {
      const r = await api.rename.apply()
      toast(
        `Renomeados: ${r.renamed}\nPulados (sumiram): ${r.skipped_missing}\nColisão: ${r.skipped_collision}\nErros: ${r.errors_count}`,
        r.errors_count ? 'error' : 'success',
      )
      await load()
      onChanged?.()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div className="flex items-center gap-2 text-slate-500"><Spinner /> Carregando…</div>

  return (
    <div className="space-y-5">
      {/* Ações de geração */}
      <Card className="flex flex-wrap items-center gap-2 p-4">
        <Button variant="primary" disabled={!!busy} onClick={() => generate('sample')}>
          Gerar amostra (50)
        </Button>
        <Button disabled={!!busy} onClick={() => generate('all')}>
          Gerar todas
        </Button>
        <div className="mx-1 h-6 w-px bg-slate-200" />
        <Button disabled={!!busy || !stats.colisao} onClick={resolveCollisions}>
          Resolver colisões {stats.colisao ? `(${stats.colisao})` : ''}
        </Button>
        <Button disabled={!!busy || !stats.pendente} onClick={approveAll}>
          Aprovar todas
        </Button>
        <Button variant="success" disabled={!!busy || !stats.aprovada} onClick={apply} className="ml-auto">
          Aplicar aprovadas ({stats.aprovada})
        </Button>
      </Card>

      {busy && (
        <div className="flex items-center gap-3 rounded-lg bg-indigo-50 px-4 py-2.5 text-sm text-indigo-700">
          <Spinner />
          {busy}
          {progress && progress.total ? ` ${progress.done}/${progress.total} (${Math.round(progress.percent || 0)}%)` : ''}
        </div>
      )}

      {results.length === 0 ? (
        <Empty title="Nenhuma sugestão ainda" hint='Clique em "Gerar amostra (50)" para começar.' />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Stat label="Total" value={stats.total} />
            <Stat label="Pendentes" value={stats.pendente} tone="amber" />
            <Stat label="Aprovadas" value={stats.aprovada} tone="green" />
            <Stat label="Recusadas" value={stats.recusada} />
            <Stat label="Colisões" value={stats.colisao} tone="red" />
          </div>

          {stats.colisao > 0 && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm text-rose-700">
              ⚠ {stats.colisao} arquivo(s) ficariam com o <b>mesmo nome</b> de outro na mesma pasta.
              Use <b>Resolver colisões</b> ou edite antes de aplicar.
            </div>
          )}

          <Card>
            <div className="flex items-center justify-between border-b border-slate-100 p-3">
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filtrar por nome original…"
                className="w-64 max-w-[50vw] rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-indigo-500"
              />
              <span className="text-xs text-slate-400">{filtered.length} mostrados</span>
            </div>
            <div className="divide-y divide-slate-100">
              {filtered.map((r) => (
                <RenameRow
                  key={r.full_path}
                  r={r}
                  editing={editing === r.full_path}
                  onEdit={() => {
                    editValue.current = r.nome_sugerido || ''
                    setEditing(r.full_path)
                  }}
                  onEditChange={(v) => (editValue.current = v)}
                  onSaveEdit={() => saveEdit(r)}
                  onCancelEdit={() => setEditing(null)}
                  onApprove={() => setStatus(r, 'aprovada')}
                  onReject={() => setStatus(r, 'recusada')}
                />
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}

function RenameRow({ r, editing, onEdit, onEditChange, onSaveEdit, onCancelEdit, onApprove, onReject }) {
  const rowTone =
    r.status === 'aprovada'
      ? 'bg-emerald-50/40'
      : r.status === 'recusada'
        ? 'bg-slate-50 opacity-60'
        : r._collision
          ? 'bg-rose-50/40'
          : ''
  return (
    <div className={`flex flex-col gap-2 p-3 sm:flex-row sm:items-center ${rowTone}`}>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs text-slate-400" title={dirname(r.full_path)}>
          {dirname(r.full_path)}
        </div>
        <div className="truncate text-sm text-slate-500 line-through">{r.original_name}</div>
        {editing ? (
          <input
            autoFocus
            defaultValue={r.nome_sugerido}
            onChange={(e) => onEditChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSaveEdit()
              if (e.key === 'Escape') onCancelEdit()
            }}
            className="mt-0.5 w-full rounded border border-indigo-400 px-2 py-1 text-sm outline-none"
          />
        ) : (
          <div className="truncate text-sm font-semibold text-slate-900">{r.nome_sugerido}</div>
        )}
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Badge tone={CONF_TONE[r.confianca] || 'slate'}>{r.confianca}</Badge>
          {r.is_dir && <Badge tone="indigo">Pasta</Badge>}
          {r._collision && <Badge tone="red">Nome repetido</Badge>}
          {r.edited && <Badge tone="violet">Editado</Badge>}
          {r.error && <Badge tone="red">Erro IA</Badge>}
          {r.motivo && <span className="truncate text-xs text-slate-400">· {r.motivo}</span>}
        </div>
      </div>
      <div className="flex shrink-0 gap-1.5">
        {editing ? (
          <>
            <Button variant="success" onClick={onSaveEdit}>Salvar</Button>
            <Button variant="ghost" onClick={onCancelEdit}>Cancelar</Button>
          </>
        ) : (
          <>
            <Button variant="success" className={r.status === 'aprovada' ? 'ring-2 ring-emerald-400' : ''} onClick={onApprove}>
              Aprovar
            </Button>
            <Button variant="danger" className={r.status === 'recusada' ? 'ring-2 ring-rose-300' : ''} onClick={onReject}>
              Recusar
            </Button>
            <Button variant="ghost" onClick={onEdit}>Editar</Button>
          </>
        )}
      </div>
    </div>
  )
}
