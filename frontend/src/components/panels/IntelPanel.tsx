'use client'

import { useEffect, useRef, useState } from 'react'
import { FLOOD_LEVEL, SURVIVOR_SENSOR_RANGE, survivorDistance, survivorKey } from '../../../constants/missionConstants'
import type { SurvivorPoint } from '../../types/worldTypes'
import { StatCounter } from './StatCounter'

interface IntelCardProps {
  survivors: SurvivorPoint[]
  dronePos: { x: number; y: number; z: number }
  totalSurvivors: number
  deliveringTo: Set<string>
  deliveredTo: Set<string>
  onSendSupplies: (survivor: SurvivorPoint) => void
  onRetryDelivery: (survivor: SurvivorPoint) => void
}

export function IntelCard({
  survivors,
  dronePos,
  totalSurvivors,
  deliveringTo,
  deliveredTo,
  onSendSupplies,
  onRetryDelivery,
}: IntelCardProps) {
  const detected = survivors.length
  const submerged = survivors.filter(s => s.y < FLOOD_LEVEL - 0.2).length
  const critical = submerged > 0
  const deliveredCount = deliveredTo.size
  const summaryCols = 2 + (submerged > 0 ? 1 : 0) + (deliveredCount > 0 ? 1 : 0)
  const summaryColsClass = summaryCols === 4 ? 'grid-cols-4' : summaryCols === 3 ? 'grid-cols-3' : 'grid-cols-2'
  const panelBorderClass = critical
    ? 'border-[rgba(255,70,70,0.3)] border-l-[#cc3333]'
    : 'border-[rgba(40,140,180,0.2)] border-l-[#cc8800]'

  const knownKeysRef = useRef<Set<string>>(new Set())
  const [alertSignal, setAlertSignal] = useState<string | null>(null)
  const [newKeys, setNewKeys] = useState<Set<string>>(new Set())
  const alertTimeoutRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    const currentKeys = new Set(survivors.map(survivorKey))
    const brandNew: string[] = []
    currentKeys.forEach(k => {
      if (!knownKeysRef.current.has(k)) brandNew.push(k)
    })
    if (brandNew.length > 0 && knownKeysRef.current.size > 0) {
      const idx = survivors.findIndex(s => survivorKey(s) === brandNew[0])
      const sigLabel = `SIG-${String.fromCharCode(65 + (idx >= 0 ? idx : survivors.length - 1))}`
      setAlertSignal(sigLabel)
      setNewKeys(new Set(brandNew))
      if (alertTimeoutRef.current) clearTimeout(alertTimeoutRef.current)
      alertTimeoutRef.current = setTimeout(() => {
        setAlertSignal(null)
        setNewKeys(new Set())
      }, 3000)
    }
    knownKeysRef.current = currentKeys
  }, [survivors])

  return (
    <div
      className={`pointer-events-auto relative flex max-h-[440px] min-w-[240px] flex-col overflow-hidden rounded-lg border border-l-2 bg-[linear-gradient(135deg,rgba(6,8,16,0.88),rgba(4,6,14,0.82))] font-mono text-[13px] leading-[1.7] text-[#8899bb] shadow-[0_4px_30px_rgba(0,0,0,0.4),inset_0_1px_0_rgba(200,136,0,0.06)] backdrop-blur-[12px] ${panelBorderClass}`}
    >
      <div className="pointer-events-none absolute left-[-30%] top-0 z-0 h-full w-[30%] animate-[beacon-scanLine_4s_linear_infinite] bg-[linear-gradient(90deg,transparent,rgba(80,170,255,0.03),transparent)]" />

      <div className="relative z-[2] shrink-0 bg-[linear-gradient(135deg,rgba(6,8,16,0.95),rgba(4,6,14,0.9))] px-[14px] pb-0 pt-[10px]">
        {alertSignal && (
          <div className="mb-2 animate-[beacon-alertFlash_3s_ease-in-out_forwards] rounded border border-[rgba(255,120,0,0.5)] bg-[linear-gradient(135deg,rgba(255,60,0,0.2),rgba(255,120,0,0.15))] px-[10px] py-[6px] text-center">
            <div className="text-[13px] font-bold tracking-[1.5px] text-[#ff8833]">
              SIGNAL ACQUIRED
            </div>
            <div className="text-xs text-[#ffaa55]">
              {alertSignal} — Heat signature confirmed
            </div>
          </div>
        )}

        <div className="mb-2 flex items-center justify-between tracking-[1.5px] text-[#99b]">
          <span className="font-bold">SCAN INTEL</span>
          <span className="inline-flex items-center gap-1 text-xs">
            {detected > 0 && (
              <span className="inline-block h-1.5 w-1.5 animate-[beacon-signalDot_1.5s_ease-in-out_infinite] rounded-full bg-[#ff6] text-[#ff6]" />
            )}
            <span className={detected > 0 ? 'text-[#ff6]' : 'text-[#7a8a9a]'}>
              {detected > 0 ? 'LIVE' : 'NO CONTACT'}
            </span>
          </span>
        </div>

        <div className={`mb-2 grid gap-1 border-b border-[rgba(50,60,80,0.5)] pb-2 ${summaryColsClass}`}>
          <StatCounter value={detected} label="DETECTED" color={detected > 0 ? '#44ff66' : '#7a8a9a'} />
          <StatCounter value={totalSurvivors - detected} label="UNSCANNED" color="#7a8a9a" />
          {submerged > 0 && <StatCounter value={submerged} label="SUBMERGED" color="#ff4444" />}
          {deliveredCount > 0 && <StatCounter value={deliveredCount} label="SUPPLIED" color="#44ccff" />}
        </div>

        <div className="mb-2 flex justify-between text-[11px] text-[#7a8a9a]">
          <span>SENSOR @ ({dronePos.x.toFixed(1)}, {dronePos.y.toFixed(1)}, {dronePos.z.toFixed(1)})</span>
          <span className="text-[#8899aa]">{SURVIVOR_SENSOR_RANGE}m</span>
        </div>
      </div>

      <div className="relative z-[1] max-h-[220px] overflow-y-auto px-[14px] pb-[10px] pt-0">
        {detected === 0 ? (
          <div className="py-2 text-xs italic text-[#6a7a8a]">
            No heat signatures in sensor range.
            <br />
            <span className="text-[#5a6a7a]">Move drone closer to scan targets.</span>
          </div>
        ) : (
          survivors.map((s, i) => {
            const key = survivorKey(s)
            const dist = survivorDistance(dronePos, s)
            const isSubmerged = s.y < FLOOD_LEVEL - 0.2
            const isDelivering = deliveringTo.has(key)
            const isDelivered = deliveredTo.has(key)
            const isNew = newKeys.has(key)
            const cardStateClass = isDelivered
              ? 'border-[rgba(60,200,255,0.25)] bg-[rgba(60,200,255,0.08)]'
              : isSubmerged
                ? 'border-[rgba(255,80,80,0.3)] bg-[rgba(255,50,50,0.10)]'
                : 'border-[rgba(80,255,80,0.15)] bg-[rgba(60,255,60,0.06)]'
            const cardAnimationClass = isNew
              ? 'animate-[beacon-survivorIn_0.5s_ease-out_forwards]'
              : isSubmerged && !isDelivered
                ? 'animate-[beacon-criticalPulse_2s_ease-in-out_infinite]'
                : ''
            const signalColorClass = isDelivered ? 'text-[#4cf]' : isSubmerged ? 'text-[#ff6666]' : 'text-[#66ff88]'
            const signalDotClass = isDelivered ? 'bg-[#4cf]' : isSubmerged ? 'bg-[#f66]' : 'bg-[#6f6]'

            return (
              <div key={i} className={`mb-[5px] rounded border px-2 py-1.5 ${cardStateClass} ${cardAnimationClass}`}>
                <div className="mb-[3px] flex items-center justify-between">
                  <span className={`flex items-center gap-[5px] font-bold ${signalColorClass}`}>
                    <span
                      className={`inline-block h-[5px] w-[5px] rounded-full ${signalDotClass} ${!isDelivered ? 'animate-[beacon-signalDot_1.5s_ease-in-out_infinite]' : ''}`}
                    />
                    SIG-{String.fromCharCode(65 + i)}
                    {isNew && (
                      <span className="animate-[beacon-newBadge_0.8s_ease-in-out_3] text-[10px] font-bold tracking-[1px] text-[#ff8833]">
                        NEW
                      </span>
                    )}
                    {isSubmerged && !isDelivered && (
                      <span className="text-[11px] font-normal text-[#ff5555]">SUBMERGED</span>
                    )}
                    {isDelivered && (
                      <span className="text-[11px] font-normal text-[#4cf]">SUPPLIED</span>
                    )}
                  </span>
                  <span className="text-xs text-[#8899aa]">{dist.toFixed(1)}m</span>
                </div>

                <div className="flex items-center justify-between text-xs text-[#8899aa]">
                  <span>
                    ({s.x.toFixed(1)}, {s.y.toFixed(1)}, {s.z.toFixed(1)})
                    {isSubmerged && !isDelivered && (
                      <span className="ml-1.5 text-[11px] font-bold text-[#ff3333]">
                        ⚠ CRITICAL
                      </span>
                    )}
                  </span>
                  {isDelivering ? (
                    <span className="inline-flex gap-[3px]">
                      <span className="rounded-[3px] border border-[rgba(255,200,0,0.3)] bg-[rgba(255,200,0,0.12)] px-[7px] py-[2px] text-[11px] text-[#ff6]">
                        EN ROUTE
                      </span>
                      <button
                        onClick={() => onRetryDelivery(s)}
                        className="cursor-pointer rounded-[3px] border border-[rgba(255,100,100,0.5)] bg-[rgba(255,60,60,0.15)] px-[7px] py-[2px] font-mono text-[11px] text-[#f88]"
                      >
                        RETRY
                      </button>
                    </span>
                  ) : (
                    <button
                      onClick={() => onSendSupplies(s)}
                      disabled={isDelivered}
                      className={`rounded-[3px] border px-[7px] py-[2px] font-mono text-[11px] ${
                        isDelivered
                          ? 'cursor-default border-[rgba(60,200,255,0.3)] bg-[rgba(60,200,255,0.15)] text-[#4cf] opacity-70'
                          : 'cursor-pointer border-[rgba(255,160,0,0.5)] bg-[rgba(255,140,0,0.15)] text-[#fa0]'
                      }`}
                    >
                      {isDelivered ? '✓ DONE' : 'DELIVER'}
                    </button>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

