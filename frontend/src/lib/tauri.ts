export interface DesktopStatus {
  runtime: string
  app_name: string
  backend_mode: string
}

export interface NetworkStatus {
  watcher_running: boolean
  target_ssid: string
  note: string
}

export interface SidecarStatus {
  backend_running: boolean
  note: string
}

export function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__)
}

export async function invokeTauriCommand<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  if (!isTauriRuntime()) {
    throw new Error('Tauri runtime is not available')
  }

  const { invoke } = await import('@tauri-apps/api/core')
  return invoke<T>(command, args)
}

export async function getNetworkStatus(): Promise<NetworkStatus> {
  return invokeTauriCommand<NetworkStatus>('network_status')
}

export async function startNetworkWatcher(targetSsid?: string): Promise<string> {
  return invokeTauriCommand<string>('start_network_watcher', {
    targetSsid: targetSsid ?? null
  })
}

export async function stopNetworkWatcher(): Promise<string> {
  return invokeTauriCommand<string>('stop_network_watcher')
}

export async function getBackendSidecarStatus(): Promise<SidecarStatus> {
  return invokeTauriCommand<SidecarStatus>('backend_sidecar_status')
}

export async function startBackendSidecar(): Promise<string> {
  return invokeTauriCommand<string>('start_backend_sidecar')
}

export async function stopBackendSidecar(): Promise<string> {
  return invokeTauriCommand<string>('stop_backend_sidecar')
}
