export interface DesktopStatus {
  runtime: string
  app_name: string
  backend_mode: string
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
