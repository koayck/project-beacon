import { useEffect, useRef, useState } from 'react'

export interface TelemetryPayload {
  asset_id: string
  x: number
  y: number
  z: number
  battery: number
  status: string
  timestamp_ms: number
}

export type DroneMap = Record<string, TelemetryPayload>

export function useTelemetry(url: string): DroneMap {
  const [drones, setDrones] = useState<DroneMap>({})
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const payload: TelemetryPayload = JSON.parse(e.data)
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

  return drones
}
