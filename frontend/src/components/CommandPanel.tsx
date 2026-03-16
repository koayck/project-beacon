'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import type { AgentStreamEvent } from '@/lib/api'
import { setDroneSpeed, resetDroneToBase } from '@/lib/api'

interface AgentMessage {
  role: 'user' | 'agent'
  lines: string[]
  ts: number
}

interface Props {
  assetId: string
  connected: boolean
  uplinked: boolean
  battery: number | null
  onCommand: (prompt: string, onEvent: (e: AgentStreamEvent) => void) => Promise<void>
  onStop?: () => void
}

const QUICK_ACTIONS = [
  { label: 'SCAN TARGET', prompt: 'Scan the target building for survivors', color: '#ffaa44', border: 'rgba(255,170,0,0.35)', bg: 'rgba(255,170,0,0.08)' },
  { label: 'SURVEY', prompt: 'Survey the perimeter of the area', color: '#4cf', border: 'rgba(0,200,255,0.35)', bg: 'rgba(0,200,255,0.08)' },
  { label: 'STATUS', prompt: 'Report current mission status', color: '#6c6', border: 'rgba(100,200,100,0.35)', bg: 'rgba(100,200,100,0.08)' },
  { label: 'RTB', prompt: 'Return the drone to base', color: '#99f', border: 'rgba(130,130,255,0.35)', bg: 'rgba(130,130,255,0.08)' },
] as const

function formatToolCall(name: string, args: Record<string, unknown>, agent: string): string {
  const argStr = Object.entries(args)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(', ')
  return `[${agent}] -> ${name}(${argStr})`
}

function formatToolResult(name: string, success: boolean, result: string): string {
  return `  ${success ? '✓' : '✗'} ${name}: ${result}`
}

/** Flatten a message pair (user + following agent) into a plain string */
function messagesToText(messages: AgentMessage[]): string {
  return messages
    .map(m => {
      const prefix = m.role === 'user' ? 'YOU' : 'ADK'
      return `${prefix}: ${m.lines.join('\n')}`
    })
    .join('\n\n')
}

export default function CommandPanel({ assetId, connected, uplinked, battery, onCommand, onStop }: Props) {
  const [input, setInput]       = useState('')
  const [busy, setBusy]         = useState(false)
  const [elapsed, setElapsed]   = useState(0)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [ttft, setTtft]         = useState<number | null>(null)
  const [tps, setTps]           = useState<number | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied]     = useState(false)
  const [fastMode, setFastMode] = useState(false)
  const [resetting, setResetting] = useState(false)
  const copiedTimer             = useRef<ReturnType<typeof setTimeout> | null>(null)
  const bottomRef               = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const appendAgentLine = (line: string) => {
    setMessages(prev => {
      const last = prev[prev.length - 1]
      if (last?.role === 'agent') {
        return [...prev.slice(0, -1), { ...last, lines: [...last.lines, line] }]
      }
      return [...prev, { role: 'agent', lines: [line], ts: Date.now() }]
    })
  }

  const clearHistory = useCallback(() => {
    setMessages([])
    setTtft(null)
    setTps(null)
  }, [])

  const copyAll = useCallback(() => {
    if (messages.length === 0) return
    const text = messagesToText(messages)
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    if (copiedTimer.current) clearTimeout(copiedTimer.current)
    copiedTimer.current = setTimeout(() => setCopied(false), 1800)
  }, [messages])

  const toggleSpeed = useCallback(async () => {
    if (!connected) return
    const next = !fastMode
    setFastMode(next)
    try {
      await setDroneSpeed(assetId, next ? 20.0 : 5.0)
    } catch {
      setFastMode(!next) // revert on failure
    }
  }, [assetId, connected, fastMode])

  const handleReset = useCallback(async () => {
    if (!connected || resetting) return
    setResetting(true)
    try {
      await resetDroneToBase(assetId)
    } finally {
      setResetting(false)
    }
  }, [assetId, connected, resetting])

  const submit = async (directPrompt?: string) => {
    const text = directPrompt ?? input.trim()
    if (!text || busy || !connected) return

    if (!directPrompt) setInput('')
    setElapsed(0)
    setTtft(null)
    setTps(null)
    setMessages(prev => [...prev, { role: 'user', lines: [text], ts: Date.now() }])
    setMessages(prev => [...prev, { role: 'agent', lines: [], ts: Date.now() }])
    setBusy(true)

    try {
      await onCommand(text, (event) => {
        if (event.type === 'heartbeat') {
          setElapsed(event.elapsed)
        } else if (event.type === 'tool_call') {
          appendAgentLine(formatToolCall(event.name, event.args, event.agent))
        } else if (event.type === 'tool_result') {
          appendAgentLine(formatToolResult(event.name, event.success, event.result))
        } else if (event.type === 'text' || event.type === 'final') {
          appendAgentLine(event.text)
        } else if (event.type === 'error') {
          appendAgentLine(`Error: ${event.text}`)
        } else if (event.type === 'done') {
          setTtft(event.ttft_ms)
          setTps(event.tps)
        }
      })
    } catch (err) {
      appendAgentLine(`Error: ${err}`)
    } finally {
      setBusy(false)
    }
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const logHeight = expanded ? 480 : 200
  const panelWidth = expanded ? 780 : 560

  return (
    <div style={{
      position: 'absolute',
      bottom: 20,
      left: '50%',
      transform: 'translateX(-50%)',
      width: panelWidth,
      transition: 'width 0.2s ease',
      background: 'rgba(8, 10, 20, 0.88)',
      border: '1px solid rgba(80, 120, 200, 0.35)',
      borderRadius: 8,
      fontFamily: 'Courier New, monospace',
      fontSize: 12,
      backdropFilter: 'blur(6px)',
      boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 14px',
        borderBottom: '1px solid rgba(80, 120, 200, 0.2)',
      }}>
        {/* Status dot */}
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: connected ? '#33ff88' : uplinked ? '#ffcc66' : '#ff4444',
          boxShadow: connected ? '0 0 6px #33ff88' : uplinked ? '0 0 6px #ffcc66' : '0 0 6px #ff4444',
          flexShrink: 0,
        }} />
        <span style={{ color: connected ? '#33ff88' : uplinked ? '#ffcc66' : '#ff6666', fontWeight: 'bold', letterSpacing: 1 }}>
          {assetId}
        </span>
        <span style={{ color: '#445', marginLeft: 4 }}>
          {connected ? 'LIVE' : uplinked ? 'REGISTERED / OFFLINE' : 'OFFLINE'}
        </span>

        {battery !== null && (
          <span style={{ marginLeft: 'auto', color: battery > 30 ? '#88cc66' : '#ff9933' }}>
            ⚡ {battery.toFixed(0)}%
          </span>
        )}

        {(ttft !== null || tps !== null) && (
          <span style={{ display: 'flex', gap: 10, marginLeft: battery !== null ? 8 : 'auto', color: '#5af', fontSize: 11 }}>
            {ttft !== null && (
              <span title="Time to First Token">
                <span style={{ color: '#446' }}>TTFT </span>
                {ttft < 1000 ? `${ttft}ms` : `${(ttft / 1000).toFixed(1)}s`}
              </span>
            )}
            {tps !== null && (
              <span title="Tokens per Second">
                <span style={{ color: '#446' }}>TPS </span>{tps}
              </span>
            )}
          </span>
        )}

        <span style={{ color: '#336', marginLeft: (ttft !== null || tps !== null || battery !== null) ? 8 : 'auto' }}>
          ADK / Qwen3.5
        </span>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
          {/* Copy */}
          <HeaderBtn
            title="Copy conversation"
            disabled={messages.length === 0}
            active={copied}
            onClick={copyAll}
          >
            {copied ? '✓' : '⎘'}
          </HeaderBtn>
          {/* Clear */}
          <HeaderBtn
            title="Clear chat history"
            disabled={messages.length === 0 || busy}
            onClick={clearHistory}
          >
            ✕
          </HeaderBtn>
          {/* Expand / collapse */}
          <HeaderBtn
            title={expanded ? 'Collapse panel' : 'Expand panel'}
            onClick={() => setExpanded(v => !v)}
          >
            {expanded ? '⊟' : '⊞'}
          </HeaderBtn>
        </div>
      </div>

      <div style={{
        height: logHeight,
        transition: 'height 0.2s ease',
        overflowY: 'auto',
        padding: '8px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}>
        {messages.length === 0 && (
          <div style={{ color: '#334', fontStyle: 'italic', marginTop: 4 }}>
            {connected ? 'Type a natural language command...' : 'Waiting for backend connection...'}
          </div>
        )}
        {messages.map((m) => (
          <div key={m.ts} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {m.role === 'user' ? (
              <div style={{ color: '#6af', alignSelf: 'flex-end' }}>
                <span style={{ color: '#445', marginRight: 6 }}>YOU</span>
                {m.lines[0]}
              </div>
            ) : (
              <div style={{ color: '#aec', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                {m.lines.length === 0 && busy && (
                  <span style={{ color: '#556', fontStyle: 'italic' }}>
                    <Spinner /> LLM inferring{elapsed > 0 ? ` (${elapsed}s)` : '...'}
                  </span>
                )}
                {m.lines.map((line, i) => (
                  <div key={i} style={{
                    color: line.startsWith('[') && line.includes('→')
                      ? '#7af'
                      : line.startsWith('  ✓')
                      ? '#4c8'
                      : line.startsWith('  ✗')
                      ? '#f66'
                      : '#aec',
                  }}>
                    {i === 0 && <span style={{ color: '#33cc66', marginRight: 6 }}>ADK</span>}
                    {line}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Quick-action bar (agent commands) */}
      <div style={{
        display: 'flex',
        gap: 5,
        padding: '5px 10px',
        borderTop: '1px solid rgba(80, 120, 200, 0.15)',
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <span style={{ color: '#556', fontSize: 10, letterSpacing: 1, marginRight: 2 }}>QUICK</span>
        {QUICK_ACTIONS.map(action => (
          <button
            key={action.label}
            onClick={() => submit(action.prompt)}
            disabled={!connected || busy}
            title={action.prompt}
            style={{
              background: action.bg,
              border: `1px solid ${action.border}`,
              borderRadius: 4,
              color: (!connected || busy) ? '#334' : action.color,
              padding: '2px 8px',
              cursor: (!connected || busy) ? 'default' : 'pointer',
              fontFamily: 'Courier New, monospace',
              fontSize: 10,
              letterSpacing: 0.5,
              transition: 'all 0.15s',
            }}
          >
            {action.label}
          </button>
        ))}
      </div>

      {/* Direct-action bar */}
      <div style={{
        display: 'flex',
        gap: 6,
        padding: '5px 10px',
        borderTop: '1px solid rgba(80, 120, 200, 0.15)',
        alignItems: 'center',
      }}>
        <span style={{ color: '#334', fontSize: 10, letterSpacing: 1, marginRight: 2 }}>DIRECT</span>
        <button
          onClick={toggleSpeed}
          disabled={!connected}
          title={fastMode ? 'Switch to normal speed (5 m/s)' : 'Switch to fast speed (20 m/s)'}
          style={{
            background: fastMode ? 'rgba(255, 180, 0, 0.15)' : 'transparent',
            border: `1px solid ${fastMode ? 'rgba(255,180,0,0.45)' : 'rgba(80,120,200,0.25)'}`,
            borderRadius: 4,
            color: !connected ? '#334' : fastMode ? '#ffcc44' : '#5af',
            padding: '2px 10px',
            cursor: !connected ? 'default' : 'pointer',
            fontFamily: 'Courier New, monospace',
            fontSize: 11,
            letterSpacing: 0.5,
            transition: 'all 0.15s',
          }}
        >
          {fastMode ? '⚡ FAST' : '⚡ NORMAL'}
        </button>
        <button
          onClick={handleReset}
          disabled={!connected || resetting}
          title="Immediately return drone to base (bypasses ADK)"
          style={{
            background: resetting ? 'rgba(0,200,255,0.10)' : 'transparent',
            border: `1px solid ${resetting ? 'rgba(0,200,255,0.4)' : 'rgba(80,120,200,0.25)'}`,
            borderRadius: 4,
            color: (!connected || resetting) ? '#334' : '#4cf',
            padding: '2px 10px',
            cursor: (!connected || resetting) ? 'default' : 'pointer',
            fontFamily: 'Courier New, monospace',
            fontSize: 11,
            letterSpacing: 0.5,
            transition: 'all 0.15s',
          }}
        >
          {resetting ? '↩ RETURNING...' : '↩ RESET TO BASE'}
        </button>
      </div>

      {/* Input row */}
      <div style={{ display: 'flex', borderTop: '1px solid rgba(80, 120, 200, 0.2)' }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={busy || !connected}
          placeholder={connected ? 'e.g. "scan building at 7.6, 0.1, -14.9"' : 'backend offline'}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: '#cde',
            padding: '9px 14px',
            fontFamily: 'Courier New, monospace',
            fontSize: 12,
            opacity: (busy || !connected) ? 0.4 : 1,
          }}
        />
        {busy ? (
          <button
            onClick={() => { onStop?.(); setBusy(false) }}
            title="Abort running agent"
            style={{
              background: 'rgba(200, 40, 40, 0.15)',
              border: 'none',
              borderLeft: '1px solid rgba(200, 60, 60, 0.35)',
              color: '#f66',
              padding: '0 16px',
              cursor: 'pointer',
              fontFamily: 'Courier New, monospace',
              fontSize: 12,
              letterSpacing: 1,
            }}
          >
            ■ STOP
          </button>
        ) : (
          <button
            onClick={() => submit()}
            disabled={!connected || !input.trim()}
            style={{
              background: 'transparent',
              border: 'none',
              borderLeft: '1px solid rgba(80, 120, 200, 0.2)',
              color: (!connected || !input.trim()) ? '#334' : '#4af',
              padding: '0 16px',
              cursor: (!connected || !input.trim()) ? 'default' : 'pointer',
              fontFamily: 'Courier New, monospace',
              fontSize: 12,
              letterSpacing: 1,
            }}
          >
            SEND
          </button>
        )}
      </div>
    </div>
  )
}

interface HeaderBtnProps {
  onClick: () => void
  title?: string
  disabled?: boolean
  active?: boolean
  children: React.ReactNode
}

function HeaderBtn({ onClick, title, disabled = false, active = false, children }: HeaderBtnProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        background: active ? 'rgba(50,200,100,0.15)' : 'transparent',
        border: `1px solid ${active ? '#33cc6655' : 'rgba(80,120,200,0.25)'}`,
        borderRadius: 4,
        color: disabled ? '#334' : active ? '#4c8' : '#5af',
        padding: '1px 7px',
        cursor: disabled ? 'default' : 'pointer',
        fontFamily: 'Courier New, monospace',
        fontSize: 12,
        lineHeight: '18px',
        transition: 'color 0.15s, background 0.15s',
      }}
    >
      {children}
    </button>
  )
}

function Spinner() {
  const frames = ['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏']
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI(p => (p + 1) % frames.length), 100)
    return () => clearInterval(t)
  }, [])
  return <span style={{ marginRight: 4, color: '#6af' }}>{frames[i]}</span>
}

