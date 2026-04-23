'use client'

import { useEffect, useState } from 'react'
import type { DashboardCurrentMission } from '@/lib/api'

export function CurrentMissionStrip({ mission }: { mission: DashboardCurrentMission }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const start = new Date(mission.started_at).getTime()
    const tick = () => setElapsed(Date.now() - start)
    tick()
    const id = setInterval(tick, 500)
    return () => clearInterval(id)
  }, [mission.started_at])

  const mm = String(Math.floor(elapsed / 60000)).padStart(2, '0')
  const ss = String(Math.floor((elapsed % 60000) / 1000)).padStart(2, '0')

  return (
    <section className="mb-4 flex items-center justify-between rounded-lg border border-[rgba(68,221,255,0.3)] bg-[rgba(40,140,180,0.08)] px-4 py-2 font-mono text-[12px]">
      <div className="flex items-center gap-3">
        <span className="h-2 w-2 animate-pulse rounded-full bg-[#44ddff]" />
        <span className="text-[10px] tracking-[1.5px] text-[#556677]">IN FLIGHT</span>
        <span className="text-[#cde]">{mission.prompt}</span>
      </div>
      <span className="tabular-nums text-[14px] font-bold text-[#44ddff]">{mm}:{ss}</span>
    </section>
  )
}
