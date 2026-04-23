import type { DashboardOverview } from '@/lib/api'

function formatMs(ms: number | null): string {
  if (ms === null) return '--'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function formatSeconds(s: number | null): string {
  if (s === null) return '--:--'
  const total = Math.max(0, Math.round(s))
  const m = Math.floor(total / 60)
  const r = total % 60
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
}

function formatDurationMs(ms: number | null): string {
  if (ms === null) return '--:--'
  return formatSeconds(ms / 1000)
}

function Card({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="flex flex-col rounded-lg border border-[rgba(40,140,180,0.2)] bg-[linear-gradient(135deg,rgba(6,8,16,0.88),rgba(4,6,14,0.82))] p-4 shadow-[inset_0_1px_0_rgba(50,136,204,0.06)]">
      <span className="mb-2 text-[10px] font-bold tracking-[1.5px] text-[#556677]">
        {label}
      </span>
      <span className={`text-[26px] font-bold tabular-nums ${accent}`}>{value}</span>
    </div>
  )
}

export function OverviewCards({ overview }: { overview: DashboardOverview }) {
  return (
    <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      <Card label="TOTAL MISSIONS" value={String(overview.total_missions)} accent="text-[#44ddff]" />
      <Card label="AVG TTFT" value={formatMs(overview.avg_ttft_ms)} accent="text-[#cc88ff]" />
      <Card label="AVG RESCUE TIME" value={formatSeconds(overview.avg_rescue_time_s)} accent="text-[#ffaa33]" />
      <Card label="RESCUE SUCCESS" value={`${Math.round(overview.rescue_success_rate)}%`} accent="text-[#44dd88]" />
      <Card label="SURVIVORS RESCUED" value={String(overview.total_survivors_rescued)} accent="text-[#44ff66]" />
      <Card label="AVG MISSION" value={formatDurationMs(overview.avg_duration_ms)} accent="text-[#55aaff]" />
    </section>
  )
}
