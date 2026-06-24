import { useState } from 'react'
import { api } from './api'
import { Button, Spinner } from './components/ui'
import { Toaster, toast } from './components/toast'
import Overview from './views/Overview'
import Rename from './views/Rename'
import Analytics from './views/Analytics'

const VIEWS = [
  { id: 'overview', label: 'Visão geral' },
  { id: 'rename', label: 'Renomeações IA' },
  { id: 'analytics', label: 'Analytics' },
]

export default function App() {
  const [view, setView] = useState('overview')
  const [path, setPath] = useState('C:\\Users\\kfpno\\OneDrive - Kfp Distribuidora Ltda')
  const [scanning, setScanning] = useState(false)
  const [scanProgress, setScanProgress] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  async function runScan() {
    if (!path.trim()) return
    if (!confirm('Escanear esta pasta? Pode levar alguns minutos em árvores grandes.')) return
    setScanning(true)
    setScanProgress({ phase: 'Iniciando', files: 0, folders: 0 })
    try {
      await api.scan(path.trim())
      // Polling do progresso até concluir
      for (;;) {
        await new Promise((r) => setTimeout(r, 1200))
        const s = await api.scanStatus()
        setScanProgress(s)
        if (!s.running) {
          if (s.error) throw new Error(s.error)
          break
        }
      }
      setRefreshKey((k) => k + 1)
      setView('overview')
      toast('Scan concluído.', 'success')
    } catch (e) {
      toast('Falha no scan: ' + e.message, 'error')
    } finally {
      setScanning(false)
      setScanProgress(null)
    }
  }

  return (
    <div className="mx-auto flex min-h-full max-w-5xl flex-col px-4 py-5 sm:px-6">
      <header className="mb-5">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 font-bold text-white">O</div>
          <div>
            <h1 className="text-lg font-bold leading-tight text-slate-900">Organiza</h1>
            <p className="text-xs text-slate-500">Saneamento de documentos para OneDrive</p>
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            disabled={scanning}
            placeholder="Caminho da pasta a escanear…"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 disabled:bg-slate-50"
          />
          <Button variant="primary" disabled={scanning} onClick={runScan}>
            {scanning ? (
              <>
                <Spinner className="border-white/40 border-t-white" /> Escaneando…
              </>
            ) : (
              'Escanear'
            )}
          </Button>
        </div>
      </header>

      <nav className="mb-5 flex gap-1 border-b border-slate-200">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            onClick={() => setView(v.id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
              view === v.id
                ? 'border-indigo-600 text-indigo-700'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            {v.label}
          </button>
        ))}
      </nav>

      <main className="flex-1">
        {scanning && (
          <div className="mb-4 rounded-lg bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
            <div className="flex items-center gap-3">
              <Spinner />
              <span className="font-medium">{scanProgress?.phase || 'Escaneando'}…</span>
              {scanProgress && (scanProgress.files > 0 || scanProgress.folders > 0) && (
                <span className="text-indigo-500">
                  {scanProgress.files.toLocaleString('pt-BR')} arquivos · {scanProgress.folders.toLocaleString('pt-BR')} pastas
                </span>
              )}
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-indigo-100">
              <div className="h-full w-1/3 animate-pulse rounded-full bg-indigo-500" />
            </div>
            <div className="mt-1 text-xs text-indigo-400">Árvores grandes (centenas de milhares de arquivos) levam alguns minutos.</div>
          </div>
        )}
        {view === 'overview' && <Overview refreshKey={refreshKey} />}
        {view === 'rename' && <Rename onChanged={() => setRefreshKey((k) => k + 1)} />}
        {view === 'analytics' && <Analytics refreshKey={refreshKey} />}
      </main>

      <footer className="mt-8 text-center text-xs text-slate-400">Organiza 2.0 · local</footer>
      <Toaster />
    </div>
  )
}
