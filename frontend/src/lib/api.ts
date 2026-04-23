const BASE = 'http://localhost:8000'

export interface CommandResponse {
  asset_id: string
  response: string
  prompt: string
  requires_confirmation?: boolean
  already_scanned_buildings?: number[]
}

export interface SimulationSurvivor {
  x: number
  y: number
  z: number
  supplied: boolean
}

export interface SimulationBuilding {
  building_id: number
  detected_survivors: SimulationSurvivor[]
}

export interface SimulationState {
  id: string
  scanned_buildings: SimulationBuilding[]
  created_at?: string | null
  updated_at?: string | null
}

export interface DetectedSurvivor {
  x: number
  y: number
  z: number
}

export interface SupplyDispatchEvent {
  asset_id: string
  survivor: { x: number; y: number; z: number }
  building?: { x: number; z: number }
  drop_point: { x: number; y: number; z: number }
}

export type AgentStreamEvent =
  | { type: 'tool_call'; name: string; args: Record<string, unknown>; agent: string }
  | { type: 'tool_result'; name: string; success: boolean; result: string; survivors?: DetectedSurvivor[]; supply_dispatches?: SupplyDispatchEvent[] }
  | { type: 'thinking'; text: string; agent: string }
  | { type: 'text'; text: string; agent: string; survivors?: DetectedSurvivor[] }
  | { type: 'final'; text: string; agent: string }
  | { type: 'heartbeat'; elapsed: number }
  | { type: 'error'; text: string }
  | { type: 'done'; ttft_ms: number | null; tps: number | null }
  
export interface UplinkResponse {
  asset_id: string
  grpc_host: string
  grpc_port: number
  message: string
}

export interface DiscoveredDrone {
  asset_id: string
  x: number
  y: number
  z: number
  battery: number
  status: string
  signal_pct: number
}

export interface FleetDrone {
  asset_id: string
  active: boolean
  uplinked: boolean
  battery: number | null
  status: string
  x: number | null
  y: number | null
  z: number | null
  grpc_host: string | null
  grpc_port: number | null
}

export interface AutoRecallConfig {
  enabled: boolean
  battery_threshold: number
  cooldown_seconds: number
}

export interface NetworkMockStatus {
  mode: string
  updated_at: string | null
  source: string | null
  target_ssid: string | null
  active_ssids: string[]
  container_count: number
  status_file: string
}

export async function uplink(assetId: string): Promise<UplinkResponse> {
  const res = await fetch(`${BASE}/uplink/${assetId}`, { method: 'POST' })
  if (!res.ok) throw new Error(`Uplink failed: ${res.status}`)
  return res.json()
}

export async function sendCommand(
  assetId: string,
  prompt: string,
  simulationId?: string,
  confirmRescan = false,
): Promise<CommandResponse> {
  const res = await fetch(`${BASE}/command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      asset_id: assetId,
      prompt,
      simulation_id: simulationId,
      confirm_rescan: confirmRescan,
    }),
  })
  if (!res.ok) throw new Error(`Command failed: ${res.status}`)
  return res.json()
}

export async function createSimulation(simulationId?: string): Promise<SimulationState> {
  const res = await fetch(`${BASE}/simulation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ simulation_id: simulationId }),
  })
  if (!res.ok) throw new Error(`Simulation create failed: ${res.status}`)
  return res.json()
}

export async function getSimulation(simulationId: string): Promise<SimulationState> {
  const res = await fetch(`${BASE}/simulation/${simulationId}`)
  if (!res.ok) throw new Error(`Simulation lookup failed: ${res.status}`)
  return res.json()
}

export async function syncSimulationState(
  simulationId: string,
  scannedBuildings: SimulationBuilding[],
): Promise<SimulationState> {
  const res = await fetch(`${BASE}/simulation/${simulationId}/state`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scanned_buildings: scannedBuildings }),
  })
  if (!res.ok) throw new Error(`Simulation sync failed: ${res.status}`)
  return res.json()
}

export async function scan(): Promise<{ discovered: DiscoveredDrone[] }> {
  const res = await fetch(`${BASE}/scan`)
  if (!res.ok) throw new Error(`Scan failed: ${res.status}`)
  return res.json()
}

export async function getFleet(): Promise<{ fleet: FleetDrone[]; count: number; active_count: number }> {
  const res = await fetch(`${BASE}/fleet`)
  if (!res.ok) throw new Error(`Fleet lookup failed: ${res.status}`)
  return res.json()
}

export async function getAutoRecallConfig(): Promise<AutoRecallConfig> {
  const res = await fetch(`${BASE}/config/auto-recall`)
  if (!res.ok) throw new Error(`Auto-recall config lookup failed: ${res.status}`)
  return res.json()
}

export async function getNetworkMockStatus(): Promise<NetworkMockStatus> {
  const res = await fetch(`${BASE}/network/mock-status`)
  if (!res.ok) throw new Error(`Network mock status lookup failed: ${res.status}`)
  return res.json()
}

export async function* streamCommand(
  assetId: string,
  prompt: string,
  simulationId?: string,
  confirmRescan = false,
  signal?: AbortSignal,
): AsyncGenerator<AgentStreamEvent> {
  const res = await fetch(`${BASE}/command/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      asset_id: assetId,
      prompt,
      simulation_id: simulationId,
      confirm_rescan: confirmRescan,
    }),
    signal,
  })
  if (!res.ok) throw new Error(`Command stream failed: ${res.status}`)
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done || signal?.aborted) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try { yield JSON.parse(line.slice(6)) as AgentStreamEvent } catch { /* ignore */ }
        }
      }
    }
  } finally {
    reader.cancel()
  }
}

export async function setDroneSpeed(assetId: string, speed: number): Promise<void> {
  const res = await fetch(`${BASE}/drone/${assetId}/speed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speed }),
  })
  if (!res.ok) throw new Error(`Set speed failed: ${res.status}`)
}

export async function resetDroneToBase(assetId: string): Promise<void> {
  const res = await fetch(`${BASE}/drone/${assetId}/reset`, { method: 'POST' })
  if (!res.ok) throw new Error(`Reset failed: ${res.status}`)
}

export async function recallFleet(): Promise<void> {
  const res = await fetch(`${BASE}/fleet/recall`, { method: 'POST' })
  if (!res.ok) throw new Error(`Fleet recall failed: ${res.status}`)
}

export async function setFleetSpeed(speed: number): Promise<void> {
  const res = await fetch(`${BASE}/fleet/speed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speed }),
  })
  if (!res.ok) throw new Error(`Fleet speed failed: ${res.status}`)
}

export async function switchWorld(worldId: number): Promise<void> {
  await fetch(`${BASE}/world/${worldId}`, { method: 'POST' })
}

export async function deployScout(): Promise<void> {
  await fetch(`${BASE}/scout/sweep`, { method: 'POST' })
}

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) })
    return res.ok
  } catch {
    return false
  }
}
