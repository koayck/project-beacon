const DEFAULT_BACKEND_HTTP_BASE = 'http://127.0.0.1:8000'

function normalizeBackendBase(rawValue: string | undefined): string {
  const trimmed = rawValue?.trim()
  if (!trimmed) return DEFAULT_BACKEND_HTTP_BASE

  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return DEFAULT_BACKEND_HTTP_BASE
    }
    parsed.pathname = ''
    parsed.search = ''
    parsed.hash = ''
    return parsed.toString().replace(/\/+$/, '')
  } catch {
    return DEFAULT_BACKEND_HTTP_BASE
  }
}

function buildTelemetryWsUrl(httpBase: string): string {
  const parsed = new URL(httpBase)
  parsed.protocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:'
  parsed.pathname = '/ws/telemetry'
  parsed.search = ''
  parsed.hash = ''
  return parsed.toString()
}

export const BACKEND_HTTP_BASE = normalizeBackendBase(process.env.NEXT_PUBLIC_BEACON_BACKEND_URL)
export const TELEMETRY_WS_URL = buildTelemetryWsUrl(BACKEND_HTTP_BASE)
