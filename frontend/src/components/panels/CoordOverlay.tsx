import * as THREE from 'three'


export function CoordOverlay({ point, copied }: { point: THREE.Vector3 | null; copied: boolean }) {
  if (!point) return null
  return (
    <div
      className={`pointer-events-none absolute left-1/2 top-14 z-10 flex -translate-x-1/2 gap-5 whitespace-nowrap rounded-[5px] border px-[18px] py-[5px] font-mono text-sm tracking-[1px] backdrop-blur-[8px] transition-[background,color,border] duration-150 ${
        copied
          ? 'border-[#44ff8833] bg-[rgba(40,80,40,0.92)] text-[#88ff88]'
          : 'border-[#ffe06030] bg-[rgba(6,8,16,0.85)] text-[#ffe060]'
      }`}
    >
      {copied
        ? <span>✓ copied to clipboard</span>
        : <>
            <span>X&nbsp;<span className="text-white">{point.x.toFixed(1)}</span></span>
            <span>Y&nbsp;<span className="text-white">{point.y.toFixed(1)}</span></span>
            <span>Z&nbsp;<span className="text-white">{point.z.toFixed(1)}</span></span>
            <span className="text-xs text-[#888]">double-click to copy</span>
          </>
      }
    </div>
  )
}