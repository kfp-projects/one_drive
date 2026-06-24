import { useEffect, useState } from 'react'
import { api } from '../api'
import { Button, Spinner } from './ui'
import { toast } from './toast'

// Modal pra navegar pastas e escolher uma. onPick(path) recebe a pasta escolhida.
export default function FolderBrowser({ initial = '', title = 'Escolher pasta', pickLabel = 'Selecionar esta pasta', onPick, onClose }) {
  const [path, setPath] = useState(initial)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  async function load(p) {
    setLoading(true)
    try {
      const d = await api.folders(p)
      setData(d)
      setPath(d.path)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(initial)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 p-4">
          <h3 className="font-semibold text-slate-800">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2">
          <Button variant="ghost" disabled={!data?.parent} onClick={() => load(data.parent)} title="Subir um nível">
            ↑
          </Button>
          <div className="flex-1 truncate rounded bg-slate-50 px-2 py-1 text-xs text-slate-600" title={path}>
            {path || 'Selecione um drive ou pasta'}
          </div>
        </div>

        <div className="min-h-[200px] flex-1 overflow-auto p-2">
          {loading ? (
            <div className="flex items-center gap-2 p-4 text-slate-500"><Spinner /> Carregando…</div>
          ) : (
            <div className="divide-y divide-slate-50">
              {(data?.folders || []).map((f) => (
                <button
                  key={f.path}
                  onClick={() => load(f.path)}
                  className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm text-slate-700 hover:bg-indigo-50"
                >
                  <span>📁</span>
                  <span className="truncate">{f.name}</span>
                </button>
              ))}
              {data && data.folders.length === 0 && (
                <div className="p-4 text-sm text-slate-400">Sem subpastas aqui.</div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 p-3">
          <Button variant="ghost" onClick={onClose}>Cancelar</Button>
          <Button variant="primary" disabled={!path} onClick={() => onPick(path)}>
            {pickLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
