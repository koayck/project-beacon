'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import type { AgentStreamEvent } from '@/lib/api'
import { setFleetSpeed, recallFleet } from '@/lib/api'

interface AgentMessage {
  role: 'user' | 'agent'
  lines: string[]
  thinking: string[]
  ts: number
}

export interface CommandDecisionOption {
  id: string
  label: string
}

export interface CommandDecisionPrompt {
  title: string
  message: string
  details?: string[]
  options: CommandDecisionOption[]
}

export interface AgentMetrics {
  ttft: number | null
  tps: number | null
  busy: boolean
  elapsed: number
}

interface Props {
  assetId: string
  connected: boolean
  uplinked: boolean
  battery: number | null
  onCommand: (prompt: string, onEvent: (e: AgentStreamEvent) => void, assetIdOverride?: string) => Promise<void>
  onStop?: () => Promise<void> | void
  externalPrompt?: string | null
  onExternalPromptConsumed?: () => void
  externalAssetId?: string | null
  onMetricsChange?: (metrics: AgentMetrics) => void
  scoutAvailable?: boolean
  decisionPrompt?: CommandDecisionPrompt | null
  onDecisionOptionSelect?: (optionId: string) => void
  onDecisionDismiss?: () => void
}

const SCOUT_DEPLOY_PROMPT = 'Deploy the scout drone to survey the disaster zone and map every sector.'

const QUICK_ACTIONS = [
  { label: 'SCAN TARGET', prompt: 'Scan the target building for survivors using all available drones', color: '#ffaa44', border: 'rgba(255,170,0,0.35)', bg: 'rgba(255,170,0,0.08)' },
  { label: 'SURVEY', prompt: 'Survey the perimeter of the area using all available drones', color: '#4cf', border: 'rgba(0,200,255,0.35)', bg: 'rgba(0,200,255,0.08)' },
  { label: 'STATUS', prompt: 'Report current mission status for all drones', color: '#6c6', border: 'rgba(100,200,100,0.35)', bg: 'rgba(100,200,100,0.08)' },
  { label: 'RTB', prompt: 'Recall all drones to base', color: '#99f', border: 'rgba(130,130,255,0.35)', bg: 'rgba(130,130,255,0.08)', direct: true },
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

export default function CommandPanel({
  assetId,
  connected,
  uplinked,
  battery,
  onCommand,
  onStop,
  externalPrompt,
  onExternalPromptConsumed,
  externalAssetId,
  onMetricsChange,
  scoutAvailable,
  decisionPrompt,
  onDecisionOptionSelect,
  onDecisionDismiss,
}: Props) {
  const [input, setInput]       = useState('')
  const [busy, setBusy]         = useState(false)
  const [elapsed, setElapsed]   = useState(0)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [ttft, setTtft]         = useState<number | null>(null)
  const [tps, setTps]           = useState<number | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [minimized, setMinimized] = useState(false)
  const [copied, setCopied]     = useState(false)
  const [fastMode, setFastMode] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const copiedTimer             = useRef<ReturnType<typeof setTimeout> | null>(null)
  const bottomRef               = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    onMetricsChange?.({ ttft, tps, busy, elapsed })
  }, [ttft, tps, busy, elapsed, onMetricsChange])

  // Auto-submit externally injected prompts (e.g. from area scan)
  useEffect(() => {
    if (!externalPrompt || busy || !connected) return
    setInput(externalPrompt)
    onExternalPromptConsumed?.()
    // Defer to next tick so input state is set before submit reads it
    setTimeout(() => {
      setInput('')
      setElapsed(0)
      setTtft(null)
      setTps(null)
      setMessages(prev => [...prev, { role: 'user', lines: [externalPrompt], thinking: [], ts: Date.now() }])
      setMessages(prev => [...prev, { role: 'agent', lines: [], thinking: [], ts: Date.now() }])
      setBusy(true)
      onCommand(externalPrompt, (event) => {
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
      }, externalAssetId ?? undefined).catch(err => {
        appendAgentLine(`Error: ${err}`)
      }).finally(() => {
        setBusy(false)
      })
    }, 0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalPrompt])

  const appendAgentLine = (line: string) => {
    setMessages(prev => {
      const last = prev[prev.length - 1]
      if (last?.role === 'agent') {
        return [...prev.slice(0, -1), { ...last, lines: [...last.lines, line] }]
      }
      return [...prev, { role: 'agent', lines: [line], thinking: [], ts: Date.now() }]
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
      await setFleetSpeed(next ? 20.0 : 5.0)
    } catch {
      setFastMode(!next) // revert on failure
    }
  }, [connected, fastMode])

  const handleReset = useCallback(async () => {
    if (!connected || resetting) return
    setResetting(true)
    try {
      await recallFleet()
    } finally {
      setResetting(false)
    }
  }, [connected, resetting])

  const submit = async (directPrompt?: string) => {
    const text = directPrompt ?? input.trim()
    if (!text || busy || !connected) return

    if (!directPrompt) setInput('')
    setElapsed(0)
    setTtft(null)
    setTps(null)
    setMessages(prev => [...prev, { role: 'user', lines: [text], thinking: [], ts: Date.now() }])
    setMessages(prev => [...prev, { role: 'agent', lines: [], thinking: [], ts: Date.now() }])
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
  const panelWidth = minimized ? 480 : expanded ? 780 : 560

  return (
    <div style={{
      position: 'absolute',
      bottom: 16,
      left: '50%',
      transform: 'translateX(-50%)',
      width: panelWidth,
      transition: 'width 0.2s ease',
      background: 'linear-gradient(135deg, rgba(6,8,16,0.92), rgba(4,6,14,0.88))',
      border: '1px solid rgba(60,100,180,0.2)',
      borderRadius: 8,
      fontFamily: "'Courier New', monospace",
      fontSize: 14,
      backdropFilter: 'blur(14px)',
      boxShadow: '0 8px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(100,150,255,0.05)',
    }}>
      {/* Primary header row — identity + actions */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 14px 4px',
      }}>
        {/* Status dot */}
        <span style={{
          width: 7, height: 7, borderRadius: '50%',
          background: connected ? '#33ff88' : uplinked ? '#ffcc66' : '#ff4444',
          boxShadow: connected ? '0 0 8px #33ff88' : uplinked ? '0 0 8px #ffcc66' : '0 0 8px #ff4444',
          flexShrink: 0,
        }} />
        <span style={{ color: connected ? '#33ff88' : uplinked ? '#ffcc66' : '#ff6666', fontWeight: 'bold', letterSpacing: 1.5, fontSize: 13 }}>
          COMMANDER
        </span>
        <span style={{ color: '#6a7a8a', fontSize: 12 }}>
          {connected ? 'CONNECTED' : uplinked ? 'REGISTERED / OFFLINE' : 'OFFLINE'}
        </span>

        {/* Action buttons — push right */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
          <HeaderBtn
            title="Copy conversation"
            disabled={messages.length === 0}
            active={copied}
            onClick={copyAll}
          >
            {copied ? '✓' : '⎘'}
          </HeaderBtn>
          <HeaderBtn
            title="Clear chat history"
            disabled={messages.length === 0 || busy}
            onClick={clearHistory}
          >
            ✕
          </HeaderBtn>
          <HeaderBtn
            title={expanded ? 'Collapse panel' : 'Expand panel'}
            onClick={() => { setExpanded(v => !v); if (minimized) setMinimized(false) }}
          >
            {expanded ? '⊟' : '⊞'}
          </HeaderBtn>
          <HeaderBtn
            title={minimized ? 'Restore panel' : 'Minimize panel'}
            onClick={() => { setMinimized(v => !v); if (!minimized) setExpanded(false) }}
          >
            {minimized ? '▲' : '▼'}
          </HeaderBtn>
        </div>
      </div>

      {/* Thin divider under header */}
      <div style={{ borderBottom: '1px solid rgba(60,100,180,0.12)' }} />

      {!minimized && (
        <>
          <div style={{
              height: logHeight,
              transition: 'height 0.2s ease',
              overflowY: 'auto',
              overflowX: 'hidden',
              padding: '8px 14px',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}>
            {messages.length === 0 && (
              <div style={{ color: '#5a6a7a', fontStyle: 'italic', marginTop: 4 }}>
                {connected ? 'Type a natural language command...' : 'Waiting for backend connection...'}
              </div>
            )}
            {messages.map((m) => (
              <div key={m.ts} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {m.role === 'user' ? (
                  <div style={{ color: '#6af', alignSelf: 'flex-end' }}>
                    <span style={{ color: '#6a7a8a', marginRight: 6 }}>YOU</span>
                    {m.lines[0]}
                  </div>
                ) : (
                  <div style={{ color: '#aec', whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.6 }}>
                    {m.lines.length === 0 && busy && (
                      <span style={{ color: '#7a8a9a', fontStyle: 'italic' }}>
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

          {decisionPrompt && (
            <div style={{
              margin: '0 10px 8px',
              padding: '8px 10px',
              borderRadius: 6,
              border: '1px solid rgba(255,185,90,0.45)',
              background: 'linear-gradient(135deg, rgba(36,20,6,0.86), rgba(18,10,3,0.86))',
              color: '#ffe8c7',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontSize: 12, letterSpacing: 1, color: '#ffcf8a', fontWeight: 'bold' }}>
                  {decisionPrompt.title}
                </div>
                <button
                  onClick={() => onDecisionDismiss?.()}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#ffcf8a',
                    cursor: 'pointer',
                    fontFamily: 'Courier New, monospace',
                    fontSize: 12,
                    padding: '0 4px',
                  }}
                  title="Dismiss decision prompt"
                >
                  ✕
                </button>
              </div>
              <div style={{ fontSize: 12, lineHeight: 1.5, color: '#ffe0b2', whiteSpace: 'pre-wrap' }}>
                {decisionPrompt.message}
              </div>
              {(decisionPrompt.details ?? []).length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  {(decisionPrompt.details ?? []).map((detail, index) => (
                    <div key={`${detail}-${index}`} style={{ fontSize: 11, color: '#ffbf66', lineHeight: 1.45 }}>
                      {detail}
                    </div>
                  ))}
                </div>
              )}
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {decisionPrompt.options.map(option => (
                  <button
                    key={option.id}
                    onClick={() => onDecisionOptionSelect?.(option.id)}
                    style={{
                      background: option.id === 'halt' ? 'rgba(40,22,6,0.45)' : 'rgba(255,165,60,0.18)',
                      border: option.id === 'halt'
                        ? '1px solid rgba(255,190,120,0.35)'
                        : '1px solid rgba(255,195,110,0.45)',
                      borderRadius: 4,
                      color: '#fff4e1',
                      padding: '2px 8px',
                      cursor: 'pointer',
                      fontFamily: 'Courier New, monospace',
                      fontSize: 12,
                      letterSpacing: 0.4,
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 11, color: '#c7ab84' }}>
                Or type a custom command below.
              </div>
            </div>
          )}

          {/* Quick-action bar (agent commands) */}
          <div style={{
            display: 'flex',
            gap: 5,
            padding: '5px 10px',
            borderTop: '1px solid rgba(60,100,180,0.1)',
            alignItems: 'center',
            flexWrap: 'wrap',
          }}>
            <span style={{ color: '#7a8a9a', fontSize: 12, letterSpacing: 1, marginRight: 2 }}>QUICK</span>
            {scoutAvailable && (
              <button
                onClick={() => submit(SCOUT_DEPLOY_PROMPT)}
                disabled={!connected || busy}
                title={SCOUT_DEPLOY_PROMPT}
                style={{
                  background: 'rgba(255,204,0,0.10)',
                  border: '1px solid rgba(255,204,0,0.40)',
                  borderRadius: 4,
                  color: (!connected || busy) ? '#334' : '#ffcc00',
                  padding: '2px 8px',
                  cursor: (!connected || busy) ? 'default' : 'pointer',
                  fontFamily: 'Courier New, monospace',
                  fontSize: 12,
                  fontWeight: 'bold',
                  letterSpacing: 0.5,
                  transition: 'all 0.15s',
                }}
              >
                DEPLOY SCOUT
              </button>
            )}
            {QUICK_ACTIONS.map(action => (
              <button
                key={action.label}
                onClick={() => 'direct' in action && action.direct ? handleReset() : submit(action.prompt)}
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
                  fontSize: 12,
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
            borderTop: '1px solid rgba(60,100,180,0.1)',
            alignItems: 'center',
          }}>
            <span style={{ color: '#5a6a7a', fontSize: 12, letterSpacing: 1, marginRight: 2 }}>DIRECT</span>
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
                fontSize: 13,
                letterSpacing: 0.5,
                transition: 'all 0.15s',
              }}
            >
              {fastMode ? 'FAST' : 'NORMAL'}
            </button>
            <button
              onClick={handleReset}
              disabled={!connected || resetting}
              title="Immediately return all drones to base (bypasses ADK)"
              style={{
                background: resetting ? 'rgba(0,200,255,0.10)' : 'transparent',
                border: `1px solid ${resetting ? 'rgba(0,200,255,0.4)' : 'rgba(80,120,200,0.25)'}`,
                borderRadius: 4,
                color: (!connected || resetting) ? '#334' : '#4cf',
                padding: '2px 10px',
                cursor: (!connected || resetting) ? 'default' : 'pointer',
                fontFamily: 'Courier New, monospace',
                fontSize: 13,
                letterSpacing: 0.5,
                transition: 'all 0.15s',
              }}
            >
              {resetting ? 'RETURNING...' : 'RESET TO BASE'}
            </button>
          </div>
        </>
      )}

      {/* Input row */}
      <div style={{ display: 'flex', borderTop: '1px solid rgba(60,100,180,0.12)' }}>
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
            fontFamily: "'Courier New', monospace",
            fontSize: 14,
            opacity: (busy || !connected) ? 0.4 : 1,
          }}
        />
        {busy && (
          <span style={{ color: '#5af', padding: '0 8px', display: 'flex', alignItems: 'center', fontSize: 12 }}>
            <Spinner /> {elapsed > 0 ? `${elapsed}s` : '...'}
          </span>
        )}
        {busy ? (
          <button
            onClick={async () => {
              if (stopping) return
              setStopping(true)
              try {
                await onStop?.()
              } finally {
                setStopping(false)
              }
            }}
            title="Abort running agent"
            style={{
              background: 'rgba(200, 40, 40, 0.15)',
              border: 'none',
              borderLeft: '1px solid rgba(200, 60, 60, 0.35)',
              color: '#f66',
              padding: '0 16px',
              cursor: stopping ? 'default' : 'pointer',
              fontFamily: "'Courier New', monospace",
              fontSize: 14,
              letterSpacing: 1,
              opacity: stopping ? 0.7 : 1,
            }}
          >
            {stopping ? 'STOPPING...' : 'STOP'}
          </button>
        ) : (
          <button
            onClick={() => submit()}
            disabled={!connected || !input.trim()}
            style={{
              background: 'transparent',
              border: 'none',
              borderLeft: '1px solid rgba(60, 100, 180, 0.2)',
              color: (!connected || !input.trim()) ? '#334' : '#4af',
              padding: '0 16px',
              cursor: (!connected || !input.trim()) ? 'default' : 'pointer',
              fontFamily: "'Courier New', monospace",
              fontSize: 14,
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
        background: active ? 'rgba(50,200,100,0.12)' : 'rgba(15,20,30,0.5)',
        border: `1px solid ${active ? 'rgba(50,200,100,0.3)' : 'rgba(50,70,120,0.25)'}`,
        borderRadius: 4,
        color: disabled ? '#2a3040' : active ? '#4c8' : '#5580aa',
        padding: '1px 7px',
        cursor: disabled ? 'default' : 'pointer',
        fontFamily: "'Courier New', monospace",
        fontSize: 14,
        lineHeight: '20px',
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