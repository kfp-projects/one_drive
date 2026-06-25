import { useEffect, useState } from 'react'
import { api } from '../api'
import { Button, Spinner } from './ui'
import { toast } from './toast'
import FolderBrowser from './FolderBrowser'

// Painel pra ver/adicionar/remover pastas excluídas do scan (sem editar JSON).
export default function Exclusions({ onClose, onChanged }) {
  const [paths, setPaths] = useState([])
  const [names, setNames] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [browsing, setBrowsing] = useState(false)

  useEffect(() => {
    api
      .getExclusions()
      .then((d) => {
        setPaths(d.excluded_folder_paths || [])
        setNames(d.excluded_folder_names || [])
      })
      .catch((e) => toast(e.message, 'error'))
      .finally(() => setLoading(false))
  }, [])

  async function persist(newPaths) {
    setSaving(true)
    try {
      const d = await api.setExclusions({ excluded_folder_paths: newPaths, excluded_folder_names: names })
      setPaths(d.excluded_folder_paths)
      toast('Exclusões salvas.', 'success')
      onChanged?.()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const remove = (p) => persist(paths.filter((x) => x !== p))
  const add = (p) => {
    setBrowsing(false)
    if (p && !paths.includes(p)) persist([...paths, p])
  }

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="flex max-h-[80vh] w-full max-w-xl flex-col rounded-xl bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 p-4">
          <div>
            <h3 className="font-semibold text-slate-800">Pastas excluídas do scan</h3>
            <p className="text-xs text-slate-500">Essas pastas (e tudo dentro delas) ficam de fora da análise e do renome.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {loading ? (
            <div className="flex items-center gap-2 text-slate-500"><Spinner /> Carregando…</div>
          ) : paths.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 py-8 text-center text-sm text-slate-400">
              Nenhuma pasta excluída ainda.
            </div>
          ) : (
            <ul className="space-y-2">
              {paths.map((p) => (
                <li key={p} className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2">
                  <span className="flex-1 truncate text-sm text-slate-700" title={p}>📁 {p}</span>
                  <Button variant="danger" disabled={saving} onClick={() => remove(p)}>Remover</Button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-slate-100 p-3">
          <Button variant="primary" disabled={saving} onClick={() => setBrowsing(true)}>+ Adicionar pasta</Button>
          <Button variant="ghost" onClick={onClose}>Fechar</Button>
        </div>
      </div>

      {browsing && (
        <FolderBrowser
          title="Escolher pasta para EXCLUIR"
          pickLabel="Excluir esta pasta"
          onPick={add}
          onClose={() => setBrowsing(false)}
        />
      )}
    </div>
  )
}
