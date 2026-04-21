interface SurvivorPoint {
  x: number
  y: number
  z: number
}

interface NetworkMockStatus {
  mode: string
  target_ssid: string | null
}

export function TopStatusBar({
  selectMode,
  floodLevel,
  survivors,
  activeWorld,
  onWorldChange,
  networkMockStatus,
}: {
  selectMode: boolean
  floodLevel: number
  survivors: SurvivorPoint[]
  activeWorld: 1 | 2
  onWorldChange: (world: 1 | 2) => void
  networkMockStatus: NetworkMockStatus | null
}) {
  const submerged = survivors.filter(p => p.y < floodLevel - 0.2).length
  const networkMode = networkMockStatus?.mode ?? 'unknown'
  const starlinkActive = networkMode === 'starlink' || networkMode === 'degraded'
  const networkLabel = starlinkActive
    ? `STARLINK MOCK ${networkMode === 'degraded' ? 'DEGRADED' : 'ACTIVE'}`
    : 'DIRECT LINK'
  const worldButtonClass = (active: boolean) =>
    active
      ? 'rounded border border-[rgba(0,180,255,0.35)] bg-[rgba(0,180,255,0.15)] px-[10px] py-[3px] font-mono text-[11px] font-bold tracking-[1.2px] text-[#00ccff] transition-all duration-200'
      : 'rounded border border-[rgba(100,120,140,0.2)] bg-transparent px-[10px] py-[3px] font-mono text-[11px] font-medium tracking-[1.2px] text-[#5a6a7a] transition-all duration-200'

  return (
    <div className="pointer-events-auto absolute left-0 right-0 top-0 z-20 flex h-12 items-center justify-between border-b border-[rgba(0,180,255,0.08)] bg-[linear-gradient(180deg,rgba(6,6,16,0.95),rgba(6,6,16,0.78))] px-6 font-mono backdrop-blur-[16px]">
      <div className="absolute bottom-0 left-0 right-0 h-px bg-[linear-gradient(90deg,transparent_5%,rgba(0,200,255,0.25)_30%,rgba(0,200,255,0.15)_70%,transparent_95%)]" />

      <div className="flex items-center gap-3.5">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 animate-[beacon-signalDot_2s_ease-in-out_infinite] rounded-full bg-[#00ccff] shadow-[0_0_10px_rgba(0,200,255,0.6),0_0_20px_rgba(0,200,255,0.2)]" />
          <span className="text-[15px] font-bold tracking-[3px] text-[#e0f0ff] drop-shadow-[0_0_20px_rgba(0,200,255,0.2)]">
            PROJECT BEACON
          </span>
        </div>
        <span className="text-sm text-[#3a4a5a]">|</span>
        <div className="flex gap-0.5">
          {([2, 1] as const).map(w => {
            const active = activeWorld === w
            const label = w === 2 ? 'HAT YAI' : 'WORLD 1'
            return (
              <button
                key={w}
                onClick={() => onWorldChange(w)}
                className={worldButtonClass(active)}
              >
                {label}
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex items-center gap-2.5 text-xs">
        <span className={starlinkActive
          ? 'rounded-[3px] border border-[rgba(0,170,255,0.35)] bg-[rgba(0,110,255,0.15)] px-2 py-0.5 tracking-[0.8px] text-[#7dcfff]'
          : 'rounded-[3px] border border-[rgba(80,100,120,0.25)] bg-[rgba(70,85,100,0.12)] px-2 py-0.5 tracking-[0.8px] text-[#9cb0c4]'
        }>
          {networkLabel}
          {networkMockStatus?.target_ssid ? ` • SSID ${networkMockStatus.target_ssid}` : ''}
        </span>
        {/* {selectMode && (
          <span className="rounded-[3px] border border-[rgba(255,140,0,0.3)] bg-[rgba(255,100,0,0.1)] px-2 py-0.5 font-bold tracking-[1px] text-[#ff9933]">
            AREA SELECT
          </span>
        )} */}
        {submerged > 0 && (
          <span className="flex items-center gap-1 rounded-[3px] border border-[rgba(255,60,60,0.25)] bg-[rgba(255,40,40,0.08)] px-2 py-0.5 text-[#ff5555]">
            <span className="h-[5px] w-[5px] shrink-0 animate-[beacon-livePulse_1.5s_ease-in-out_infinite] rounded-full bg-[#ff4444]" />
            {submerged} SUBMERGED
          </span>
        )}
        <span className="tracking-[0.5px] text-[#e87730]">
          FLOOD +{floodLevel.toFixed(1)}m
        </span>
      </div>
    </div>
  )
}
