'use client'

import type { DashboardRun } from '@/lib/api'

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

function StatusBadge({ status }: { status: DashboardRun['status'] }) {
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

function Field({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div>
      <div className="text-[10px] font-bold tracking-[1.5px] text-[#556677]">{label}</div>
      <div className={`mt-1 text-[18px] font-bold tabular-nums ${accent ?? 'text-[#cde]'}`}>{value}</div>
    </div>
  )
}

export function MissionReportSummary({ run }: { run: DashboardRun }) {
  return (
    <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-5">
      <header className="mb-4 flex items-center justify-between">
        <h3 className="text-[11px] font-bold tracking-[1.5px] text-[#556677]">
          MISSION #{run.id} · {run.asset_id}
        </h3>
        <StatusBadge status={run.status} />
      </header>

      <div className="mb-5 rounded border border-[rgba(40,140,180,0.15)] bg-[rgba(4,6,14,0.6)] p-3 text-[13px] text-[#cde]">
        <div className="mb-1 text-[10px] font-bold tracking-[1.5px] text-[#556677]">PROMPT</div>
        {run.prompt}
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
        <Field label="DURATION" value={fmtMs(run.duration_ms)} accent="text-[#55aaff]" />
        <Field label="TTFT" value={fmtMs(run.ttft_ms)} accent="text-[#cc88ff]" />
        <Field label="DETECTED" value={String(run.survivors_detected)} accent="text-[#44ff66]" />
        <Field label="RESCUED" value={String(run.survivors_rescued)} accent="text-[#44dd88]" />
        <Field label="TOKENS" value={fmtTokens(run.total_tokens)} />
        <Field label="COST" value={fmtCost(run.cost_usd)} accent="text-[#ffaa55]" />
      </div>

      {run.result_summary && (
        <div className="mt-5 rounded border border-[rgba(40,140,180,0.15)] bg-[rgba(4,6,14,0.6)] p-3">
          <div className="mb-2 text-[10px] font-bold tracking-[1.5px] text-[#556677]">RESULT</div>
          <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-[#cde]">
            {run.result_summary}
          </pre>
        </div>
      )}

      {run.error_message && (
        <div className="mt-5 rounded border border-[rgba(255,85,85,0.3)] bg-[rgba(255,85,85,0.08)] p-3">
          <div className="mb-2 text-[10px] font-bold tracking-[1.5px] text-[#ff5555]">ERROR</div>
          <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-[#ff8888]">
            {run.error_message}
          </pre>
        </div>
      )}
    </section>
  )
}
