'use client'

import { useState } from 'react'
import type { DashboardRun } from '@/lib/api'

function timeAgo(iso: string): string {
  const delta = Date.now() - new Date(iso).getTime()
  const s = Math.floor(delta / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function fmtMs(ms: number | null): string {
  if (ms === null) return '--'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return '--'
  if (usd < 0.001) return `<$0.001`
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function fmtTokens(n: number | null | undefined): string {
  if (n === null || n === undefined) return '--'
  if (n < 1000) return String(n)
  return `${(n / 1000).toFixed(1)}k`
}

function StatusChip({ status }: { status: DashboardRun['status'] }) {
  const style =
    status === 'success' ? 'bg-[rgba(68,221,136,0.15)] text-[#44dd88] border-[rgba(68,221,136,0.3)]' :
    status === 'failed'  ? 'bg-[rgba(255,85,85,0.15)] text-[#ff5555] border-[rgba(255,85,85,0.3)]' :
                            'bg-[rgba(255,170,51,0.15)] text-[#ffaa33] border-[rgba(255,170,51,0.3)]'
  return (
    <span className={`inline-block rounded border px-2.5 py-1 text-[11px] font-bold tracking-[1px] ${style}`}>
      {status.toUpperCase()}
    </span>
  )
}

function RunRow({
  run,
  expanded,
  onToggle,
}: {
  run: DashboardRun
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr
        className="cursor-pointer border-b border-[rgba(40,140,180,0.08)] text-[#8899bb] hover:bg-[rgba(40,140,180,0.05)]"
        onClick={onToggle}
      >
        <td className="px-4 py-3 tabular-nums">{run.id}</td>
        <td className="px-4 py-3 max-w-[420px] truncate text-[#cde]">{run.prompt}</td>
        <td className="px-4 py-3">{run.asset_id}</td>
        <td className="px-4 py-3"><StatusChip status={run.status} /></td>
        <td className="px-4 py-3 text-right tabular-nums text-[#cc88ff]">{fmtMs(run.ttft_ms)}</td>
        <td className="px-4 py-3 text-right tabular-nums text-[#55aaff]">{fmtMs(run.duration_ms)}</td>
        <td className="px-4 py-3 text-right tabular-nums text-[#44ff66]">{run.survivors_detected}</td>
        <td className="px-4 py-3 text-right tabular-nums text-[#44dd88]">{run.survivors_rescued}</td>
        <td className="px-4 py-3 text-right tabular-nums text-[#e0e8ff]">{fmtTokens(run.total_tokens)}</td>
        <td className="px-4 py-3 text-right tabular-nums text-[#ffaa55]">{fmtCost(run.cost_usd)}</td>
        <td className="px-4 py-3 text-right text-[#556677]">{timeAgo(run.started_at)}</td>
      </tr>
      {expanded && (
        <tr className="border-b border-[rgba(40,140,180,0.08)] bg-[rgba(4,6,14,0.5)]">
          <td colSpan={11} className="px-4 py-4 text-[13px] text-[#8899bb]">
            <div className="mb-2"><span className="text-[#556677]">PROMPT:</span> {run.prompt}</div>
            {run.result_summary && (
              <div className="mb-2"><span className="text-[#556677]">RESULT:</span> {run.result_summary}</div>
            )}
            {run.error_message && (
              <div className="text-[#ff5555]"><span className="text-[#556677]">ERROR:</span> {run.error_message}</div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export function RunsTable({ runs }: { runs: DashboardRun[] }) {
  const [expanded, setExpanded] = useState<number | null>(null)
  if (runs.length === 0) {
    return (
      <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-6 text-center text-[#556677]">
        No missions yet — run a command from the scene to populate.
      </section>
    )
  }
  return (
    <section className="overflow-x-auto rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)]">
      <table className="w-full font-mono text-[14px]">
        <thead>
          <tr className="border-b border-[rgba(40,140,180,0.15)] text-[11px] tracking-[1.5px] text-[#556677]">
            <th className="px-4 py-3 text-left">#</th>
            <th className="px-4 py-3 text-left">PROMPT</th>
            <th className="px-4 py-3 text-left">ASSET</th>
            <th className="px-4 py-3 text-left">STATUS</th>
            <th className="px-4 py-3 text-right">TTFT</th>
            <th className="px-4 py-3 text-right">DURATION</th>
            <th className="px-4 py-3 text-right">DETECT</th>
            <th className="px-4 py-3 text-right">RESCUE</th>
            <th className="px-4 py-3 text-right">TOKENS</th>
            <th className="px-4 py-3 text-right">COST</th>
            <th className="px-4 py-3 text-right">WHEN</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(run => (
            <RunRow
              key={run.id}
              run={run}
              expanded={expanded === run.id}
              onToggle={() => setExpanded(expanded === run.id ? null : run.id)}
            />
          ))}
        </tbody>
      </table>
    </section>
  )
}
