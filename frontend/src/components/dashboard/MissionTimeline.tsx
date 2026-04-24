'use client'

import type { MissionRunEvent } from '@/lib/api'
import { TimelineEvent } from './TimelineEvent'

export function MissionTimeline({ events }: { events: MissionRunEvent[] }) {
  if (events.length === 0) {
    return (
      <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-6 text-[13px] text-[#556677]">
        No detailed timeline available for this run. (Mission predates the
        timeline-capture feature, or events failed to persist.)
      </section>
    )
  }
  return (
    <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-5">
      <h3 className="mb-4 text-[11px] font-bold tracking-[1.5px] text-[#556677]">
        AGENT TIMELINE — {events.length} EVENT{events.length === 1 ? '' : 'S'}
      </h3>
      <div className="space-y-1">
        {events.map(e => <TimelineEvent key={e.seq} event={e} />)}
      </div>
    </section>
  )
}
