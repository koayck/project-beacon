'use client'

import { useEffect, useMemo, useState } from 'react'
import { fetchMissionEvents, type DashboardRun, type MissionRunEvent } from '@/lib/api'
import { MissionReportSummary } from './MissionReportSummary'
import { MissionTimeline } from './MissionTimeline'

export function MissionReportTab({ runs }: { runs: DashboardRun[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(runs[0]?.id ?? null)
  const [events, setEvents] = useState<MissionRunEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedRun = useMemo(
    () => runs.find(r => r.id === selectedId) ?? null,
    [runs, selectedId],
  )

  useEffect(() => {
    if (selectedId === null) {
      setEvents([])
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchMissionEvents(selectedId)
      .then(res => { if (!cancelled) setEvents(res.events) })
      .catch(e => { if (!cancelled) setError(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedId])

  if (runs.length === 0) {
    return (
      <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-6 text-center text-[#556677]">
        No missions yet — run a command from the scene to populate.
      </section>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
      <aside className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-3">
        <div className="mb-3 px-2 text-[11px] font-bold tracking-[1.5px] text-[#556677]">
          RECENT MISSIONS
        </div>
        <ul className="space-y-1">
          {runs.map(run => {
            const active = run.id === selectedId
            return (
              <li key={run.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(run.id)}
                  className={`w-full rounded px-3 py-2 text-left text-[12px] transition ${
                    active
                      ? 'bg-[rgba(40,140,180,0.18)] text-[#cde]'
                      : 'text-[#8899bb] hover:bg-[rgba(40,140,180,0.08)]'
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-bold tabular-nums">#{run.id}</span>
                    <span className="text-[10px] uppercase tracking-[1px] text-[#556677]">
                      {run.status}
                    </span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-[11px] text-[#667788]">
                    {run.prompt}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      </aside>

      <div className="space-y-5">
        {selectedRun && <MissionReportSummary run={selectedRun} />}
        {loading && (
          <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-5 text-[13px] text-[#556677]">
            Loading timeline…
          </section>
        )}
        {error && (
          <section className="rounded-lg border border-[rgba(255,85,85,0.3)] bg-[rgba(255,85,85,0.08)] p-5 text-[13px] text-[#ff8888]">
            Failed to load events: {error}
          </section>
        )}
        {!loading && !error && selectedRun && <MissionTimeline events={events} />}
      </div>
    </div>
  )
}
