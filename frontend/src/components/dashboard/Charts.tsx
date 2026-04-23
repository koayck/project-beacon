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
              <Tooltip
                contentStyle={{
                  backgroundColor: 'rgba(6,8,16,0.95)',
                  border: '1px solid rgba(40,140,180,0.3)',
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: '#cde',
                }}
              />
              <Legend
                wrapperStyle={{ fontSize: 10, fontFamily: 'monospace', color: '#8899bb', letterSpacing: 1 }}
              />
            </PieChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard title="TTFT & DURATION (seconds, oldest → newest)">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={trend}>
            <CartesianGrid stroke="rgba(40,140,180,0.12)" strokeDasharray="3 3" />
            <XAxis dataKey="idx" stroke="#556677" fontSize={10} />
            <YAxis stroke="#556677" fontSize={10} />
            <Tooltip
              contentStyle={{
                backgroundColor: 'rgba(6,8,16,0.95)',
                border: '1px solid rgba(40,140,180,0.3)',
                fontSize: 11,
                fontFamily: 'monospace',
                color: '#cde',
              }}
              labelFormatter={(value) => `Run #${trend[+value - 1]?.id ?? value}`}
            />
            <Legend wrapperStyle={{ fontSize: 10, fontFamily: 'monospace', color: '#8899bb' }} />
            <Line
              type="monotone"
              dataKey="ttft_s"
              stroke="#cc88ff"
              strokeWidth={2}
              dot={{ r: 2 }}
              connectNulls
              name="TTFT"
            />
            <Line
              type="monotone"
              dataKey="duration_s"
              stroke="#55aaff"
              strokeWidth={2}
              dot={{ r: 2 }}
              connectNulls
              name="Duration"
            />
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
              contentStyle={{
                backgroundColor: 'rgba(6,8,16,0.95)',
                border: '1px solid rgba(40,140,180,0.3)',
                fontSize: 11,
                fontFamily: 'monospace',
                color: '#cde',
              }}
              labelFormatter={(value) => `Run #${trend[+value - 1]?.id ?? value}`}
            />
            <Bar dataKey="tool_calls" fill="#44ddff" radius={[2, 2, 0, 0]} name="Tool Calls" />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>
    </section>
  )
}
