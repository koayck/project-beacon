'use client'

import { useState, useRef, useEffect } from 'react'
import type { AgentStreamEvent } from '@/lib/api'

interface AgentMessage {
  role: 'user' | 'agent'
  lines: string[]   // rendered lines (supports live append)
  ts: number
}

interface Props {
  assetId: string
  connected: boolean
  battery: number | null
  onCommand: (prompt: string, onEvent: (e: AgentStreamEvent) => void) => Promise<void>
}

function formatToolCall(name: string, args: Record<string, unknown>, agent: string): string {
  const argStr = Object.entries(args)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(', ')
  return `[${agent}] → ${name}(${argStr})`
}

function formatToolResult(name: string, success: boolean, result: string): string {
  return `  ${success ? '✓' : '✗'} ${name}: ${result}`
}

export default function CommandPanel({ assetId, connected, battery, onCommand }: Props) {
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

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

  const submit = async () => {
    const text = input.trim()
    if (!text || busy || !connected) return

    setInput('')
    setElapsed(0)
    setMessages(prev => [...prev, { role: 'user', lines: [text], ts: Date.now() }])
    // Seed an empty agent message that we'll fill progressively
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

  return (
    <div style={{
      position: 'absolute',
      bottom: 20,
      left: '50%',
      transform: 'translateX(-50%)',
      width: 560,
      background: 'rgba(8, 10, 20, 0.88)',
      border: '1px solid rgba(80, 120, 200, 0.35)',
      borderRadius: 8,
      fontFamily: 'Courier New, monospace',
      fontSize: 12,
      backdropFilter: 'blur(6px)',
      boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
    }}>
      {/* Header bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 14px',
        borderBottom: '1px solid rgba(80, 120, 200, 0.2)',
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: connected ? '#33ff88' : '#ff4444',
          boxShadow: connected ? '0 0 6px #33ff88' : '0 0 6px #ff4444',
          flexShrink: 0,
        }} />
        <span style={{ color: connected ? '#33ff88' : '#ff6666', fontWeight: 'bold', letterSpacing: 1 }}>
          {assetId}
        </span>
        <span style={{ color: '#445', marginLeft: 4 }}>
          {connected ? 'UPLINKED' : 'OFFLINE'}
        </span>
        {battery !== null && (
          <span style={{
            marginLeft: 'auto',
            color: battery > 30 ? '#88cc66' : '#ff9933',
          }}>
            ⚡ {battery.toFixed(0)}%
          </span>
        )}
        <span style={{ color: '#336', marginLeft: battery !== null ? 8 : 'auto' }}>
          ADK / Qwen3.5
        </span>
      </div>

      {/* Message log */}
      <div style={{
        height: 200,
        overflowY: 'auto',
        padding: '8px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}>
        {messages.length === 0 && (
          <div style={{ color: '#334', fontStyle: 'italic', marginTop: 4 }}>
            {connected
              ? 'Type a natural language command...'
              : 'Waiting for backend connection...'}
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
                      ? '#7af'        // tool call
                      : line.startsWith('  ✓')
                      ? '#4c8'        // tool success
                      : line.startsWith('  ✗')
                      ? '#f66'        // tool failure
                      : '#aec',       // regular text
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

      {/* Input row */}
      <div style={{
        display: 'flex',
        gap: 0,
        borderTop: '1px solid rgba(80, 120, 200, 0.2)',
      }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={busy || !connected}
          placeholder={connected ? 'e.g. "move BEACON-01 to floor 2"' : 'backend offline'}
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
        <button
          onClick={submit}
          disabled={busy || !connected || !input.trim()}
          style={{
            background: 'transparent',
            border: 'none',
            borderLeft: '1px solid rgba(80, 120, 200, 0.2)',
            color: (busy || !connected || !input.trim()) ? '#334' : '#4af',
            padding: '0 16px',
            cursor: (busy || !connected || !input.trim()) ? 'default' : 'pointer',
            fontFamily: 'Courier New, monospace',
            fontSize: 12,
            letterSpacing: 1,
          }}
        >
          {busy ? <Spinner /> : 'SEND'}
        </button>
      </div>
    </div>
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
