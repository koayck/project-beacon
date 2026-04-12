import { useEffect, useRef, useState } from 'react'

export interface TelemetryPayload {
  asset_id: string
  x: number
  y: number
  z: number
  battery: number
  status: string
  timestamp_ms: number
  // environment awareness fields (enriched by drone-sim world sensor)
  nearby_obstacles?: number
  nearest_obstacle_dist?: number
  survivors_in_range?: number
  over_flood?: boolean
  altitude_agl?: number
  heading_deg?: number
  scan_tilt_deg?: number
}

export type DroneMap = Record<string, TelemetryPayload>

/** If no heartbeat arrives for this long, mark the drone OFFLINE. */
const STALE_TIMEOUT_MS = 3000

export function useTelemetry(url: string): DroneMap {
  const [drones, setDrones] = useState<DroneMap>({})
  const wsRef = useRef<WebSocket | null>(null)
  const lastSeenRef = useRef<Record<string, number>>({})

  useEffect(() => {
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const payload: TelemetryPayload = JSON.parse(e.data)
          lastSeenRef.current[payload.asset_id] = Date.now()
          setDrones(prev => ({ ...prev, [payload.asset_id]: payload }))
        } catch { /* ignore malformed packets */ }
      }

      ws.onclose = () => {
        if (!cancelled) setTimeout(connect, 2000)
      }
    }

    connect()
    return () => {
      cancelled = true
      wsRef.current?.close()
    }
  }, [url])

  // Periodically mark drones whose heartbeats have stopped as OFFLINE.
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now()
      setDrones(prev => {
        let changed = false
        const next = { ...prev }
        for (const [id, entry] of Object.entries(next)) {
          const lastSeen = lastSeenRef.current[id]
          if (
            entry.status !== 'OFFLINE'
            && lastSeen !== undefined
            && now - lastSeen > STALE_TIMEOUT_MS
          ) {
            next[id] = { ...entry, status: 'OFFLINE' }
            changed = true
          }
        }
        return changed ? next : prev
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [])

  return drones
}
