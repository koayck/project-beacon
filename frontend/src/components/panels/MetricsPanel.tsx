'use client'

import { useState, useEffect, useRef, useMemo } from 'react'
import type { DroneMap } from '@/lib/ws'
import type { ActivityItem } from './StatPanel'

interface MetricsPanelProps {
  missionStartTs: number | null
  activities: ActivityItem[]
  detectedCount: number
  rescuedCount: number
  totalSurvivors: number
  drones: DroneMap
  lastTtftMs: number | null
  survivorDetectionTimestamps: Map<string, number>
  survivorDeliveryTimestamps: Map<string, number>
}

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function MetricRow({ label, value, unit, color }: { label: string; value: string; unit?: string; color: string }) {
  return (
    <div className="flex items-center justify-between py-[3px]">
      <span className="text-[11px] tracking-[0.8px] text-[#667788]">{label}</span>
      <span className={`text-[13px] font-bold tabular-nums ${color}`}>
        {value}
        {unit && <span className="ml-0.5 text-[10px] font-normal opacity-60">{unit}</span>}
      </span>
    </div>
  )
}

export function MetricsPanel({
  missionStartTs,
  activities,
  detectedCount,
  rescuedCount,
  totalSurvivors,
  drones,
  lastTtftMs,
  survivorDetectionTimestamps,
  survivorDeliveryTimestamps,
}: MetricsPanelProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Live mission timer
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (missionStartTs) {
      setElapsed(Date.now() - missionStartTs)
      intervalRef.current = setInterval(() => {
        setElapsed(Date.now() - missionStartTs)
      }, 1000)
    } else {
      setElapsed(0)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [missionStartTs])

  // Derived metrics
  const buildingsScanned = useMemo(() => {
    const seen = new Set<string>()
    for (const a of activities) {
      if (a.category === 'scan' && a.label === 'Scanning building' && a.status === 'done' && a.detail) {
        seen.add(a.detail)
      }
    }
    return seen.size
  }, [activities])

  const commandsIssued = useMemo(
    () => activities.filter(a => a.category === 'dispatch').length,
    [activities],
  )

  const toolCallCount = useMemo(
    () => activities.filter(a =>
      a.category === 'movement' || a.category === 'scan',
    ).length,
    [activities],
  )

  // Fleet utilization: % of drones not IDLE
  const droneEntries = Object.values(drones)
  const fleetUtil = droneEntries.length > 0
    ? Math.round((droneEntries.filter(d => d.status !== 'IDLE').length / droneEntries.length) * 100)
    : 0

  // Average rescue time
  const avgRescueMs = useMemo(() => {
    if (survivorDeliveryTimestamps.size === 0) return null
    let total = 0
    let count = 0
    survivorDeliveryTimestamps.forEach((deliveryTs, key) => {
      const detectionTs = survivorDetectionTimestamps.get(key)
      if (detectionTs) {
        total += deliveryTs - detectionTs
        count++
      }
    })
    return count > 0 ? total / count : null
  }, [survivorDetectionTimestamps, survivorDeliveryTimestamps])

  // Average battery across fleet
  const avgBattery = droneEntries.length > 0
    ? Math.round(droneEntries.reduce((sum, d) => sum + d.battery, 0) / droneEntries.length)
    : null

  const rescueRate = totalSurvivors > 0
    ? Math.round((rescuedCount / totalSurvivors) * 100)
    : 0

  return (
    <div className="pointer-events-auto flex min-w-[220px] flex-col overflow-hidden rounded-lg border border-l-2 border-[rgba(40,140,180,0.2)] border-l-[#3388cc] bg-[linear-gradient(135deg,rgba(6,8,16,0.88),rgba(4,6,14,0.82))] font-mono text-[13px] leading-[1.7] text-[#8899bb] shadow-[0_4px_30px_rgba(0,0,0,0.4),inset_0_1px_0_rgba(50,136,204,0.06)] backdrop-blur-[12px]">
      {/* Header */}
      <button
        onClick={() => setCollapsed(c => !c)}
        className="flex w-full cursor-pointer items-center justify-between border-none bg-[linear-gradient(135deg,rgba(6,8,16,0.95),rgba(4,6,14,0.9))] px-[14px] py-[8px] text-left font-mono"
      >
        <span className="text-[11px] font-bold tracking-[1.5px] text-[#5599bb]">
          PERFORMANCE
        </span>
        <span className="text-[10px] text-[#556]">{collapsed ? '▸' : '▾'}</span>
      </button>

      {!collapsed && (
        <div className="px-[14px] pb-[10px]">
          {/* Mission timer — prominent */}
          <div className="mb-[6px] flex items-center justify-between border-b border-[rgba(40,140,180,0.1)] pb-[6px]">
            <span className="text-[10px] tracking-[1px] text-[#556677]">MISSION TIME</span>
            <span className={`text-[18px] font-bold tabular-nums ${missionStartTs ? 'text-[#44ddff]' : 'text-[#334455]'}`}>
              {formatDuration(elapsed)}
            </span>
          </div>

          {/* Rescue progress bar */}
          <div className="mb-[8px]">
            <div className="mb-[2px] flex items-center justify-between">
              <span className="text-[10px] tracking-[0.8px] text-[#556677]">RESCUE PROGRESS</span>
              <span className="text-[11px] font-bold tabular-nums text-[#44dd88]">{rescueRate}%</span>
            </div>
            <div className="h-[4px] w-full overflow-hidden rounded-full bg-[rgba(40,60,80,0.4)]">
              <div
                className="h-full rounded-full bg-[linear-gradient(90deg,#226644,#44dd88)] transition-all duration-700"
                style={{ width: `${rescueRate}%` }}
              />
            </div>
            <div className="mt-[2px] text-right text-[10px] tabular-nums text-[#556677]">
              {rescuedCount}/{totalSurvivors} survivors
            </div>
          </div>

          {/* Stats grid */}
          <div className="space-y-0 border-t border-[rgba(40,140,180,0.1)] pt-[4px]">
            <MetricRow
              label="PLANNING (TTFT)"
              value={lastTtftMs !== null ? (lastTtftMs / 1000).toFixed(1) : '--'}
              unit="s"
              color="text-[#cc88ff]"
            />
            <MetricRow
              label="AVG RESCUE TIME"
              value={avgRescueMs !== null ? formatDuration(avgRescueMs) : '--:--'}
              color="text-[#ffaa33]"
            />
            <MetricRow
              label="BUILDINGS SCANNED"
              value={String(buildingsScanned)}
              color="text-[#55aaff]"
            />
            <MetricRow
              label="DETECTED"
              value={`${detectedCount}/${totalSurvivors}`}
              color="text-[#44ff66]"
            />
            <MetricRow
              label="COMMANDS ISSUED"
              value={String(commandsIssued)}
              color="text-[#e0e8ff]"
            />
            <MetricRow
              label="TOOL CALLS"
              value={String(toolCallCount)}
              color="text-[#8899bb]"
            />
            <MetricRow
              label="FLEET UTILIZATION"
              value={String(fleetUtil)}
              unit="%"
              color="text-[#44ccff]"
            />
            {avgBattery !== null && (
              <MetricRow
                label="AVG BATTERY"
                value={String(avgBattery)}
                unit="%"
                color={avgBattery > 50 ? 'text-[#44dd88]' : avgBattery > 20 ? 'text-[#ffaa33]' : 'text-[#ff5555]'}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}