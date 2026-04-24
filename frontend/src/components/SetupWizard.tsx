'use client'

import { useState, useCallback } from 'react'
import {
  getStoredConfig,
  saveConfig,
  activateLicense,
  configureLLM,
  testLLMConnection,
  listModels,
  setSelectedModel,
  listVertexModels,
  type LLMConfig,
  type ModelInfo,
  type VertexModelInfo,
} from '@/lib/config'

type Step = 'license' | 'llm' | 'complete'

interface SetupWizardProps {
  onComplete: () => void
}

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const [step, setStep] = useState<Step>('license')
  const [licenseKey, setLicenseKey] = useState('')
  const [licenseError, setLicenseError] = useState<string | null>(null)
  const [licenseLoading, setLicenseLoading] = useState(false)
  const [orgName, setOrgName] = useState<string | null>(null)

  const [llmMode, setLlmMode] = useState<'api' | 'local'>('api')
  const [apiKey, setApiKey] = useState('')
  const [localUrl, setLocalUrl] = useState('http://localhost:11434')
  const [llmError, setLlmError] = useState<string | null>(null)
  const [llmLoading, setLlmLoading] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const [models, setModels] = useState<(ModelInfo | VertexModelInfo)[]>([])
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [llmConfigured, setLlmConfigured] = useState(false)

  const handleLicenseSubmit = useCallback(async () => {
    if (!licenseKey.trim()) {
      setLicenseError('Please enter a license key')
      return
    }

    setLicenseLoading(true)
    setLicenseError(null)

    try {
      const status = await activateLicense(licenseKey.trim())
      if (status.valid) {
        setOrgName(status.org_name)
        const config = getStoredConfig()
        saveConfig({ ...config, licenseKey: licenseKey.trim() })
        setStep('llm')
      } else {
        setLicenseError(status.message || 'Invalid license key')
      }
    } catch (err) {
      setLicenseError(err instanceof Error ? err.message : 'License activation failed')
    } finally {
      setLicenseLoading(false)
    }
  }, [licenseKey])

  const loadModels = useCallback(async () => {
    setModelsLoading(true)
    setModelsError(null)
    try {
      if (llmMode === 'api') {
        const modelList = await listVertexModels()
        setModels(modelList)
      } else {
        const modelList = await listModels()
        setModels(modelList)
      }
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Failed to load models')
      setModels([])
    } finally {
      setModelsLoading(false)
    }
  }, [llmMode])

  const handleTestConnection = useCallback(async () => {
    setLlmLoading(true)
    setLlmError(null)
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
  }, [llmMode, apiKey, localUrl])

  const handleSaveAndLoadModels = useCallback(async () => {
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

    const llmConfig: LLMConfig =
      llmMode === 'api' ? { mode: 'api', apiKey: apiKey.trim() } : { mode: 'local', localUrl: localUrl.trim() }

    try {
      await configureLLM(llmConfig)

      setLlmConfigured(true)
      const config = getStoredConfig()
      saveConfig({ ...config, llm: llmConfig })

      await loadModels()
    } catch (err) {
      setLlmError(err instanceof Error ? err.message : 'LLM configuration failed')
    } finally {
      setLlmLoading(false)
    }
  }, [llmMode, apiKey, localUrl, loadModels])

  const handleModelSelect = useCallback(async (modelId: string) => {
    setSelectedModelId(modelId)
    try {
      await setSelectedModel(modelId)
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Failed to select model')
    }
  }, [])

  const handleLLMSubmit = useCallback(async () => {
    if (!llmConfigured) {
      setLlmError('Please save LLM configuration first')
      return
    }
    if (!selectedModelId) {
      setLlmError('Please select a model')
      return
    }

    const llmConfig: LLMConfig =
      llmMode === 'api' ? { mode: 'api', apiKey: apiKey.trim() } : { mode: 'local', localUrl: localUrl.trim() }

    const config = getStoredConfig()
    saveConfig({ ...config, llm: llmConfig, setupCompleted: true })
    setStep('complete')
    setTimeout(onComplete, 1500)
  }, [llmConfigured, selectedModelId, llmMode, apiKey, localUrl, onComplete])

  const formatLicenseKey = (value: string) => {
    const cleaned = value.toUpperCase().replace(/[^A-Z0-9]/g, '')
    const parts: string[] = []

    if (cleaned.length > 0) {
      parts.push('BEACON')
    }

    let remaining = cleaned.replace(/^BEACON/, '')
    for (let i = 0; i < 4 && remaining.length > 0; i++) {
      parts.push(remaining.slice(0, 4))
      remaining = remaining.slice(4)
    }

    return parts.join('-')
  }

  const handleLicenseKeyChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    if (raw.startsWith('BEACON-') || raw.length <= 6) {
      setLicenseKey(raw.toUpperCase())
    } else {
      setLicenseKey(formatLicenseKey(raw))
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#060610] p-4">
      <div className="w-full max-w-lg">
        {/* Header */}
        <div className="mb-8 text-center">
          <div className="mb-4 flex items-center justify-center gap-2">
            <div className="h-3 w-3 animate-pulse rounded-full bg-[#00ccff] shadow-[0_0_15px_rgba(0,200,255,0.6)]" />
            <h1 className="font-mono text-2xl font-bold tracking-[4px] text-[#e0f0ff]">
              PROJECT BEACON
            </h1>
          </div>
          <p className="font-mono text-sm tracking-wide text-[#6a8a9a]">
            Setup Wizard
          </p>
        </div>

        {/* Progress Steps */}
        <div className="mb-8 flex items-center justify-center gap-2">
          {(['license', 'llm', 'complete'] as const).map((s, i) => {
            const currentStepIndex = ['license', 'llm', 'complete'].indexOf(step)
            const isCompleted = i < currentStepIndex
            const isClickable = isCompleted && step !== 'complete'

            return (
              <div key={s} className="flex items-center gap-2">
                <button
                  onClick={() => isClickable && setStep(s)}
                  disabled={!isClickable}
                  className={`flex h-8 w-8 items-center justify-center rounded-full border font-mono text-sm transition-all ${
                    step === s
                      ? 'border-[#00ccff] bg-[rgba(0,200,255,0.15)] text-[#00ccff]'
                      : isCompleted
                      ? 'border-[#00ff88] bg-[rgba(0,255,136,0.15)] text-[#00ff88] hover:bg-[rgba(0,255,136,0.25)] cursor-pointer'
                      : 'border-[#3a4a5a] bg-transparent text-[#5a6a7a] cursor-default'
                  }`}
                >
                  {isCompleted ? '✓' : i + 1}
                </button>
                {i < 2 && (
                  <div
                    className={`h-px w-12 ${
                      isCompleted ? 'bg-[#00ff88]' : 'bg-[#3a4a5a]'
                    }`}
                  />
                )}
              </div>
            )
          })}
        </div>

        {/* Step Content */}
        <div className="rounded-lg border border-[rgba(0,180,255,0.15)] bg-[rgba(10,15,25,0.9)] p-6 backdrop-blur-xl">
          {step === 'license' && (
            <div className="space-y-6">
              <div>
                <h2 className="mb-2 font-mono text-lg font-semibold text-[#e0f0ff]">
                  License Activation
                </h2>
                <p className="font-mono text-sm text-[#6a8a9a]">
                  Enter your license key to activate Project Beacon
                </p>
              </div>

              <div>
                <label className="mb-2 block font-mono text-xs tracking-wide text-[#8899aa]">
                  LICENSE KEY
                </label>
                <input
                  type="text"
                  value={licenseKey}
                  onChange={handleLicenseKeyChange}
                  placeholder="BEACON-XXXX-XXXX-XXXX-XXXX"
                  className="w-full rounded border border-[rgba(100,120,140,0.3)] bg-[rgba(20,25,35,0.8)] px-4 py-3 font-mono text-sm tracking-wider text-[#e0f0ff] placeholder-[#4a5a6a] outline-none transition-all focus:border-[rgba(0,180,255,0.5)] focus:shadow-[0_0_15px_rgba(0,180,255,0.1)]"
                  onKeyDown={(e) => e.key === 'Enter' && handleLicenseSubmit()}
                />
                <p className="mt-2 font-mono text-xs text-[#5a6a7a]">
                  Format: BEACON-XXXX-XXXX-XXXX-XXXX
                </p>
              </div>

              {licenseError && (
                <div className="rounded border border-[rgba(255,80,80,0.3)] bg-[rgba(255,40,40,0.1)] p-3 font-mono text-sm text-[#ff6666]">
                  {licenseError}
                </div>
              )}

              <button
                onClick={handleLicenseSubmit}
                disabled={licenseLoading || !licenseKey.trim()}
                className={`w-full rounded border py-3 font-mono text-sm font-semibold tracking-wider transition-all ${
                  licenseLoading || !licenseKey.trim()
                    ? 'cursor-not-allowed border-[#3a4a5a] bg-[#2a3a4a] text-[#5a6a7a]'
                    : 'border-[rgba(0,200,255,0.4)] bg-[rgba(0,150,255,0.2)] text-[#00ccff] hover:bg-[rgba(0,150,255,0.3)]'
                }`}
              >
                {licenseLoading ? 'ACTIVATING...' : 'ACTIVATE LICENSE'}
              </button>
            </div>
          )}

          {step === 'llm' && (
            <div className="space-y-6">
              <div>
                <h2 className="mb-2 font-mono text-lg font-semibold text-[#e0f0ff]">
                  LLM Configuration
                </h2>
                <p className="font-mono text-sm text-[#6a8a9a]">
                  {orgName && <span className="text-[#00ff88]">Welcome, {orgName}!</span>}
                  {orgName && <br />}
                  Choose how to connect to the AI model
                </p>
              </div>

              {/* Mode Selection */}
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    setLlmMode('api')
                    setLlmError(null)
                    setTestResult(null)
                  }}
                  className={`flex-1 rounded border p-4 text-left transition-all ${
                    llmMode === 'api'
                      ? 'border-[rgba(0,200,255,0.5)] bg-[rgba(0,150,255,0.15)]'
                      : 'border-[rgba(100,120,140,0.3)] bg-transparent hover:border-[rgba(100,120,140,0.5)]'
                  }`}
                >
                  <div className="mb-1 font-mono text-sm font-semibold text-[#e0f0ff]">
                    Cloud API
                  </div>
                  <div className="font-mono text-xs text-[#6a8a9a]">
                    Use Gemini or other cloud providers
                  </div>
                </button>
                <button
                  onClick={() => {
                    setLlmMode('local')
                    setLlmError(null)
                    setTestResult(null)
                  }}
                  className={`flex-1 rounded border p-4 text-left transition-all ${
                    llmMode === 'local'
                      ? 'border-[rgba(0,200,255,0.5)] bg-[rgba(0,150,255,0.15)]'
                      : 'border-[rgba(100,120,140,0.3)] bg-transparent hover:border-[rgba(100,120,140,0.5)]'
                  }`}
                >
                  <div className="mb-1 font-mono text-sm font-semibold text-[#e0f0ff]">
                    Local LLM
                  </div>
                  <div className="font-mono text-xs text-[#6a8a9a]">
                    Self-hosted Ollama or compatible
                  </div>
                </button>
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

              {/* Test Result */}
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

              {llmError && !testResult && (
                <div className="rounded border border-[rgba(255,80,80,0.3)] bg-[rgba(255,40,40,0.1)] p-3 font-mono text-sm text-[#ff6666]">
                  {llmError}
                </div>
              )}

              <div className="flex gap-3">
                <button
                  onClick={() => {
                    setStep('license')
                    setLlmError(null)
                    setTestResult(null)
                    setLlmConfigured(false)
                    setModels([])
                  }}
                  disabled={llmLoading}
                  className="rounded border border-[rgba(100,120,140,0.4)] bg-transparent px-4 py-3 font-mono text-sm tracking-wider text-[#8899aa] transition-all hover:border-[rgba(100,120,140,0.6)] hover:text-[#aabbcc]"
                >
                  ← BACK
                </button>
                <button
                  onClick={handleTestConnection}
                  disabled={llmLoading}
                  className="flex-1 rounded border border-[rgba(100,120,140,0.4)] bg-transparent py-3 font-mono text-sm tracking-wider text-[#8899aa] transition-all hover:border-[rgba(100,120,140,0.6)] hover:text-[#aabbcc]"
                >
                  {llmLoading ? 'TESTING...' : 'TEST CONNECTION'}
                </button>
                <button
                  onClick={handleSaveAndLoadModels}
                  disabled={llmLoading || llmConfigured}
                  className={`flex-1 rounded border py-3 font-mono text-sm font-semibold tracking-wider transition-all ${
                    llmLoading || llmConfigured
                      ? 'cursor-not-allowed border-[#3a4a5a] bg-[#2a3a4a] text-[#5a6a7a]'
                      : 'border-[rgba(0,200,255,0.4)] bg-[rgba(0,150,255,0.2)] text-[#00ccff] hover:bg-[rgba(0,150,255,0.3)]'
                  }`}
                >
                  {llmLoading ? 'SAVING...' : llmConfigured ? 'SAVED ✓' : 'SAVE & LOAD MODELS'}
                </button>
              </div>

              {/* Model Selection */}
              {llmConfigured && (
                <div className="space-y-4 border-t border-[rgba(0,180,255,0.1)] pt-6">
                  <div className="flex items-center justify-between">
                    <label className="font-mono text-xs tracking-wide text-[#8899aa]">
                      SELECT MODEL
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
                    <div className="rounded border border-[rgba(255,80,80,0.3)] bg-[rgba(255,40,40,0.1)] p-2 font-mono text-xs text-[#ff6666]">
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
                      No models found
                    </div>
                  ) : null}

                  <button
                    onClick={handleLLMSubmit}
                    disabled={!selectedModelId}
                    className={`w-full rounded border py-3 font-mono text-sm font-semibold tracking-wider transition-all ${
                      !selectedModelId
                        ? 'cursor-not-allowed border-[#3a4a5a] bg-[#2a3a4a] text-[#5a6a7a]'
                        : 'border-[rgba(0,200,255,0.4)] bg-[rgba(0,150,255,0.2)] text-[#00ccff] hover:bg-[rgba(0,150,255,0.3)]'
                    }`}
                  >
                    CONTINUE →
                  </button>
                </div>
              )}
            </div>
          )}

          {step === 'complete' && (
            <div className="space-y-6 text-center">
              <div className="flex justify-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full border-2 border-[#00ff88] bg-[rgba(0,255,136,0.15)]">
                  <span className="text-3xl text-[#00ff88]">✓</span>
                </div>
              </div>
              <div>
                <h2 className="mb-2 font-mono text-lg font-semibold text-[#e0f0ff]">
                  Setup Complete
                </h2>
                <p className="font-mono text-sm text-[#6a8a9a]">
                  Project Beacon is ready to launch
                </p>
              </div>
              <div className="font-mono text-sm text-[#00ccff]">
                Launching Ground Control Station...
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mt-6 text-center font-mono text-xs text-[#4a5a6a]">
          Offline-first Ground Control Station for SAR Drone Swarms
        </div>
      </div>
    </div>
  )
}
