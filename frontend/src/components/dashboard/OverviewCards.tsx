import type { DashboardOverview } from '@/lib/api'

function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '--'
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

function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '--:--'
  return formatSeconds(ms / 1000)
}

function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined || usd === 0) return '--'
  if (usd < 0.01) return `<$0.01`
  if (usd < 1) return `$${usd.toFixed(3)}`
  return `$${usd.toFixed(2)}`
}

function formatCostPrecise(usd: number | null | undefined): string {
  if (usd === null || usd === undefined || usd === 0) return '--'
  if (usd < 0.001) return '<$0.001'
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return '--'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`
  return `${(n / 1_000_000).toFixed(2)}M`
}

function Card({ label, value, accent, sub }: { label: string; value: string; accent: string; sub?: string }) {
  return (
    <div className="flex flex-col rounded-lg border border-[rgba(40,140,180,0.2)] bg-[linear-gradient(135deg,rgba(6,8,16,0.88),rgba(4,6,14,0.82))] p-4 shadow-[inset_0_1px_0_rgba(50,136,204,0.06)]">
      <span className="mb-2 text-[10px] font-bold tracking-[1.5px] text-[#556677]">
        {label}
      </span>
      <span className={`text-[26px] font-bold tabular-nums ${accent}`}>{value}</span>
      {sub && <span className="mt-1 text-[10px] text-[#556677]">{sub}</span>}
    </div>
  )
}

export function OverviewCards({ overview }: { overview: DashboardOverview }) {
  const rescues = overview.total_survivors_rescued || 0
  const costPerRescue = rescues > 0 && overview.total_cost_usd
    ? overview.total_cost_usd / rescues
    : null
  const tokensPerRescue = rescues > 0 && overview.total_tokens
    ? Math.round(overview.total_tokens / rescues)
    : null

  return (
    <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      <Card label="TOTAL MISSIONS" value={String(overview.total_missions)} accent="text-[#44ddff]" />
      <Card label="RESCUE SUCCESS" value={`${Math.round(overview.rescue_success_rate)}%`} accent="text-[#44dd88]" />
      <Card label="SURVIVORS RESCUED" value={String(rescues)} accent="text-[#44ff66]" />
      <Card
        label="AVG TTFT"
        value={formatMs(overview.avg_ttft_ms)}
        accent="text-[#cc88ff]"
        sub={overview.median_ttft_ms !== null && overview.median_ttft_ms !== undefined
          ? `med ${formatMs(overview.median_ttft_ms)}`
          : undefined}
      />
      <Card
        label="AVG MISSION"
        value={formatDurationMs(overview.avg_duration_ms)}
        accent="text-[#55aaff]"
        sub={overview.median_duration_ms !== null && overview.median_duration_ms !== undefined
          ? `med ${formatDurationMs(overview.median_duration_ms)}`
          : undefined}
      />
      <Card label="AVG RESCUE TIME" value={formatSeconds(overview.avg_rescue_time_s)} accent="text-[#ffaa33]" />
      <Card label="TOTAL TOOL CALLS" value={String(overview.total_tool_calls ?? '--')} accent="text-[#44ddff]" />
      <Card label="TOTAL TOKENS" value={formatTokens(overview.total_tokens)} accent="text-[#e0e8ff]" />
      <Card label="TOTAL COST" value={formatCost(overview.total_cost_usd)} accent="text-[#ffaa55]" />
      <Card
        label="COST PER RESCUE"
        value={formatCostPrecise(costPerRescue)}
        accent="text-[#ffdd66]"
        sub={rescues > 0 ? 'AI cost / survivor saved' : undefined}
      />
      <Card
        label="TOKENS PER RESCUE"
        value={formatTokens(tokensPerRescue)}
        accent="text-[#e0e8ff]"
        sub={rescues > 0 ? 'tokens / survivor saved' : undefined}
      />
    </section>
  )
}
