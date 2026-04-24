'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { fetchDashboard, type DashboardPayload } from '@/lib/api'
import { OverviewCards } from '@/components/dashboard/OverviewCards'
import { RunsTable } from '@/components/dashboard/RunsTable'
import { CurrentMissionStrip } from '@/components/dashboard/CurrentMissionStrip'
import { Charts } from '@/components/dashboard/Charts'
import { MissionReportTab } from '@/components/dashboard/MissionReportTab'

type TabKey = 'performance' | 'report'

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-5 py-2 text-[12px] font-bold tracking-[1.5px] transition ${
        active
          ? 'border-b-2 border-[#5599bb] text-[#88ccee]'
          : 'border-b-2 border-transparent text-[#556677] hover:text-[#8899bb]'
      }`}
    >
      {children}
    </button>
  )
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabKey>('performance')

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
    <main className="h-screen overflow-y-auto bg-[#040612] px-8 py-6 font-mono text-[#cde]">
      <header className="mb-5 flex items-end justify-between border-b border-[rgba(40,140,180,0.15)] pb-5">
        <div>
          <h1 className="text-[28px] font-bold leading-none tracking-[3px] text-[#5599bb] drop-shadow-[0_0_24px_rgba(85,153,187,0.35)]">
            PROJECT BEACON — PERFORMANCE
          </h1>
          <p className="mt-3 text-[13px] tracking-[1px] text-[#556677]">
            Historical mission telemetry · {data.runs.length} recent runs
          </p>
        </div>
        <Link
          href="/"
          className="rounded-md border border-[rgba(50,136,204,0.4)] bg-[rgba(40,140,180,0.06)] px-4 py-2 text-[12px] font-bold tracking-[1.5px] text-[#88ccee] hover:bg-[rgba(40,140,180,0.15)]"
        >
          ← BACK TO SCENE
        </Link>
      </header>

      <nav className="mb-6 flex gap-2 border-b border-[rgba(40,140,180,0.15)]">
        <TabButton active={tab === 'performance'} onClick={() => setTab('performance')}>
          PERFORMANCE
        </TabButton>
        <TabButton active={tab === 'report'} onClick={() => setTab('report')}>
          MISSION REPORT
        </TabButton>
      </nav>

      {tab === 'performance' && (
        <>
          {data.currentMission && <CurrentMissionStrip mission={data.currentMission} />}
          <OverviewCards overview={data.overview} />
          <Charts runs={data.runs} />
          <RunsTable runs={data.runs} />
        </>
      )}

      {tab === 'report' && <MissionReportTab runs={data.runs} />}
    </main>
  )
}
