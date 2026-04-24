'use client'

import type { DashboardRun } from '@/lib/api'
import { MissionOutcomeReport } from './MissionOutcomeReport'

function fmtMs(ms: number | null): string {
  if (ms === null) return '--'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return '--'
  if (usd < 0.001) return '<$0.001'
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function fmtTokens(n: number | null | undefined): string {
  if (n === null || n === undefined) return '--'
  if (n < 1000) return String(n)
  return `${(n / 1000).toFixed(1)}k`
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '--'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '--'
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

type StatusTheme = {
  text: string
  border: string
  bg: string
  dot: string
  bar: string
}

function statusTheme(status: DashboardRun['status']): StatusTheme {
  if (status === 'success') {
    return {
      text: 'text-[#44dd88]',
      border: 'border-[rgba(68,221,136,0.4)]',
      bg: 'bg-[rgba(68,221,136,0.1)]',
      dot: 'bg-[#44dd88]',
      bar: 'from-transparent via-[rgba(68,221,136,0.6)] to-transparent',
    }
  }
  if (status === 'failed') {
    return {
      text: 'text-[#ff5555]',
      border: 'border-[rgba(255,85,85,0.4)]',
      bg: 'bg-[rgba(255,85,85,0.1)]',
      dot: 'bg-[#ff5555]',
      bar: 'from-transparent via-[rgba(255,85,85,0.55)] to-transparent',
    }
  }
  return {
    text: 'text-[#ffaa33]',
    border: 'border-[rgba(255,170,51,0.4)]',
    bg: 'bg-[rgba(255,170,51,0.1)]',
    dot: 'bg-[#ffaa33]',
    bar: 'from-transparent via-[rgba(255,170,51,0.55)] to-transparent',
  }
}

function StatusBadge({ theme, status }: { theme: StatusTheme; status: string }) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-bold tracking-[1.5px] ${theme.bg} ${theme.text} ${theme.border}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${theme.dot} shadow-[0_0_8px_currentColor]`}
      />
      {status.toUpperCase()}
    </span>
  )
}

function SectionLabel({ index, title }: { index: string; title: string }) {
  return (
    <div className="mb-3 flex items-center gap-3">
      <span className="text-[10px] font-bold tracking-[2px] text-[rgba(80,170,210,0.9)]">
        §{index}
      </span>
      <span className="text-[10px] font-bold tracking-[2px] text-[#667788]">
        {title}
      </span>
      <div className="h-px flex-1 bg-gradient-to-r from-[rgba(40,140,180,0.3)] to-transparent" />
    </div>
  )
}

function StatTile({
  label,
  value,
  accent,
  sub,
}: {
  label: string
  value: string
  accent?: string
  sub?: string
}) {
  return (
    <div className="group relative rounded border border-[rgba(40,140,180,0.18)] bg-[rgba(4,6,14,0.5)] px-3 py-3 transition hover:border-[rgba(40,140,180,0.35)]">
      <span className="pointer-events-none absolute left-0 top-0 h-2 w-2 border-l border-t border-[rgba(40,140,180,0.4)]" />
      <span className="pointer-events-none absolute bottom-0 right-0 h-2 w-2 border-b border-r border-[rgba(40,140,180,0.4)]" />
      <div className="text-[9px] font-bold tracking-[1.5px] text-[#556677]">
        {label}
      </div>
      <div
        className={`mt-1 text-[20px] font-bold leading-none tabular-nums ${accent ?? 'text-[#cde]'}`}
      >
        {value}
      </div>
      {sub && (
        <div className="mt-1.5 text-[9px] tracking-[0.5px] text-[#556677]">
          {sub}
        </div>
      )}
    </div>
  )
}

export function MissionReportSummary({ run }: { run: DashboardRun }) {
  const theme = statusTheme(run.status)
  const traceShort = run.langfuse_trace_id
    ? `${run.langfuse_trace_id.slice(0, 8)}…${run.langfuse_trace_id.slice(-4)}`
    : null
  const tokenSub =
    run.input_tokens != null && run.output_tokens != null
      ? `${fmtTokens(run.input_tokens)} in · ${fmtTokens(run.output_tokens)} out`
      : undefined
  const missionId = `#${String(run.id).padStart(4, '0')}`
  const outcomeIndex = run.result_summary ? '03' : null
  const errorIndex = run.error_message ? (run.result_summary ? '04' : '03') : null

  return (
    <section className="relative overflow-hidden rounded-lg border border-[rgba(40,140,180,0.25)] bg-gradient-to-b from-[rgba(6,10,20,0.85)] to-[rgba(4,6,14,0.75)] shadow-[0_0_40px_-20px_rgba(40,140,180,0.4)]">
      <div className={`h-[2px] bg-gradient-to-r ${theme.bar}`} />

      <header className="relative border-b border-[rgba(40,140,180,0.15)] px-6 pb-4 pt-4">
        <div className="mb-3 flex items-center justify-between text-[9px] font-bold tracking-[2.5px] text-[#445566]">
          <span className="flex items-center gap-2">
            <span className="inline-block h-1 w-1 rotate-45 bg-[rgba(80,170,210,0.7)]" />
            AFTER-ACTION REPORT · CONFIDENTIAL
          </span>
          <span>FILED {fmtDate(run.started_at)}</span>
        </div>

        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-[10px] font-bold tracking-[1.5px] text-[#556677]">
              MISSION DOSSIER
            </div>
            <h3 className="mt-1 flex items-baseline gap-2 text-[22px] font-bold tracking-[0.5px] text-[#eef] tabular-nums">
              <span>{missionId}</span>
              <span className="text-[#445566]">—</span>
              <span className="text-[#55aaff]">{run.asset_id}</span>
            </h3>
          </div>
          <StatusBadge theme={theme} status={run.status} />
        </div>
      </header>

      <div className="space-y-6 px-6 py-5">
        <div>
          <SectionLabel index="01" title="OBJECTIVE" />
          <blockquote className="relative rounded border-l-2 border-[rgba(40,140,180,0.55)] bg-[rgba(4,6,14,0.6)] px-4 py-3 text-[13px] leading-relaxed text-[#cde]">
            {run.prompt}
          </blockquote>
        </div>

        <div>
          <SectionLabel index="02" title="PERFORMANCE METRICS" />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <StatTile
              label="DURATION"
              value={fmtMs(run.duration_ms)}
              accent="text-[#55aaff]"
            />
            <StatTile
              label="TTFT"
              value={fmtMs(run.ttft_ms)}
              accent="text-[#cc88ff]"
            />
            <StatTile
              label="DETECTED"
              value={String(run.survivors_detected)}
              accent="text-[#44ff66]"
            />
            <StatTile
              label="RESCUED"
              value={String(run.survivors_rescued)}
              accent="text-[#44dd88]"
            />
            <StatTile
              label="TOKENS"
              value={fmtTokens(run.total_tokens)}
              sub={tokenSub}
            />
            <StatTile
              label="COST"
              value={fmtCost(run.cost_usd)}
              accent="text-[#ffaa55]"
            />
          </div>
        </div>

        {outcomeIndex && run.result_summary && (
          <div>
            <SectionLabel index={outcomeIndex} title="MISSION OUTCOME" />
            <MissionOutcomeReport
              text={run.result_summary}
              toolCallCount={run.tool_call_count}
            />
          </div>
        )}

        {errorIndex && (
          <div>
            <SectionLabel index={errorIndex} title="FAILURE DIAGNOSTIC" />
            <div className="overflow-hidden rounded border border-[rgba(255,85,85,0.3)] bg-[rgba(25,10,12,0.6)]">
              <div className="border-b border-[rgba(255,85,85,0.2)] bg-[rgba(255,85,85,0.08)] px-3 py-1.5 text-[9px] font-bold tracking-[1.5px] text-[#ff5555]">
                ERROR TRACE
              </div>
              <pre className="whitespace-pre-wrap break-words px-4 py-3 font-mono text-[12px] leading-[1.65] text-[#ff8888]">
                {run.error_message}
              </pre>
            </div>
          </div>
        )}
      </div>

      <footer className="flex items-center justify-between border-t border-[rgba(40,140,180,0.15)] bg-[rgba(2,4,10,0.5)] px-6 py-2 text-[9px] font-bold tracking-[1.5px] text-[#445566]">
        <span>ENDED · {fmtDate(run.ended_at)}</span>
        {traceShort ? <span>TRACE · {traceShort}</span> : <span>LOCAL RUN</span>}
      </footer>
    </section>
  )
}
