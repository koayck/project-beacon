'use client'

import { useState, useEffect, useRef } from "react"
import type { AgentStreamEvent } from '@/lib/api'

export type ActivityCategory = 'dispatch' | 'agent' | 'reasoning' | 'movement' | 'scan' | 'complete' | 'error' | 'system' | 'scout'

export interface ActivityItem {
  id: number
  icon: string
  label: string
  detail?: string
  thinkingLines?: string[]
  ts: number
  status: 'active' | 'done' | 'error'
  category: ActivityCategory
}

let activityId = 0

export function nextActivityId(): number {
  activityId += 1
  return activityId
}

const CATEGORY_STYLE: Record<ActivityCategory, { colorClass: string; glowClass: string; detailClass: string }> = {
  dispatch: { colorClass: 'text-[#e0e8ff]', glowClass: 'bg-[rgba(180,200,255,0.12)]', detailClass: 'text-[#667]' },
  agent: { colorClass: 'text-[#c090ff]', glowClass: 'bg-[rgba(160,100,255,0.12)]', detailClass: 'text-[#667]' },
  reasoning: { colorClass: 'text-[#60aacc]', glowClass: 'bg-[rgba(80,160,200,0.06)]', detailClass: 'text-[#4a7a90]' },
  movement: { colorClass: 'text-[#55aaff]', glowClass: 'bg-[rgba(80,170,255,0.10)]', detailClass: 'text-[#667]' },
  scan: { colorClass: 'text-[#ffaa33]', glowClass: 'bg-[rgba(255,170,50,0.10)]', detailClass: 'text-[#667]' },
  complete: { colorClass: 'text-[#44dd88]', glowClass: 'bg-[rgba(60,220,120,0.10)]', detailClass: 'text-[#667]' },
  error: { colorClass: 'text-[#ff5555]', glowClass: 'bg-[rgba(255,80,80,0.10)]', detailClass: 'text-[#667]' },
  system: { colorClass: 'text-[#8899aa]', glowClass: 'bg-[rgba(100,130,160,0.06)]', detailClass: 'text-[#667]' },
  scout: { colorClass: 'text-[#ffcc44]', glowClass: 'bg-[rgba(255,204,68,0.10)]', detailClass: 'text-[#aa9944]' },
}

function missionTime(ts: number): string {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

export function parseEventToActivity(event: AgentStreamEvent): ActivityItem | null {
  if (event.type === 'tool_call') {
    const { name, args, agent } = event
    if (name === 'transfer_to_agent') {
      const target = String(args.agent_name ?? '').replace(/_/g, ' ')
      return { id: nextActivityId(), icon: '◈', label: `${target}`, ts: Date.now(), status: 'done', category: 'agent' }
    }
    if (name === 'plan_route') {
      const x = Number(args.target_x ?? 0).toFixed(0)
      const z = Number(args.target_z ?? 0).toFixed(0)
      const y = Number(args.target_y ?? 0).toFixed(0)
      return { id: nextActivityId(), icon: '◇', label: 'Planning route', detail: `→ (${x}, ${y}, ${z})`, ts: Date.now(), status: 'active', category: 'movement' }
    }
    if (name === 'move_drone_to') {
      const x = Number(args.x ?? 0).toFixed(1)
      const z = Number(args.z ?? 0).toFixed(1)
      const y = Number(args.y ?? 0).toFixed(1)
      return { id: nextActivityId(), icon: '▸', label: 'Moving to waypoint', detail: `(${x}, ${y}, ${z})`, ts: Date.now(), status: 'active', category: 'movement' }
    }
    if (name === 'sweep_scan_building') {
      const x = Number(args.target_x ?? 0).toFixed(0)
      const z = Number(args.target_z ?? 0).toFixed(0)
      return { id: nextActivityId(), icon: '◉', label: 'Scanning building', detail: `(${x}, ${z})`, ts: Date.now(), status: 'active', category: 'scan' }
    }
    if (name === 'return_to_base') {
      return { id: nextActivityId(), icon: '⌂', label: 'Returning to base', ts: Date.now(), status: 'active', category: 'movement' }
    }
    if (name === 'resolve_scan_target') {
      const x = Number(args.target_x ?? 0).toFixed(0)
      const z = Number(args.target_z ?? 0).toFixed(0)
      return { id: nextActivityId(), icon: '⊕', label: 'Resolving target', detail: `(${x}, ${z})`, ts: Date.now(), status: 'active', category: 'scan' }
    }
    if (name === 'pick_next_building') {
      return { id: nextActivityId(), icon: '⊞', label: 'Selecting next building', ts: Date.now(), status: 'active', category: 'scan' }
    }
    if (name === 'save_scan_result') {
      return { id: nextActivityId(), icon: '✎', label: 'Saving scan results', ts: Date.now(), status: 'active', category: 'system' }
    }
    if (name === 'get_scan_results') {
      return { id: nextActivityId(), icon: '⊡', label: 'Compiling report', ts: Date.now(), status: 'active', category: 'system' }
    }
    return { id: nextActivityId(), icon: '⟡', label: name.replace(/_/g, ' '), detail: `[${agent}]`, ts: Date.now(), status: 'active', category: 'system' }
  }

  if (event.type === 'thinking') {
    return { id: nextActivityId(), icon: '◇', label: 'Agent reasoning', thinkingLines: [event.text], ts: Date.now(), status: 'active', category: 'reasoning' }
  }

  if (event.type === 'text' || event.type === 'final') {
    const t = event.text
    const arriveMatch = t.match(/arrived at \(([^)]+)\)/)
    if (arriveMatch) {
      return { id: nextActivityId(), icon: '✓', label: 'Arrived', detail: `(${arriveMatch[1]})`, ts: Date.now(), status: 'done', category: 'complete' }
    }
    const sweepMatch = t.match(/SWEEP SCAN COMPLETE/)
    if (sweepMatch) {
      const findingsMatch = t.match(/Findings\s*:\s*(.+)/)
      return { id: nextActivityId(), icon: '✓', label: 'Sweep complete', detail: findingsMatch?.[1]?.trim(), ts: Date.now(), status: 'done', category: 'complete' }
    }
    const areaMatch = t.match(/AREA SCAN COMPLETE.*?(\d+)\s*building/)
    if (areaMatch) {
      const totalMatch = t.match(/TOTAL SURVIVORS DETECTED:\s*(\d+)/)
      return { id: nextActivityId(), icon: '◈', label: 'Area scan done', detail: `${areaMatch[1]} bldg · ${totalMatch?.[1] ?? '?'} survivors`, ts: Date.now(), status: 'done', category: 'complete' }
    }
    const supplyAreaMatch = t.match(/AREA SUPPLY DISPATCH COMPLETE.*?(\d+)\s*building/)
    if (supplyAreaMatch) {
      const totalSupplyMatch = t.match(/TOTAL SUPPLY DISPATCHED:\s*(\d+)/)
      return { id: nextActivityId(), icon: '◈', label: 'Area supply done', detail: `${supplyAreaMatch[1]} bldg · ${totalSupplyMatch?.[1] ?? '?'} supplied`, ts: Date.now(), status: 'done', category: 'complete' }
    }
    const scanTargetMatch = t.match(/SCAN TARGET.*?building at \(x=([^,]+),\s*z=([^)]+)\)/)
    if (scanTargetMatch) {
      return { id: nextActivityId(), icon: '▶', label: 'Next target', detail: `building (${scanTargetMatch[1]}, ${scanTargetMatch[2]})`, ts: Date.now(), status: 'active', category: 'scan' }
    }
    if (t.includes('QUEUE_EMPTY')) {
      return { id: nextActivityId(), icon: '✓', label: 'All buildings scanned', ts: Date.now(), status: 'done', category: 'complete' }
    }
    return null
  }

  if (event.type === 'error') {
    return { id: nextActivityId(), icon: '✗', label: 'Error', detail: event.text.slice(0, 60), ts: Date.now(), status: 'error', category: 'error' }
  }
  if (event.type === 'done') {
    return { id: nextActivityId(), icon: '●', label: 'Agent done', ts: Date.now(), status: 'done', category: 'complete' }
  }

  return null
}


function ThinkingEntry({ lines, streaming }: { lines: string[]; streaming: boolean }) {
  const [open, setOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [open, lines.length])

  return (
    <div className="mt-px">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex w-full cursor-pointer items-center gap-1.5 border-none bg-transparent p-0 text-left font-mono text-[11px] text-[#daa832]"
        style={{ opacity: 0.85 }}
      >
        <span style={{
          display: 'inline-block',
          transition: 'transform 0.15s',
          transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
          fontSize: 9,
        }}>&#9654;</span>
        {streaming && (
          <span className="inline-block h-[5px] w-[5px] animate-pulse rounded-full bg-[#daa832] shadow-[0_0_6px_#daa832]" />
        )}
        <span style={{ letterSpacing: 1 }}>COT</span>
        <span className="text-[#7a6a3a]">({lines.length} steps)</span>
      </button>
      {open && (
        <div
          ref={scrollRef}
          className="mt-1 overflow-y-auto border-l-2 border-[rgba(220,170,50,0.2)] pl-2"
          style={{ maxHeight: 160 }}
        >
          {lines.map((line, i) => (
            <div
              key={i}
              className="mb-1 text-[11px] italic leading-[1.5] text-[#b89a40]"
              style={{ opacity: 0.8 }}
            >
              {line}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


interface ActivityFeedProps {
  items: ActivityItem[]
  busy: boolean
  onClear: () => void
}

export function ActivityFeed({ items, busy, onClear }: ActivityFeedProps) {
  const [collapsed, setCollapsed] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!collapsed) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [items.length, collapsed])

  return (
    <div className="pointer-events-auto relative flex max-h-full w-[340px] flex-col overflow-hidden rounded-lg border border-l-2 border-[#2090b033] border-l-[#2090b0] bg-[linear-gradient(135deg,rgba(6,8,16,0.88),rgba(4,6,14,0.82))] font-mono text-[13px] leading-[1.6] shadow-[0_4px_30px_rgba(0,0,0,0.4),inset_0_1px_0_rgba(32,144,176,0.08)] backdrop-blur-[12px]">
      <div className="pointer-events-none absolute left-[-30%] top-0 z-0 h-full w-[30%] animate-[beacon-scanLine_5s_linear_infinite] bg-[linear-gradient(90deg,transparent,rgba(32,144,176,0.04),transparent)]" />

      <button
        onClick={() => setCollapsed(c => !c)}
        className="relative z-[2] flex w-full shrink-0 cursor-pointer items-center justify-between border-b border-[rgba(32,144,176,0.15)] border-x-0 border-t-0 bg-[linear-gradient(135deg,rgba(6,8,16,0.95),rgba(4,6,14,0.9))] px-4 pb-[10px] pt-3 text-left font-mono tracking-[2px] text-[#c0d0e0]"
      >
        <span className="flex items-center gap-2 text-sm font-bold">
          <span className="text-base text-[#2090b0] drop-shadow-[0_0_8px_rgba(32,144,176,0.5)]">◉</span>
          MISSION LOG
          {collapsed && items.length > 0 && (
            <span className="text-[11px] font-normal tracking-[0.5px] text-[#5a6a7a]">({items.length})</span>
          )}
        </span>
        <div className="flex items-center gap-2">
          {busy && (
            <span className="inline-flex animate-[beacon-livePulse_1.5s_ease-in-out_infinite] items-center gap-[5px] rounded-[3px] border border-[rgba(50,120,255,0.15)] bg-[rgba(50,120,255,0.08)] px-[7px] py-[2px] text-[11px] text-[#55aaff]">
              <span className="inline-block h-[5px] w-[5px] rounded-full bg-[#55aaff] shadow-[0_0_8px_#55aaff]" />
              LIVE
            </span>
          )}
          {!collapsed && items.length > 0 && (
            <span
              role="button"
              tabIndex={0}
              onClick={e => { e.stopPropagation(); onClear() }}
              onKeyDown={e => { if (e.key === 'Enter') { e.stopPropagation(); onClear() } }}
              className="cursor-pointer rounded-[3px] border border-[rgba(80,120,200,0.15)] bg-[rgba(20,25,40,0.5)] px-[6px] py-[1px] font-mono text-[11px] leading-[18px] text-[#6a7a8a] transition-colors duration-150"
              title="Clear mission log"
            >
              CLR
            </span>
          )}
          <span className="text-[10px] text-[#556]">{collapsed ? '▸' : '▾'}</span>
        </div>
      </button>

      {!collapsed && (
        items.length === 0 ? (
          <div className="relative z-[1] px-4 py-3 text-center text-xs italic text-[#6a7a8a]">
            Awaiting mission orders...
          </div>
        ) : (
          <div className="relative z-[1] flex min-h-0 flex-1 flex-col gap-px overflow-y-auto px-[14px] pb-[10px] pt-1">
            {items.map((item, idx) => {
              const cat = CATEGORY_STYLE[item.category] ?? CATEGORY_STYLE.system
              const isLast = idx === items.length - 1
              return (
                <div
                  key={item.id}
                  className={`flex items-start gap-2 rounded-[3px] border-b border-[rgba(50,60,80,0.3)] px-[6px] py-[5px] ${isLast ? 'animate-[beacon-slideIn_0.3s_ease-out]' : ''} ${isLast && busy ? cat.glowClass : 'bg-transparent'}`}
                >
                  <div className="flex w-4 shrink-0 flex-col items-center pt-0.5">
                    <span className={`text-sm leading-none ${cat.colorClass}`}>{item.icon}</span>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className={`text-[13px] ${item.category === 'reasoning' ? 'font-normal italic' : 'font-semibold'} ${cat.colorClass}`}>
                        {item.label}
                      </span>
                      <span className="shrink-0 text-[11px] tabular-nums text-[#5a6a7a]">
                        {missionTime(item.ts)}
                      </span>
                    </div>
                    {item.thinkingLines && item.thinkingLines.length > 0 ? (
                      <ThinkingEntry lines={item.thinkingLines} streaming={busy && isLast} />
                    ) : item.detail ? (
                      <div className={`mt-px break-words whitespace-pre-wrap text-xs ${cat.detailClass}`}>
                        {item.detail}
                      </div>
                    ) : null}
                  </div>
                </div>
              )
            })}
            <div ref={bottomRef} />
          </div>
        )
      )}
    </div>
  )
}
