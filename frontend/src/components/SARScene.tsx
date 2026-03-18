'use client'

import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Line, OrbitControls, PerspectiveCamera, Html } from '@react-three/drei'
import { useRef, useState, useEffect, useMemo, useCallback, type RefObject, type MutableRefObject } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import CommandPanel from './CommandPanel'
import { useTelemetry, type DroneMap } from '@/lib/ws'
import { uplink, streamCommand, healthCheck, getFleet, getAutoRecallConfig, resetDroneToBase, type AgentStreamEvent } from '@/lib/api'
import WORLD from '@shared/world.json'
import { BasePad, GridOverlay, Ground, MissionBuildings, SurvivorScanRays, Survivors } from './sar-scene/SceneStructures'

// ── Constants (from shared/world.json) ────────────────────────────────────────

type WindowFace = 'north' | 'south' | 'west' | 'east'

interface WorldWindowLayout {
  floor: number
  face: WindowFace
  offset: number
  width: number
  height: number
  sill: number
}

interface WorldBalconyLayout {
  floor: number
  face: WindowFace
  depth: number
  width: number
}

interface WorldBuilding {
  id: number
  name: string
  cx: number
  cz: number
  w: number
  d: number
  h: number
  windows: WorldWindowLayout[]
  balcony: WorldBalconyLayout | null
}

const GRID_CELLS  = 50
const GRID_SPACING = 2

const FLOOR_H = WORLD.scene.floor_height_m
const FLOOR_T = WORLD.scene.floor_slab_thickness_m
const SURV_HOVER  = WORLD.scene.surv_hover_m
const FLOOD_LEVEL = WORLD.scene.flood_level_m

const span    = GRID_CELLS * GRID_SPACING           // 100
const slabY   = (n: number) => (n - 1) * FLOOR_H
const survY   = (n: number) => slabY(n) + FLOOR_T / 2 + SURV_HOVER

const WORLD_BUILDINGS = [...(WORLD.buildings as WorldBuilding[])].sort((a, b) => a.id - b.id)

// Drone start position
const DRONE_START = new THREE.Vector3(13, 1, 13)

// Camera — pulled back for larger city
const CAM_POS: [number, number, number] = [45, 95, 70]
const FOLLOW_CAMERA_OFFSET = new THREE.Vector3(18, 14, 18)

// ── Survivor positions (from shared/world.json) ───────────────────────────────
const SURVIVOR_POSITIONS = WORLD.survivors.map(s => ({ x: s.x, y: s.y, z: s.z }))

const SURVIVOR_SENSOR_RANGE = 3.0
const LOS_SAMPLE_COUNT = 30
const APPROACH_OFFSET = 2.5

interface SimWindowAperture {
  face: WindowFace
  axisCenter: number
  sillY: number
  width: number
  height: number
}

interface SimBuilding {
  id: number
  name: string
  cx: number
  cz: number
  w: number
  d: number
  h: number
  windows: SimWindowAperture[]
}

interface SurvivorPoint {
  x: number
  y: number
  z: number
}

const SIM_BUILDINGS: SimBuilding[] = WORLD_BUILDINGS.map((building) => ({
  id: building.id,
  name: building.name,
  cx: building.cx,
  cz: building.cz,
  w: building.w,
  d: building.d,
  h: building.h,
  windows: building.windows.map((window) => ({
    face: window.face,
    axisCenter: (window.face === 'north' || window.face === 'south')
      ? building.cx + window.offset
      : building.cz + window.offset,
    sillY: (window.floor - 1) * FLOOR_H + window.sill,
    width: window.width,
    height: window.height,
  })),
}))

function buildingPromptName(building: SimBuilding): string {
  const normalized = (building.name || '').trim().replace(/[_-]+/g, ' ')
  if (normalized.length > 0) return normalized
  return `building ${building.id}`
}

function buildingBounds(b: SimBuilding) {
  return {
    minX: b.cx - b.w / 2,
    maxX: b.cx + b.w / 2,
    minZ: b.cz - b.d / 2,
    maxZ: b.cz + b.d / 2,
  }
}

function containsPoint(b: SimBuilding, x: number, y: number, z: number): boolean {
  const { minX, maxX, minZ, maxZ } = buildingBounds(b)
  return minX <= x && x <= maxX && 0 <= y && y <= b.h && minZ <= z && z <= maxZ
}

function containsFloorSlabPoint(b: SimBuilding, x: number, y: number, z: number): boolean {
  if (!containsPoint(b, x, y, z)) return false
  const epsilon = 1e-6
  const half = FLOOR_T / 2

  let level = 0.0
  while (level <= b.h + epsilon) {
    if (level - half - epsilon <= y && y <= level + half + epsilon) return true
    level += FLOOR_H
  }
  return b.h - half - epsilon <= y && y <= b.h + half + epsilon
}

function findBuildingAt(x: number, y: number, z: number): SimBuilding | null {
  for (const b of SIM_BUILDINGS) {
    if (containsPoint(b, x, y, z)) return b
  }
  return null
}

function segmentIntersectsWindow(
  building: SimBuilding,
  window: SimWindowAperture,
  fromX: number,
  fromY: number,
  fromZ: number,
  toX: number,
  toY: number,
  toZ: number,
): boolean {
  const { minX, maxX, minZ, maxZ } = buildingBounds(building)
  const dx = toX - fromX
  const dy = toY - fromY
  const dz = toZ - fromZ
  const epsilon = 1e-6
  const minAxis = window.axisCenter - window.width / 2
  const maxAxis = window.axisCenter + window.width / 2
  const minY = window.sillY
  const maxY = window.sillY + window.height

  if (window.face === 'north' || window.face === 'south') {
    if (Math.abs(dz) <= epsilon) return false
    const planeZ = window.face === 'north' ? minZ : maxZ
    const t = (planeZ - fromZ) / dz
    if (t <= epsilon || t >= 1.0 - epsilon) return false
    const hitX = fromX + dx * t
    const hitY = fromY + dy * t
    return (
      minAxis - epsilon <= hitX && hitX <= maxAxis + epsilon &&
      minY - epsilon <= hitY && hitY <= maxY + epsilon
    )
  }

  if (Math.abs(dx) <= epsilon) return false
  const planeX = window.face === 'west' ? minX : maxX
  const t = (planeX - fromX) / dx
  if (t <= epsilon || t >= 1.0 - epsilon) return false
  const hitZ = fromZ + dz * t
  const hitY = fromY + dy * t
  return (
    minAxis - epsilon <= hitZ && hitZ <= maxAxis + epsilon &&
    minY - epsilon <= hitY && hitY <= maxY + epsilon
  )
}

function hasWindowLineOfSight(
  building: SimBuilding,
  fromX: number,
  fromY: number,
  fromZ: number,
  toX: number,
  toY: number,
  toZ: number,
): boolean {
  return building.windows.some(window => (
    segmentIntersectsWindow(building, window, fromX, fromY, fromZ, toX, toY, toZ)
  ))
}

function lineOfSightClear(
  fromX: number,
  fromY: number,
  fromZ: number,
  toX: number,
  toY: number,
  toZ: number,
  ignoreBuildingIds?: Set<number>,
): boolean {
  const ignored = ignoreBuildingIds ?? new Set<number>()
  for (let i = 1; i <= LOS_SAMPLE_COUNT; i += 1) {
    const t = i / LOS_SAMPLE_COUNT
    const sx = fromX + (toX - fromX) * t
    const sy = fromY + (toY - fromY) * t
    const sz = fromZ + (toZ - fromZ) * t

    for (const b of SIM_BUILDINGS) {
      if (!containsPoint(b, sx, sy, sz)) continue
      if (ignored.has(b.id)) {
        if (containsFloorSlabPoint(b, sx, sy, sz)) return false
        continue
      }
      return false
    }
  }
  return true
}

function survivorDistance(from: THREE.Vector3, target: SurvivorPoint): number {
  const dx = target.x - from.x
  const dy = target.y - from.y
  const dz = target.z - from.z
  return Math.sqrt(dx * dx + dy * dy + dz * dz)
}

function survivorVisibleFromDrone(dronePos: THREE.Vector3, survivor: SurvivorPoint): boolean {
  const survivorBuilding = findBuildingAt(survivor.x, survivor.y, survivor.z)
  if (!survivorBuilding) {
    return lineOfSightClear(dronePos.x, dronePos.y, dronePos.z, survivor.x, survivor.y, survivor.z)
  }

  if (!hasWindowLineOfSight(
    survivorBuilding,
    dronePos.x,
    dronePos.y,
    dronePos.z,
    survivor.x,
    survivor.y,
    survivor.z,
  )) {
    return false
  }

  return lineOfSightClear(
    dronePos.x,
    dronePos.y,
    dronePos.z,
    survivor.x,
    survivor.y,
    survivor.z,
    new Set([survivorBuilding.id]),
  )
}

function scannedSurvivorsFromDrone(dronePos: THREE.Vector3): SurvivorPoint[] {
  return SURVIVOR_POSITIONS.filter((survivor) => {
    if (survivorDistance(dronePos, survivor) > SURVIVOR_SENSOR_RANGE) return false
    return survivorVisibleFromDrone(dronePos, survivor)
  })
}

function nearbySurvivorsFromDrone(dronePos: THREE.Vector3): SurvivorPoint[] {
  return SURVIVOR_POSITIONS
    .filter((survivor) => survivorDistance(dronePos, survivor) <= SURVIVOR_SENSOR_RANGE)
    .sort((a, b) => survivorDistance(dronePos, a) - survivorDistance(dronePos, b))
}

function detectedSurvivorsFromTelemetryEntry(telemetryEntry: DroneMap[string]): SurvivorPoint[] {
  const visibleCount = Math.max(0, Math.floor(telemetryEntry.survivors_in_range ?? 0))
  if (visibleCount <= 0) return []

  const dronePos = new THREE.Vector3(telemetryEntry.x, telemetryEntry.y, telemetryEntry.z)
  const losMatches = scannedSurvivorsFromDrone(dronePos)
  if (losMatches.length >= visibleCount) return losMatches

  const fallback = nearbySurvivorsFromDrone(dronePos).filter((survivor) => {
    return !losMatches.some((match) => survivorKey(match) === survivorKey(survivor))
  })
  return [...losMatches, ...fallback.slice(0, Math.max(0, visibleCount - losMatches.length))]
}

// ── Approach position computation ─────────────────────────────────────────────

function computeApproachPosition(survivor: SurvivorPoint): SurvivorPoint {
  const building = findBuildingAt(survivor.x, survivor.y, survivor.z)
  if (!building) return survivor  // outside — go directly

  const bounds = buildingBounds(building)

  // Find the window closest to the survivor (prefer same floor, then distance)
  if (building.windows.length > 0) {
    let bestWindow: SimWindowAperture | null = null
    let bestDist = Infinity

    for (const w of building.windows) {
      const windowCenterY = w.sillY + w.height / 2
      const yDist = Math.abs(survivor.y - windowCenterY)
      let wx: number, wz: number
      if (w.face === 'north')      { wx = w.axisCenter; wz = bounds.minZ }
      else if (w.face === 'south') { wx = w.axisCenter; wz = bounds.maxZ }
      else if (w.face === 'west')  { wx = bounds.minX;  wz = w.axisCenter }
      else                         { wx = bounds.maxX;  wz = w.axisCenter }

      const xzDist = Math.sqrt((survivor.x - wx) ** 2 + (survivor.z - wz) ** 2)
      const totalDist = yDist * 2 + xzDist
      if (totalDist < bestDist) {
        bestDist = totalDist
        bestWindow = w
      }
    }

    if (bestWindow) {
      const wy = bestWindow.sillY + bestWindow.height / 2
      if (bestWindow.face === 'west')
        return { x: bounds.minX - APPROACH_OFFSET, y: wy, z: bestWindow.axisCenter }
      if (bestWindow.face === 'east')
        return { x: bounds.maxX + APPROACH_OFFSET, y: wy, z: bestWindow.axisCenter }
      if (bestWindow.face === 'north')
        return { x: bestWindow.axisCenter, y: wy, z: bounds.minZ - APPROACH_OFFSET }
      // south
      return { x: bestWindow.axisCenter, y: wy, z: bounds.maxZ + APPROACH_OFFSET }
    }
  }

  // Fallback for windowless buildings — nearest face at survivor height
  const distToWest  = survivor.x - bounds.minX
  const distToEast  = bounds.maxX - survivor.x
  const distToNorth = survivor.z - bounds.minZ
  const distToSouth = bounds.maxZ - survivor.z
  const minDist = Math.min(distToWest, distToEast, distToNorth, distToSouth)

  if (minDist === distToWest)       return { x: bounds.minX - APPROACH_OFFSET, y: survivor.y, z: survivor.z }
  else if (minDist === distToEast)  return { x: bounds.maxX + APPROACH_OFFSET, y: survivor.y, z: survivor.z }
  else if (minDist === distToNorth) return { x: survivor.x, y: survivor.y, z: bounds.minZ - APPROACH_OFFSET }
  else                              return { x: survivor.x, y: survivor.y, z: bounds.maxZ + APPROACH_OFFSET }
}

function survivorKey(s: SurvivorPoint): string {
  return `${s.x.toFixed(1)},${s.y.toFixed(1)},${s.z.toFixed(1)}`
}

function mergeUniqueSurvivors(
  existing: SurvivorPoint[],
  incoming: SurvivorPoint[],
): SurvivorPoint[] {
  if (incoming.length === 0) return existing
  const merged = new Map<string, SurvivorPoint>()
  for (const survivor of existing) {
    merged.set(survivorKey(survivor), survivor)
  }
  for (const survivor of incoming) {
    merged.set(survivorKey(survivor), survivor)
  }
  return [...merged.values()]
}

function SupplyCrates({ deliveredTo }: { deliveredTo: Set<string> }) {
  const crates = useMemo(() => {
    return SURVIVOR_POSITIONS
      .filter(s => deliveredTo.has(survivorKey(s)))
      .map(s => ({ x: s.x, y: s.y, z: s.z }))
  }, [deliveredTo])

  const groupRef = useRef<THREE.Group>(null)

  useFrame(({ clock }) => {
    if (!groupRef.current) return
    const t = clock.elapsedTime
    groupRef.current.children.forEach((child, i) => {
      // Gentle hover bob
      child.position.y = crates[i].y - 0.6 + Math.sin(t * 1.5 + i * 2.1) * 0.08
      child.rotation.y = t * 0.4 + i * 1.2
    })
  })

  if (crates.length === 0) return null

  return (
    <group ref={groupRef}>
      {crates.map((pos, i) => (
        <group key={i} position={[pos.x, pos.y - 0.6, pos.z]}>
          {/* Main crate body */}
          <mesh castShadow>
            <boxGeometry args={[0.5, 0.4, 0.5]} />
            <meshStandardMaterial color="#ff8800" emissive="#cc5500" emissiveIntensity={0.4} />
          </mesh>
          {/* Cross straps */}
          <mesh position={[0, 0.01, 0]}>
            <boxGeometry args={[0.52, 0.06, 0.12]} />
            <meshStandardMaterial color="#ffffff" emissive="#aaaaaa" emissiveIntensity={0.3} />
          </mesh>
          <mesh position={[0, 0.01, 0]}>
            <boxGeometry args={[0.12, 0.06, 0.52]} />
            <meshStandardMaterial color="#ffffff" emissive="#aaaaaa" emissiveIntensity={0.3} />
          </mesh>
          {/* Glow ring on ground */}
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.19, 0]}>
            <ringGeometry args={[0.35, 0.5, 16]} />
            <meshBasicMaterial color="#ff8800" transparent opacity={0.25} />
          </mesh>
        </group>
      ))}
    </group>
  )
}

// Wave-animated floodwater at a fixed level
function FloodWater() {
  const meshRef = useRef<THREE.Mesh>(null)
  const geoRef  = useRef<THREE.PlaneGeometry>(null)
  const timeRef = useRef(0)

  // Disable raycasting so the flood plane doesn't block the coordinate probe
  useEffect(() => {
    if (meshRef.current) meshRef.current.raycast = () => {}
  }, [])

  useFrame((_, delta) => {
    timeRef.current += delta
    const t = timeRef.current

    if (geoRef.current) {
      const pos = geoRef.current.attributes.position as THREE.BufferAttribute
      for (let i = 0; i < pos.count; i++) {
        const vx = pos.getX(i)
        const vy = pos.getY(i)
        const wave =
          Math.sin(vx * 0.18 + t * 1.4) * 0.10 +
          Math.sin(vy * 0.14 + t * 1.1) * 0.08 +
          Math.sin((vx - vy) * 0.10 + t * 0.7) * 0.05
        pos.setZ(i, wave)
      }
      pos.needsUpdate = true
      geoRef.current.computeVertexNormals()
    }
  })

  return (
    <mesh ref={meshRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, FLOOD_LEVEL, 0]} renderOrder={2}>
      <planeGeometry ref={geoRef} args={[span, span, 40, 40]} />
      <meshStandardMaterial
        color="#1a5a9e"
        transparent
        opacity={0.68}
        roughness={0.06}
        metalness={0.2}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  )
}

// ── Ground coordinate probe & cursor ─────────────────────────────────────────

// Invisible plane that emits world-space intersection points on hover
function GroundProbe({ onMove, onDoubleClick }: {
  onMove: (v: THREE.Vector3 | null) => void
  onDoubleClick: (v: THREE.Vector3) => void
}) {
  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, 0.05, 0]}
      onPointerMove={e => { e.stopPropagation(); onMove(e.point) }}
      onPointerLeave={() => onMove(null)}
      onDoubleClick={e => { e.stopPropagation(); onDoubleClick(e.point) }}
    >
      <planeGeometry args={[span, span]} />
      <meshBasicMaterial transparent opacity={0} depthWrite={false} />
    </mesh>
  )
}

// Yellow crosshair that follows the cursor on the ground plane
function GroundCursor({ point }: { point: THREE.Vector3 | null }) {
  if (!point) return null
  return (
    <group position={[point.x, 0.07, point.z]}>
      {/* E-W arm */}
      <mesh>
        <boxGeometry args={[4, 0.05, 0.09]} />
        <meshBasicMaterial color="#ffe060" />
      </mesh>
      {/* N-S arm */}
      <mesh>
        <boxGeometry args={[0.09, 0.05, 4]} />
        <meshBasicMaterial color="#ffe060" />
      </mesh>
      {/* Centre pip */}
      <mesh>
        <cylinderGeometry args={[0.28, 0.28, 0.05, 8]} />
        <meshBasicMaterial color="#ffe060" />
      </mesh>
    </group>
  )
}

// ── Area selection ────────────────────────────────────────────────────────────

interface AreaSelection {
  minX: number
  maxX: number
  minZ: number
  maxZ: number
}

function snapToGrid(v: number): number {
  return Math.round(v / GRID_SPACING) * GRID_SPACING
}

function selectionFromPoints(a: THREE.Vector3, b: THREE.Vector3): AreaSelection {
  return {
    minX: snapToGrid(Math.min(a.x, b.x)),
    maxX: snapToGrid(Math.max(a.x, b.x)),
    minZ: snapToGrid(Math.min(a.z, b.z)),
    maxZ: snapToGrid(Math.max(a.z, b.z)),
  }
}

// Invisible ground plane that captures drag-to-select events
function AreaSelectProbe({
  onDragUpdate,
  onDragEnd,
}: {
  onDragUpdate: (start: THREE.Vector3, end: THREE.Vector3) => void
  onDragEnd: (sel: AreaSelection) => void
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
        const sel = selectionFromPoints(dragStart.current, e.point.clone())
        dragStart.current = null
        onDragEnd(sel)
      }}
    >
      <planeGeometry args={[span, span]} />
      <meshBasicMaterial transparent opacity={0} depthWrite={false} />
    </mesh>
  )
}

// Orange selection rectangle on the ground plane
function AreaHighlight({
  start,
  end,
  finalised,
}: {
  start: THREE.Vector3
  end: THREE.Vector3
  finalised: boolean
}) {
  const meshRef = useRef<THREE.Mesh>(null)
  const t = useRef(0)

  const sel = selectionFromPoints(start, end)
  const cx = (sel.minX + sel.maxX) / 2
  const cz = (sel.minZ + sel.maxZ) / 2
  const w = Math.max(sel.maxX - sel.minX, GRID_SPACING)
  const d = Math.max(sel.maxZ - sel.minZ, GRID_SPACING)

  useFrame((_, delta) => {
    if (!finalised || !meshRef.current) return
    t.current += delta * 3
    const mat = meshRef.current.material as THREE.MeshStandardMaterial
    mat.opacity = 0.18 + Math.sin(t.current) * 0.08
  })

  return (
    <group>
      {/* Fill */}
      <mesh ref={meshRef} position={[cx, 0.09, cz]}>
        <boxGeometry args={[w, 0.04, d]} />
        <meshStandardMaterial
          color={finalised ? '#ff9900' : '#ff6600'}
          transparent
          opacity={finalised ? 0.22 : 0.15}
          depthWrite={false}
        />
      </mesh>
      {/* Border lines */}
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

// HTML context menu anchored near screen-centre of the selection
function AreaContextMenu({
  selection,
  onScan,
  onClose,
}: {
  selection: AreaSelection
  onScan: () => void
  onClose: () => void
}) {
  const w = selection.maxX - selection.minX
  const d = selection.maxZ - selection.minZ

  return (
    <div style={{
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
      background: 'rgba(8, 12, 22, 0.94)',
      border: '1px solid #ff880066',
      borderTop: '2px solid #ff8800',
      borderRadius: 7,
      padding: '12px 16px',
      fontFamily: 'Courier New, monospace',
      fontSize: 11,
      color: '#aabbcc',
      pointerEvents: 'auto',
      minWidth: 220,
      zIndex: 30,
      boxShadow: '0 4px 24px rgba(0,0,0,0.6)',
    }}>
      <div style={{ color: '#ff9933', fontWeight: 'bold', marginBottom: 8, letterSpacing: 0.5 }}>
        📐 AREA SELECTED
      </div>
      <div style={{ color: '#778899', marginBottom: 2 }}>
        From&nbsp;
        <span style={{ color: '#ccd' }}>({selection.minX}, {selection.minZ})</span>
      </div>
      <div style={{ color: '#778899', marginBottom: 2 }}>
        To&nbsp;&nbsp;&nbsp;
        <span style={{ color: '#ccd' }}>({selection.maxX}, {selection.maxZ})</span>
      </div>
      <div style={{ color: '#556677', marginBottom: 12 }}>
        {w}m × {d}m area
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={onScan}
          style={{
            flex: 1,
            background: 'rgba(255,136,0,0.18)',
            border: '1px solid rgba(255,136,0,0.55)',
            borderRadius: 4,
            color: '#ffaa44',
            padding: '6px 10px',
            cursor: 'pointer',
            fontSize: 11,
            fontFamily: 'Courier New, monospace',
          }}
        >
          📡 Scan this area
        </button>
        <button
          onClick={onClose}
          style={{
            background: 'rgba(80,80,100,0.18)',
            border: '1px solid rgba(120,130,150,0.4)',
            borderRadius: 4,
            color: '#889',
            padding: '6px 10px',
            cursor: 'pointer',
            fontSize: 11,
            fontFamily: 'Courier New, monospace',
          }}
        >
          ✕
        </button>
      </div>
    </div>
  )
}

// ── Drone status panel (HTML overlay) ────────────────────────────────────────

function _batteryColor(pct: number): string {
  if (pct > 50) return '#44cc66'
  if (pct > 20) return '#ffcc00'
  if (pct > 10) return '#ff8800'
  return '#ff3333'
}

function _statusColor(s: string): string {
  switch (s.toUpperCase()) {
    case 'MOVING':    return '#00ff88'
    case 'SCANNING':  return '#ffaa00'
    case 'RETURNING': return '#00ccff'
    case 'IDLE':      return '#7799bb'
    default:          return '#556677'
  }
}

function TopStatusBar({ selectMode, floodLevel }: { selectMode: boolean; floodLevel: number }) {
  const submerged = SURVIVOR_POSITIONS.filter(p => p.y < floodLevel - 0.2).length

  return (
    <div style={{
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: 48,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 24px',
      background: 'linear-gradient(180deg, rgba(6,6,16,0.95), rgba(6,6,16,0.78))',
      borderBottom: '1px solid rgba(0,180,255,0.08)',
      backdropFilter: 'blur(16px)',
      zIndex: 20,
      pointerEvents: 'auto',
      fontFamily: "'Courier New', monospace",
    }}>
      {/* Bottom glow line */}
      <div style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        height: 1,
        background: 'linear-gradient(90deg, transparent 5%, rgba(0,200,255,0.25) 30%, rgba(0,200,255,0.15) 70%, transparent 95%)',
      }} />

      {/* Left: Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: '#00ccff',
            boxShadow: '0 0 10px rgba(0,200,255,0.6), 0 0 20px rgba(0,200,255,0.2)',
            animation: 'beacon-signalDot 2s ease-in-out infinite',
          }} />
          <span style={{
            color: '#e0f0ff',
            fontSize: 15,
            fontWeight: 700,
            letterSpacing: 3,
            textShadow: '0 0 20px rgba(0,200,255,0.2)',
          }}>
            PROJECT BEACON
          </span>
        </div>
        <span style={{ color: '#3a4a5a', fontSize: 14 }}>|</span>
        <span style={{ color: '#6a7a90', fontSize: 12, letterSpacing: 1.5 }}>
          THAILAND TOWN SAR
        </span>
      </div>

      {/* Right: Status indicators */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
        {selectMode && (
          <span style={{
            color: '#ff9933',
            fontWeight: 700,
            letterSpacing: 1,
            padding: '2px 8px',
            border: '1px solid rgba(255,140,0,0.3)',
            borderRadius: 3,
            background: 'rgba(255,100,0,0.1)',
          }}>
            AREA SELECT
          </span>
        )}
        {submerged > 0 && (
          <span style={{
            color: '#ff5555',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 8px',
            border: '1px solid rgba(255,60,60,0.25)',
            borderRadius: 3,
            background: 'rgba(255,40,40,0.08)',
          }}>
            <span style={{
              width: 5,
              height: 5,
              borderRadius: '50%',
              background: '#ff4444',
              animation: 'beacon-livePulse 1.5s ease-in-out infinite',
              flexShrink: 0,
            }} />
            {submerged} SUBMERGED
          </span>
        )}
        <span style={{ color: '#e87730', letterSpacing: 0.5 }}>
          FLOOD +{floodLevel.toFixed(1)}m
        </span>
      </div>
    </div>
  )
}

function DroneStatusPanel({ drones }: { drones: DroneMap }) {
  const entries = Object.values(drones)
  if (entries.length === 0) return null

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 6,
    }}>
      {entries.map(d => {
        const batCol = _batteryColor(d.battery)
        const sCol   = _statusColor(d.status)
        const hasEnv = d.nearby_obstacles !== undefined
        return (
          <div key={d.asset_id} style={{
            background: 'linear-gradient(135deg, rgba(6,8,16,0.88), rgba(4,6,14,0.82))',
            border: `1px solid ${sCol}30`,
            borderLeft: `2px solid ${sCol}`,
            borderRadius: 6,
            padding: '8px 12px',
            fontFamily: "'Courier New', monospace",
            fontSize: 12,
            lineHeight: 1.7,
            backdropFilter: 'blur(12px)',
          }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ color: '#ccdde8', fontWeight: 700, letterSpacing: 0.5 }}>{d.asset_id}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 5, color: sCol, fontSize: 11 }}>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%', background: sCol,
                  boxShadow: `0 0 6px ${sCol}80`,
                }} />
                {d.status}
              </span>
            </div>
            {/* Battery bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ color: '#7a8a9a', fontSize: 11 }}>BAT</span>
              <div style={{ flex: 1, background: '#0a0e18', height: 4, borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${d.battery}%`, height: '100%', background: batCol, transition: 'width 0.4s' }} />
              </div>
              <span style={{ color: batCol, width: 34, textAlign: 'right', fontSize: 11 }}>{d.battery}%</span>
            </div>
            {/* Coords + environment in one row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11 }}>
              <span style={{ color: '#6a8aa0', letterSpacing: 0.3 }}>
                <span style={{ color: '#99bbcc' }}>{d.x.toFixed(1)}</span>
                <span style={{ color: '#5a7a8a' }}>,&nbsp;</span>
                <span style={{ color: '#99bbcc' }}>{d.y.toFixed(1)}</span>
                <span style={{ color: '#5a7a8a' }}>,&nbsp;</span>
                <span style={{ color: '#99bbcc' }}>{d.z.toFixed(1)}</span>
              </span>
              {hasEnv && (
                <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ color: '#99aabb' }}>
                    <span style={{ color: '#6a7a8a' }}>AGL </span>{(d.altitude_agl ?? 0).toFixed(1)}m
                  </span>
                  <span style={{ color: (d.nearby_obstacles ?? 0) > 0 ? '#ff8800' : '#55aa66' }}>
                    <span style={{ color: '#6a7a8a' }}>OBS </span>{d.nearby_obstacles ?? 0}
                    {(d.nearest_obstacle_dist ?? 999) < 10 && (
                      <span style={{ color: '#ff6600' }}> ({(d.nearest_obstacle_dist ?? 0).toFixed(1)}m)</span>
                    )}
                  </span>
                  {d.over_flood && <span style={{ color: '#44aaff', fontWeight: 600 }}>FLOOD</span>}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// Floating coordinate readout shown while hovering over the ground
function CoordOverlay({ point, copied }: { point: THREE.Vector3 | null; copied: boolean }) {
  if (!point) return null
  return (
    <div style={{
      position: 'absolute',
      top: 56,
      left: '50%',
      transform: 'translateX(-50%)',
      background: copied ? 'rgba(40,80,40,0.92)' : 'rgba(6,8,16,0.85)',
      border: `1px solid ${copied ? '#44ff8833' : '#ffe06030'}`,
      borderRadius: 5,
      padding: '5px 18px',
      color: copied ? '#88ff88' : '#ffe060',
      fontFamily: "'Courier New', monospace",
      fontSize: 14,
      letterSpacing: 1,
      pointerEvents: 'none',
      display: 'flex',
      gap: 20,
      whiteSpace: 'nowrap',
      zIndex: 10,
      backdropFilter: 'blur(8px)',
      transition: 'background 0.15s, color 0.15s, border 0.15s',
    }}>
      {copied
        ? <span>✓ copied to clipboard</span>
        : <>
            <span>X&nbsp;<span style={{ color: '#fff' }}>{point.x.toFixed(1)}</span></span>
            <span>Y&nbsp;<span style={{ color: '#fff' }}>{point.y.toFixed(1)}</span></span>
            <span>Z&nbsp;<span style={{ color: '#fff' }}>{point.z.toFixed(1)}</span></span>
            <span style={{ color: '#888', fontSize: 12 }}>double-click to copy</span>
          </>
      }
    </div>
  )
}

// Tracks the camera orientation each frame and writes the screen angle of
// world-North (-Z axis) into a shared ref. Must live inside <Canvas>.
function CameraTracker({ northAngleRef }: { northAngleRef: MutableRefObject<number> }) {
  const { camera } = useThree()
  const _v = useRef(new THREE.Vector3())
  useFrame(() => {
    // World North is -Z. Project it into view space, then read its screen angle.
    _v.current.set(0, 0, -1).transformDirection(camera.matrixWorldInverse)
    northAngleRef.current = Math.atan2(_v.current.x, _v.current.y)
  })
  return null
}

// Positions N/S/E/W labels on the viewport edge, following the camera via rAF.
function CompassLabels({ northAngleRef }: { northAngleRef: MutableRefObject<number> }) {
  const nRef = useRef<HTMLDivElement>(null)
  const sRef = useRef<HTMLDivElement>(null)
  const eRef = useRef<HTMLDivElement>(null)
  const wRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const PAD = 22
    // Given a direction angle on screen (0=up, cw+), compute the edge position.
    function edgePos(angle: number, w: number, h: number): { x: number; y: number } {
      const dx = Math.sin(angle)
      const dy = -Math.cos(angle)
      const sx = Math.abs(dx) > 1e-9 ? (w / 2 - PAD) / Math.abs(dx) : Infinity
      const sy = Math.abs(dy) > 1e-9 ? (h / 2 - PAD) / Math.abs(dy) : Infinity
      const s  = Math.min(sx, sy)
      return { x: w / 2 + dx * s, y: h / 2 + dy * s }
    }

    const SHARED_STYLE: Partial<CSSStyleDeclaration> = {
      position: 'absolute',
      color: 'rgba(180,200,255,0.55)',
      fontFamily: 'Courier New, monospace',
      fontSize: '11px',
      letterSpacing: '2px',
      pointerEvents: 'none',
      userSelect: 'none',
      zIndex: '5',
      transform: 'translate(-50%, -50%)',
    }
    ;[nRef, sRef, eRef, wRef].forEach(r => {
      if (r.current) Object.assign(r.current.style, SHARED_STYLE)
    })

    const DIRS: [RefObject<HTMLDivElement | null>, number][] = [
      [nRef, 0],
      [sRef, Math.PI],
      [eRef, Math.PI / 2],
      [wRef, -Math.PI / 2],
    ]

    let rafId: number
    function tick() {
      const az = northAngleRef.current
      const w  = window.innerWidth
      const h  = window.innerHeight
      for (const [ref, offset] of DIRS) {
        if (!ref.current) continue
        const { x, y } = edgePos(az + offset, w, h)
        ref.current.style.left = `${x}px`
        ref.current.style.top  = `${y}px`
      }
      rafId = requestAnimationFrame(tick)
    }
    rafId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafId)
  }, [northAngleRef])

  return (
    <>
      <div ref={nRef}>N</div>
      <div ref={sRef}>S</div>
      <div ref={eRef}>E</div>
      <div ref={wRef}>W</div>
    </>
  )
}

// ── Supply throw animation ───────────────────────────────────────────────────

const THROW_DURATION = 1.2  // seconds for supply to fly from drone to survivor

interface SupplyThrowProps {
  from: THREE.Vector3
  to: SurvivorPoint
  onComplete: () => void
}

function SupplyThrow({ from, to, onComplete }: SupplyThrowProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const progress = useRef(0)
  const startPos = useRef(from.clone())

  useFrame((_, delta) => {
    if (!meshRef.current) return
    progress.current += delta / THROW_DURATION
    const t = Math.min(progress.current, 1)

    const x = startPos.current.x + (to.x - startPos.current.x) * t
    const z = startPos.current.z + (to.z - startPos.current.z) * t
    const arc = 4 * t * (1 - t) * 1.2
    const y = startPos.current.y + (to.y - startPos.current.y) * t + arc

    meshRef.current.position.set(x, y, z)
    meshRef.current.rotation.x += delta * 5
    meshRef.current.rotation.z += delta * 3

    if (t >= 1) onComplete()
  })

  return (
    <mesh ref={meshRef} position={startPos.current.toArray()}>
      <boxGeometry args={[0.35, 0.28, 0.35]} />
      <meshStandardMaterial color="#ff8800" emissive="#cc5500" emissiveIntensity={0.5} />
    </mesh>
  )
}

// ── Drone (telemetry-driven position with smooth lerp) ────────────────────────

interface DroneProps {
  targetPos: THREE.Vector3
  status: string
  hasCargo: boolean
  nearbyObstacles?: number
  nearestObstacleDist?: number
  survivorsInRange?: number
  assetId?: string
  headingDeg?: number
  scanTiltDeg?: number
}

function DroneMesh({ targetPos, status, hasCargo, nearbyObstacles = 0, nearestObstacleDist = 999, survivorsInRange = 0, assetId = '', headingDeg = 0, scanTiltDeg = 0 }: DroneProps) {
  const groupRef = useRef<THREE.Group>(null)
  const cargoRef = useRef<THREE.Mesh>(null)
  const coneRef = useRef<THREE.Mesh>(null)
  const lerpPos = useRef(DRONE_START.clone())

  // Keep refs so useFrame always reads fresh prop values (avoids stale closure)
  const statusRef = useRef(status)
  const headingDegRef = useRef(headingDeg)
  const scanTiltDegRef = useRef(scanTiltDeg)
  statusRef.current = status
  headingDegRef.current = headingDeg
  scanTiltDegRef.current = scanTiltDeg

  // Track whether we're mid-scan-session: turns on when SCANNING seen,
  // only turns off when drone returns to a terminal non-scan state.
  const inScanSessionRef = useRef(false)
  if (status === 'SCANNING') inScanSessionRef.current = true
  if (status === 'IDLE' || status === 'RETURNING' || status === 'BLOCKED' || status === 'ERROR') {
    inScanSessionRef.current = false
  }

  // FOV cone: horizontal, points in heading direction, shown during full scan session
  const SCAN_FOV_HALF_DEG = 30
  const SCAN_FOV_RANGE = 3  // metres — thermal camera effective range
  const coneRadius = SCAN_FOV_RANGE * Math.tan((SCAN_FOV_HALF_DEG * Math.PI) / 180)

  useFrame((_, delta) => {
    if (!groupRef.current) return
    lerpPos.current.lerp(targetPos, Math.min(delta * 4, 1))
    groupRef.current.position.copy(lerpPos.current)

    if (coneRef.current) {
      const headingRad = (headingDegRef.current * Math.PI) / 180
      const tiltRad = (scanTiltDegRef.current * Math.PI) / 180
      const cosT = Math.cos(tiltRad)
      // Scan direction: heading in XZ, optionally tilted down
      const scanDirX = Math.sin(headingRad) * cosT
      const scanDirY = Math.sin(tiltRad)          // negative when tilting down
      const scanDirZ = -Math.cos(headingRad) * cosT

      // Apex (tip) at drone. Center = drone + scanDir*(RANGE/2) so:
      //   apex = center - scanDir*(RANGE/2) = drone ✓
      const half = SCAN_FOV_RANGE / 2
      coneRef.current.position.set(
        lerpPos.current.x + scanDirX * half,
        lerpPos.current.y + scanDirY * half,
        lerpPos.current.z + scanDirZ * half,
      )
      // Rotate ConeGeometry's -Y axis (base direction) to point along scanDir.
      // setFromUnitVectors is unambiguous — no Euler angle guessing.
      const baseDir = new THREE.Vector3(scanDirX, scanDirY, scanDirZ)
      if (baseDir.lengthSq() > 1e-6) {
        coneRef.current.quaternion.setFromUnitVectors(
          new THREE.Vector3(0, -1, 0),
          baseDir.normalize(),
        )
      }
      coneRef.current.visible = inScanSessionRef.current
    }

    // Cargo block hangs underneath drone (local coords — group already at world pos)
    if (cargoRef.current) {
      cargoRef.current.position.set(0, -0.55, 0)
      cargoRef.current.visible = hasCargo
    }

    const bodyColor =
      status === 'BLOCKED' ? 0xff2200 :
      status === 'MOVING'  ? 0x00ff88 :
      status === 'SCANNING'? 0xffaa00 :
      0x00ffff
    const emissiveColor =
      status === 'BLOCKED' ? 0x880000 :
      status === 'MOVING'  ? 0x00aa44 :
      status === 'SCANNING'? 0xaa6600 :
      0x00aaaa

    groupRef.current.traverse(child => {
      if ((child as THREE.Mesh).isMesh) {
        const mat = (child as THREE.Mesh).material as THREE.MeshStandardMaterial
        mat.color.setHex(bodyColor)
        mat.emissive.setHex(emissiveColor)
      }
    })
  })

  // Rotor positions at the 4 arm tips
  const rotorPositions: [number, number, number][] = [
    [0.48, 0.06, 0], [-0.48, 0.06, 0],
    [0, 0.06, 0.48], [0, 0.06, -0.48],
  ]

  return (
    <>
      <group ref={groupRef} position={DRONE_START.toArray()}>
        {/* Central body */}
        <mesh>
          <boxGeometry args={[0.38, 0.10, 0.38]} />
          <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} />
        </mesh>
      {/* Cargo block — hangs below drone when carrying supplies */}
      <mesh ref={cargoRef} position={[0, -0.55, 0]} visible={false}>
        <boxGeometry args={[0.4, 0.3, 0.4]} />
        <meshStandardMaterial color="#ff8800" emissive="#cc5500" emissiveIntensity={0.4} />
      </mesh>
        {/* X-axis arm */}
        <mesh>
          <boxGeometry args={[0.96, 0.05, 0.07]} />
          <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} />
        </mesh>
        {/* Z-axis arm */}
        <mesh>
          <boxGeometry args={[0.07, 0.05, 0.96]} />
          <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} />
        </mesh>
        {/* Rotor discs */}
        {rotorPositions.map((pos, i) => (
          <mesh key={i} position={pos} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.19, 0.19, 0.025, 12]} />
            <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} transparent opacity={0.75} />
          </mesh>
        ))}
        {/* Drone name label */}
        {assetId && (
          <Html position={[0, 0.9, 0]} center distanceFactor={14} zIndexRange={[0, 0]}>
            <div style={{
              color: '#00ffff',
              fontFamily: 'Courier New, monospace',
              fontSize: '48px',
              fontWeight: 'bold',
              whiteSpace: 'nowrap',
              background: 'rgba(0, 16, 24, 0.82)',
              padding: '2px 7px',
              borderRadius: 3,
              border: '1px solid rgba(0, 255, 255, 0.4)',
              letterSpacing: '0.05em',
              pointerEvents: 'none',
            }}>
              {assetId}
            </div>
          </Html>
        )}
      </group>
      {/* Horizontal FOV cone — shown only during SCANNING, faces building */}
      <mesh ref={coneRef} position={DRONE_START.toArray()} visible={false}>
        <coneGeometry args={[coneRadius, SCAN_FOV_RANGE, 32, 1, true]} />
        <meshStandardMaterial
          color="#ffaa00"
          transparent
          opacity={0.35}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
    </>
  )
}

interface FollowBeaconCameraProps {
  enabled: boolean
  targetPos: THREE.Vector3
  controlsRef: RefObject<OrbitControlsImpl | null>
}

function FollowBeaconCamera({ enabled, targetPos, controlsRef }: FollowBeaconCameraProps) {
  const { camera } = useThree()
  const desiredTarget = useRef(new THREE.Vector3())
  const desiredPosition = useRef(new THREE.Vector3())

  useFrame((_, delta) => {
    if (!enabled) return

    desiredTarget.current.set(targetPos.x, targetPos.y + 1.2, targetPos.z)
    desiredPosition.current.set(
      desiredTarget.current.x + FOLLOW_CAMERA_OFFSET.x,
      desiredTarget.current.y + FOLLOW_CAMERA_OFFSET.y,
      desiredTarget.current.z + FOLLOW_CAMERA_OFFSET.z,
    )

    const alpha = Math.min(delta * 3, 1)
    camera.position.lerp(desiredPosition.current, alpha)
    camera.lookAt(desiredTarget.current)

    const controls = controlsRef.current
    if (controls) {
      controls.target.lerp(desiredTarget.current, alpha)
      controls.update()
    }
  })

  return null
}

// ── Overlays ──────────────────────────────────────────────────────────────────

// MissionLog removed — replaced by ActivityFeed

// ── Intel Card — actionable scan findings with dramatic animations ────────────

function StatCounter({ value, label, color }: { value: number; label: string; color: string }) {
  return (
    <div style={{ textAlign: 'center', flex: 1 }}>
      <div style={{ fontSize: 24, fontWeight: 700, color, lineHeight: 1.2 }}>{value}</div>
      <div style={{ fontSize: 11, color: color === '#7a8a9a' ? '#6a7a8a' : color, opacity: 0.7, letterSpacing: 0.5 }}>{label}</div>
    </div>
  )
}

function IntelCard({
  survivors,
  dronePos,
  totalSurvivors,
  deliveringTo,
  deliveredTo,
  onSendSupplies,
  onRetryDelivery,
}: {
  survivors: SurvivorPoint[]
  dronePos: THREE.Vector3
  totalSurvivors: number
  deliveringTo: Set<string>
  deliveredTo: Set<string>
  onSendSupplies: (survivor: SurvivorPoint) => void
  onRetryDelivery: (survivor: SurvivorPoint) => void
}) {
  const detected = survivors.length
  const submerged = survivors.filter(s => s.y < FLOOD_LEVEL - 0.2).length
  const critical = submerged > 0
  const deliveredCount = deliveredTo.size

  // Track new survivor detection for animation
  const knownKeysRef = useRef<Set<string>>(new Set())
  const [alertSignal, setAlertSignal] = useState<string | null>(null)
  const [newKeys, setNewKeys] = useState<Set<string>>(new Set())
  const alertTimeoutRef = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    const currentKeys = new Set(survivors.map(survivorKey))
    const brandNew: string[] = []
    currentKeys.forEach(k => {
      if (!knownKeysRef.current.has(k)) brandNew.push(k)
    })
    if (brandNew.length > 0 && knownKeysRef.current.size > 0) {
      const idx = survivors.findIndex(s => survivorKey(s) === brandNew[0])
      const sigLabel = `SIG-${String.fromCharCode(65 + (idx >= 0 ? idx : survivors.length - 1))}`
      setAlertSignal(sigLabel)
      setNewKeys(new Set(brandNew))
      if (alertTimeoutRef.current) clearTimeout(alertTimeoutRef.current)
      alertTimeoutRef.current = setTimeout(() => {
        setAlertSignal(null)
        setNewKeys(new Set())
      }, 3000)
    }
    knownKeysRef.current = currentKeys
  }, [survivors])

  return (
    <div style={{
      background: 'linear-gradient(135deg, rgba(6,8,16,0.88), rgba(4,6,14,0.82))',
      border: `1px solid ${critical ? 'rgba(255,70,70,0.3)' : 'rgba(40,140,180,0.2)'}`,
      borderLeft: `2px solid ${critical ? '#cc3333' : '#cc8800'}`,
      borderRadius: 8,
      color: '#8899bb',
      fontSize: 13,
      fontFamily: "'Courier New', monospace",
      lineHeight: 1.7,
      pointerEvents: 'auto',
      minWidth: 240,
      maxHeight: 440,
      position: 'relative',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      boxShadow: '0 4px 30px rgba(0,0,0,0.4), inset 0 1px 0 rgba(200,136,0,0.06)',
      backdropFilter: 'blur(12px)',
    }}>
      {/* Decorative scan line */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: '-30%',
        width: '30%',
        height: '100%',
        background: 'linear-gradient(90deg, transparent, rgba(80,170,255,0.03), transparent)',
        animation: 'beacon-scanLine 4s linear infinite',
        pointerEvents: 'none',
        zIndex: 0,
      }} />

      {/* Sticky header section */}
      <div style={{
        flexShrink: 0,
        padding: '10px 14px 0',
        position: 'relative',
        zIndex: 2,
        background: 'linear-gradient(135deg, rgba(6,8,16,0.95), rgba(4,6,14,0.9))',
      }}>
        {/* Alert banner for new survivor detection */}
        {alertSignal && (
          <div style={{
            background: 'linear-gradient(135deg, rgba(255,60,0,0.2), rgba(255,120,0,0.15))',
            border: '1px solid rgba(255,120,0,0.5)',
            borderRadius: 4,
            padding: '6px 10px',
            marginBottom: 8,
            textAlign: 'center',
            animation: 'beacon-alertFlash 3s ease-in-out forwards',
          }}>
            <div style={{ color: '#ff8833', fontWeight: 700, fontSize: 13, letterSpacing: 1.5 }}>
              SIGNAL ACQUIRED
            </div>
            <div style={{ color: '#ffaa55', fontSize: 12 }}>
              {alertSignal} — Heat signature confirmed
            </div>
          </div>
        )}

        {/* Title */}
        <div style={{
          color: '#99b',
          marginBottom: 8,
          letterSpacing: 1.5,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span style={{ fontWeight: 700 }}>SCAN INTEL</span>
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 12,
          }}>
            {detected > 0 && (
              <span style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: '#ff6',
                display: 'inline-block',
                animation: 'beacon-signalDot 1.5s ease-in-out infinite',
                color: '#ff6',
              }} />
            )}
            <span style={{ color: detected > 0 ? '#ff6' : '#7a8a9a' }}>
              {detected > 0 ? 'LIVE' : 'NO CONTACT'}
            </span>
          </span>
        </div>

        {/* Summary counters */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${2 + (submerged > 0 ? 1 : 0) + (deliveredCount > 0 ? 1 : 0)}, 1fr)`,
          gap: 4,
          marginBottom: 8,
          paddingBottom: 8,
          borderBottom: '1px solid rgba(50, 60, 80, 0.5)',
        }}>
          <StatCounter value={detected} label="DETECTED" color={detected > 0 ? '#44ff66' : '#7a8a9a'} />
          <StatCounter value={totalSurvivors - detected} label="UNSCANNED" color="#7a8a9a" />
          {submerged > 0 && <StatCounter value={submerged} label="SUBMERGED" color="#ff4444" />}
          {deliveredCount > 0 && <StatCounter value={deliveredCount} label="SUPPLIED" color="#44ccff" />}
        </div>

        {/* Sensor context */}
        <div style={{
          color: '#7a8a9a',
          marginBottom: 8,
          fontSize: 11,
          display: 'flex',
          justifyContent: 'space-between',
        }}>
          <span>SENSOR @ ({dronePos.x.toFixed(1)}, {dronePos.y.toFixed(1)}, {dronePos.z.toFixed(1)})</span>
          <span style={{ color: '#8899aa' }}>{SURVIVOR_SENSOR_RANGE}m</span>
        </div>
      </div>

      {/* Scrollable survivor list — capped to ~3 visible items */}
      <div style={{ overflowY: 'auto', maxHeight: 220, padding: '0 14px 10px', position: 'relative', zIndex: 1 }}>
        {detected === 0 ? (
          <div style={{ color: '#6a7a8a', fontStyle: 'italic', fontSize: 12, padding: '8px 0' }}>
            No heat signatures in sensor range.
            <br />
            <span style={{ color: '#5a6a7a' }}>Move drone closer to scan targets.</span>
          </div>
        ) : (
          survivors.map((s, i) => {
            const key = survivorKey(s)
            const dist = Math.sqrt(
              (s.x - dronePos.x) ** 2 + (s.y - dronePos.y) ** 2 + (s.z - dronePos.z) ** 2,
            )
            const isSubmerged = s.y < FLOOD_LEVEL - 0.2
            const isDelivering = deliveringTo.has(key)
            const isDelivered = deliveredTo.has(key)
            const isNew = newKeys.has(key)
            const signalStrength = Math.max(0, Math.min(1, 1 - dist / (SURVIVOR_SENSOR_RANGE * 1.2)))

            return (
              <div key={i} style={{
                padding: '6px 8px',
                marginBottom: 5,
                borderRadius: 4,
                background: isDelivered
                  ? 'rgba(60, 200, 255, 0.08)'
                  : isSubmerged ? 'rgba(255, 50, 50, 0.10)' : 'rgba(60, 255, 60, 0.06)',
                border: `1px solid ${isDelivered
                  ? 'rgba(60, 200, 255, 0.25)'
                  : isSubmerged ? 'rgba(255, 80, 80, 0.3)' : 'rgba(80, 255, 80, 0.15)'}`,
                animation: isNew
                  ? 'beacon-survivorIn 0.5s ease-out forwards'
                  : isSubmerged && !isDelivered
                    ? 'beacon-criticalPulse 2s ease-in-out infinite'
                    : 'none',
              }}>
                {/* Row 1: ID + distance */}
                <div style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 3,
                }}>
                  <span style={{
                    color: isDelivered ? '#4cf' : isSubmerged ? '#ff6666' : '#66ff88',
                    fontWeight: 700,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 5,
                  }}>
                    <span style={{
                      width: 5,
                      height: 5,
                      borderRadius: '50%',
                      background: isDelivered ? '#4cf' : isSubmerged ? '#f66' : '#6f6',
                      display: 'inline-block',
                      animation: !isDelivered ? 'beacon-signalDot 1.5s ease-in-out infinite' : 'none',
                    }} />
                    SIG-{String.fromCharCode(65 + i)}
                    {isNew && (
                      <span style={{
                        color: '#ff8833',
                        fontSize: 10,
                        fontWeight: 700,
                        animation: 'beacon-newBadge 0.8s ease-in-out 3',
                        letterSpacing: 1,
                      }}>
                        NEW
                      </span>
                    )}
                    {isSubmerged && !isDelivered && (
                      <span style={{ color: '#ff5555', fontSize: 11, fontWeight: 400 }}>SUBMERGED</span>
                    )}
                    {isDelivered && (
                      <span style={{ color: '#4cf', fontSize: 11, fontWeight: 400 }}>SUPPLIED</span>
                    )}
                  </span>
                  <span style={{ color: '#8899aa', fontSize: 12 }}>{dist.toFixed(1)}m</span>
                </div>

                {/* Row 3: Coords + action */}
                <div style={{
                  color: '#8899aa',
                  fontSize: 12,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}>
                  <span>
                    ({s.x.toFixed(1)}, {s.y.toFixed(1)}, {s.z.toFixed(1)})
                    {isSubmerged && !isDelivered && (
                      <span style={{ color: '#ff3333', marginLeft: 6, fontWeight: 700, fontSize: 11 }}>
                        ⚠ CRITICAL
                      </span>
                    )}
                  </span>
                  {isDelivering ? (
                    <span style={{ display: 'inline-flex', gap: 3 }}>
                      <span style={{
                        border: '1px solid rgba(255,200,0,0.3)',
                        borderRadius: 3,
                        background: 'rgba(255,200,0,0.12)',
                        color: '#ff6',
                        padding: '2px 7px',
                        fontSize: 11,
                      }}>
                        EN ROUTE
                      </span>
                      <button
                        onClick={() => onRetryDelivery(s)}
                        style={{
                          border: '1px solid rgba(255,100,100,0.5)',
                          borderRadius: 3,
                          background: 'rgba(255,60,60,0.15)',
                          color: '#f88',
                          padding: '2px 7px',
                          cursor: 'pointer',
                          fontSize: 11,
                          fontFamily: "'Courier New', monospace",
                        }}
                      >
                        RETRY
                      </button>
                    </span>
                  ) : (
                    <button
                      onClick={() => onSendSupplies(s)}
                      disabled={isDelivered}
                      style={{
                        border: `1px solid ${isDelivered ? 'rgba(60,200,255,0.3)' : 'rgba(255,160,0,0.5)'}`,
                        borderRadius: 3,
                        background: isDelivered ? 'rgba(60,200,255,0.15)' : 'rgba(255,140,0,0.15)',
                        color: isDelivered ? '#4cf' : '#fa0',
                        padding: '2px 7px',
                        cursor: isDelivered ? 'default' : 'pointer',
                        fontSize: 11,
                        fontFamily: "'Courier New', monospace",
                        opacity: isDelivered ? 0.7 : 1,
                      }}
                    >
                      {isDelivered ? '✓ DONE' : 'DELIVER'}
                    </button>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

// ── Activity Feed — clean, scannable mission timeline ─────────────────────────

type ActivityCategory = 'dispatch' | 'agent' | 'reasoning' | 'movement' | 'scan' | 'complete' | 'error' | 'system'

interface ActivityItem {
  id: number
  icon: string
  label: string
  detail?: string
  ts: number
  status: 'active' | 'done' | 'error'
  category: ActivityCategory
}

let _activityId = 0

const CATEGORY_STYLE: Record<ActivityCategory, { color: string; glow: string }> = {
  dispatch:  { color: '#e0e8ff', glow: 'rgba(180,200,255,0.12)' },
  agent:     { color: '#c090ff', glow: 'rgba(160,100,255,0.12)' },
  reasoning: { color: '#60aacc', glow: 'rgba(80,160,200,0.06)' },
  movement:  { color: '#55aaff', glow: 'rgba(80,170,255,0.10)' },
  scan:      { color: '#ffaa33', glow: 'rgba(255,170,50,0.10)' },
  complete:  { color: '#44dd88', glow: 'rgba(60,220,120,0.10)' },
  error:     { color: '#ff5555', glow: 'rgba(255,80,80,0.10)' },
  system:    { color: '#8899aa', glow: 'rgba(100,130,160,0.06)' },
}

function missionTime(ts: number): string {
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function parseEventToActivity(event: import('@/lib/api').AgentStreamEvent): ActivityItem | null {
  if (event.type === 'tool_call') {
    const { name, args, agent } = event
    if (name === 'transfer_to_agent') {
      const target = String(args.agent_name ?? '').replace(/_/g, ' ')
      return { id: ++_activityId, icon: '◈', label: `${target}`, ts: Date.now(), status: 'done', category: 'agent' }
    }
    if (name === 'plan_route') {
      const x = Number(args.target_x ?? 0).toFixed(0)
      const z = Number(args.target_z ?? 0).toFixed(0)
      const y = Number(args.target_y ?? 0).toFixed(0)
      return { id: ++_activityId, icon: '◇', label: 'Planning route', detail: `→ (${x}, ${y}, ${z})`, ts: Date.now(), status: 'active', category: 'movement' }
    }
    if (name === 'move_drone_to') {
      const x = Number(args.x ?? 0).toFixed(1)
      const z = Number(args.z ?? 0).toFixed(1)
      const y = Number(args.y ?? 0).toFixed(1)
      return { id: ++_activityId, icon: '▸', label: 'Moving to waypoint', detail: `(${x}, ${y}, ${z})`, ts: Date.now(), status: 'active', category: 'movement' }
    }
    if (name === 'sweep_scan_building') {
      const x = Number(args.target_x ?? 0).toFixed(0)
      const z = Number(args.target_z ?? 0).toFixed(0)
      return { id: ++_activityId, icon: '◉', label: 'Scanning building', detail: `(${x}, ${z})`, ts: Date.now(), status: 'active', category: 'scan' }
    }
    if (name === 'return_to_base') {
      return { id: ++_activityId, icon: '⌂', label: 'Returning to base', ts: Date.now(), status: 'active', category: 'movement' }
    }
    if (name === 'resolve_scan_target') {
      const x = Number(args.target_x ?? 0).toFixed(0)
      const z = Number(args.target_z ?? 0).toFixed(0)
      return { id: ++_activityId, icon: '⊕', label: 'Resolving target', detail: `(${x}, ${z})`, ts: Date.now(), status: 'active', category: 'scan' }
    }
    if (name === 'pick_next_building') {
      return { id: ++_activityId, icon: '⊞', label: 'Selecting next building', ts: Date.now(), status: 'active', category: 'scan' }
    }
    if (name === 'save_scan_result') {
      return { id: ++_activityId, icon: '✎', label: 'Saving scan results', ts: Date.now(), status: 'active', category: 'system' }
    }
    if (name === 'get_scan_results') {
      return { id: ++_activityId, icon: '⊡', label: 'Compiling report', ts: Date.now(), status: 'active', category: 'system' }
    }
    return { id: ++_activityId, icon: '⟡', label: name.replace(/_/g, ' '), detail: `[${agent}]`, ts: Date.now(), status: 'active', category: 'system' }
  }

  if (event.type === 'text' || event.type === 'final') {
    const t = event.text
    const arriveMatch = t.match(/arrived at \(([^)]+)\)/)
    if (arriveMatch) {
      return { id: ++_activityId, icon: '✓', label: 'Arrived', detail: `(${arriveMatch[1]})`, ts: Date.now(), status: 'done', category: 'complete' }
    }
    const sweepMatch = t.match(/SWEEP SCAN COMPLETE/)
    if (sweepMatch) {
      const findingsMatch = t.match(/Findings\s*:\s*(.+)/)
      return { id: ++_activityId, icon: '✓', label: 'Sweep complete', detail: findingsMatch?.[1]?.trim(), ts: Date.now(), status: 'done', category: 'complete' }
    }
    const areaMatch = t.match(/AREA SCAN COMPLETE.*?(\d+)\s*building/)
    if (areaMatch) {
      const totalMatch = t.match(/TOTAL SURVIVORS DETECTED:\s*(\d+)/)
      return { id: ++_activityId, icon: '◈', label: `Area scan done`, detail: `${areaMatch[1]} bldg · ${totalMatch?.[1] ?? '?'} survivors`, ts: Date.now(), status: 'done', category: 'complete' }
    }
    const scanTargetMatch = t.match(/SCAN TARGET.*?building at \(x=([^,]+),\s*z=([^)]+)\)/)
    if (scanTargetMatch) {
      return { id: ++_activityId, icon: '▶', label: 'Next target', detail: `building (${scanTargetMatch[1]}, ${scanTargetMatch[2]})`, ts: Date.now(), status: 'active', category: 'scan' }
    }
    if (t.includes('QUEUE_EMPTY')) {
      return { id: ++_activityId, icon: '✓', label: 'All buildings scanned', ts: Date.now(), status: 'done', category: 'complete' }
    }
    return null
  }

  if (event.type === 'error') {
    return { id: ++_activityId, icon: '✗', label: 'Error', detail: event.text.slice(0, 60), ts: Date.now(), status: 'error', category: 'error' }
  }
  if (event.type === 'done') {
    return { id: ++_activityId, icon: '●', label: 'Agent done', ts: Date.now(), status: 'done', category: 'complete' }
  }

  return null
}

function ActivityFeed({ items, busy, onClear }: { items: ActivityItem[]; busy: boolean; onClear: () => void }) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [items.length])

  return (
    <div style={{
      background: 'linear-gradient(135deg, rgba(6,8,16,0.88), rgba(4,6,14,0.82))',
      border: '1px solid rgba(32,144,176,0.2)',
      borderLeft: '2px solid #2090b0',
      borderRadius: 8,
      fontFamily: "'Courier New', monospace",
      fontSize: 13,
      lineHeight: 1.6,
      pointerEvents: 'auto',
      width: 340,
      maxHeight: '100%',
      position: 'relative',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      boxShadow: '0 4px 30px rgba(0,0,0,0.4), inset 0 1px 0 rgba(32,144,176,0.08)',
      backdropFilter: 'blur(12px)',
    }}>
      {/* Decorative scan line */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: '-30%',
        width: '30%',
        height: '100%',
        background: 'linear-gradient(90deg, transparent, rgba(32,144,176,0.04), transparent)',
        animation: 'beacon-scanLine 5s linear infinite',
        pointerEvents: 'none',
        zIndex: 0,
      }} />

      {/* Sticky header */}
      <div style={{
        color: '#c0d0e0',
        letterSpacing: 2,
        padding: '12px 16px 10px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        position: 'relative',
        zIndex: 2,
        flexShrink: 0,
        background: 'linear-gradient(135deg, rgba(6,8,16,0.95), rgba(4,6,14,0.9))',
        borderBottom: '1px solid rgba(32,144,176,0.15)',
      }}>
        <span style={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8, fontSize: 14 }}>
          <span style={{
            color: '#2090b0',
            fontSize: 16,
            textShadow: '0 0 8px rgba(32,144,176,0.5)',
          }}>◉</span>
          MISSION LOG
        </span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {busy && (
            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              color: '#55aaff',
              fontSize: 11,
              animation: 'beacon-livePulse 1.5s ease-in-out infinite',
              padding: '2px 7px',
              borderRadius: 3,
              background: 'rgba(50,120,255,0.08)',
              border: '1px solid rgba(50,120,255,0.15)',
            }}>
              <span style={{
                width: 5,
                height: 5,
                borderRadius: '50%',
                background: '#55aaff',
                display: 'inline-block',
                boxShadow: '0 0 8px #55aaff',
              }} />
              LIVE
            </span>
          )}
          {items.length > 0 && (
            <button
              onClick={onClear}
              style={{
                background: 'rgba(20,25,40,0.5)',
                border: '1px solid rgba(80,120,200,0.15)',
                borderRadius: 3,
                color: '#6a7a8a',
                padding: '1px 6px',
                cursor: 'pointer',
                fontFamily: "'Courier New', monospace",
                fontSize: 11,
                lineHeight: '18px',
                transition: 'color 0.15s',
              }}
              title="Clear mission log"
            >
              CLR
            </button>
          )}
        </div>
      </div>

      {/* Scrollable content */}
      {items.length === 0 ? (
        <div style={{
          color: '#6a7a8a',
          fontStyle: 'italic',
          fontSize: 12,
          padding: '12px 16px',
          textAlign: 'center',
          position: 'relative',
          zIndex: 1,
        }}>
          Awaiting mission orders...
        </div>
      ) : (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 1,
          position: 'relative',
          zIndex: 1,
          overflowY: 'auto',
          flex: 1,
          minHeight: 0,
          padding: '4px 14px 10px',
        }}>
          {items.map((item, idx) => {
            const cat = CATEGORY_STYLE[item.category] ?? CATEGORY_STYLE.system
            const isLast = idx === items.length - 1
            return (
              <div key={item.id} style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8,
                padding: '5px 6px',
                borderRadius: 3,
                background: isLast && busy ? cat.glow : 'transparent',
                animation: isLast ? 'beacon-slideIn 0.3s ease-out' : 'none',
                borderBottom: '1px solid rgba(50,60,80,0.3)',
              }}>
                {/* Icon */}
                <div style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  flexShrink: 0,
                  width: 16,
                  paddingTop: 2,
                }}>
                  <span style={{
                    color: cat.color,
                    fontSize: 14,
                    lineHeight: 1,
                  }}>
                    {item.icon}
                  </span>
                </div>

                {/* Content */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    gap: 8,
                  }}>
                    <span style={{
                      color: cat.color,
                      fontSize: 13,
                      fontWeight: item.category === 'reasoning' ? 400 : 600,
                      fontStyle: item.category === 'reasoning' ? 'italic' : 'normal',
                    }}>
                      {item.label}
                    </span>
                    <span style={{
                      color: '#5a6a7a',
                      fontSize: 11,
                      flexShrink: 0,
                      fontVariantNumeric: 'tabular-nums',
                    }}>
                      {missionTime(item.ts)}
                    </span>
                  </div>
                  {item.detail && (
                    <div style={{
                      color: item.category === 'reasoning' ? '#4a7a90' : '#667',
                      fontSize: 12,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                      marginTop: 1,
                    }}>
                      {item.detail}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  )
}


interface ControlsProps {
  followBeacon: boolean
  onToggleFollow: () => void
  transparentWalls: boolean
  onToggleWalls: () => void
  scanRaysEnabled: boolean
  onToggleScanRays: () => void
  selectMode: boolean
}

function Controls({
  followBeacon,
  onToggleFollow,
  transparentWalls,
  onToggleWalls,
  scanRaysEnabled,
  onToggleScanRays,
  selectMode,
}: ControlsProps) {
  return (
    <div style={{
      background: selectMode
        ? 'linear-gradient(135deg, rgba(30,16,0,0.85), rgba(20,10,0,0.75))'
        : 'linear-gradient(135deg, rgba(8,10,20,0.82), rgba(6,8,16,0.72))',
      border: selectMode ? '1px solid rgba(255,136,0,0.3)' : '1px solid rgba(40,60,100,0.25)',
      borderRadius: 8,
      padding: '10px 12px',
      color: '#8899aa',
      fontSize: 12,
      fontFamily: "'Courier New', monospace",
      lineHeight: 1.6,
      pointerEvents: 'auto',
      minWidth: 210,
      backdropFilter: 'blur(12px)',
    }}>
      {selectMode ? (
        <div style={{ color: '#ff9933', fontWeight: 'bold', letterSpacing: 1, textAlign: 'center', padding: '4px 0', fontSize: 13 }}>
          AREA SELECT ACTIVE
          <div style={{ color: '#997744', fontSize: 11, fontWeight: 400, marginTop: 2 }}>Ctrl+S / Esc to cancel</div>
        </div>
      ) : (
        <>
          <div style={{ color: '#7a8a9a', fontSize: 11, letterSpacing: 1, marginBottom: 6, textAlign: 'center' }}>
            SCENE CONTROLS
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px 8px', color: '#7a8a9a', fontSize: 11, marginBottom: 8, justifyContent: 'center' }}>
            <span>Drag: orbit/pan</span>
            <span style={{ color: '#3a4a5a' }}>│</span>
            <span>Scroll: zoom</span>
            <span style={{ color: '#3a4a5a' }}>│</span>
            <span style={{ color: '#6a8aaa' }}>F: follow</span>
            <span style={{ color: '#3a4a5a' }}>│</span>
            <span style={{ color: '#c87' }}>Ctrl+S: select</span>
          </div>
        </>
      )}
      {/* Toggle buttons row */}
      <div style={{ display: 'flex', gap: 4 }}>
        <button
          onClick={onToggleFollow}
          style={{
            flex: 1,
            border: `1px solid ${followBeacon ? 'rgba(90,140,255,0.4)' : 'rgba(40,50,70,0.5)'}`,
            borderRadius: 4,
            background: followBeacon ? 'rgba(40,130,255,0.2)' : 'rgba(15,20,30,0.6)',
            color: followBeacon ? '#9fd0ff' : '#4a5a6a',
            padding: '6px 6px',
            cursor: 'pointer',
            fontSize: 11,
            fontFamily: "'Courier New', monospace",
            textAlign: 'center',
            letterSpacing: 0.5,
            transition: 'all 0.15s',
          }}
        >
          FOLLOW {followBeacon ? 'ON' : 'OFF'}
        </button>
        <button
          onClick={onToggleWalls}
          style={{
            flex: 1,
            border: `1px solid ${transparentWalls ? 'rgba(120,190,255,0.4)' : 'rgba(40,50,70,0.5)'}`,
            borderRadius: 4,
            background: transparentWalls ? 'rgba(60,170,255,0.18)' : 'rgba(15,20,30,0.6)',
            color: transparentWalls ? '#b5e6ff' : '#4a5a6a',
            padding: '6px 6px',
            cursor: 'pointer',
            fontSize: 11,
            fontFamily: "'Courier New', monospace",
            textAlign: 'center',
            letterSpacing: 0.5,
            transition: 'all 0.15s',
          }}
        >
          WALLS {transparentWalls ? 'X-RAY' : 'SOLID'}
        </button>
        <button
          onClick={onToggleScanRays}
          style={{
            flex: 1,
            border: `1px solid ${scanRaysEnabled ? 'rgba(255,120,150,0.4)' : 'rgba(40,50,70,0.5)'}`,
            borderRadius: 4,
            background: scanRaysEnabled ? 'rgba(255,70,110,0.15)' : 'rgba(15,20,30,0.6)',
            color: scanRaysEnabled ? '#ff9fb3' : '#4a5a6a',
            padding: '6px 6px',
            cursor: 'pointer',
            fontSize: 11,
            fontFamily: "'Courier New', monospace",
            textAlign: 'center',
            letterSpacing: 0.5,
            transition: 'all 0.15s',
          }}
        >
          RAYS {scanRaysEnabled ? 'ON' : 'OFF'}
        </button>
      </div>
    </div>
  )
}

// ── Main scene ────────────────────────────────────────────────────────────────

const ASSET_ID = 'BEACON-01'
const WS_URL   = 'ws://localhost:8000/ws/telemetry'
const AUTO_RECALL_UI_DELAY_MS = 5000

export default function SARScene() {
  const [log, setLog]       = useState<string[]>(['Connecting to backend...'])
  const [uplinked, setUplinked] = useState(false)
  const [hoverPt, setHoverPt]     = useState<THREE.Vector3 | null>(null)
  const [copied, setCopied]       = useState(false)
  const [followBeacon, setFollowBeacon] = useState(false)
  const [transparentWalls, setTransparentWalls] = useState(false)
  const [scanRaysEnabled, setScanRaysEnabled] = useState(true)
  const [deliveredTo, setDeliveredTo] = useState<Set<string>>(new Set())
  const [deliveringTo, setDeliveringTo] = useState<Set<string>>(new Set())
  const [activities, setActivities] = useState<ActivityItem[]>([])
  const [agentBusy, setAgentBusy] = useState(false)
  const [hasCargo, setHasCargo] = useState(false)
  const [activeThrow, setActiveThrow] = useState<{ from: THREE.Vector3; to: SurvivorPoint } | null>(null)
  const deliveryTarget = useRef<SurvivorPoint | null>(null)
  const deliveryApproach = useRef<SurvivorPoint | null>(null)
  const [routeArrived, setRouteArrived] = useState(false)
  const [autoRecallThreshold, setAutoRecallThreshold] = useState<number | null>(null)
  const [autoRecallPrompt, setAutoRecallPrompt] = useState<{ assetId: string; battery: number } | null>(null)
  const [autoRecallCountdown, setAutoRecallCountdown] = useState(5)
  const autoRecallDismissedRef = useRef<Set<string>>(new Set())
  const autoRecallTriggeredRef = useRef<Set<string>>(new Set())
  const autoRecallInFlightRef = useRef<Set<string>>(new Set())
  // ── Area selection state ─────────────────────────────────────────────────────
  const [selectMode, setSelectMode]       = useState(false)
  const [dragStart, setDragStart]         = useState<THREE.Vector3 | null>(null)
  const [dragEnd, setDragEnd]             = useState<THREE.Vector3 | null>(null)
  const [selection, setSelection]         = useState<AreaSelection | null>(null)
  const [showContextMenu, setShowContextMenu] = useState(false)
  // ─────────────────────────────────────────────────────────────────────────────
  const copiedTimer               = useRef<ReturnType<typeof setTimeout> | null>(null)
  const orbitRef                  = useRef<OrbitControlsImpl | null>(null)
  const northAngleRef             = useRef<number>(0)

  const handleGroundClick = useCallback((pt: THREE.Vector3) => {
    const text = `${pt.x.toFixed(1)}, ${pt.y.toFixed(1)}, ${pt.z.toFixed(1)}`
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    if (copiedTimer.current) clearTimeout(copiedTimer.current)
    copiedTimer.current = setTimeout(() => setCopied(false), 1500)
  }, [])
  const drones = useTelemetry(WS_URL)

  const telemetry = drones[ASSET_ID] ?? null
  const dronePos = useMemo(
    () => telemetry ? new THREE.Vector3(telemetry.x, telemetry.y, telemetry.z) : DRONE_START.clone(),
    [telemetry?.x, telemetry?.y, telemetry?.z]
  )
  const droneStatus = telemetry?.status ?? 'IDLE'
  const battery   = telemetry?.battery ?? null
  const connected = telemetry !== null

  const addLog = useCallback((msg: string) => {
    setLog(prev => [...prev.slice(-6), msg])
  }, [])

  const executeAutoRecall = useCallback(async (assetId: string, batteryPct: number) => {
    setAutoRecallPrompt(current => (current?.assetId === assetId ? null : current))
    autoRecallDismissedRef.current.add(assetId)
    autoRecallTriggeredRef.current.add(assetId)
    autoRecallInFlightRef.current.add(assetId)
    addLog(`⚠ ${assetId} battery ${batteryPct.toFixed(1)}% — auto recall initiated`)
    try {
      await resetDroneToBase(assetId)
      addLog(`⌂ ${assetId} returning to base`)
    } catch {
      autoRecallTriggeredRef.current.delete(assetId)
      addLog(`⚠ Auto recall failed for ${assetId}`)
    } finally {
      autoRecallInFlightRef.current.delete(assetId)
    }
  }, [addLog])

  const cancelAutoRecall = useCallback(() => {
    if (!autoRecallPrompt) return
    autoRecallDismissedRef.current.add(autoRecallPrompt.assetId)
    setAutoRecallPrompt(null)
    addLog(`⏸ Auto recall cancelled for ${autoRecallPrompt.assetId}`)
  }, [autoRecallPrompt, addLog])

  const toggleFollowBeacon = useCallback(() => {
    setFollowBeacon(prev => {
      const next = !prev
      addLog(next ? `👁 Following ${ASSET_ID}` : '👁 Follow mode disabled')
      return next
    })
  }, [addLog])

  const toggleWallTransparency = useCallback(() => {
    setTransparentWalls(prev => {
      const next = !prev
      addLog(next ? '🧱 Target walls set to transparent' : '🧱 Target walls set to solid')
      return next
    })
  }, [addLog])

  const toggleScanRays = useCallback(() => {
    setScanRaysEnabled(prev => {
      const next = !prev
      addLog(next ? '📡 Survivor scan rays enabled' : '📡 Survivor scan rays disabled')
      return next
    })
  }, [addLog])

  // Auto-uplink all active drones on mount
  useEffect(() => {
    let mounted = true
    const init = async () => {
      const ok = await healthCheck()
      if (!ok || !mounted) {
        addLog('⚠ Backend offline — start FastAPI sidecar')
        return
      }
      try {
        const config = await getAutoRecallConfig()
        if (mounted) setAutoRecallThreshold(config.battery_threshold)
      } catch {
        addLog('⚠ Failed to load auto-recall config')
      }
      let fleet: Awaited<ReturnType<typeof getFleet>>
      try {
        fleet = await getFleet()
      } catch {
        addLog('⚠ Failed to fetch fleet')
        return
      }
      if (!mounted) return
      const active = fleet.fleet.filter(d => d.active)
      if (active.length === 0) {
        addLog('⚠ No active drones found — start drone containers first')
        return
      }
      let anyUplinked = false
      await Promise.all(active.map(async d => {
        try {
          await uplink(d.asset_id)
          if (mounted) addLog(`✓ ${d.asset_id} uplinked — agent ready`)
          anyUplinked = true
        } catch {
          // Already uplinked or unreachable — check current status
          if (d.uplinked) {
            if (mounted) addLog(`✓ ${d.asset_id} registered with commander`)
            anyUplinked = true
          } else {
            if (mounted) addLog(`⚠ ${d.asset_id} not discoverable yet`)
          }
        }
      }))
      if (mounted && anyUplinked) setUplinked(true)
    }
    init()
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    if (!telemetry) return
    if (telemetry.status === 'MOVING') {
      addLog(`→ ${ASSET_ID} moving to (${telemetry.x.toFixed(1)}, ${telemetry.y.toFixed(1)}, ${telemetry.z.toFixed(1)})`)
    }
  }, [telemetry?.status])

  useEffect(() => {
    if (autoRecallThreshold === null) return
    const lowBatteryIdle = Object.values(drones)
      .filter(entry => entry.status === 'IDLE' && entry.battery <= autoRecallThreshold)
      .sort((a, b) => a.asset_id.localeCompare(b.asset_id))
    const lowBatteryIdleIds = new Set(lowBatteryIdle.map(entry => entry.asset_id))

    for (const assetId of [...autoRecallDismissedRef.current]) {
      if (!lowBatteryIdleIds.has(assetId)) autoRecallDismissedRef.current.delete(assetId)
    }
    for (const assetId of [...autoRecallTriggeredRef.current]) {
      if (!lowBatteryIdleIds.has(assetId)) autoRecallTriggeredRef.current.delete(assetId)
    }

    if (autoRecallPrompt && !lowBatteryIdleIds.has(autoRecallPrompt.assetId)) {
      setAutoRecallPrompt(null)
      return
    }
    if (autoRecallPrompt) return

    const nextPrompt = lowBatteryIdle.find(entry =>
      !autoRecallDismissedRef.current.has(entry.asset_id)
      && !autoRecallTriggeredRef.current.has(entry.asset_id)
      && !autoRecallInFlightRef.current.has(entry.asset_id)
    )
    if (nextPrompt) {
      setAutoRecallPrompt({ assetId: nextPrompt.asset_id, battery: nextPrompt.battery })
    }
  }, [drones, autoRecallPrompt, autoRecallThreshold])

  useEffect(() => {
    if (!autoRecallPrompt) return
    const deadline = Date.now() + AUTO_RECALL_UI_DELAY_MS
    setAutoRecallCountdown(Math.ceil(AUTO_RECALL_UI_DELAY_MS / 1000))

    const interval = setInterval(() => {
      const remainingMs = Math.max(0, deadline - Date.now())
      setAutoRecallCountdown(Math.ceil(remainingMs / 1000))
    }, 200)

    const timeout = setTimeout(() => {
      void executeAutoRecall(autoRecallPrompt.assetId, autoRecallPrompt.battery)
    }, AUTO_RECALL_UI_DELAY_MS)

    return () => {
      clearInterval(interval)
      clearTimeout(timeout)
    }
  }, [autoRecallPrompt, executeAutoRecall])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable

      // F key — follow toggle (skip if in input)
      if (!event.repeat && event.key.toLowerCase() === 'f' && !inInput) {
        event.preventDefault()
        toggleFollowBeacon()
        return
      }

      // Ctrl+S — toggle area select mode (always prevent browser save)
      if (event.ctrlKey && event.key.toLowerCase() === 's') {
        event.preventDefault()
        if (inInput) return
        setSelectMode(prev => {
          const next = !prev
          if (!next) {
            setDragStart(null)
            setDragEnd(null)
            setSelection(null)
            setShowContextMenu(false)
          }
          return next
        })
        return
      }

      // Escape — exit select mode
      if (event.key === 'Escape' && selectMode) {
        setSelectMode(false)
        setDragStart(null)
        setDragEnd(null)
        setSelection(null)
        setShowContextMenu(false)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [toggleFollowBeacon, selectMode])

  const abortRef = useRef<AbortController | null>(null)
  const pendingDeliveryKey = useRef<string | null>(null)
  const deliveryDroneId = useRef<string | null>(null)

  // ── Cargo pickup at base ──────────────────────────────────────────────────
  const cargoPickedUp = useRef(false)
  const BASE_PICKUP_RANGE = 3.0

  useEffect(() => {
    if (!deliveryTarget.current || cargoPickedUp.current) return
    if (!pendingDeliveryKey.current || !deliveryDroneId.current) return

    const t = drones[deliveryDroneId.current]
    if (!t) return

    const distToBase = Math.sqrt(t.x ** 2 + t.y ** 2 + t.z ** 2)
    if (distToBase < BASE_PICKUP_RANGE) {
      cargoPickedUp.current = true
      setHasCargo(true)
      addLog(`📦 Supplies collected from base (${deliveryDroneId.current})`)
    }
  }, [drones, addLog])

  // ── Cargo throw trigger ───────────────────────────────────────────────────

  useEffect(() => {
    const target = deliveryTarget.current
    if (!target || activeThrow || !cargoPickedUp.current) return
    if (!routeArrived || !deliveryDroneId.current) return

    const t = drones[deliveryDroneId.current]
    if (!t) return

    cargoPickedUp.current = false
    setHasCargo(false)
    setRouteArrived(false)
    setActiveThrow({ from: new THREE.Vector3(t.x, t.y, t.z), to: target })
    addLog('📦 Supply thrown to survivor')
  }, [routeArrived, drones, activeThrow, addLog])



  const handleCommand = useCallback(async (
    prompt: string,
    onEvent: (e: AgentStreamEvent) => void,
    assetIdOverride?: string,
  ): Promise<void> => {
    const ac = new AbortController()
    abortRef.current = ac
    addLog(`⬆ ${prompt}`)
    setAgentBusy(true)
    setActivities(prev => [...prev, { id: ++_activityId, icon: '◆', label: prompt.length > 50 ? prompt.slice(0, 47) + '...' : prompt, ts: Date.now(), status: 'done', category: 'dispatch' as ActivityCategory }])
    const effectiveAssetId = assetIdOverride ?? ASSET_ID
    try {
      for await (const event of streamCommand(effectiveAssetId, prompt, ac.signal)) {
        onEvent(event)
        if (event.type === 'tool_result') {
          setActivities(prev => {
            const idx = [...prev].reverse().findIndex(a => a.status === 'active')
            if (idx === -1) return prev
            const realIdx = prev.length - 1 - idx
            const updated = [...prev]
            updated[realIdx] = { ...updated[realIdx], status: event.success ? 'done' : 'error' }
            return updated
          })
        }
        const activity = parseEventToActivity(event)
        if (activity) {
          setActivities(prev => {
            if (activity.label === 'Moving to waypoint' && prev.length > 0) {
              const last = prev[prev.length - 1]
              if (last.label === 'Moving to waypoint') {
                const updated = [...prev]
                updated[updated.length - 1] = { ...activity, id: last.id }
                return updated
              }
            }
            return [...prev, activity]
          })
        }
        if (
          (event.type === 'tool_result' || event.type === 'text') &&
          event.survivors &&
          event.survivors.length > 0
        ) {
          setDiscoveredSurvivors(prev => mergeUniqueSurvivors(prev, event.survivors!))
        }
        // Detect final route arrival — agent emits "BEACON-XX arrived at (x,y,z)"
        // only after ALL waypoints are complete, so this gates the supply throw.
        if (
          (event.type === 'text' || event.type === 'final') &&
          deliveryTarget.current &&
          /arrived at \(/.test(event.text)
        ) {
          setRouteArrived(true)
        }
        if (event.type === 'done') addLog('✓ Agent responded')
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') {
        addLog('⚠ Command aborted')
        setActivities(prev => [...prev, { id: ++_activityId, icon: '✗', label: 'Aborted', ts: Date.now(), status: 'error', category: 'error' as ActivityCategory }])
      } else {
        throw e
      }
      const key = pendingDeliveryKey.current
      if (key) {
        setDeliveringTo(prev => {
          const next = new Set(prev)
          next.delete(key)
          return next
        })
        setHasCargo(false)
        cargoPickedUp.current = false
        setRouteArrived(false)
        deliveryTarget.current = null
        deliveryApproach.current = null
        deliveryDroneId.current = null
        pendingDeliveryKey.current = null
      }
    } finally {
      setAgentBusy(false)
    }
  }, [addLog])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  // ── Area scan injection ────────────────────────────────────────────────────
  // We store a pending prompt and pass it to CommandPanel via the externalPrompt
  // prop so the command appears in its input, then auto-submits.
  const [pendingScanPrompt, setPendingScanPrompt] = useState<string | null>(null)
  const [pendingScanAssetId, setPendingScanAssetId] = useState<string | null>(null)

  const handleAreaScan = useCallback(() => {
    if (!selection) return

    // Detect which named buildings overlap the selected area.
    const overlapping = SIM_BUILDINGS.filter(b => {
      const bb = buildingBounds(b)
      // AABB overlap between selection and building footprint
      return bb.minX <= selection.maxX && bb.maxX >= selection.minX &&
             bb.minZ <= selection.maxZ && bb.maxZ >= selection.minZ
    })
    const buildingNames = overlapping
      .map(buildingPromptName)
      .filter(Boolean)

    let prompt: string
    if (buildingNames.length === 1) {
      // Entire selection is dominated by one building — scan the building directly.
      prompt = `scan the ${buildingNames[0]} at coordinates (${overlapping[0].cx.toFixed(1)}, 0, ${overlapping[0].cz.toFixed(1)}) for survivors`
    } else if (buildingNames.length > 1) {
      const buildingList = overlapping
        .map(b => {
          const name = buildingPromptName(b)
          return `${name} at (${b.cx.toFixed(1)}, 0, ${b.cz.toFixed(1)})`
        })
        .join('; ')
      prompt = `scan for survivors in each of the following buildings: ${buildingList}. Do not ask for coordinates — they are provided above. Scan each building in sequence.`
    } else {
      prompt = `scan area from (${selection.minX}, ${selection.minZ}) to (${selection.maxX}, ${selection.maxZ}) for survivors`
    }

    addLog(`📐 Area scan: (${selection.minX},${selection.minZ}) → (${selection.maxX},${selection.maxZ})`)
    // Clear selection state
    setSelectMode(false)
    setDragStart(null)
    setDragEnd(null)
    setSelection(null)
    setShowContextMenu(false)
    // Inject prompt into CommandPanel; use "auto" asset for multi-building so the
    // fleet assigner picks the closest available drones.
    setPendingScanAssetId(buildingNames.length > 1 ? 'auto' : null)
    setPendingScanPrompt(prompt)
  }, [selection, addLog])

  const handleThrowComplete = useCallback(() => {
    if (!activeThrow) return
    const key = survivorKey(activeThrow.to)
    setDeliveredTo(prev => new Set(prev).add(key))
    setDeliveringTo(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
    deliveryTarget.current = null
    deliveryApproach.current = null
    deliveryDroneId.current = null
    setActiveThrow(null)
    addLog('✓ Supply delivered to survivor')
  }, [activeThrow, addLog])

  const handleSelectionClose = useCallback(() => {
    setSelectMode(false)
    setDragStart(null)
    setDragEnd(null)
    setSelection(null)
    setShowContextMenu(false)
  }, [])

  const scannedSurvivors = useMemo(
    () => scannedSurvivorsFromDrone(dronePos),
    [dronePos.x, dronePos.y, dronePos.z],
  )
  const fleetScannedSurvivors = useMemo(() => {
    const merged = new Map<string, SurvivorPoint>()
    for (const telemetryEntry of Object.values(drones)) {
      for (const survivor of detectedSurvivorsFromTelemetryEntry(telemetryEntry)) {
        merged.set(survivorKey(survivor), survivor)
      }
    }
    return [...merged.values()]
  }, [drones])

  const handleSendSupplies = useCallback((survivor: SurvivorPoint) => {
    const key = survivorKey(survivor)
    const coords = `(${survivor.x.toFixed(1)}, ${survivor.y.toFixed(1)}, ${survivor.z.toFixed(1)})`
    const approach = computeApproachPosition(survivor)
    const approachCoords = `(${approach.x.toFixed(1)}, ${approach.y.toFixed(1)}, ${approach.z.toFixed(1)})`

    // Pick the drone closest to base (0,0,0) — it minimises total trip since
    // the drone must return to base first to collect supplies.
    const droneEntries = Object.values(drones)
    let chosenId = ASSET_ID  // fallback
    if (droneEntries.length > 0) {
      let bestDist = Infinity
      for (const d of droneEntries) {
        const dist = Math.sqrt(d.x ** 2 + d.y ** 2 + d.z ** 2)
        if (dist < bestDist) {
          bestDist = dist
          chosenId = d.asset_id
        }
      }
    }

    setDeliveringTo(prev => new Set(prev).add(key))
    pendingDeliveryKey.current = key
    deliveryDroneId.current = chosenId
    deliveryTarget.current = survivor
    deliveryApproach.current = approach
    setRouteArrived(false)
    addLog(`Dispatching ${chosenId} with supplies to survivor at ${coords}`)

    const isInside = findBuildingAt(survivor.x, survivor.y, survivor.z) !== null
    const prompt = isInside
      ? `Deliver emergency supplies to survivor at ${coords}. ` +
        `First return to base at (0, 0, 0) to collect supplies, ` +
        `then navigate to the approach position ${approachCoords} outside the building. ` +
        `Do NOT navigate to the survivor's interior coordinates — the approach position is the drop point.`
      : `Deliver emergency supplies to survivor at ${coords}. ` +
        `First return to base at (0, 0, 0) to collect supplies, ` +
        `then navigate to ${coords} to drop supplies.`

    setPendingScanPrompt(prompt)
    setPendingScanAssetId(chosenId)
  }, [addLog, drones])

  const handleRetryDelivery = useCallback((survivor: SurvivorPoint) => {
    const key = survivorKey(survivor)
    setDeliveringTo(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
    setHasCargo(false)
    cargoPickedUp.current = false
    setRouteArrived(false)
    deliveryTarget.current = null
    deliveryApproach.current = null
    deliveryDroneId.current = null
    pendingDeliveryKey.current = null
    setActiveThrow(null)
    addLog(`↻ Retrying delivery to survivor at (${survivor.x.toFixed(1)}, ${survivor.y.toFixed(1)}, ${survivor.z.toFixed(1)})`)
    setTimeout(() => handleSendSupplies(survivor), 0)
  }, [addLog, handleSendSupplies])

  // Persistent intel — accumulate survivors across all scans
  const [discoveredSurvivors, setDiscoveredSurvivors] = useState<SurvivorPoint[]>([])
  const intelSurvivors = useMemo(
    () => mergeUniqueSurvivors(discoveredSurvivors, fleetScannedSurvivors),
    [discoveredSurvivors, fleetScannedSurvivors],
  )
  const detectedSurvivorKeys = useMemo(
    () => new Set(intelSurvivors.map(survivorKey)),
    [intelSurvivors],
  )
  const survivorStatsByBuilding = useMemo(() => {
    const stats: Record<number, { detected: number; supplied: number }> = {}
    for (const building of WORLD_BUILDINGS) {
      stats[building.id] = { detected: 0, supplied: 0 }
    }
    for (const survivor of SURVIVOR_POSITIONS) {
      const building = findBuildingAt(survivor.x, survivor.y, survivor.z)
      if (!building) continue
      const key = survivorKey(survivor)
      if (detectedSurvivorKeys.has(key)) {
        stats[building.id].detected += 1
      }
      if (deliveredTo.has(key)) {
        stats[building.id].supplied += 1
      }
    }
    return stats
  }, [deliveredTo, detectedSurvivorKeys])

  useEffect(() => {
    if (fleetScannedSurvivors.length === 0) return
    setDiscoveredSurvivors(prev => mergeUniqueSurvivors(prev, fleetScannedSurvivors))
  }, [fleetScannedSurvivors])

  return (
    <div style={{
      width: '100%',
      height: '100%',
      position: 'relative',
      background: '#0a0a14',
      cursor: selectMode ? 'crosshair' : 'default',
    }}>
      <Canvas shadows>
        <fog attach="fog" args={['#0d0d1f', 90, 260]} />
        <PerspectiveCamera makeDefault position={CAM_POS} fov={60} near={0.1} far={1000} />
        <OrbitControls
          ref={orbitRef}
          enabled={!followBeacon && !selectMode}
          enableDamping
          dampingFactor={0.08}
          minDistance={5}
          maxDistance={400}
          target={[0, 5, 0]}
        />
        <FollowBeaconCamera enabled={followBeacon} targetPos={dronePos} controlsRef={orbitRef} />
        <CameraTracker northAngleRef={northAngleRef} />

        {/* Lighting */}
        <ambientLight intensity={0.55} />
        <directionalLight position={[50, 100, 40]} intensity={1.2} castShadow />
        <hemisphereLight args={['#1a1a2e', '#0d0d0d', 0.4]} />

        {/* Scene */}
        <Ground span={span} />
        <GridOverlay span={span} gridCells={GRID_CELLS} />
        <BasePad />
        <MissionBuildings
          buildings={WORLD_BUILDINGS}
          transparentWalls={transparentWalls}
          floorHeight={FLOOR_H}
          floorThickness={FLOOR_T}
          survivorStatsByBuilding={survivorStatsByBuilding}
        />
        <Survivors
          floodY={FLOOD_LEVEL}
          survivors={SURVIVOR_POSITIONS}
          deliveredTo={deliveredTo}
          detectedSurvivors={detectedSurvivorKeys}
        />
        {selectMode ? (
          <AreaSelectProbe
            onDragUpdate={(start, end) => {
              setDragStart(start)
              setDragEnd(end)
              setShowContextMenu(false)
              setSelection(null)
            }}
            onDragEnd={sel => {
              setSelection(sel)
              setShowContextMenu(true)
            }}
          />
        ) : (
          <>
            <GroundProbe onMove={setHoverPt} onDoubleClick={handleGroundClick} />
            <GroundCursor point={hoverPt} />
          </>
        )}
        {dragStart && dragEnd && (
          <AreaHighlight start={dragStart} end={dragEnd} finalised={showContextMenu} />
        )}
        {Object.values(drones).map(t => (
          <DroneMesh
            key={t.asset_id}
            targetPos={new THREE.Vector3(t.x, t.y, t.z)}
            status={t.status}
            hasCargo={hasCargo && deliveryDroneId.current === t.asset_id}
            nearbyObstacles={t.nearby_obstacles}
            nearestObstacleDist={t.nearest_obstacle_dist}
            survivorsInRange={t.survivors_in_range}
            assetId={t.asset_id}
            headingDeg={t.heading_deg}
            scanTiltDeg={t.scan_tilt_deg}
          />
        ))}
        {activeThrow && (
          <SupplyThrow
            from={activeThrow.from}
            to={activeThrow.to}
            onComplete={handleThrowComplete}
          />
        )}
        <SupplyCrates deliveredTo={deliveredTo} />
        <SurvivorScanRays
          enabled={scanRaysEnabled}
          dronePos={dronePos}
          survivors={scannedSurvivors}
        />
      </Canvas>

      {/* Top Status Bar */}
      <TopStatusBar selectMode={selectMode} floodLevel={FLOOD_LEVEL} />

      {/* Left panel — Mission Log */}
      <div style={{
        position: 'absolute',
        top: 60,
        left: 16,
        display: 'flex',
        flexDirection: 'column',
        pointerEvents: 'auto',
        maxHeight: 'calc(100% - 180px)',
      }}>
        <ActivityFeed items={activities} busy={agentBusy} onClear={() => setActivities([])} />
      </div>
      {!selectMode && <CoordOverlay point={hoverPt} copied={copied} />}
      <CompassLabels northAngleRef={northAngleRef} />
      <div style={{
        position: 'absolute',
        top: 60,
        right: 16,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        pointerEvents: 'auto',
        maxHeight: 'calc(100% - 180px)',
      }}>
        <Controls
          followBeacon={followBeacon}
          onToggleFollow={toggleFollowBeacon}
          transparentWalls={transparentWalls}
          onToggleWalls={toggleWallTransparency}
          scanRaysEnabled={scanRaysEnabled}
          onToggleScanRays={toggleScanRays}
          selectMode={selectMode}
        />
        <DroneStatusPanel drones={drones} />
        <IntelCard
          survivors={intelSurvivors}
          dronePos={dronePos}
          totalSurvivors={SURVIVOR_POSITIONS.length}
          deliveringTo={deliveringTo}
          deliveredTo={deliveredTo}
          onSendSupplies={handleSendSupplies}
          onRetryDelivery={handleRetryDelivery}
        />
      </div>
      {showContextMenu && selection && (
        <AreaContextMenu
          selection={selection}
          onScan={handleAreaScan}
          onClose={handleSelectionClose}
        />
      )}
      {autoRecallPrompt && (
        <div style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'rgba(2, 4, 10, 0.55)',
          zIndex: 40,
          pointerEvents: 'auto',
        }}>
          <div style={{
            width: 420,
            background: 'linear-gradient(135deg, rgba(20,7,7,0.96), rgba(12,3,3,0.95))',
            border: '1px solid rgba(255, 90, 90, 0.5)',
            borderLeft: '3px solid #ff4d4d',
            borderRadius: 8,
            padding: '14px 16px',
            boxShadow: '0 12px 48px rgba(0,0,0,0.55)',
            fontFamily: "'Courier New', monospace",
            color: '#ffd2d2',
          }}>
            <div style={{ color: '#ff8a8a', fontWeight: 700, letterSpacing: 1.2, marginBottom: 8 }}>
              LOW BATTERY AUTO RECALL
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.5, color: '#ffb1b1' }}>
              {autoRecallPrompt.assetId} is IDLE at {autoRecallPrompt.battery.toFixed(1)}% battery.
            </div>
            <div style={{ marginTop: 6, fontSize: 12, color: '#ff8a8a' }}>
              Auto recall in {autoRecallCountdown}s unless cancelled.
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
              <button
                onClick={cancelAutoRecall}
                style={{
                  background: 'rgba(255,70,70,0.12)',
                  border: '1px solid rgba(255,110,110,0.45)',
                  borderRadius: 4,
                  color: '#ffd2d2',
                  padding: '4px 12px',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  fontSize: 12,
                  letterSpacing: 0.6,
                }}
              >
                CANCEL
              </button>
            </div>
          </div>
        </div>
      )}
      <CommandPanel
        assetId={ASSET_ID}
        connected={connected}
        uplinked={uplinked}
        battery={battery}
        onCommand={handleCommand}
        onStop={handleStop}
        externalPrompt={pendingScanPrompt}
        externalAssetId={pendingScanAssetId}
        onExternalPromptConsumed={() => {
          setPendingScanPrompt(null)
          setPendingScanAssetId(null)
        }}
      />
    </div>
  )
}
