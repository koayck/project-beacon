import type { DroneMap } from '@/lib/ws'
import { Progress } from '@/components/ui/progress'
import { useState } from 'react'

interface DroneStatusPanelProps {
  drones: DroneMap
  dronesVisible?: boolean
  onToggleDronesVisible?: () => void
}


function statusTextColorClass(status: string): string {
  switch (status.toUpperCase()) {
    case 'MOVING': return 'text-[#00ff88]'
    case 'SCANNING': return 'text-[#ffaa00]'
    case 'RETURNING': return 'text-[#00ccff]'
    case 'IDLE': return 'text-[#7799bb]'
    default: return 'text-[#556677]'
  }
}

function droneCardClass(status: string): string {
  switch (status.toUpperCase()) {
    case 'MOVING':
      return 'border-[rgba(0,255,136,0.19)] border-l-[#00ff88]'
    case 'SCANNING':
      return 'border-[rgba(255,170,0,0.19)] border-l-[#ffaa00]'
    case 'RETURNING':
      return 'border-[rgba(0,204,255,0.19)] border-l-[#00ccff]'
    case 'IDLE':
      return 'border-[rgba(119,153,187,0.19)] border-l-[#7799bb]'
    default:
      return 'border-[rgba(85,102,119,0.19)] border-l-[#556677]'
  }
}

function batteryFillClass(pct: number): string {
  if (pct > 50) return 'bg-[#44cc66]'
  if (pct > 20) return 'bg-[#ffcc00]'
  if (pct > 10) return 'bg-[#ff8800]'
  return 'bg-[#ff3333]'
}

function batteryTextClass(pct: number): string {
  return batteryFillClass(pct).replace('bg-', 'text-')
}

function batteryTrackClass(pct: number): string {
  if (pct > 50) return 'bg-[#44cc66]'
  if (pct > 20) return 'bg-[#ffcc00]'
  if (pct > 10) return 'bg-[#ff8800]'
  return 'bg-[#ff3333]'
}

function statusGlowClass(status: string): string {
  switch (status.toUpperCase()) {
    case 'MOVING': return 'shadow-[0_0_6px_#00ff8880]'
    case 'SCANNING': return 'shadow-[0_0_6px_#ffaa0080]'
    case 'RETURNING': return 'shadow-[0_0_6px_#00ccff80]'
    case 'IDLE': return 'shadow-[0_0_6px_#7799bb80]'
    default: return 'shadow-[0_0_6px_#55667780]'
  }
}

export function DroneStatusPanel({
  drones,
  dronesVisible,
  onToggleDronesVisible,
}: DroneStatusPanelProps) {
  const [localDronesVisible, setLocalDronesVisible] = useState(true)
  const visible = dronesVisible ?? localDronesVisible
  const handleToggleVisible = () => {
    if (onToggleDronesVisible) {
      onToggleDronesVisible()
      return
    }
    setLocalDronesVisible(prev => !prev)
  }

  const entries = Object.values(drones)
  if (entries.length === 0) return null

  return (
    <div className="pointer-events-auto min-w-[240px] overflow-hidden rounded-lg border border-[rgba(40,140,180,0.2)] bg-[linear-gradient(135deg,rgba(6,8,16,0.88),rgba(4,6,14,0.82))] p-[8px_10px] font-mono shadow-[0_4px_30px_rgba(0,0,0,0.4),inset_0_1px_0_rgba(80,140,180,0.08)] backdrop-blur-[12px]">
      <button
        onClick={handleToggleVisible}
        className="mb-2 flex w-full cursor-pointer items-center justify-between border-b border-[rgba(32,144,176,0.15)] border-x-0 border-t-0 bg-[linear-gradient(135deg,rgba(6,8,16,0.95),rgba(4,6,14,0.9))] px-2 pb-[8px] pt-2 text-left font-mono tracking-[1.2px] text-[#99b]"
        title={visible ? 'Collapse drone fleet' : 'Expand drone fleet'}
      >
        <span className="text-[12px] font-bold">DRONE FLEET</span>
        <span className="text-[10px] text-[#556]">{visible ? '▾' : '▸'}</span>
      </button>

      {!visible && (
        <div className="rounded border border-[rgba(90,120,150,0.25)] bg-[rgba(8,12,22,0.45)] p-2">
          <div className="mb-1.5 text-[10px] tracking-[0.4px] text-[#7f93a8]">
            Fleet panel collapsed ({entries.length} active)
          </div>
          <div className="space-y-1.5">
            {entries.map(d => {
              const batteryClass = batteryTrackClass(d.battery)
              return (
                <div
                  key={`collapsed-${d.asset_id}`}
                  className="grid grid-cols-[auto_1fr_auto] items-center gap-2"
                  title={`${d.asset_id}: ${d.battery}% battery`}
                >
                  <span className="w-[72px] truncate text-[10px] font-semibold tracking-[0.2px] text-[#b8c8d7]">
                    {d.asset_id}
                  </span>
                  <div className="relative flex items-center">
                    <Progress
                      value={d.battery}
                      indicatorClassName={batteryClass}
                      className="h-2.5 border border-[rgba(130,150,170,0.5)] bg-[rgba(11,17,27,0.75)]"
                    />
                    <span className="ml-0.5 h-1.5 w-[2px] rounded-r-[1px] bg-[rgba(130,150,170,0.7)]" />
                  </div>
                  <span className="w-[34px] text-right text-[10px] font-semibold text-[#9fb3c6]">
                    {d.battery}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {visible && (
        <div className="space-y-2">
          {entries.map(d => {
            const cardClass = droneCardClass(d.status)
            const statusClass = statusTextColorClass(d.status)
            const statusGlow = statusGlowClass(d.status)
            const batteryClass = batteryFillClass(d.battery)
            const batteryTextClassName = batteryTextClass(d.battery)
            const hasEnv = d.nearby_obstacles !== undefined
            return (
              <div
                key={d.asset_id}
                className={`rounded-md border border-l-2 bg-[linear-gradient(135deg,rgba(6,8,16,0.88),rgba(4,6,14,0.82))] p-[6px_10px] font-mono text-[11px] leading-[1.45] backdrop-blur-[12px] ${cardClass}`}
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-bold tracking-[0.4px] text-[#ccdde8]">{d.asset_id}</span>
                  <span className={`flex items-center gap-1 text-[10px] ${statusClass}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${statusClass.replace('text-', 'bg-')} ${statusGlow}`} />
                    {d.status}
                  </span>
                </div>
                <div className="mb-1 flex items-center gap-1.5">
                  <span className="text-[10px] text-[#7a8a9a]">BAT</span>
                  <div className="flex h-1 flex-1 overflow-hidden rounded-[3px] bg-[#0a0e18]">
                    {Array.from({ length: 20 }, (_, index) => {
                      const filled = d.battery >= (index + 1) * 5
                      return (
                        <span
                          key={`${d.asset_id}-bat-${index}`}
                          className={`h-full flex-1 ${filled ? batteryClass : 'bg-transparent'}`}
                        />
                      )
                    })}
                  </div>
                  <span className={`w-[32px] text-right text-[10px] ${batteryTextClassName}`}>{d.battery}%</span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="tracking-[0.25px] text-[#6a8aa0]">
                    <span className="text-[#99bbcc]">{d.x.toFixed(1)}</span>
                    <span className="text-[#5a7a8a]">,&nbsp;</span>
                    <span className="text-[#99bbcc]">{d.y.toFixed(1)}</span>
                    <span className="text-[#5a7a8a]">,&nbsp;</span>
                    <span className="text-[#99bbcc]">{d.z.toFixed(1)}</span>
                  </span>
                  {hasEnv && (
                    <span className="flex items-center gap-1.5">
                      <span className="text-[#99aabb]">
                        <span className="text-[#6a7a8a]">AGL </span>{(d.altitude_agl ?? 0).toFixed(1)}m
                      </span>
                      <span className={(d.nearby_obstacles ?? 0) > 0 ? 'text-[#ff8800]' : 'text-[#55aa66]'}>
                        <span className="text-[#6a7a8a]">OBS </span>{d.nearby_obstacles ?? 0}
                        {(d.nearest_obstacle_dist ?? 999) < 10 && (
                          <span className="text-[#ff6600]"> ({(d.nearest_obstacle_dist ?? 0).toFixed(1)}m)</span>
                        )}
                      </span>
                      {d.over_flood && <span className="font-semibold text-[#44aaff]">FLOOD</span>}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
