// Cliente da API FastAPI. Em dev o Vite faz proxy de /api -> :8000.
// Em produção (servido pelo FastAPI) os caminhos relativos já batem.

async function req(method, path, body) {
  const opts = { method, headers: {} }
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(path, opts)
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!res.ok) {
    const detail = (data && data.detail) || res.statusText
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return data
}

export const api = {
  scan: (path) => req('POST', '/api/scan', { path }),
  scanStatus: () => req('GET', '/api/scan/status'),
  latestReport: () => req('GET', '/api/reports/latest'),
  latestAnalytics: () => req('GET', '/api/analytics/latest'),

  rename: {
    suggestSample: () => req('POST', '/api/rename/suggest-sample'),
    suggestAll: () => req('POST', '/api/rename/suggest-all'),
    status: () => req('GET', '/api/rename/status'),
    results: () => req('GET', '/api/rename/results'),
    approve: (full_path) => req('POST', '/api/rename/approve', { full_path }),
    reject: (full_path) => req('POST', '/api/rename/reject', { full_path }),
    edit: (full_path, nome_sugerido) =>
      req('POST', '/api/rename/edit', { full_path, nome_sugerido }),
    resolveCollisions: () => req('POST', '/api/rename/resolve-collisions'),
    resolveStatus: () => req('GET', '/api/rename/resolve-status'),
    apply: () => req('POST', '/api/rename/apply'),
  },
}

export function basename(p) {
  if (!p) return ''
  return p.replace(/[\\/]+$/, '').split(/[\\/]/).pop()
}

export function dirname(p) {
  if (!p) return ''
  return p.replace(/[\\/][^\\/]+[\\/]?$/, '')
}
