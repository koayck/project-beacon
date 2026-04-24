import { BACKEND_HTTP_BASE } from './backend'

export interface LicenseStatus {
  valid: boolean
  license_key: string | null
  org_name: string | null
  expiry_date: string | null
  days_remaining: number | null
  message: string
}

export interface LLMConfig {
  mode: 'api' | 'local'
  apiKey?: string
  localUrl?: string
}

export interface SetupConfig {
  licenseKey: string | null
  llm: LLMConfig | null
  setupCompleted: boolean
}

const STORAGE_KEY = 'beacon_setup_config'

export function getStoredConfig(): SetupConfig {
  if (typeof window === 'undefined') {
    return { licenseKey: null, llm: null, setupCompleted: false }
  }
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      return JSON.parse(stored)
    }
  } catch {
    // ignore parse errors
  }
  return { licenseKey: null, llm: null, setupCompleted: false }
}

export function saveConfig(config: SetupConfig): void {
  if (typeof window === 'undefined') return
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
}

export function clearConfig(): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem(STORAGE_KEY)
}

export async function activateLicense(licenseKey: string): Promise<LicenseStatus> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/license/activate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ license_key: licenseKey }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'License activation failed' }))
    throw new Error(error.detail || 'License activation failed')
  }

  return res.json()
}

export async function getLicenseStatus(): Promise<LicenseStatus> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/license/status`)

  if (!res.ok) {
    throw new Error('Failed to fetch license status')
  }

  return res.json()
}

export async function configureLLM(config: LLMConfig): Promise<void> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/config/llm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'LLM configuration failed' }))
    throw new Error(error.detail || 'LLM configuration failed')
  }
}

export async function testLLMConnection(config: LLMConfig): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/config/llm/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Connection test failed' }))
    return { success: false, message: error.detail || 'Connection test failed' }
  }

  return res.json()
}

export interface ModelInfo {
  id: string
  name: string
  provider: string
}

export async function getLLMConfig(): Promise<LLMConfig | null> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/config/llm`)

  if (!res.ok) {
    throw new Error('Failed to fetch LLM config')
  }

  const data = await res.json()
  if (data.mode === 'unconfigured') {
    return null
  }
  return data
}

export async function listModels(): Promise<ModelInfo[]> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/config/llm/models`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to list models' }))
    throw new Error(error.detail || 'Failed to list models')
  }

  return res.json()
}

export async function getSelectedModel(): Promise<string | null> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/config/llm/model`)

  if (!res.ok) {
    throw new Error('Failed to fetch selected model')
  }

  const data = await res.json()
  return data.model_id
}

export async function setSelectedModel(modelId: string): Promise<void> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/config/llm/model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to set model' }))
    throw new Error(error.detail || 'Failed to set model')
  }
}

export interface VertexModelInfo {
  id: string
  name: string
  version: string | null
  publisher: string
}

export async function listVertexModels(): Promise<VertexModelInfo[]> {
  const res = await fetch(`${BACKEND_HTTP_BASE}/config/vertex/models`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Failed to list Vertex AI models' }))
    throw new Error(error.detail || 'Failed to list Vertex AI models')
  }

  return res.json()
}
