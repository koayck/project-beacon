'use client'

import { useState, useEffect, useCallback, type ReactNode } from 'react'
import { SetupWizard } from './SetupWizard'
import { getStoredConfig, getLicenseStatus } from '@/lib/config'

interface AppShellProps {
  children: ReactNode
}

type AppState = 'loading' | 'setup' | 'ready'

export function AppShell({ children }: AppShellProps) {
  const [appState, setAppState] = useState<AppState>('loading')

  const checkSetupStatus = useCallback(async () => {
    const config = getStoredConfig()

    if (!config.setupCompleted || !config.licenseKey) {
      setAppState('setup')
      return
    }

    try {
      const licenseStatus = await getLicenseStatus()
      if (!licenseStatus.valid) {
        setAppState('setup')
        return
      }
    } catch {
      setAppState('setup')
      return
    }

    setAppState('ready')
  }, [])

  useEffect(() => {
    checkSetupStatus()
  }, [checkSetupStatus])

  const handleSetupComplete = useCallback(() => {
    setAppState('ready')
  }, [])

  if (appState === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#060610]">
        <div className="text-center">
          <div className="mb-4 flex items-center justify-center gap-2">
            <div className="h-3 w-3 animate-pulse rounded-full bg-[#00ccff] shadow-[0_0_15px_rgba(0,200,255,0.6)]" />
            <span className="font-mono text-xl font-bold tracking-[4px] text-[#e0f0ff]">
              PROJECT BEACON
            </span>
          </div>
          <div className="font-mono text-sm text-[#6a8a9a]">Initializing...</div>
        </div>
      </div>
    )
  }

  if (appState === 'setup') {
    return <SetupWizard onComplete={handleSetupComplete} />
  }

  return <>{children}</>
}
