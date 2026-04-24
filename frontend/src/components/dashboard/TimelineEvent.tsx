'use client'

import { useState } from 'react'
import type { MissionRunEvent } from '@/lib/api'

const TYPE_STYLES: Record<MissionRunEvent['event_type'], { label: string; color: string }> = {
  tool_call:   { label: 'TOOL CALL',   color: 'text-[#88ccee]' },
  tool_result: { label: 'TOOL RESULT', color: 'text-[#44dd88]' },
  thinking:    { label: 'THINKING',    color: 'text-[#cc88ff]' },
  text:        { label: 'TEXT',        color: 'text-[#cde]' },
  final:       { label: 'FINAL',       color: 'text-[#ffaa55]' },
  error:       { label: 'ERROR',       color: 'text-[#ff5555]' },
}

const SENTINEL_TEXTS = new Set(['Report emitted.'])

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('en-US', { hour12: false }) +
    `.${String(d.getMilliseconds()).padStart(3, '0')}`
}

function eventBody(event: MissionRunEvent): string {
  const p = event.payload
  if (event.event_type === 'tool_call') {
    const name = String(p.name ?? '?')
    const args = JSON.stringify(p.args ?? {}, null, 2)
    return `${name}(${args})`
  }
  if (event.event_type === 'tool_result') {
    const name = String(p.name ?? '?')
    const result = typeof p.result === 'string'
      ? p.result
      : JSON.stringify(p.result, null, 2)
    return `${name} →\n${result}`
  }
  if (event.event_type === 'error') {
    return String(p.text ?? p.message ?? '(no detail)')
  }
  return String(p.text ?? '')
}

export function TimelineEvent({ event }: { event: MissionRunEvent }) {
  const style = TYPE_STYLES[event.event_type]
  const isThinking = event.event_type === 'thinking'
  const [open, setOpen] = useState(!isThinking)

  const body = eventBody(event)
  const isSentinel =
    (event.event_type === 'text' || event.event_type === 'final') &&
    SENTINEL_TEXTS.has(body.trim())

  return (
    <div className="border-l-2 border-[rgba(40,140,180,0.25)] pl-4 py-2">
      <button
        type="button"
        className="flex w-full items-baseline gap-3 text-left"
        onClick={() => setOpen(!open)}
      >
        <span className={`text-[10px] font-bold tracking-[1.5px] ${style.color}`}>
          {style.label}
        </span>
        <span className="text-[10px] text-[#556677] tabular-nums">
          {formatTime(event.ts)}
        </span>
        {isSentinel && (
          <span className="rounded bg-[rgba(85,102,119,0.2)] px-1.5 py-0.5 text-[9px] tracking-[1px] text-[#667788]">
            SENTINEL
          </span>
        )}
        <span className="ml-auto text-[10px] text-[#556677]">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <pre className={`mt-2 whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed ${
          isSentinel ? 'text-[#667788]' : 'text-[#cde]'
        }`}>
          {body || '(empty)'}
        </pre>
      )}
    </div>
  )
}
