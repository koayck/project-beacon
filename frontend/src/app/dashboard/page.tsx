'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { fetchDashboard, type DashboardPayload } from '@/lib/api'
import { OverviewCards } from '@/components/dashboard/OverviewCards'
import { RunsTable } from '@/components/dashboard/RunsTable'
import { CurrentMissionStrip } from '@/components/dashboard/CurrentMissionStrip'
import { Charts } from '@/components/dashboard/Charts'

export default function DashboardPage() {
  const [data, setData] = useState<DashboardPayload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDashboard().then(setData).catch(e => setError(String(e)))
  }, [])

  if (error) {
    return (
      <main className="h-screen overflow-y-auto bg-[#040612] p-6 font-mono text-[#ff8888]">
        Failed to load dashboard: {error}
      </main>
    )
  }
  if (!data) {
    return (
      <main className="h-screen overflow-y-auto bg-[#040612] p-6 font-mono text-[#667788]">
        Loading…
      </main>
    )
  }

  return (
    <main className="h-screen overflow-y-auto bg-[#040612] p-6 font-mono text-[#cde]">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold tracking-[2px] text-[#5599bb]">
            PROJECT BEACON — PERFORMANCE
          </h1>
          <p className="text-[11px] text-[#556677]">
            Historical mission telemetry · {data.runs.length} recent runs
          </p>
        </div>
        <Link
          href="/"
          className="rounded border border-[rgba(50,136,204,0.3)] px-3 py-1 text-[11px] tracking-[1px] text-[#88ccee] hover:bg-[rgba(40,140,180,0.1)]"
        >
          ← BACK TO SCENE
        </Link>
      </header>

      {data.currentMission && <CurrentMissionStrip mission={data.currentMission} />}
      <OverviewCards overview={data.overview} />
      <Charts runs={data.runs} />
      <RunsTable runs={data.runs} />
    </main>
  )
}
