import { MutableRefObject, RefObject, useEffect, useRef } from "react"

export function CompassLabels({ northAngleRef }: { northAngleRef: MutableRefObject<number> }) {
  const nRef = useRef<HTMLDivElement>(null)
  const sRef = useRef<HTMLDivElement>(null)
  const eRef = useRef<HTMLDivElement>(null)
  const wRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const PAD = 22
    function edgePos(angle: number, w: number, h: number): { x: number; y: number } {
      const dx = Math.sin(angle)
      const dy = -Math.cos(angle)
      const sx = Math.abs(dx) > 1e-9 ? (w / 2 - PAD) / Math.abs(dx) : Infinity
      const sy = Math.abs(dy) > 1e-9 ? (h / 2 - PAD) / Math.abs(dy) : Infinity
      const s = Math.min(sx, sy)
      return { x: w / 2 + dx * s, y: h / 2 + dy * s }
    }

    const directions: [RefObject<HTMLDivElement | null>, number][] = [
      [nRef, 0],
      [sRef, Math.PI],
      [eRef, Math.PI / 2],
      [wRef, -Math.PI / 2],
    ]

    let rafId: number
    function tick() {
      const az = northAngleRef.current
      const width = window.innerWidth
      const height = window.innerHeight
      for (const [ref, offset] of directions) {
        if (!ref.current) continue
        const { x, y } = edgePos(az + offset, width, height)
        ref.current.style.left = `${x}px`
        ref.current.style.top = `${y}px`
      }
      rafId = requestAnimationFrame(tick)
    }
    rafId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafId)
  }, [northAngleRef])

  return (
    <>
      <div ref={nRef} className="pointer-events-none absolute z-[5] select-none -translate-x-1/2 -translate-y-1/2 font-mono text-[11px] tracking-[2px] text-[rgba(180,200,255,0.55)]">N</div>
      <div ref={sRef} className="pointer-events-none absolute z-[5] select-none -translate-x-1/2 -translate-y-1/2 font-mono text-[11px] tracking-[2px] text-[rgba(180,200,255,0.55)]">S</div>
      <div ref={eRef} className="pointer-events-none absolute z-[5] select-none -translate-x-1/2 -translate-y-1/2 font-mono text-[11px] tracking-[2px] text-[rgba(180,200,255,0.55)]">E</div>
      <div ref={wRef} className="pointer-events-none absolute z-[5] select-none -translate-x-1/2 -translate-y-1/2 font-mono text-[11px] tracking-[2px] text-[rgba(180,200,255,0.55)]">W</div>
    </>
  )
}