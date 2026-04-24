'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  getLicenseStatus,
  getLLMConfig,
  configureLLM,
  testLLMConnection,
  listModels,
  getSelectedModel,
  setSelectedModel,
  listVertexModels,
  type LicenseStatus,
  type LLMConfig,
  type ModelInfo,
  type VertexModelInfo,
} from '@/lib/config'

interface SettingsModalProps {
  isOpen: boolean
  onClose: () => void
}

type Tab = 'license' | 'llm'

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<Tab>('llm')

  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null)
  const [licenseLoading, setLicenseLoading] = useState(false)

  const [llmMode, setLlmMode] = useState<'api' | 'local'>('api')
  const [apiKey, setApiKey] = useState('')
  const [localUrl, setLocalUrl] = useState('http://localhost:11434')
  const [llmLoading, setLlmLoading] = useState(false)
  const [llmError, setLlmError] = useState<string | null>(null)
  const [llmSuccess, setLlmSuccess] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const [models, setModels] = useState<(ModelInfo | VertexModelInfo)[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)

  const loadLicenseStatus = useCallback(async () => {
    setLicenseLoading(true)
    try {
      const status = await getLicenseStatus()
      setLicenseStatus(status)
    } catch {
      setLicenseStatus(null)
    } finally {
      setLicenseLoading(false)
    }
  }, [])

  const loadLLMConfig = useCallback(async () => {
    try {
      const config = await getLLMConfig()
      if (config) {
        setLlmMode(config.mode)
        if (config.apiKey) setApiKey(config.apiKey)
        if (config.localUrl) setLocalUrl(config.localUrl)
      }
    } catch {
      // ignore
    }
  }, [])

  const loadModels = useCallback(async () => {
    setModelsLoading(true)
    setModelsError(null)
    try {
      let modelList: (ModelInfo | VertexModelInfo)[] = []

      if (llmMode === 'api') {
        modelList = await listVertexModels()
      } else {
        modelList = await listModels()
      }

      const currentModel = await getSelectedModel()
      setModels(modelList)
      setSelectedModelId(currentModel)
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Failed to load models')
      setModels([])
    } finally {
      setModelsLoading(false)
    }
  }, [llmMode])

  useEffect(() => {
    if (isOpen) {
      loadLicenseStatus()
      loadLLMConfig()
      loadModels()
    }
  }, [isOpen, loadLicenseStatus, loadLLMConfig, loadModels])

  const handleTestConnection = async () => {
    setLlmLoading(true)
    setLlmError(null)
    setLlmSuccess(null)
    setTestResult(null)

    const config: LLMConfig =
      llmMode === 'api' ? { mode: 'api', apiKey } : { mode: 'local', localUrl }

    try {
      const result = await testLLMConnection(config)
      setTestResult(result)
      if (!result.success) {
        setLlmError(result.message)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Connection test failed'
      setTestResult({ success: false, message })
      setLlmError(message)
    } finally {
      setLlmLoading(false)
    }
  }

  const handleSaveLLMConfig = async () => {
    if (llmMode === 'api' && !apiKey.trim()) {
      setLlmError('Please enter an API key')
      return
    }
    if (llmMode === 'local' && !localUrl.trim()) {
      setLlmError('Please enter the local LLM URL')
      return
    }

    setLlmLoading(true)
    setLlmError(null)
    setLlmSuccess(null)

    const config: LLMConfig =
      llmMode === 'api' ? { mode: 'api', apiKey: apiKey.trim() } : { mode: 'local', localUrl: localUrl.trim() }

    try {
      await configureLLM(config)
      setLlmSuccess('Configuration saved successfully')
      loadModels()
    } catch (err) {
      setLlmError(err instanceof Error ? err.message : 'Failed to save configuration')
    } finally {
      setLlmLoading(false)
    }
  }

  const handleModelSelect = async (modelId: string) => {
    setSelectedModelId(modelId)
    try {
      await setSelectedModel(modelId)
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Failed to select model')
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      <div className="relative z-10 w-full max-w-2xl rounded-lg border border-[rgba(0,180,255,0.2)] bg-[rgba(10,15,25,0.95)] shadow-[0_0_40px_rgba(0,150,255,0.15)] backdrop-blur-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[rgba(0,180,255,0.1)] px-6 py-4">
          <h2 className="font-mono text-lg font-semibold tracking-wide text-[#e0f0ff]">
            Settings
          </h2>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded text-[#6a8a9a] transition-colors hover:bg-[rgba(100,120,140,0.2)] hover:text-[#8899aa]"
          >
            ×
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[rgba(0,180,255,0.1)] px-6">
          {(['llm', 'license'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 font-mono text-sm tracking-wide transition-all ${
                activeTab === tab
                  ? 'border-b-2 border-[#00ccff] text-[#00ccff]'
                  : 'text-[#6a8a9a] hover:text-[#8899aa]'
              }`}
            >
              {tab === 'llm' ? 'LLM Configuration' : 'License'}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="max-h-[60vh] overflow-y-auto p-6">
          {activeTab === 'license' && (
            <div className="space-y-6">
              {licenseLoading ? (
                <div className="text-center font-mono text-sm text-[#6a8a9a]">
                  Loading license info...
                </div>
              ) : licenseStatus?.valid ? (
                <div className="space-y-4">
                  <div className="rounded border border-[rgba(0,255,136,0.2)] bg-[rgba(0,255,136,0.05)] p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <div className="h-2 w-2 rounded-full bg-[#00ff88]" />
                      <span className="font-mono text-sm font-semibold text-[#00ff88]">
                        License Active
                      </span>
                    </div>
                    <div className="space-y-2 font-mono text-sm">
                      <div className="flex justify-between">
                        <span className="text-[#6a8a9a]">License Key</span>
                        <span className="text-[#e0f0ff]">{licenseStatus.license_key}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-[#6a8a9a]">Organization</span>
                        <span className="text-[#e0f0ff]">{licenseStatus.org_name}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-[#6a8a9a]">Expires</span>
                        <span className="text-[#e0f0ff]">{licenseStatus.expiry_date}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-[#6a8a9a]">Days Remaining</span>
                        <span className={licenseStatus.days_remaining! > 30 ? 'text-[#00ff88]' : 'text-[#ffaa00]'}>
                          {licenseStatus.days_remaining} days
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rounded border border-[rgba(255,80,80,0.2)] bg-[rgba(255,40,40,0.05)] p-4 text-center">
                  <span className="font-mono text-sm text-[#ff6666]">
                    {licenseStatus?.message || 'No license activated'}
                  </span>
                </div>
              )}
            </div>
          )}

          {activeTab === 'llm' && (
            <div className="space-y-6">
              {/* Mode Selection */}
              <div>
                <label className="mb-3 block font-mono text-xs tracking-wide text-[#8899aa]">
                  CONNECTION MODE
                </label>
                <div className="flex gap-3">
                  <button
                    onClick={() => {
                      setLlmMode('api')
                      setLlmError(null)
                      setLlmSuccess(null)
                      setTestResult(null)
                    }}
                    className={`flex-1 rounded border p-4 text-left transition-all ${
                      llmMode === 'api'
                        ? 'border-[rgba(0,200,255,0.5)] bg-[rgba(0,150,255,0.15)]'
                        : 'border-[rgba(100,120,140,0.3)] bg-transparent hover:border-[rgba(100,120,140,0.5)]'
                    }`}
                  >
                    <div className="mb-1 font-mono text-sm font-semibold text-[#e0f0ff]">
                      Online (Cloud API)
                    </div>
                    <div className="font-mono text-xs text-[#6a8a9a]">
                      Use Gemini or other cloud providers
                    </div>
                  </button>
                  <button
                    onClick={() => {
                      setLlmMode('local')
                      setLlmError(null)
                      setLlmSuccess(null)
                      setTestResult(null)
                    }}
                    className={`flex-1 rounded border p-4 text-left transition-all ${
                      llmMode === 'local'
                        ? 'border-[rgba(0,200,255,0.5)] bg-[rgba(0,150,255,0.15)]'
                        : 'border-[rgba(100,120,140,0.3)] bg-transparent hover:border-[rgba(100,120,140,0.5)]'
                    }`}
                  >
                    <div className="mb-1 font-mono text-sm font-semibold text-[#e0f0ff]">
                      Offline (Local LLM)
                    </div>
                    <div className="font-mono text-xs text-[#6a8a9a]">
                      Self-hosted Ollama or compatible
                    </div>
                  </button>
                </div>
              </div>

              {/* API Key Input */}
              {llmMode === 'api' && (
                <div>
                  <label className="mb-2 block font-mono text-xs tracking-wide text-[#8899aa]">
                    API KEY
                  </label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="Enter your API key"
                    className="w-full rounded border border-[rgba(100,120,140,0.3)] bg-[rgba(20,25,35,0.8)] px-4 py-3 font-mono text-sm text-[#e0f0ff] placeholder-[#4a5a6a] outline-none transition-all focus:border-[rgba(0,180,255,0.5)]"
                  />
                  <p className="mt-2 font-mono text-xs text-[#5a6a7a]">
                    Gemini API key from Google AI Studio
                  </p>
                </div>
              )}

              {/* Local URL Input */}
              {llmMode === 'local' && (
                <div>
                  <label className="mb-2 block font-mono text-xs tracking-wide text-[#8899aa]">
                    LOCAL LLM URL
                  </label>
                  <input
                    type="text"
                    value={localUrl}
                    onChange={(e) => setLocalUrl(e.target.value)}
                    placeholder="http://localhost:11434"
                    className="w-full rounded border border-[rgba(100,120,140,0.3)] bg-[rgba(20,25,35,0.8)] px-4 py-3 font-mono text-sm text-[#e0f0ff] placeholder-[#4a5a6a] outline-none transition-all focus:border-[rgba(0,180,255,0.5)]"
                  />
                  <p className="mt-2 font-mono text-xs text-[#5a6a7a]">
                    Ollama default: http://localhost:11434
                  </p>
                </div>
              )}

              {/* Test Result / Success / Error */}
              {testResult && (
                <div
                  className={`rounded border p-3 font-mono text-sm ${
                    testResult.success
                      ? 'border-[rgba(0,255,136,0.3)] bg-[rgba(0,255,136,0.1)] text-[#00ff88]'
                      : 'border-[rgba(255,80,80,0.3)] bg-[rgba(255,40,40,0.1)] text-[#ff6666]'
                  }`}
                >
                  {testResult.success ? '✓ ' : '✗ '}
                  {testResult.message}
                </div>
              )}

              {llmSuccess && !testResult && (
                <div className="rounded border border-[rgba(0,255,136,0.3)] bg-[rgba(0,255,136,0.1)] p-3 font-mono text-sm text-[#00ff88]">
                  ✓ {llmSuccess}
                </div>
              )}

              {llmError && !testResult && (
                <div className="rounded border border-[rgba(255,80,80,0.3)] bg-[rgba(255,40,40,0.1)] p-3 font-mono text-sm text-[#ff6666]">
                  {llmError}
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex gap-3">
                <button
                  onClick={handleTestConnection}
                  disabled={llmLoading}
                  className="flex-1 rounded border border-[rgba(100,120,140,0.4)] bg-transparent py-2.5 font-mono text-sm tracking-wider text-[#8899aa] transition-all hover:border-[rgba(100,120,140,0.6)] hover:text-[#aabbcc] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {llmLoading ? 'TESTING...' : 'TEST CONNECTION'}
                </button>
                <button
                  onClick={handleSaveLLMConfig}
                  disabled={llmLoading}
                  className="flex-1 rounded border border-[rgba(0,200,255,0.4)] bg-[rgba(0,150,255,0.2)] py-2.5 font-mono text-sm font-semibold tracking-wider text-[#00ccff] transition-all hover:bg-[rgba(0,150,255,0.3)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {llmLoading ? 'SAVING...' : 'SAVE CONFIGURATION'}
                </button>
              </div>

              {/* Model Selection */}
              <div className="border-t border-[rgba(0,180,255,0.1)] pt-6">
                <div className="mb-3 flex items-center justify-between">
                  <label className="font-mono text-xs tracking-wide text-[#8899aa]">
                    MODEL SELECTION
                  </label>
                  <button
                    onClick={loadModels}
                    disabled={modelsLoading}
                    className="font-mono text-xs text-[#00ccff] hover:underline disabled:opacity-50"
                  >
                    {modelsLoading ? 'Loading...' : 'Refresh'}
                  </button>
                </div>

                {modelsError && (
                  <div className="mb-3 rounded border border-[rgba(255,80,80,0.3)] bg-[rgba(255,40,40,0.1)] p-2 font-mono text-xs text-[#ff6666]">
                    {modelsError}
                  </div>
                )}

                {models.length > 0 ? (
                  <div className="max-h-48 space-y-1.5 overflow-y-auto rounded border border-[rgba(100,120,140,0.2)] bg-[rgba(20,25,35,0.5)] p-2">
                    {models.map((model) => (
                      <button
                        key={model.id}
                        onClick={() => handleModelSelect(model.id)}
                        className={`w-full rounded px-3 py-2 text-left font-mono text-sm transition-all ${
                          selectedModelId === model.id
                            ? 'border border-[rgba(0,200,255,0.4)] bg-[rgba(0,150,255,0.15)] text-[#00ccff]'
                            : 'border border-transparent text-[#8899aa] hover:bg-[rgba(100,120,140,0.1)] hover:text-[#e0f0ff]'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span>{model.name}</span>
                          <span className="text-xs text-[#5a6a7a]">
                            {'publisher' in model ? model.publisher : 'provider' in model ? model.provider : ''}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : !modelsLoading && !modelsError ? (
                  <div className="rounded border border-[rgba(100,120,140,0.2)] bg-[rgba(20,25,35,0.5)] p-4 text-center font-mono text-sm text-[#6a8a9a]">
                    Save your LLM configuration to see available models
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
