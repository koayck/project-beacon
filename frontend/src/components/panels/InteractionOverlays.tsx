'use client'

import { Line } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'

export interface AreaSelection {
  minX: number
  maxX: number
  minZ: number
  maxZ: number
}

function snapToGrid(v: number, spacing: number): number {
  return Math.round(v / spacing) * spacing
}

function selectionFromPoints(a: THREE.Vector3, b: THREE.Vector3, spacing: number): AreaSelection {
  return {
    minX: snapToGrid(Math.min(a.x, b.x), spacing),
    maxX: snapToGrid(Math.max(a.x, b.x), spacing),
    minZ: snapToGrid(Math.min(a.z, b.z), spacing),
    maxZ: snapToGrid(Math.max(a.z, b.z), spacing),
  }
}

export function GroundProbe({ onMove, onDoubleClick, onClick, worldSpan }: {
  onMove: (v: THREE.Vector3 | null) => void
  onDoubleClick: (v: THREE.Vector3) => void
  onClick?: (v: THREE.Vector3) => void
  worldSpan: number
}) {
  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, 0.05, 0]}
      onPointerMove={e => { e.stopPropagation(); onMove(e.point) }}
      onPointerLeave={() => onMove(null)}
      onDoubleClick={e => { e.stopPropagation(); onDoubleClick(e.point) }}
      onClick={onClick ? (e => { e.stopPropagation(); onClick(e.point) }) : undefined}
    >
      <planeGeometry args={[worldSpan, worldSpan]} />
      <meshBasicMaterial transparent opacity={0} depthWrite={false} />
    </mesh>
  )
}

export function GroundCursor({ point }: { point: THREE.Vector3 | null }) {
  if (!point) return null
  return (
    <group position={[point.x, 0.07, point.z]}>
      <mesh>
        <boxGeometry args={[4, 0.05, 0.09]} />
        <meshBasicMaterial color="#ffe060" />
      </mesh>
      <mesh>
        <boxGeometry args={[0.09, 0.05, 4]} />
        <meshBasicMaterial color="#ffe060" />
      </mesh>
      <mesh>
        <cylinderGeometry args={[0.28, 0.28, 0.05, 8]} />
        <meshBasicMaterial color="#ffe060" />
      </mesh>
    </group>
  )
}

export function AreaSelectProbe({
  onDragUpdate,
  onDragEnd,
  worldSpan,
  gridSpacing,
}: {
  onDragUpdate: (start: THREE.Vector3, end: THREE.Vector3) => void
  onDragEnd: (sel: AreaSelection) => void
  worldSpan: number
  gridSpacing: number
}) {
  const dragStart = useRef<THREE.Vector3 | null>(null)
  const isDragging = useRef(false)

  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, 0.06, 0]}
      onPointerDown={e => {
        e.stopPropagation()
        ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
        dragStart.current = e.point.clone()
        isDragging.current = true
        onDragUpdate(e.point.clone(), e.point.clone())
      }}
      onPointerMove={e => {
        e.stopPropagation()
        if (!isDragging.current || !dragStart.current) return
        onDragUpdate(dragStart.current, e.point.clone())
      }}
      onPointerUp={e => {
        e.stopPropagation()
        if (!isDragging.current || !dragStart.current) return
        isDragging.current = false
        const sel = selectionFromPoints(dragStart.current, e.point.clone(), gridSpacing)
        dragStart.current = null
        onDragEnd(sel)
      }}
    >
      <planeGeometry args={[worldSpan, worldSpan]} />
      <meshBasicMaterial transparent opacity={0} depthWrite={false} />
    </mesh>
  )
}

export function AreaHighlight({
  start,
  end,
  finalised,
  gridSpacing,
}: {
  start: THREE.Vector3
  end: THREE.Vector3
  finalised: boolean
  gridSpacing: number
}) {
  const meshRef = useRef<THREE.Mesh>(null)
  const t = useRef(0)

  const sel = selectionFromPoints(start, end, gridSpacing)
  const cx = (sel.minX + sel.maxX) / 2
  const cz = (sel.minZ + sel.maxZ) / 2
  const w = Math.max(sel.maxX - sel.minX, gridSpacing)
  const d = Math.max(sel.maxZ - sel.minZ, gridSpacing)

  useFrame((_, delta) => {
    if (!finalised || !meshRef.current) return
    t.current += delta * 3
    const mat = meshRef.current.material as THREE.MeshStandardMaterial
    mat.opacity = 0.18 + Math.sin(t.current) * 0.08
  })

  return (
    <group>
      <mesh ref={meshRef} position={[cx, 0.09, cz]}>
        <boxGeometry args={[w, 0.04, d]} />
        <meshStandardMaterial
          color={finalised ? '#ff9900' : '#ff6600'}
          transparent
          opacity={finalised ? 0.22 : 0.15}
          depthWrite={false}
        />
      </mesh>
      <Line
        points={[
          [sel.minX, 0.12, sel.minZ],
          [sel.maxX, 0.12, sel.minZ],
          [sel.maxX, 0.12, sel.maxZ],
          [sel.minX, 0.12, sel.maxZ],
          [sel.minX, 0.12, sel.minZ],
        ]}
        color={finalised ? '#ffaa22' : '#ff8844'}
        lineWidth={1.5}
        transparent
        opacity={0.9}
      />
    </group>
  )
}

export function AreaContextMenu({
  selection,
  onScan,
  onSendSupply,
  onClose,
}: {
  selection: AreaSelection
  onScan: () => void
  onSendSupply: () => void
  onClose: () => void
}) {
  const w = selection.maxX - selection.minX
  const d = selection.maxZ - selection.minZ

  return (
    <div className="pointer-events-auto absolute left-1/2 top-1/2 z-30 min-w-[220px] -translate-x-1/2 -translate-y-1/2 rounded-[7px] border border-[#ff880066] border-t-2 border-t-[#ff8800] bg-[rgba(8,12,22,0.94)] p-[12px_16px] font-mono text-[11px] text-[#aabbcc] shadow-[0_4px_24px_rgba(0,0,0,0.6)]">
      <div className="mb-2 font-bold tracking-[0.5px] text-[#ff9933]">
        📐 AREA SELECTED
      </div>
      <div className="mb-0.5 text-[#778899]">
        From&nbsp;
        <span className="text-[#ccd]">({selection.minX}, {selection.minZ})</span>
      </div>
      <div className="mb-0.5 text-[#778899]">
        To&nbsp;&nbsp;&nbsp;
        <span className="text-[#ccd]">({selection.maxX}, {selection.maxZ})</span>
      </div>
      <div className="mb-3 text-[#556677]">
        {w}m × {d}m area
      </div>
      <div className="flex gap-2">
        <button
          onClick={onScan}
          className="flex-1 cursor-pointer rounded border border-[rgba(255,136,0,0.55)] bg-[rgba(255,136,0,0.18)] px-[10px] py-[6px] font-mono text-[11px] text-[#ffaa44]"
        >
          📡 Scan this area
        </button>
        <button
          onClick={onSendSupply}
          className="flex-1 cursor-pointer rounded border border-[rgba(80,190,255,0.55)] bg-[rgba(50,170,255,0.16)] px-[10px] py-[6px] font-mono text-[11px] text-[#7fd0ff]"
        >
          📦 Send supplies
        </button>
        <button
          onClick={onClose}
          className="cursor-pointer rounded border border-[rgba(120,130,150,0.4)] bg-[rgba(80,80,100,0.18)] px-[10px] py-[6px] font-mono text-[11px] text-[#889]"
        >
          ✕
        </button>
      </div>
    </div>
  )
}
