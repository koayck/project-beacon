interface ControlsProps {
  followBeacon: boolean
  onToggleFollow: () => void
  transparentWalls: boolean
  onToggleWalls: () => void
  fogEnabled: boolean
  onToggleFog: () => void
  showFogToggle: boolean
  followedAssetId: string | null
  activeAssetIds: string[]
  onFollowPrevious: () => void
  onFollowNext: () => void
  selectMode: boolean
  placingStation: boolean
  onTogglePlaceStation: () => void
}

export function Controls({
  followBeacon,
  onToggleFollow,
  transparentWalls,
  onToggleWalls,
  fogEnabled,
  onToggleFog,
  showFogToggle,
  followedAssetId,
  activeAssetIds,
  onFollowPrevious,
  onFollowNext,
  selectMode,
  placingStation,
  onTogglePlaceStation,
}: ControlsProps) {
  const buttonClass = (enabled: boolean, onClasses: string, offClasses: string) =>
    `flex-1 rounded border px-[6px] py-[6px] text-center font-mono text-[11px] tracking-[0.5px] transition-all duration-150 ${enabled ? onClasses : offClasses}`

  const followIndex = followedAssetId ? activeAssetIds.indexOf(followedAssetId) : -1
  const canCycleTargets = activeAssetIds.length > 1

  return (
    <div className={`pointer-events-auto w-full min-w-[320px] rounded-lg border p-[10px_12px] font-mono text-xs leading-[1.6] text-[#8899aa] backdrop-blur-[12px] ${
      selectMode
        ? 'border-[rgba(255,136,0,0.3)] bg-[linear-gradient(135deg,rgba(30,16,0,0.85),rgba(20,10,0,0.75))]'
        : 'border-[rgba(40,60,100,0.25)] bg-[linear-gradient(135deg,rgba(8,10,20,0.82),rgba(6,8,16,0.72))]'
    }`}>
      {selectMode ? (
        <div className="py-1 text-center text-[13px] font-bold tracking-[1px] text-[#ff9933]">
          AREA SELECT ACTIVE
          <div className="mt-0.5 text-[11px] font-normal text-[#997744]">Ctrl+S / Esc to cancel</div>
        </div>
      ) : (
        <>
          <div className="mb-1.5 text-center text-[11px] tracking-[1px] text-[#7a8a9a]">
            SCENE CONTROLS
          </div>
          <div className="mb-2 flex flex-wrap justify-center gap-y-[3px] gap-x-2 text-[11px] text-[#7a8a9a]">
            <span>Drag: orbit/pan</span>
            <span className="text-[#3a4a5a]">│</span>
            <span>Scroll: zoom</span>
            <span className="text-[#3a4a5a]">│</span>
            <span className="text-[#6a8aaa]">F: follow</span>
            <span className="text-[#3a4a5a]">│</span>
            <span className="text-[#c87]">Ctrl+S: select</span>
          </div>
        </>
      )}
      <div className="flex gap-1">
        <button
          onClick={onToggleFollow}
          className={buttonClass(
            followBeacon,
            'border-[rgba(90,140,255,0.4)] bg-[rgba(40,130,255,0.2)] text-[#9fd0ff]',
            'border-[rgba(40,50,70,0.5)] bg-[rgba(15,20,30,0.6)] text-[#4a5a6a]',
          )}
        >
          FOLLOW {followBeacon ? 'ON' : 'OFF'}
        </button>
        <button
          onClick={onToggleWalls}
          className={buttonClass(
            transparentWalls,
            'border-[rgba(120,190,255,0.4)] bg-[rgba(60,170,255,0.18)] text-[#b5e6ff]',
            'border-[rgba(40,50,70,0.5)] bg-[rgba(15,20,30,0.6)] text-[#4a5a6a]',
          )}
        >
          WALLS {transparentWalls ? 'X-RAY' : 'SOLID'}
        </button>
        {showFogToggle && (
          <button
            onClick={onToggleFog}
            className={buttonClass(
              fogEnabled,
              'border-[rgba(255,204,68,0.4)] bg-[rgba(255,180,40,0.18)] text-[#ffe39a]',
              'border-[rgba(40,50,70,0.5)] bg-[rgba(15,20,30,0.6)] text-[#4a5a6a]',
            )}
            title="Toggle fog-of-war (hides unexplored sectors)"
          >
            FOG {fogEnabled ? 'ON' : 'OFF'}
          </button>
        )}
        <button
          onClick={onTogglePlaceStation}
          disabled={selectMode}
          className={buttonClass(
            placingStation,
            'border-[#ff8800] bg-[rgba(255,136,0,0.18)] text-[#ffaa55]',
            'border-[rgba(40,60,100,0.25)] bg-[rgba(10,14,24,0.6)] text-[#7a8a9a]',
          ) + (selectMode ? ' cursor-not-allowed opacity-40' : '')}
          title={selectMode ? 'Exit area-select mode to place stations' : 'Click the ground to place a supply station'}
        >
          {placingStation ? 'PLACING…  Esc' : '+ STATION'}
        </button>
      </div>
      {followBeacon && activeAssetIds.length > 0 && (
        <div className="mt-2 flex items-center gap-1">
          <button
            onClick={onFollowPrevious}
            disabled={!canCycleTargets}
            className="w-7 rounded border border-[rgba(90,140,255,0.4)] bg-[rgba(40,130,255,0.12)] px-[4px] py-[4px] text-[11px] text-[#9fd0ff] disabled:border-[rgba(40,50,70,0.5)] disabled:bg-[rgba(15,20,30,0.6)] disabled:text-[#4a5a6a]"
            aria-label="Follow previous drone"
          >
            ←
          </button>
          <div className="flex-1 rounded border border-[rgba(40,50,70,0.45)] bg-[rgba(12,17,28,0.7)] px-[8px] py-[4px] text-center text-[10px] tracking-[0.5px] text-[#8fa5bc]">
            TARGET {followedAssetId ?? 'N/A'} {followIndex >= 0 ? `(${followIndex + 1}/${activeAssetIds.length})` : ''}
          </div>
          <button
            onClick={onFollowNext}
            disabled={!canCycleTargets}
            className="w-7 rounded border border-[rgba(90,140,255,0.4)] bg-[rgba(40,130,255,0.12)] px-[4px] py-[4px] text-[11px] text-[#9fd0ff] disabled:border-[rgba(40,50,70,0.5)] disabled:bg-[rgba(15,20,30,0.6)] disabled:text-[#4a5a6a]"
            aria-label="Follow next drone"
          >
            →
          </button>
        </div>
      )}
    </div>
  )
}

// export function CameraTracker({ northAngleRef }: { northAngleRef: MutableRefObject<number> }) {
//   const { camera } = useThree()
//   const dirRef = useRef(new THREE.Vector3())
//   useFrame(() => {
//     dirRef.current.set(0, 0, -1).transformDirection(camera.matrixWorldInverse)
//     northAngleRef.current = Math.atan2(dirRef.current.x, dirRef.current.y)
//   })
//   return null
// }