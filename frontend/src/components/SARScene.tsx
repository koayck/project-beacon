'use client'

import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Line, OrbitControls, PerspectiveCamera } from '@react-three/drei'
import { useRef, useState, useEffect, useMemo, useCallback, type RefObject } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import CommandPanel from './CommandPanel'
import { useTelemetry, type DroneMap } from '@/lib/ws'
import { uplink, streamCommand, healthCheck, getFleet, type AgentStreamEvent } from '@/lib/api'

// ── Constants ─────────────────────────────────────────────────────────────────

const GRID_CELLS = 50
const GRID_SPACING = 2
const NUM_FLOORS = 4
const FLOOR_H = 3.0
const FLOOR_W = 8
const FLOOR_D = 8
const FLOOR_T = 0.20
const SURV_HOVER = 0.55

const span = GRID_CELLS * GRID_SPACING           // 100
const total_h = NUM_FLOORS * FLOOR_H             // 12

const slabY = (n: number) => (n - 1) * FLOOR_H
const survY = (n: number) => slabY(n) + FLOOR_T / 2 + SURV_HOVER

// Fixed flood level (metres above ground)
const FLOOD_LEVEL = 1.4

// Target building position (not at origin — base/home pad is at 0,0,0)
const TARGET_BX = -15
const TARGET_BZ = -20
const TARGET_WINDOW_LAYOUT = [
  { floor: 1, face: 'west', offset: 0.0 },
  { floor: 2, face: 'north', offset: -1.5 },
  { floor: 3, face: 'east', offset: -0.5 },
  { floor: 4, face: 'south', offset: 1.5 },
] as const
const TARGET_WINDOW_WIDTH = 2.0
const TARGET_WINDOW_HEIGHT = 1.6
const TARGET_WINDOW_SILL = 0.4

// Obstacle building — sits on the direct line from base to target building
// Direct route (0,0,0) → (-15,0,-20): midpoint ≈ (-7.5, 0, -10)
const OBS_X = -7
const OBS_Z = -10
const OBS_W = 6
const OBS_D = 5
const OBS_H = 10

// Drone start position
const DRONE_START = new THREE.Vector3(13, 1, 13)

// Camera — pulled back for larger city
const CAM_POS: [number, number, number] = [45, 95, 70]
const FOLLOW_CAMERA_OFFSET = new THREE.Vector3(18, 14, 18)

// ── Colour palette ────────────────────────────────────────────────────────────

const C_GROUND    = '#1e1e22'
const C_ROAD      = '#2c2c32'
const C_LINE      = '#D7CDA5'
const C_PARK      = '#286C34'
const C_GRID_MAJ  = '#363a40'
const C_GRID_MIN  = '#26282e'
const C_TRUNK     = '#5F4126'
const C_LEAF      = '#267632'
const C_SLAB      = '#94A2AF'
const C_GLASS     = '#7DBCE1'
const C_GLASSBAND = '#AAD2F0'
const C_CANAL     = '#1a4a7a'

// ── City buildings: [cx, cz, w, d, h, bodyHex, roofHex] ──────────────────────
const CITY_BUILDINGS = [
  // ── Inner core (original) ────────────────────────────────────────────────
  [-14,-12, 8, 8,20, '#466291', '#5A76A5'],
  [ 14,-10, 7, 9,14, '#BCA580', '#CDB691'],
  [-16, 10, 9, 7, 9, '#C6B696', '#D4C6A8'],
  [ 16, 14, 7, 8,24, '#303E52', '#445266'],
  [  0,-20,14, 6, 7, '#B2AFA5', '#C0BEB4'],
  [-22,  2, 7, 7,16, '#52769E', '#668AB2'],
  [ 20,  0, 9, 8,12, '#A86C48', '#B9805A'],
  [  0, 22,10, 9,15, '#465562', '#5A6976'],
  [  8,-15, 5, 5,22, '#34486E', '#485C82'],
  [ -8, 17, 8, 6,10, '#BEAF91', '#D0C0A2'],
  [-10, -8, 4, 4,30, '#263658', '#38486C'],
  [ 10,  8, 6, 6,11, '#98765A', '#A8876C'],
  [ -6,-18, 6, 6,18, '#374E76', '#4B628A'],
  [ 18, -6, 5, 8,16, '#768A98', '#8A9EAC'],
  [-18, -4, 8, 5, 8, '#CDBEA0', '#DACDAF'],
  [  5,-10, 4, 4,12, '#588250', '#6C9664'],
  [-12, 14, 6, 5,14, '#94483E', '#A55A4E'],
  [ 15,  5, 5, 7,19, '#3C5070', '#506484'],
  [-20, 18, 6, 6,10, '#628E73', '#76A287'],
  [  6, 18, 7, 5, 8, '#B2946E', '#C3A580'],
  // ── Thai shophouse strip (N edge) ────────────────────────────────────────
  [-32,-27, 6, 4,10, '#D4A87C', '#C49870'],
  [-24,-27, 6, 4,10, '#C89E74', '#B88E64'],
  [-16,-27, 6, 4,12, '#D0A882', '#C09876'],
  [  0,-27, 8, 4, 8, '#BCA880', '#ACA070'],
  [ 16,-27, 6, 4,11, '#D2AE86', '#C29E76'],
  [ 24,-27, 6, 4,10, '#C8A47A', '#B89468'],
  [ 32,-27, 6, 4,10, '#CCA882', '#BC9870'],
  // ── Western tower cluster ────────────────────────────────────────────────
  [-32,  0,10, 8,14, '#C46040', '#B45030'],
  [-38,-14, 8, 6,20, '#3A5878', '#4A688A'],
  [-38, 14, 9, 7, 6, '#D0C8A8', '#C0B898'],
  [-44, -6, 7, 7,16, '#5A8496', '#6A94A6'],
  [-44,  8, 6, 6,10, '#9A7860', '#AA8870'],
  // ── Eastern district ─────────────────────────────────────────────────────
  [ 30,-20, 9, 8,18, '#4A6E9E', '#5A7EAE'],
  [ 38,-14, 7, 7,26, '#303848', '#404858'],
  [ 30, -6, 6, 8,12, '#A87E58', '#B88E68'],
  [ 38,  4, 8, 6, 8, '#C0B090', '#D0C0A0'],
  [ 30, 14, 7, 9,22, '#46607E', '#56708E'],
  [ 38, 22, 6, 6,14, '#888060', '#989070'],
  [ 30, 30, 9, 7, 9, '#C0785A', '#D0886A'],
  // ── Southern district ────────────────────────────────────────────────────
  [-24, 30,10, 8, 7, '#A8C490', '#B8D4A0'],
  [ -8, 30, 7, 7,16, '#5A4A7E', '#6A5A8E'],
  [  8, 30, 8, 6,13, '#B86848', '#C87858'],
  [ 24, 30, 7, 8,20, '#304858', '#405868'],
  // ── Wat / temple district (NW quadrant) ──────────────────────────────────
  [-30,-40,20,14, 5, '#F0EAD0', '#E4DEC4'],  // temple courtyard
  [-26,-38, 8, 8,22, '#D4A020', '#EAB830'],  // main prang  (gold spire)
  [-36,-38, 6, 6,14, '#C89820', '#DCA820'],  // side prang
  [-30,-44,14, 4, 6, '#EEE8C8', '#E0DAB8'],  // boundary wall
  [-20,-42, 6, 8, 8, '#F4EED8', '#E8E0C8'],  // temple hall
  // ── Modern CBD (NE quadrant) ─────────────────────────────────────────────
  [ 30,-38,12,12,40, '#2A3C58', '#384C68'],  // tallest skyscraper
  [ 42,-38, 8, 8,32, '#36507A', '#46608A'],
  [ 42,-26, 7, 7,24, '#3E5E82', '#4E6E92'],
  [ 30,-50,14, 8, 8, '#A0A8B0', '#B0B8C0'],  // CBD podium
  // ── Market / low-rise (SE of centre) ─────────────────────────────────────
  [ -8,-38, 8, 6, 5, '#C8A060', '#D8B070'],
  [  4,-38, 7, 5, 5, '#C09050', '#D0A060'],
  [ 14,-38, 6, 6, 6, '#B88840', '#C89850'],
  [-16,-46, 9, 7, 4, '#C8B888', '#D8C898'],
  [  0,-46, 8, 6, 5, '#C0B070', '#D0C080'],
  [ 14,-46, 7, 7, 6, '#B8A860', '#C8B870'],
] as const

// ── Trees: [x, z] ─────────────────────────────────────────────────────────────
const TREE_XZ = [
  // original park clusters
  [-4,5],[-5,8],[-8,5],[-7,9],[-9,8],[-5,6],
  [9,-9],[12,-13],[13,-10],[10,-13],
  [-14,-4],[-17,-8],[-15,-8],
  [4,3],[4,-3],[-4,3],[-4,-3],
  [10,3],[10,-3],[-10,3],[-10,-3],[16,3],[16,-3],
  // avenues along secondary roads
  [-28,-5],[-28,5],[-28,12],[-28,-12],
  [28,-5],[28,5],[28,12],[28,-12],
  [-5,-28],[-12,-28],[5,-28],[12,-28],
  [-5,28],[-12,28],[5,28],[12,28],
  // temple gardens
  [-24,-36],[-34,-36],[-24,-42],[-34,-42],[-20,-44],
  // canal bank (west)
  [-46,20],[-46,10],[-46,0],[-46,-10],[-46,-20],[-46,-30],
  // outer ring scattered
  [-40,0],[-40,18],[-40,-18],[40,0],[40,18],[40,-18],
  [0,-44],[0,44],[-44,28],[44,-28],
] as const

// ── Parks: [cx, cz, w, d] ─────────────────────────────────────────────────────
const PARKS = [
  [-7,  7,  9, 9],
  [11,-11,  7, 7],
  [-16, -6, 6, 6],
  [-30,  8, 12,10],
  [ 28, 24, 14,10],
  [-20,-34, 10, 8],
  [  0, 36, 20, 8],
  [-44,  0,  8,16],
] as const

// ── Survivor positions — offset to match TARGET_BX / TARGET_BZ ────────────────
const SURVIVOR_POSITIONS = [
  { x: TARGET_BX - 1.5, y: survY(2), z: TARGET_BZ + 1.0 },
  { x: TARGET_BX + 0.5, y: survY(3), z: TARGET_BZ - 0.5 },
  { x: TARGET_BX + 1.5, y: survY(4), z: TARGET_BZ - 1.0 },
  // building rooftops
  // { x: -10,  y: 31.0,  z:  -8  },  // ultra-slim skyscraper
  // { x:  16,  y: 25.0,  z:   14 },  // charcoal tower
  // { x:   8,  y: 23.0,  z:  -15 },  // cobalt slim
  // { x:  38,  y: 27.5,  z:  -14 },  // eastern dark tower
  // { x:  30,  y: 41.5,  z:  -38 },  // CBD tallest
  // { x: -26,  y: 23.0,  z:  -38 },  // golden prang top
  // // street level (will submerge as flood rises)
  // { x:   8,  y: 0.4,   z:    5 },
  // { x:  -7,  y: 0.4,   z:   -6 },
  // { x:   3,  y: 0.4,   z:   12 },
  // { x: -14,  y: 0.4,   z:   -2 },
  // { x:  18,  y: 0.4,   z:    8 },
  // { x:  -4,  y: 0.4,   z:  -14 },
  // { x:  25,  y: 0.4,   z:  -10 },
  // { x: -28,  y: 0.4,   z:   18 },
  // { x:  12,  y: 0.4,   z:  -30 },
  // { x: -18,  y: 0.4,   z:   26 },
  // // mid-level ledges
  // { x: -22,  y: 4.0,   z:    2 },
  // { x:  20,  y: 6.5,   z:    0 },
  // { x: -32,  y: 5.0,   z:    0 },
  // { x:  30,  y: 7.0,   z:   14 },
  // { x: -38,  y: 11.0,  z:  -14 },
]

const SURVIVOR_SENSOR_RANGE = 12.0
const LOS_SAMPLE_COUNT = 30

type WindowFace = 'north' | 'south' | 'west' | 'east'

interface SimWindowAperture {
  face: WindowFace
  axisCenter: number
  sillY: number
  width: number
  height: number
}

interface SimBuilding {
  id: number
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

const TARGET_BUILDING_WINDOWS: SimWindowAperture[] = TARGET_WINDOW_LAYOUT.map(({ floor, face, offset }) => ({
  face,
  axisCenter: face === 'north' || face === 'south' ? TARGET_BX + offset : TARGET_BZ + offset,
  sillY: (floor - 1) * FLOOR_H + TARGET_WINDOW_SILL,
  width: TARGET_WINDOW_WIDTH,
  height: TARGET_WINDOW_HEIGHT,
}))

const SIM_BUILDINGS: SimBuilding[] = [
  { id: 0, cx: TARGET_BX, cz: TARGET_BZ, w: FLOOR_W, d: FLOOR_D, h: total_h, windows: TARGET_BUILDING_WINDOWS },
  { id: 1, cx: OBS_X, cz: OBS_Z, w: OBS_W, d: OBS_D, h: OBS_H, windows: [] },
]

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

// ── Scene components ──────────────────────────────────────────────────────────

function Ground() {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
      <planeGeometry args={[span, span]} />
      <meshStandardMaterial color={C_GROUND} />
    </mesh>
  )
}

function Roads() {
  return (
    <>
      {/* Main E-W road (width 7) */}
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[span, 0.01, 7]} />
        <meshStandardMaterial color={C_ROAD} />
      </mesh>
      {/* Main N-S road (width 7) */}
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[7, 0.01, span]} />
        <meshStandardMaterial color={C_ROAD} />
      </mesh>
      {/* Secondary E-W roads */}
      {([-28, 28] as number[]).map(z => (
        <mesh key={`ew${z}`} position={[0, 0.02, z]}>
          <boxGeometry args={[span, 0.01, 4]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
      {/* Secondary N-S roads */}
      {([-28, 28] as number[]).map(x => (
        <mesh key={`ns${x}`} position={[x, 0.02, 0]}>
          <boxGeometry args={[4, 0.01, span]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
      {/* Tertiary roads */}
      {([-14, 14] as number[]).map(z => (
        <mesh key={`t-ew${z}`} position={[0, 0.02, z]}>
          <boxGeometry args={[span, 0.01, 3]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
      {([-14, 14] as number[]).map(x => (
        <mesh key={`t-ns${x}`} position={[x, 0.02, 0]}>
          <boxGeometry args={[3, 0.01, span]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
      {/* Centre lane markings */}
      <mesh position={[0, 0.03, 0]}>
        <boxGeometry args={[span, 0.01, 0.14]} />
        <meshStandardMaterial color={C_LINE} />
      </mesh>
      <mesh position={[0, 0.03, 0]}>
        <boxGeometry args={[0.14, 0.01, span]} />
        <meshStandardMaterial color={C_LINE} />
      </mesh>
    </>
  )
}

function Canal() {
  return (
    <mesh position={[-47, 0.06, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[6, span]} />
      <meshStandardMaterial color={C_CANAL} transparent opacity={0.9} depthWrite={false} />
    </mesh>
  )
}

function Parks() {
  return (
    <>
      {PARKS.map(([px, pz, pw, pd], i) => (
        <mesh key={i} position={[px, 0.02, pz]}>
          <boxGeometry args={[pw, 0.01, pd]} />
          <meshStandardMaterial color={C_PARK} />
        </mesh>
      ))}
    </>
  )
}

function GridOverlay() {
  return (
    <gridHelper
      args={[span, GRID_CELLS, C_GRID_MAJ, C_GRID_MIN]}
      position={[0, 0.01, 0]}
    />
  )
}

function Trees() {
  return (
    <>
      {TREE_XZ.map(([tx, tz], i) => (
        <group key={i}>
          <mesh position={[tx, 0.8, tz]}>
            <boxGeometry args={[0.18, 1.6, 0.18]} />
            <meshStandardMaterial color={C_TRUNK} />
          </mesh>
          <mesh position={[tx, 2.1, tz]}>
            <sphereGeometry args={[0.5, 8, 6]} />
            <meshStandardMaterial color={C_LEAF} />
          </mesh>
        </group>
      ))}
    </>
  )
}

function CityBuildings() {
  return (
    <>
      {CITY_BUILDINGS.map(([cx, cz, w, d, h, bodyColor, roofColor], i) => (
        <group key={i}>
          <mesh position={[cx, h / 2, cz]}>
            <boxGeometry args={[w, h, d]} />
            <meshStandardMaterial color={bodyColor} />
          </mesh>
          <mesh position={[cx, h + 0.08, cz]}>
            <boxGeometry args={[w, 0.16, d]} />
            <meshStandardMaterial color={roofColor} />
          </mesh>
          {h >= 14 && Array.from({ length: Math.floor(h / FLOOR_H) - 1 }, (_, fi) => (
            <mesh key={fi} position={[cx, (fi + 1) * FLOOR_H, cz]}>
              <boxGeometry args={[w * 0.92, 0.28, d * 0.92]} />
              <meshStandardMaterial color={C_GLASSBAND} transparent opacity={0.45} depthWrite={false} />
            </mesh>
          ))}
        </group>
      ))}
    </>
  )
}

function TargetBuilding({ transparentWalls }: { transparentWalls: boolean }) {
  const hw = FLOOR_W / 2
  const hd = FLOOR_D / 2
  const windowYCenter = (floor: number) =>
    (floor - 1) * FLOOR_H + TARGET_WINDOW_SILL + TARGET_WINDOW_HEIGHT / 2

  const wallPanels = [
    { pos: [TARGET_BX,      total_h / 2, TARGET_BZ - hd] as [number, number, number], size: [FLOOR_W, total_h, 0.14] as [number, number, number] },
    { pos: [TARGET_BX,      total_h / 2, TARGET_BZ + hd] as [number, number, number], size: [FLOOR_W, total_h, 0.14] as [number, number, number] },
    { pos: [TARGET_BX - hw, total_h / 2, TARGET_BZ]      as [number, number, number], size: [0.14, total_h, FLOOR_D] as [number, number, number] },
    { pos: [TARGET_BX + hw, total_h / 2, TARGET_BZ]      as [number, number, number], size: [0.14, total_h, FLOOR_D] as [number, number, number] },
  ]

  const windowPanels = TARGET_WINDOW_LAYOUT.map(({ floor, face, offset }) => {
    const y = windowYCenter(floor)
    if (face === 'north') {
      return {
        key: `${face}-${floor}`,
        pos: [TARGET_BX + offset, y, TARGET_BZ - hd - 0.07] as [number, number, number],
        size: [TARGET_WINDOW_WIDTH, TARGET_WINDOW_HEIGHT, 0.10] as [number, number, number],
      }
    }
    if (face === 'south') {
      return {
        key: `${face}-${floor}`,
        pos: [TARGET_BX + offset, y, TARGET_BZ + hd + 0.07] as [number, number, number],
        size: [TARGET_WINDOW_WIDTH, TARGET_WINDOW_HEIGHT, 0.10] as [number, number, number],
      }
    }
    if (face === 'west') {
      return {
        key: `${face}-${floor}`,
        pos: [TARGET_BX - hw - 0.07, y, TARGET_BZ + offset] as [number, number, number],
        size: [0.10, TARGET_WINDOW_HEIGHT, TARGET_WINDOW_WIDTH] as [number, number, number],
      }
    }
    return {
      key: `${face}-${floor}`,
      pos: [TARGET_BX + hw + 0.07, y, TARGET_BZ + offset] as [number, number, number],
      size: [0.10, TARGET_WINDOW_HEIGHT, TARGET_WINDOW_WIDTH] as [number, number, number],
    }
  })

  return (
    <>
      {Array.from({ length: NUM_FLOORS + 1 }, (_, n) => (
        <mesh key={n} position={[TARGET_BX, n * FLOOR_H, TARGET_BZ]}>
          <boxGeometry args={[FLOOR_W, FLOOR_T, FLOOR_D]} />
          <meshStandardMaterial color={C_SLAB} />
        </mesh>
      ))}
      {wallPanels.map(({ pos, size }, i) => (
        <mesh key={i} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial
            color={transparentWalls ? '#7d9ab1' : '#5f6b77'}
            transparent={transparentWalls}
            opacity={transparentWalls ? 0.22 : 1}
            depthWrite={!transparentWalls}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
      {windowPanels.map(({ key, pos, size }) => (
        <mesh key={key} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial color={C_GLASS} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </>
  )
}

function ObstacleBuilding() {
  return (
    <mesh position={[OBS_X, OBS_H / 2, OBS_Z]}>
      <boxGeometry args={[OBS_W, OBS_H, OBS_D]} />
      <meshStandardMaterial color="#5a4a3a" />
    </mesh>
  )
}

// Survivors pulse faster and turn orange when submerged by the flood
function Survivors({ floodY }: { floodY: number }) {
  const refs = useRef<(THREE.Mesh | null)[]>(SURVIVOR_POSITIONS.map(() => null))

  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    refs.current.forEach((mesh, i) => {
      if (!mesh) return
      const pos = SURVIVOR_POSITIONS[i]
      const submerged = pos.y < floodY - 0.2
      const speed = submerged ? 6 : 3
      const pulse = 1 + Math.sin(t * speed + i * 0.9) * 0.18
      mesh.scale.setScalar(pulse)
      const mat = mesh.material as THREE.MeshStandardMaterial
      if (submerged) {
        mat.color.setHex(0xff8800)
        mat.emissive.setHex(0xcc4400)
        mat.emissiveIntensity = 0.7
      } else {
        mat.color.setHex(0xff2222)
        mat.emissive.setHex(0xff0000)
        mat.emissiveIntensity = 0.45
      }
    })
  })

  return (
    <>
      {SURVIVOR_POSITIONS.map((pos, i) => (
        <mesh
          key={i}
          ref={el => { refs.current[i] = el }}
          position={[pos.x, pos.y, pos.z]}
        >
          <sphereGeometry args={[0.32, 10, 7]} />
          <meshStandardMaterial color="#ff2222" emissive="#ff0000" emissiveIntensity={0.45} />
        </mesh>
      ))}
    </>
  )
}

function SurvivorScanRays({
  enabled,
  dronePos,
  survivors,
}: {
  enabled: boolean
  dronePos: THREE.Vector3
  survivors: SurvivorPoint[]
}) {
  if (!enabled || survivors.length === 0) return null
  return (
    <>
      {survivors.map((survivor, index) => (
        <Line
          key={`scan-ray-${index}-${survivor.x}-${survivor.y}-${survivor.z}`}
          points={[
            [dronePos.x, dronePos.y, dronePos.z],
            [survivor.x, survivor.y, survivor.z],
          ]}
          color="#ff4466"
          lineWidth={1.2}
          transparent
          opacity={0.9}
          depthTest={false}
          depthWrite={false}
        />
      ))}
    </>
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
function GroundProbe({ onMove, onDoubleClick, onClick }: {
  onMove: (v: THREE.Vector3 | null) => void
  onDoubleClick: (v: THREE.Vector3) => void
  onClick?: (v: THREE.Vector3) => void
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
      <planeGeometry args={[span, span]} />
      <meshBasicMaterial transparent opacity={0} depthWrite={false} />
    </mesh>
  )
}

// Yellow crosshair that follows the cursor on the ground plane
function GroundCursor({ point, color = '#ffe060' }: { point: THREE.Vector3 | null; color?: string }) {
  if (!point) return null
  return (
    <group position={[point.x, 0.07, point.z]}>
      {/* E-W arm */}
      <mesh>
        <boxGeometry args={[4, 0.05, 0.09]} />
        <meshBasicMaterial color={color} />
      </mesh>
      {/* N-S arm */}
      <mesh>
        <boxGeometry args={[0.09, 0.05, 4]} />
        <meshBasicMaterial color={color} />
      </mesh>
      {/* Centre pip */}
      <mesh>
        <cylinderGeometry args={[0.28, 0.28, 0.05, 8]} />
        <meshBasicMaterial color={color} />
      </mesh>
    </group>
  )
}

// ── Area selection rectangle (rendered on ground plane) ──────────────────────

function AreaSelectionRect({ corner1, corner2 }: {
  corner1: THREE.Vector3
  corner2: THREE.Vector3
}) {
  const cx = (corner1.x + corner2.x) / 2
  const cz = (corner1.z + corner2.z) / 2
  const w = Math.abs(corner2.x - corner1.x)
  const d = Math.abs(corner2.z - corner1.z)

  if (w < 0.1 || d < 0.1) return null

  return (
    <group position={[cx, 0.1, cz]}>
      {/* Filled rectangle */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[w, d]} />
        <meshBasicMaterial color="#ff6088" transparent opacity={0.08} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      {/* Border */}
      <Line
        points={[
          [corner1.x - cx, 0, corner1.z - cz],
          [corner2.x - cx, 0, corner1.z - cz],
          [corner2.x - cx, 0, corner2.z - cz],
          [corner1.x - cx, 0, corner2.z - cz],
          [corner1.x - cx, 0, corner1.z - cz],
        ]}
        color="#ff6088"
        lineWidth={1.5}
      />
      {/* Corner markers */}
      {[corner1, corner2, new THREE.Vector3(corner1.x, 0, corner2.z), new THREE.Vector3(corner2.x, 0, corner1.z)].map((c, i) => (
        <mesh key={i} position={[c.x - cx, 0.05, c.z - cz]}>
          <cylinderGeometry args={[0.3, 0.3, 0.06, 8]} />
          <meshBasicMaterial color="#ff6088" />
        </mesh>
      ))}
    </group>
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

function DroneStatusPanel({ drones }: { drones: DroneMap }) {
  const entries = Object.values(drones)
  if (entries.length === 0) return null

  return (
    <div style={{
      position: 'absolute',
      top: 16,
      left: 16,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      pointerEvents: 'none',
    }}>
      {entries.map(d => {
        const batCol = _batteryColor(d.battery)
        const sCol   = _statusColor(d.status)
        const hasEnv = d.nearby_obstacles !== undefined
        return (
          <div key={d.asset_id} style={{
            background: 'rgba(0,0,0,0.72)',
            border: `1px solid ${sCol}55`,
            borderLeft: `3px solid ${sCol}`,
            borderRadius: 6,
            padding: '8px 12px',
            fontFamily: 'Courier New, monospace',
            fontSize: 11,
            lineHeight: 1.7,
            minWidth: 210,
          }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
              <span style={{ color: '#dde', fontWeight: 'bold', letterSpacing: 0.5 }}>{d.asset_id}</span>
              <span style={{ color: sCol, fontSize: 10 }}>● {d.status}</span>
            </div>
            {/* Battery bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
              <span style={{ color: '#556', fontSize: 10 }}>BAT</span>
              <div style={{ flex: 1, background: '#181820', height: 5, borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${d.battery}%`, height: '100%', background: batCol, transition: 'width 0.4s' }} />
              </div>
              <span style={{ color: batCol, width: 34, textAlign: 'right', fontSize: 10.5 }}>{d.battery}%</span>
            </div>
            {/* Coordinates */}
            <div style={{ color: '#5580a0', fontSize: 10.5, letterSpacing: 0.3, marginBottom: hasEnv ? 5 : 0 }}>
              X&nbsp;<span style={{ color: '#aabfd0' }}>{d.x.toFixed(1)}</span>
              &nbsp;&nbsp;Y&nbsp;<span style={{ color: '#aabfd0' }}>{d.y.toFixed(1)}</span>
              &nbsp;&nbsp;Z&nbsp;<span style={{ color: '#aabfd0' }}>{d.z.toFixed(1)}</span>
            </div>
            {/* Environment awareness */}
            {hasEnv && (
              <div style={{ borderTop: '1px solid #223', paddingTop: 4, fontSize: 10, color: '#778' }}>
                <div>
                  <span style={{ color: '#446' }}>AGL&nbsp;</span>
                  <span style={{ color: '#99b' }}>{(d.altitude_agl ?? 0).toFixed(1)}m</span>
                  {d.over_flood && <span style={{ color: '#4af', marginLeft: 8 }}>FLOOD</span>}
                </div>
                <div>
                  <span style={{ color: '#446' }}>OBST&nbsp;</span>
                  <span style={{ color: (d.nearby_obstacles ?? 0) > 0 ? '#f80' : '#4a4' }}>
                    {d.nearby_obstacles ?? 0}
                  </span>
                  {(d.nearest_obstacle_dist ?? 999) < 10 && (
                    <span style={{ color: '#f60', marginLeft: 4 }}>
                      ({(d.nearest_obstacle_dist ?? 0).toFixed(1)}m)
                    </span>
                  )}
                </div>
              </div>
            )}
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
      top: 16,
      left: '50%',
      transform: 'translateX(-50%)',
      background: copied ? 'rgba(40,80,40,0.92)' : 'rgba(0,0,0,0.80)',
      border: `1px solid ${copied ? '#44ff8888' : '#ffe06055'}`,
      borderRadius: 5,
      padding: '5px 18px',
      color: copied ? '#88ff88' : '#ffe060',
      fontFamily: 'Courier New, monospace',
      fontSize: 12,
      letterSpacing: 1,
      pointerEvents: 'none',
      display: 'flex',
      gap: 20,
      whiteSpace: 'nowrap',
      zIndex: 10,
      transition: 'background 0.15s, color 0.15s, border 0.15s',
    }}>
      {copied
        ? <span>✓ copied to clipboard</span>
        : <>
            <span>X&nbsp;<span style={{ color: '#fff' }}>{point.x.toFixed(1)}</span></span>
            <span>Y&nbsp;<span style={{ color: '#fff' }}>{point.y.toFixed(1)}</span></span>
            <span>Z&nbsp;<span style={{ color: '#fff' }}>{point.z.toFixed(1)}</span></span>
            <span style={{ color: '#888', fontSize: 10 }}>double-click to copy</span>
          </>
      }
    </div>
  )
}

function CompassLabels() {
  const style = (top?: string, bottom?: string, left?: string, right?: string): React.CSSProperties => ({
    position: 'absolute',
    top, bottom, left, right,
    transform: top === '50%' || bottom === '50%' ? 'translateY(-50%)' : 'translateX(-50%)',
    color: 'rgba(180,200,255,0.55)',
    fontFamily: 'Courier New, monospace',
    fontSize: 11,
    letterSpacing: 2,
    pointerEvents: 'none',
    userSelect: 'none',
    zIndex: 5,
  })
  return (
    <>
      <div style={style('18px', undefined, '50%', undefined)}>N</div>
      <div style={style(undefined, '18px', '50%', undefined)}>S</div>
      <div style={{ ...style('50%', undefined, undefined, '18px'), transform: 'translateY(-50%)' }}>W</div>
      <div style={{ ...style('50%', undefined, undefined, undefined), right: 18, transform: 'translateY(-50%)' }}>E</div>
    </>
  )
}

// ── Drone (telemetry-driven position with smooth lerp) ────────────────────────

interface DroneProps {
  targetPos: THREE.Vector3
  status: string
  nearbyObstacles?: number
  nearestObstacleDist?: number
  survivorsInRange?: number
}

function DroneMesh({ targetPos, status, nearbyObstacles = 0, nearestObstacleDist = 999, survivorsInRange = 0 }: DroneProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const coneRef = useRef<THREE.Mesh>(null)
  const lerpPos = useRef(DRONE_START.clone())

  // FOV cone: points downward from drone, color encodes situation
  const coneColor = useMemo(() => {
    if (status === 'BLOCKED') return 0xff2200
    if (nearestObstacleDist < 5) return 0xff6600
    if (nearbyObstacles > 0) return 0xffaa00
    if (survivorsInRange > 0) return 0xff4444
    return 0x00ff88
  }, [status, nearbyObstacles, nearestObstacleDist, survivorsInRange])

  useFrame((_, delta) => {
    if (!meshRef.current) return
    lerpPos.current.lerp(targetPos, Math.min(delta * 4, 1))
    meshRef.current.position.copy(lerpPos.current)

    if (coneRef.current) {
      coneRef.current.position.copy(lerpPos.current)
      // cone hangs below drone
      coneRef.current.position.y -= 0.3
      const mat = coneRef.current.material as THREE.MeshStandardMaterial
      mat.color.setHex(coneColor)
    }

    const mat = meshRef.current.material as THREE.MeshStandardMaterial
    if (status === 'BLOCKED') {
      mat.color.setHex(0xff2200)
      mat.emissive.setHex(0x880000)
    } else if (status === 'MOVING') {
      mat.color.setHex(0x00ff88)
      mat.emissive.setHex(0x00aa44)
    } else if (status === 'SCANNING') {
      mat.color.setHex(0xffaa00)
      mat.emissive.setHex(0xaa6600)
    } else {
      mat.color.setHex(0x00ffff)
      mat.emissive.setHex(0x00aaaa)
    }
  })

  return (
    <>
      <mesh ref={meshRef} position={DRONE_START.toArray()}>
        <boxGeometry args={[0.6, 0.6, 0.6]} />
        <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} />
      </mesh>
      {/* Downward-facing FOV cone */}
      <mesh ref={coneRef} position={DRONE_START.toArray()} rotation={[Math.PI, 0, 0]}>
        <coneGeometry args={[8, 12, 16, 1, true]} />
        <meshStandardMaterial
          color="#00ff88"
          transparent
          opacity={0.08}
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

function MissionLog({ lines }: { lines: string[] }) {
  return (
    <div style={{
      position: 'absolute',
      bottom: 20,
      left: 20,
      background: 'rgba(0,0,0,0.65)',
      border: '1px solid #334',
      borderRadius: 6,
      padding: '10px 14px',
      color: '#9cf',
      fontSize: 12,
      fontFamily: 'Courier New, monospace',
      lineHeight: 1.6,
      maxWidth: 420,
      pointerEvents: 'none',
    }}>
      {lines.map((l, i) => (
        <div key={i} style={{ color: l.includes('confirmed') ? '#4f4' : '#9cf' }}>{l}</div>
      ))}
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
}

function Controls({
  followBeacon,
  onToggleFollow,
  transparentWalls,
  onToggleWalls,
  scanRaysEnabled,
  onToggleScanRays,
}: ControlsProps) {
  const submerged = SURVIVOR_POSITIONS.filter(p => p.y < FLOOD_LEVEL - 0.2).length

  return (
    <div style={{
      position: 'absolute',
      top: 16,
      right: 16,
      background: 'rgba(0,0,0,0.60)',
      border: '1px solid #334',
      borderRadius: 6,
      padding: '10px 14px',
      color: '#667',
      fontSize: 11,
      fontFamily: 'Courier New, monospace',
      lineHeight: 1.8,
      pointerEvents: 'auto',
      minWidth: 200,
    }}>
      <div style={{ color: '#99b', marginBottom: 4, letterSpacing: 1 }}>PROJECT BEACON — THAILAND TOWN SAR</div>
      <div>Left drag  : orbit</div>
      <div>Right drag : pan</div>
      <div>Scroll     : zoom</div>
      <div>F key      : toggle follow beacon</div>
      <div style={{ marginTop: 6, color: '#4cf' }}>Enter      : send command</div>
      <button
        onClick={onToggleFollow}
        style={{
          marginTop: 8,
          width: '100%',
          border: '1px solid rgba(90,140,255,0.35)',
          borderRadius: 4,
          background: followBeacon ? 'rgba(40,130,255,0.25)' : 'rgba(30,40,60,0.6)',
          color: followBeacon ? '#9fd0ff' : '#7f8fa8',
          padding: '5px 8px',
          cursor: 'pointer',
          fontSize: 11,
          fontFamily: 'Courier New, monospace',
          textAlign: 'left',
        }}
      >
        {followBeacon ? 'FOLLOW MODE: ON' : 'FOLLOW MODE: OFF'}
      </button>
      <button
        onClick={onToggleWalls}
        style={{
          marginTop: 6,
          width: '100%',
          border: '1px solid rgba(120,190,255,0.35)',
          borderRadius: 4,
          background: transparentWalls ? 'rgba(60,170,255,0.24)' : 'rgba(30,40,60,0.6)',
          color: transparentWalls ? '#b5e6ff' : '#7f8fa8',
          padding: '5px 8px',
          cursor: 'pointer',
          fontSize: 11,
          fontFamily: 'Courier New, monospace',
          textAlign: 'left',
        }}
      >
        {transparentWalls ? 'WALLS: TRANSPARENT' : 'WALLS: SOLID'}
      </button>
      <button
        onClick={onToggleScanRays}
        style={{
          marginTop: 6,
          width: '100%',
          border: '1px solid rgba(255,120,150,0.45)',
          borderRadius: 4,
          background: scanRaysEnabled ? 'rgba(255,70,110,0.20)' : 'rgba(30,40,60,0.6)',
          color: scanRaysEnabled ? '#ff9fb3' : '#7f8fa8',
          padding: '5px 8px',
          cursor: 'pointer',
          fontSize: 11,
          fontFamily: 'Courier New, monospace',
          textAlign: 'left',
        }}
      >
        {scanRaysEnabled ? 'SCAN RAYS: ON' : 'SCAN RAYS: OFF'}
      </button>
      <div style={{ marginTop: 8, borderTop: '1px solid #334', paddingTop: 6 }}>
        <div style={{ color: '#f84' }}>FLOOD: +{FLOOD_LEVEL.toFixed(1)}m above ground</div>
        <div style={{ color: '#f44', marginTop: 3 }}>
          Victims submerged: {submerged} / {SURVIVOR_POSITIONS.length}
        </div>
      </div>
    </div>
  )
}

// ── Main scene ────────────────────────────────────────────────────────────────

const ASSET_ID = 'BEACON-01'
const WS_URL   = 'ws://localhost:8000/ws/telemetry'

export default function SARScene() {
  const [log, setLog]       = useState<string[]>(['Connecting to backend...'])
  const [uplinked, setUplinked] = useState(false)
  const [hoverPt, setHoverPt]     = useState<THREE.Vector3 | null>(null)
  const [copied, setCopied]       = useState(false)
  const [followBeacon, setFollowBeacon] = useState(false)
  const [transparentWalls, setTransparentWalls] = useState(false)
  const [scanRaysEnabled, setScanRaysEnabled] = useState(true)
  const [areaSelectMode, setAreaSelectMode] = useState(false)
  const [areaCorner1, setAreaCorner1] = useState<THREE.Vector3 | null>(null)
  const [areaCorner2, setAreaCorner2] = useState<THREE.Vector3 | null>(null)
  const copiedTimer               = useRef<ReturnType<typeof setTimeout> | null>(null)
  const orbitRef                  = useRef<OrbitControlsImpl | null>(null)

  const handleGroundDoubleClick = useCallback((pt: THREE.Vector3) => {
    if (areaSelectMode) return
    const text = `${pt.x.toFixed(1)}, ${pt.y.toFixed(1)}, ${pt.z.toFixed(1)}`
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    if (copiedTimer.current) clearTimeout(copiedTimer.current)
    copiedTimer.current = setTimeout(() => setCopied(false), 1500)
  }, [areaSelectMode])

  const handleGroundClick = useCallback((pt: THREE.Vector3) => {
    if (!areaSelectMode) return
    if (!areaCorner1) {
      setAreaCorner1(pt.clone())
    } else {
      setAreaCorner2(pt.clone())
      setAreaSelectMode(false)
    }
  }, [areaSelectMode, areaCorner1])

  const areaSelection = useMemo(() => {
    if (!areaCorner1 || !areaCorner2) return null
    return {
      x1: Math.min(areaCorner1.x, areaCorner2.x),
      z1: Math.min(areaCorner1.z, areaCorner2.z),
      x2: Math.max(areaCorner1.x, areaCorner2.x),
      z2: Math.max(areaCorner1.z, areaCorner2.z),
    }
  }, [areaCorner1, areaCorner2])
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

  const toggleAreaSelect = useCallback(() => {
    setAreaSelectMode(prev => {
      if (prev) {
        setAreaCorner1(null)
        setAreaCorner2(null)
        addLog('⬚ Area selection cancelled')
        return false
      }
      setAreaCorner1(null)
      setAreaCorner2(null)
      addLog('⬚ Area selection — click two corners on the map')
      return true
    })
  }, [addLog])

  const cancelArea = useCallback(() => {
    setAreaSelectMode(false)
    setAreaCorner1(null)
    setAreaCorner2(null)
  }, [])

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

  // Auto-uplink on mount
  useEffect(() => {
    let mounted = true
    const init = async () => {
      const ok = await healthCheck()
      if (!ok || !mounted) {
        addLog('⚠ Backend offline — start FastAPI sidecar')
        return
      }
      try {
        await uplink(ASSET_ID)
        if (mounted) {
          setUplinked(true)
          addLog(`✓ ${ASSET_ID} uplinked — agent ready`)
        }
      } catch {
        if (mounted) {
          try {
            const fleet = await getFleet()
            const asset = fleet.fleet.find(item => item.asset_id === ASSET_ID)
            if (asset?.uplinked) {
              setUplinked(true)
              addLog(`✓ ${ASSET_ID} registered with commander`)
            } else {
              addLog(`⚠ ${ASSET_ID} not discoverable yet — start the drone container first`)
            }
          } catch {
            addLog(`⚠ Failed to verify ${ASSET_ID} status`)
          }
        }
      }
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
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || event.key.toLowerCase() !== 'f') return

      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return

      event.preventDefault()
      toggleFollowBeacon()
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [toggleFollowBeacon])

  // Escape cancels area selection
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && (areaSelectMode || areaCorner1 || areaCorner2)) {
        cancelArea()
        addLog('⬚ Area selection cancelled')
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [areaSelectMode, areaCorner1, areaCorner2, cancelArea, addLog])

  const abortRef = useRef<AbortController | null>(null)

  const handleCommand = useCallback(async (
    prompt: string,
    onEvent: (e: AgentStreamEvent) => void,
  ): Promise<void> => {
    const ac = new AbortController()
    abortRef.current = ac
    addLog(`⬆ ${prompt}`)
    try {
      for await (const event of streamCommand(ASSET_ID, prompt, ac.signal)) {
        onEvent(event)
        if (event.type === 'done') addLog('✓ Agent responded')
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') {
        addLog('⚠ Command aborted')
      } else {
        throw e
      }
    }
  }, [addLog])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const scannedSurvivors = useMemo(
    () => scannedSurvivorsFromDrone(dronePos),
    [dronePos.x, dronePos.y, dronePos.z],
  )

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', background: '#0d0d17', cursor: areaSelectMode ? 'crosshair' : 'default' }}>
      <Canvas shadows>
        <fog attach="fog" args={['#0d0d1f', 90, 260]} />
        <PerspectiveCamera makeDefault position={CAM_POS} fov={60} near={0.1} far={1000} />
        <OrbitControls
          ref={orbitRef}
          enabled={!followBeacon && !areaSelectMode}
          enableDamping
          dampingFactor={0.08}
          minDistance={5}
          maxDistance={400}
          target={[0, 5, 0]}
        />
        <FollowBeaconCamera enabled={followBeacon} targetPos={dronePos} controlsRef={orbitRef} />

        {/* Lighting */}
        <ambientLight intensity={0.55} />
        <directionalLight position={[50, 100, 40]} intensity={1.2} castShadow />
        <hemisphereLight args={['#1a1a2e', '#0d0d0d', 0.4]} />

        {/* Scene */}
        <Ground />
        <GridOverlay />
        <ObstacleBuilding />
        <TargetBuilding transparentWalls={transparentWalls} />
        <Survivors floodY={FLOOD_LEVEL} />
        <GroundProbe onMove={setHoverPt} onDoubleClick={handleGroundDoubleClick} onClick={areaSelectMode ? handleGroundClick : undefined} />
        <GroundCursor point={hoverPt} color={areaSelectMode ? '#ff6088' : '#ffe060'} />
        {/* Area selection preview (first corner placed, hovering for second) */}
        {areaSelectMode && areaCorner1 && hoverPt && (
          <AreaSelectionRect corner1={areaCorner1} corner2={hoverPt} />
        )}
        {/* Confirmed area selection */}
        {areaCorner1 && areaCorner2 && (
          <AreaSelectionRect corner1={areaCorner1} corner2={areaCorner2} />
        )}
        <DroneMesh
          targetPos={dronePos}
          status={droneStatus}
          nearbyObstacles={telemetry?.nearby_obstacles}
          nearestObstacleDist={telemetry?.nearest_obstacle_dist}
          survivorsInRange={telemetry?.survivors_in_range}
        />
        <SurvivorScanRays
          enabled={scanRaysEnabled}
          dronePos={dronePos}
          survivors={scannedSurvivors}
        />
      </Canvas>

      <DroneStatusPanel drones={drones} />
      <CoordOverlay point={hoverPt} copied={copied} />
      <CompassLabels />
      <MissionLog lines={log} />
      <Controls
        followBeacon={followBeacon}
        onToggleFollow={toggleFollowBeacon}
        transparentWalls={transparentWalls}
        onToggleWalls={toggleWallTransparency}
        scanRaysEnabled={scanRaysEnabled}
        onToggleScanRays={toggleScanRays}
      />
      <CommandPanel
        assetId={ASSET_ID}
        connected={connected}
        uplinked={uplinked}
        battery={battery}
        onCommand={handleCommand}
        onStop={handleStop}
        areaSelectMode={areaSelectMode}
        onToggleAreaSelect={toggleAreaSelect}
        areaSelection={areaSelection}
        onScanArea={cancelArea}
        onCancelArea={cancelArea}
      />
    </div>
  )
}
