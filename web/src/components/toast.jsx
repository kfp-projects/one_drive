import { useEffect, useState } from 'react'

// Toast simples via emitter de módulo — chame toast(msg, tipo) de qualquer lugar.
let _id = 0
const listeners = new Set()

export function toast(message, type = 'info') {
  const t = { id: ++_id, message, type }
  listeners.forEach((fn) => fn(t))
}

export function Toaster() {
  const [items, setItems] = useState([])

  useEffect(() => {
    const add = (t) => {
      setItems((prev) => [...prev, t])
      setTimeout(() => setItems((prev) => prev.filter((x) => x.id !== t.id)), 5000)
    }
    listeners.add(add)
    return () => listeners.delete(add)
  }, [])

  const tones = {
    info: 'bg-slate-800 text-white',
    success: 'bg-emerald-600 text-white',
    error: 'bg-rose-600 text-white',
  }

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[90vw] flex-col gap-2">
      {items.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto cursor-pointer whitespace-pre-line rounded-lg px-4 py-3 text-sm shadow-lg ${tones[t.type] || tones.info}`}
          onClick={() => setItems((prev) => prev.filter((x) => x.id !== t.id))}
        >
          {t.message}
        </div>
      ))}
    </div>
  )
}
