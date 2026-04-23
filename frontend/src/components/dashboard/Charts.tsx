'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DashboardRun } from '@/lib/api'

const STATUS_COLORS: Record<DashboardRun['status'], string> = {
  success: '#44dd88',
  failed: '#ff5555',
  aborted: '#ffaa33',
}

const DRONE_COLOR_PALETTE = [
  '#44ddff',
  '#cc88ff',
  '#44dd88',
  '#ffaa33',
  '#ff7bd4',
  '#55aaff',
  '#ffdd66',
  '#44ff66',
]

const PROMPT_TYPE_ORDER = ['SCAN', 'DELIVER', 'RETURN', 'MOVE', 'OTHER'] as const
const PROMPT_TYPE_COLORS: Record<(typeof PROMPT_TYPE_ORDER)[number], string> = {
  SCAN: '#44ddff',
  DELIVER: '#44dd88',
  RETURN: '#cc88ff',
  MOVE: '#55aaff',
  OTHER: '#667788',
}

function classifyPrompt(prompt: string): (typeof PROMPT_TYPE_ORDER)[number] {
  const p = prompt.toLowerCase()
  if (/\bscan\b/.test(p)) return 'SCAN'
  if (/deliver|supply|emergency|drop/.test(p)) return 'DELIVER'
  if (/return|back to base|rtb\b/.test(p)) return 'RETURN'
  if (/\bmove\b|navigate|go to|fly to/.test(p)) return 'MOVE'
  return 'OTHER'
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col rounded-lg border border-[rgba(40,140,180,0.2)] bg-[linear-gradient(135deg,rgba(6,8,16,0.88),rgba(4,6,14,0.82))] p-4 shadow-[inset_0_1px_0_rgba(50,136,204,0.06)]">
      <span className="mb-3 text-[10px] font-bold tracking-[1.5px] text-[#556677]">{title}</span>
      <div className="h-[220px] w-full">{children}</div>
    </div>
  )
}

function NoData() {
  return (
    <div className="flex h-full items-center justify-center text-[11px] text-[#556677]">
      Not enough data yet
    </div>
  )
}

const TOOLTIP_STYLE = {
  backgroundColor: 'rgba(6,8,16,0.95)',
  border: '1px solid rgba(40,140,180,0.3)',
  fontSize: 11,
  fontFamily: 'monospace',
  color: '#cde',
} as const

export function Charts({ runs }: { runs: DashboardRun[] }) {
  if (runs.length === 0) return null

  // Status distribution
  const statusCounts = runs.reduce<Record<DashboardRun['status'], number>>(
    (acc, r) => ({ ...acc, [r.status]: (acc[r.status] ?? 0) + 1 }),
    { success: 0, failed: 0, aborted: 0 },
  )
  const statusData = (Object.keys(statusCounts) as DashboardRun['status'][])
    .filter(s => statusCounts[s] > 0)
    .map(s => ({ name: s.toUpperCase(), value: statusCounts[s], fill: STATUS_COLORS[s] }))

  // Reverse runs so oldest→newest on x-axis
  const chronological = [...runs].reverse()
  const trend = chronological.map((r, idx) => ({
    idx: idx + 1,
    id: r.id,
    ttft_s: r.ttft_ms !== null ? +(r.ttft_ms / 1000).toFixed(2) : null,
    duration_s: r.duration_ms !== null ? +(r.duration_ms / 1000).toFixed(2) : null,
    tool_calls: r.tool_call_count,
  }))

  // Missions by drone (donut)
  const assetCounts = runs.reduce<Record<string, number>>((acc, r) => {
    acc[r.asset_id] = (acc[r.asset_id] ?? 0) + 1
    return acc
  }, {})
  const droneData = Object.entries(assetCounts)
    .sort(([, a], [, b]) => b - a)
    .map(([name, value], idx) => ({
      name,
      value,
      fill: DRONE_COLOR_PALETTE[idx % DRONE_COLOR_PALETTE.length],
    }))

  // Prompt type breakdown (bar)
  const promptTypeCounts = runs.reduce<Record<string, number>>((acc, r) => {
    const type = classifyPrompt(r.prompt)
    acc[type] = (acc[type] ?? 0) + 1
    return acc
  }, {})
  const promptTypeData = PROMPT_TYPE_ORDER
    .filter(t => (promptTypeCounts[t] ?? 0) > 0)
    .map(t => ({ name: t, value: promptTypeCounts[t] ?? 0, fill: PROMPT_TYPE_COLORS[t] }))

  // Time-to-rescue histogram (successful runs with at least one rescue)
  const rescueDurations = runs
    .filter(r => r.status === 'success' && r.survivors_rescued > 0 && r.duration_ms !== null)
    .map(r => (r.duration_ms as number) / 1000)

  const histogramBuckets: { label: string; min: number; max: number }[] = [
    { label: '<30s', min: 0, max: 30 },
    { label: '30–60s', min: 30, max: 60 },
    { label: '1–2m', min: 60, max: 120 },
    { label: '2–5m', min: 120, max: 300 },
    { label: '5m+', min: 300, max: Infinity },
  ]
  const rescueHistogramData = histogramBuckets.map(b => ({
    name: b.label,
    value: rescueDurations.filter(s => s >= b.min && s < b.max).length,
  }))
  const hasRescueData = rescueDurations.length > 0

  return (
    <section className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      <ChartCard title="STATUS DISTRIBUTION">
        {statusData.length === 0 ? (
          <NoData />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={statusData}
                dataKey="value"
                nameKey="name"
                innerRadius={50}
                outerRadius={85}
                paddingAngle={2}
                stroke="rgba(6,8,16,0.8)"
              >
                {statusData.map(entry => <Cell key={entry.name} fill={entry.fill} />)}
              </Pie>
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: 'monospace', color: '#8899bb', letterSpacing: 1 }} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="MISSIONS BY DRONE">
        {droneData.length === 0 ? (
          <NoData />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={droneData}
                dataKey="value"
                nameKey="name"
                innerRadius={50}
                outerRadius={85}
                paddingAngle={2}
                stroke="rgba(6,8,16,0.8)"
              >
                {droneData.map(entry => <Cell key={entry.name} fill={entry.fill} />)}
              </Pie>
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: 'monospace', color: '#8899bb', letterSpacing: 1 }} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="PROMPT TYPE BREAKDOWN">
        {promptTypeData.length === 0 ? (
          <NoData />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={promptTypeData} layout="vertical" margin={{ left: 12, right: 12 }}>
              <CartesianGrid stroke="rgba(40,140,180,0.12)" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" stroke="#556677" fontSize={10} allowDecimals={false} />
              <YAxis type="category" dataKey="name" stroke="#556677" fontSize={10} width={70} />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(40,140,180,0.08)' }} />
              <Bar dataKey="value" radius={[0, 3, 3, 0]}>
                {promptTypeData.map(entry => <Cell key={entry.name} fill={entry.fill} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="TTFT & DURATION (s, oldest → newest)">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={trend}>
            <CartesianGrid stroke="rgba(40,140,180,0.12)" strokeDasharray="3 3" />
            <XAxis dataKey="idx" stroke="#556677" fontSize={10} />
            <YAxis stroke="#556677" fontSize={10} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(value) => `Run #${trend[+value - 1]?.id ?? value}`}
            />
            <Legend wrapperStyle={{ fontSize: 10, fontFamily: 'monospace', color: '#8899bb' }} />
            <Line type="monotone" dataKey="ttft_s" stroke="#cc88ff" strokeWidth={2} dot={{ r: 2 }} connectNulls name="TTFT" />
            <Line type="monotone" dataKey="duration_s" stroke="#55aaff" strokeWidth={2} dot={{ r: 2 }} connectNulls name="Duration" />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="TOOL CALLS PER RUN">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={trend}>
            <CartesianGrid stroke="rgba(40,140,180,0.12)" strokeDasharray="3 3" />
            <XAxis dataKey="idx" stroke="#556677" fontSize={10} />
            <YAxis stroke="#556677" fontSize={10} allowDecimals={false} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(value) => `Run #${trend[+value - 1]?.id ?? value}`}
            />
            <Bar dataKey="tool_calls" fill="#44ddff" radius={[2, 2, 0, 0]} name="Tool Calls" />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="TIME-TO-RESCUE DISTRIBUTION">
        {!hasRescueData ? (
          <NoData />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rescueHistogramData}>
              <CartesianGrid stroke="rgba(40,140,180,0.12)" strokeDasharray="3 3" />
              <XAxis dataKey="name" stroke="#556677" fontSize={10} />
              <YAxis stroke="#556677" fontSize={10} allowDecimals={false} />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(40,140,180,0.08)' }} />
              <Bar dataKey="value" fill="#44dd88" radius={[2, 2, 0, 0]} name="Rescues" />
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>
    </section>
  )
}
