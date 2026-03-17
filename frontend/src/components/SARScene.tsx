'use client'

import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Line, OrbitControls, PerspectiveCamera, Text } from '@react-three/drei'
import { useRef, useState, useEffect, useMemo, useCallback, type RefObject, type MutableRefObject } from 'react'
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

// Balcony building — 3-story residential with exterior balcony on floor 3 (south face)
const BAL_X = 20
const BAL_Z = -20
const BAL_W = 6
const BAL_D = 6
const BAL_H = 9   // 3 floors × 3m
const BAL_BALCONY_FLOOR = 3
const BAL_BALCONY_DEPTH = 2.0
const BAL_BALCONY_WIDTH = 3.0

// Twin shophouse block — 2 adjoined 3-story shophouses with shared party wall
const SHOP_X = 12
const SHOP_Z = -27
const SHOP_W = 10  // 5m per unit
const SHOP_D = 8
const SHOP_H = 9   // 3 floors × 3m
const SHOP_WINDOW_LAYOUT = [
  { floor: 2, face: 'south' as const, offset: -2.5 },
  { floor: 2, face: 'south' as const, offset:  2.5 },
  { floor: 3, face: 'south' as const, offset: -2.5 },
  { floor: 3, face: 'south' as const, offset:  2.5 },
] as const
const SHOP_WINDOW_WIDTH = 1.6
const SHOP_WINDOW_HEIGHT = 1.4
const SHOP_WINDOW_SILL = 0.5

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
  // [16,-27] removed — replaced by functional ShophouseBlock
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
  // Balcony building — survivor on exterior balcony, floor 3 (outside AABB, direct LOS)
  { x: BAL_X, y: survY(BAL_BALCONY_FLOOR), z: BAL_Z + BAL_D / 2 + BAL_BALCONY_DEPTH / 2 },
  // Twin shophouse — Shop A floor 2, Shop B floor 3 (inside, visible through south windows)
  { x: SHOP_X - 2.5, y: survY(2), z: SHOP_Z },
  { x: SHOP_X + 2.5, y: survY(3), z: SHOP_Z },
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

const SHOPHOUSE_WINDOWS: SimWindowAperture[] = SHOP_WINDOW_LAYOUT.map(({ floor, face, offset }) => {
  const f = face as WindowFace
  return {
    face: f,
    axisCenter: f === 'north' || f === 'south' ? SHOP_X + offset : SHOP_Z + offset,
    sillY: (floor - 1) * FLOOR_H + SHOP_WINDOW_SILL,
    width: SHOP_WINDOW_WIDTH,
    height: SHOP_WINDOW_HEIGHT,
  }
})

const SIM_BUILDINGS: SimBuilding[] = [
  { id: 0, cx: TARGET_BX, cz: TARGET_BZ, w: FLOOR_W, d: FLOOR_D, h: total_h, windows: TARGET_BUILDING_WINDOWS },
  { id: 1, cx: OBS_X, cz: OBS_Z, w: OBS_W, d: OBS_D, h: OBS_H, windows: [] },
  { id: 2, cx: BAL_X, cz: BAL_Z, w: BAL_W, d: BAL_D, h: BAL_H, windows: [] },
  { id: 3, cx: SHOP_X, cz: SHOP_Z, w: SHOP_W, d: SHOP_D, h: SHOP_H, windows: SHOPHOUSE_WINDOWS },
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

// Compute an exterior approach position for a survivor inside a building.
// Aligns with the nearest window so the supply throw passes through it.
const APPROACH_OFFSET = 4.0

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
      // Window world position on the wall
      let wx: number, wz: number
      if (w.face === 'north')      { wx = w.axisCenter; wz = bounds.minZ }
      else if (w.face === 'south') { wx = w.axisCenter; wz = bounds.maxZ }
      else if (w.face === 'west')  { wx = bounds.minX;  wz = w.axisCenter }
      else                         { wx = bounds.maxX;  wz = w.axisCenter }

      const xzDist = Math.sqrt((survivor.x - wx) ** 2 + (survivor.z - wz) ** 2)
      const totalDist = yDist * 2 + xzDist  // weight Y more to prefer same floor
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

function BalconyBuilding({ transparentWalls }: { transparentWalls: boolean }) {
  const hw = BAL_W / 2
  const hd = BAL_D / 2
  const balconyY = (BAL_BALCONY_FLOOR - 1) * FLOOR_H
  const numFloors = Math.round(BAL_H / FLOOR_H)

  const wallPanels = [
    { pos: [BAL_X, BAL_H / 2, BAL_Z - hd] as [number, number, number], size: [BAL_W, BAL_H, 0.14] as [number, number, number] },
    { pos: [BAL_X, BAL_H / 2, BAL_Z + hd] as [number, number, number], size: [BAL_W, BAL_H, 0.14] as [number, number, number] },
    { pos: [BAL_X - hw, BAL_H / 2, BAL_Z] as [number, number, number], size: [0.14, BAL_H, BAL_D] as [number, number, number] },
    { pos: [BAL_X + hw, BAL_H / 2, BAL_Z] as [number, number, number], size: [0.14, BAL_H, BAL_D] as [number, number, number] },
  ]

  return (
    <>
      {/* Floor slabs */}
      {Array.from({ length: numFloors + 1 }, (_, n) => (
        <mesh key={n} position={[BAL_X, n * FLOOR_H, BAL_Z]}>
          <boxGeometry args={[BAL_W, FLOOR_T, BAL_D]} />
          <meshStandardMaterial color={C_SLAB} />
        </mesh>
      ))}
      {/* Walls */}
      {wallPanels.map(({ pos, size }, i) => (
        <mesh key={i} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial
            color={transparentWalls ? '#9ab1a8' : '#7a8a72'}
            transparent={transparentWalls}
            opacity={transparentWalls ? 0.22 : 1}
            depthWrite={!transparentWalls}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
      {/* Balcony platform — protrudes from south face on floor 3 */}
      <mesh position={[BAL_X, balconyY, BAL_Z + hd + BAL_BALCONY_DEPTH / 2]}>
        <boxGeometry args={[BAL_BALCONY_WIDTH, FLOOR_T, BAL_BALCONY_DEPTH]} />
        <meshStandardMaterial color={C_SLAB} />
      </mesh>
      {/* Balcony railing — front */}
      <mesh position={[BAL_X, balconyY + 0.5, BAL_Z + hd + BAL_BALCONY_DEPTH]}>
        <boxGeometry args={[BAL_BALCONY_WIDTH, 1.0, 0.08]} />
        <meshStandardMaterial color="#5a6a5a" />
      </mesh>
      {/* Balcony railing — sides */}
      <mesh position={[BAL_X - BAL_BALCONY_WIDTH / 2, balconyY + 0.5, BAL_Z + hd + BAL_BALCONY_DEPTH / 2]}>
        <boxGeometry args={[0.08, 1.0, BAL_BALCONY_DEPTH]} />
        <meshStandardMaterial color="#5a6a5a" />
      </mesh>
      <mesh position={[BAL_X + BAL_BALCONY_WIDTH / 2, balconyY + 0.5, BAL_Z + hd + BAL_BALCONY_DEPTH / 2]}>
        <boxGeometry args={[0.08, 1.0, BAL_BALCONY_DEPTH]} />
        <meshStandardMaterial color="#5a6a5a" />
      </mesh>
    </>
  )
}

function ShophouseBlock({ transparentWalls }: { transparentWalls: boolean }) {
  const hw = SHOP_W / 2
  const hd = SHOP_D / 2
  const numFloors = Math.round(SHOP_H / FLOOR_H)
  const windowYCenter = (floor: number) =>
    (floor - 1) * FLOOR_H + SHOP_WINDOW_SILL + SHOP_WINDOW_HEIGHT / 2

  const wallPanels = [
    { pos: [SHOP_X, SHOP_H / 2, SHOP_Z - hd] as [number, number, number], size: [SHOP_W, SHOP_H, 0.14] as [number, number, number] },
    { pos: [SHOP_X, SHOP_H / 2, SHOP_Z + hd] as [number, number, number], size: [SHOP_W, SHOP_H, 0.14] as [number, number, number] },
    { pos: [SHOP_X - hw, SHOP_H / 2, SHOP_Z] as [number, number, number], size: [0.14, SHOP_H, SHOP_D] as [number, number, number] },
    { pos: [SHOP_X + hw, SHOP_H / 2, SHOP_Z] as [number, number, number], size: [0.14, SHOP_H, SHOP_D] as [number, number, number] },
  ]

  return (
    <>
      {/* Floor slabs */}
      {Array.from({ length: numFloors + 1 }, (_, n) => (
        <mesh key={n} position={[SHOP_X, n * FLOOR_H, SHOP_Z]}>
          <boxGeometry args={[SHOP_W, FLOOR_T, SHOP_D]} />
          <meshStandardMaterial color={C_SLAB} />
        </mesh>
      ))}
      {/* Walls */}
      {wallPanels.map(({ pos, size }, i) => (
        <mesh key={i} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial
            color={transparentWalls ? '#b1a08a' : '#C49870'}
            transparent={transparentWalls}
            opacity={transparentWalls ? 0.22 : 1}
            depthWrite={!transparentWalls}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
      {/* Party wall divider */}
      <mesh position={[SHOP_X, SHOP_H / 2, SHOP_Z]}>
        <boxGeometry args={[0.14, SHOP_H, SHOP_D]} />
        <meshStandardMaterial color="#8a7a6a" />
      </mesh>
      {/* Windows on south face (floors 2 & 3) */}
      {SHOP_WINDOW_LAYOUT.map(({ floor, offset }, i) => (
        <mesh key={i} position={[SHOP_X + offset, windowYCenter(floor), SHOP_Z + hd + 0.07]}>
          <boxGeometry args={[SHOP_WINDOW_WIDTH, SHOP_WINDOW_HEIGHT, 0.10]} />
          <meshStandardMaterial color={C_GLASS} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
      {/* Shopfront awnings on ground floor */}
      {[-2.5, 2.5].map((offset, i) => (
        <mesh key={`awning-${i}`} position={[SHOP_X + offset, 2.6, SHOP_Z + hd + 0.6]} rotation={[-0.4, 0, 0]}>
          <boxGeometry args={[4, 0.06, 1.2]} />
          <meshStandardMaterial color="#c44830" />
        </mesh>
      ))}
    </>
  )
}

// ── Base landing pad at origin ────────────────────────────────────────────────

function BasePad() {
  const groupRef = useRef<THREE.Group>(null)
  const ringsRef = useRef<THREE.Group>(null)
  const scanRef = useRef<THREE.Mesh>(null)
  const beaconRefs = useRef<THREE.Mesh[]>([])

  const PAD_RADIUS = 5
  const PAD_HEIGHT = 0.12
  const PYLON_HEIGHT = 2.2
  const PYLON_RADIUS = 0.15
  const NUM_PULSE_RINGS = 3

  useFrame(({ clock }) => {
    const t = clock.elapsedTime

    // Rotate the scan ring slowly (z-axis after the -PI/2 X rotation lays it flat)
    if (scanRef.current) {
      scanRef.current.rotation.set(-Math.PI / 2, 0, t * 0.6)
    }

    // Pulse the beacon pylons
    beaconRefs.current.forEach((mesh, i) => {
      if (!mesh) return
      const phase = t * 2.0 + i * (Math.PI / 2)
      const pulse = 0.4 + 0.6 * Math.abs(Math.sin(phase))
      ;(mesh.material as THREE.MeshStandardMaterial).emissiveIntensity = pulse
    })

    // Animate expanding pulse rings
    if (ringsRef.current) {
      ringsRef.current.children.forEach((child, i) => {
        const mesh = child as THREE.Mesh
        const phase = (t * 0.5 + i * (1.0 / NUM_PULSE_RINGS)) % 1.0
        const scale = 0.3 + phase * 1.0
        mesh.scale.set(scale, 1, scale)
        ;(mesh.material as THREE.MeshStandardMaterial).opacity = 0.35 * (1.0 - phase)
      })
    }
  })

  // Corner pylon positions (square arrangement just inside pad edge)
  const pylonOffset = PAD_RADIUS * 0.72
  const pylonPositions: [number, number, number][] = [
    [-pylonOffset, 0, -pylonOffset],
    [ pylonOffset, 0, -pylonOffset],
    [-pylonOffset, 0,  pylonOffset],
    [ pylonOffset, 0,  pylonOffset],
  ]

  return (
    <group ref={groupRef} position={[0, 0.04, 0]}>
      {/* Main octagonal platform */}
      <mesh position={[0, PAD_HEIGHT / 2, 0]}>
        <cylinderGeometry args={[PAD_RADIUS, PAD_RADIUS, PAD_HEIGHT, 8]} />
        <meshStandardMaterial color="#1a1d24" roughness={0.7} metalness={0.3} />
      </mesh>

      {/* Raised inner ring — darker deck */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, PAD_HEIGHT + 0.02, 0]}>
        <ringGeometry args={[2.6, 3.4, 32]} />
        <meshStandardMaterial
          color="#0e1118"
          emissive="#1a3a5a"
          emissiveIntensity={0.15}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Inner cross markings — tactical crosshair */}
      {[0, Math.PI / 2].map((rot, i) => (
        <mesh key={`cross-${i}`} position={[0, PAD_HEIGHT + 0.03, 0]} rotation={[-Math.PI / 2, rot, 0]}>
          <planeGeometry args={[4.8, 0.12]} />
          <meshStandardMaterial
            color="#2a5a7a"
            emissive="#3a8abf"
            emissiveIntensity={0.5}
            side={THREE.DoubleSide}
            transparent
            opacity={0.8}
          />
        </mesh>
      ))}

      {/* Centre pip — glowing beacon dot */}
      <mesh position={[0, PAD_HEIGHT + 0.06, 0]}>
        <cylinderGeometry args={[0.35, 0.35, 0.06, 16]} />
        <meshStandardMaterial
          color="#00ccff"
          emissive="#00ccff"
          emissiveIntensity={1.2}
        />
      </mesh>

      {/* Concentric ring markings on deck */}
      {[1.6, 3.8].map((r, i) => (
        <mesh key={`ring-${i}`} rotation={[-Math.PI / 2, 0, 0]} position={[0, PAD_HEIGHT + 0.025, 0]}>
          <ringGeometry args={[r - 0.04, r + 0.04, 48]} />
          <meshStandardMaterial
            color="#1e4060"
            emissive="#2060a0"
            emissiveIntensity={0.3}
            side={THREE.DoubleSide}
            transparent
            opacity={0.7}
          />
        </mesh>
      ))}

      {/* Edge ring — bright outline */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, PAD_HEIGHT + 0.025, 0]}>
        <ringGeometry args={[PAD_RADIUS - 0.08, PAD_RADIUS + 0.02, 8]} />
        <meshStandardMaterial
          color="#2a4a6a"
          emissive="#3070a0"
          emissiveIntensity={0.4}
          side={THREE.DoubleSide}
          transparent
          opacity={0.6}
        />
      </mesh>

      {/* Animated scan arc — a partial ring that rotates */}
      <mesh ref={scanRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, PAD_HEIGHT + 0.04, 0]}>
        <ringGeometry args={[PAD_RADIUS - 0.3, PAD_RADIUS + 0.15, 32, 1, 0, Math.PI * 0.4]} />
        <meshStandardMaterial
          color="#00ddff"
          emissive="#00ddff"
          emissiveIntensity={0.9}
          side={THREE.DoubleSide}
          transparent
          opacity={0.55}
        />
      </mesh>


      {/* Diagonal corner marks — chevron-style tick marks */}
      {[0, Math.PI / 2, Math.PI, Math.PI * 1.5].map((angle, i) => {
        const dist = PAD_RADIUS * 0.55
        const cx = Math.cos(angle + Math.PI / 4) * dist
        const cz = Math.sin(angle + Math.PI / 4) * dist
        return (
          <mesh
            key={`tick-${i}`}
            position={[cx, PAD_HEIGHT + 0.03, cz]}
            rotation={[-Math.PI / 2, angle + Math.PI / 4, 0]}
          >
            <planeGeometry args={[1.2, 0.08]} />
            <meshStandardMaterial
              color="#2a5a7a"
              emissive="#3a8abf"
              emissiveIntensity={0.4}
              side={THREE.DoubleSide}
              transparent
              opacity={0.7}
            />
          </mesh>
        )
      })}

      {/* "BASE" label on the deck */}
      <Text
        position={[0, PAD_HEIGHT + 0.04, 2.0]}
        rotation={[-Math.PI / 2, 0, 0]}
        fontSize={1.1}
        letterSpacing={0.25}
        color="#3a8abf"
        anchorX="center"
        anchorY="middle"
        fontWeight="bold"
      >
        BASE
        <meshStandardMaterial
          color="#2a6a9a"
          emissive="#3a8abf"
          emissiveIntensity={0.5}
          transparent
          opacity={0.85}
        />
      </Text>

      {/* Point light for ambient base glow */}
      <pointLight position={[0, 1.5, 0]} color="#1a6090" intensity={2.5} distance={12} decay={2} />
    </group>
  )
}

// ── Supply crates — dropped at survivor locations after delivery ──────────────

function survivorKey(s: SurvivorPoint): string {
  return `${s.x.toFixed(1)},${s.y.toFixed(1)},${s.z.toFixed(1)}`
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
const BASE_PICKUP_RADIUS = 4.0  // how close to base before cargo appears

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

    // Lerp X/Z linearly, add an arc on Y
    const x = startPos.current.x + (to.x - startPos.current.x) * t
    const z = startPos.current.z + (to.z - startPos.current.z) * t
    // Parabolic arc: peaks halfway — kept low so the supply fits through windows
    const arc = 4 * t * (1 - t) * 1.2  // max +1.2m at midpoint
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
}

function DroneMesh({ targetPos, status, hasCargo, nearbyObstacles = 0, nearestObstacleDist = 999, survivorsInRange = 0 }: DroneProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const coneRef = useRef<THREE.Mesh>(null)
  const cargoRef = useRef<THREE.Mesh>(null)
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

    // Cargo block hangs underneath drone
    if (cargoRef.current) {
      cargoRef.current.position.copy(lerpPos.current)
      cargoRef.current.position.y -= 0.55
      cargoRef.current.visible = hasCargo
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
      {/* Cargo block — hangs below drone when carrying supplies */}
      <mesh ref={cargoRef} position={DRONE_START.toArray()} visible={false}>
        <boxGeometry args={[0.4, 0.3, 0.4]} />
        <meshStandardMaterial color="#ff8800" emissive="#cc5500" emissiveIntensity={0.4} />
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

// ── Intel Card — actionable scan findings ────────────────────────────────────

function IntelCard({
  survivors,
  dronePos,
  totalSurvivors,
  deliveringTo,
  deliveredTo,
  onSendSupplies,
}: {
  survivors: SurvivorPoint[]
  dronePos: THREE.Vector3
  totalSurvivors: number
  deliveringTo: Set<string>
  deliveredTo: Set<string>
  onSendSupplies: (survivor: SurvivorPoint) => void
}) {
  const detected = survivors.length
  const submerged = survivors.filter(s => s.y < FLOOD_LEVEL - 0.2).length
  const critical = submerged > 0
  const deliveredCount = deliveredTo.size

  return (
    <div style={{
      background: 'rgba(0,0,0,0.65)',
      border: `1px solid ${critical ? 'rgba(255,80,80,0.5)' : '#334'}`,
      borderRadius: 6,
      padding: '10px 14px',
      color: '#8899bb',
      fontSize: 11,
      fontFamily: 'Courier New, monospace',
      lineHeight: 1.7,
      pointerEvents: 'auto',
      minWidth: 210,
      maxHeight: 400,
      overflowY: 'auto',
    }}>
      <div style={{ color: '#99b', marginBottom: 6, letterSpacing: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>SCAN INTEL</span>
        <span style={{
          color: detected > 0 ? '#ff6' : '#556',
          fontSize: 10,
        }}>
          {detected > 0 ? 'LIVE' : 'NO CONTACT'}
        </span>
      </div>

      {/* Summary row */}
      <div style={{
        display: 'flex',
        gap: 12,
        marginBottom: 8,
        paddingBottom: 6,
        borderBottom: '1px solid #334',
      }}>
        <div style={{ textAlign: 'center', flex: 1 }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: detected > 0 ? '#4f4' : '#556' }}>
            {detected}
          </div>
          <div style={{ fontSize: 9, color: '#667' }}>DETECTED</div>
        </div>
        <div style={{ textAlign: 'center', flex: 1 }}>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#556' }}>
            {totalSurvivors - detected}
          </div>
          <div style={{ fontSize: 9, color: '#667' }}>UNSCANNED</div>
        </div>
        {submerged > 0 && (
          <div style={{ textAlign: 'center', flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#f44' }}>
              {submerged}
            </div>
            <div style={{ fontSize: 9, color: '#f66' }}>SUBMERGED</div>
          </div>
        )}
        {deliveredCount > 0 && (
          <div style={{ textAlign: 'center', flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#4cf' }}>
              {deliveredCount}
            </div>
            <div style={{ fontSize: 9, color: '#4cf' }}>SUPPLIED</div>
          </div>
        )}
      </div>

      {/* Drone position context */}
      <div style={{ color: '#667', marginBottom: 6, fontSize: 10 }}>
        SENSOR @ ({dronePos.x.toFixed(1)}, {dronePos.y.toFixed(1)}, {dronePos.z.toFixed(1)}) — {SURVIVOR_SENSOR_RANGE}m range
      </div>

      {/* Individual survivor entries */}
      {detected === 0 ? (
        <div style={{ color: '#556', fontStyle: 'italic', fontSize: 10 }}>
          No heat signatures in sensor range. Move drone closer to scan targets.
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
          return (
            <div key={i} style={{
              padding: '4px 6px',
              marginBottom: 4,
              borderRadius: 3,
              background: isDelivered
                ? 'rgba(60,200,255,0.10)'
                : isSubmerged ? 'rgba(255,50,50,0.12)' : 'rgba(60,255,60,0.08)',
              border: `1px solid ${isDelivered
                ? 'rgba(60,200,255,0.3)'
                : isSubmerged ? 'rgba(255,80,80,0.3)' : 'rgba(80,255,80,0.2)'}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ color: isDelivered ? '#4cf' : isSubmerged ? '#f66' : '#6f6' }}>
                  SIG-{String.fromCharCode(65 + i)}
                  {isSubmerged && !isDelivered && ' [SUBMERGED]'}
                  {isDelivered && ' [SUPPLIED]'}
                </span>
                <span style={{ color: '#778' }}>{dist.toFixed(1)}m</span>
              </div>
              <div style={{ color: '#889', fontSize: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>
                  ({s.x.toFixed(1)}, {s.y.toFixed(1)}, {s.z.toFixed(1)})
                  {isSubmerged && !isDelivered && <span style={{ color: '#f44', marginLeft: 6 }}>CRITICAL</span>}
                </span>
                <button
                  onClick={() => onSendSupplies(s)}
                  disabled={isDelivering || isDelivered}
                  style={{
                    marginLeft: 6,
                    border: `1px solid ${isDelivered ? 'rgba(60,200,255,0.3)' : isDelivering ? 'rgba(255,200,0,0.3)' : 'rgba(255,160,0,0.5)'}`,
                    borderRadius: 3,
                    background: isDelivered
                      ? 'rgba(60,200,255,0.15)'
                      : isDelivering ? 'rgba(255,200,0,0.12)' : 'rgba(255,140,0,0.15)',
                    color: isDelivered ? '#4cf' : isDelivering ? '#ff6' : '#fa0',
                    padding: '1px 6px',
                    cursor: isDelivering || isDelivered ? 'default' : 'pointer',
                    fontSize: 9,
                    fontFamily: 'Courier New, monospace',
                    opacity: isDelivered ? 0.7 : 1,
                  }}
                >
                  {isDelivered ? 'DONE' : isDelivering ? 'EN ROUTE...' : 'DELIVER'}
                </button>
              </div>
            </div>
          )
        })
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
  const submerged = SURVIVOR_POSITIONS.filter(p => p.y < FLOOD_LEVEL - 0.2).length

  return (
    <div style={{
      background: selectMode ? 'rgba(30, 16, 0, 0.82)' : 'rgba(0,0,0,0.60)',
      border: selectMode ? '1px solid #ff880066' : '1px solid #334',
      borderRadius: 6,
      padding: '10px 14px',
      color: '#667',
      fontSize: 11,
      fontFamily: 'Courier New, monospace',
      lineHeight: 1.8,
      pointerEvents: 'auto',
      minWidth: 200,
    }}>
      {selectMode ? (
        <>
          <div style={{ color: '#ff9933', fontWeight: 'bold', marginBottom: 6, letterSpacing: 1 }}>
            📐 SELECT MODE ACTIVE
          </div>
          <div style={{ color: '#cc7722' }}>Drag on map to select area</div>
          <div style={{ color: '#664422' }}>Ctrl+S or Esc to cancel</div>
        </>
      ) : (
        <>
          <div style={{ color: '#99b', marginBottom: 4, letterSpacing: 1 }}>PROJECT BEACON — THAILAND TOWN SAR</div>
          <div>Left drag  : orbit</div>
          <div>Right drag : pan</div>
          <div>Scroll     : zoom</div>
          <div>F key      : toggle follow beacon</div>
          <div style={{ color: '#c87' }}>Ctrl+S     : select area</div>
          <div style={{ marginTop: 6, color: '#4cf' }}>Enter      : send command</div>
        </>
      )}
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
  const [deliveringTo, setDeliveringTo] = useState<Set<string>>(new Set())
  const [deliveredTo, setDeliveredTo] = useState<Set<string>>(new Set())
  // ── Cargo / throw state ────────────────────────────────────────────────────
  const [hasCargo, setHasCargo] = useState(false)
  const [activeThrow, setActiveThrow] = useState<{ from: THREE.Vector3; to: SurvivorPoint } | null>(null)
  const deliveryTarget = useRef<SurvivorPoint | null>(null)  // survivor we're delivering to
  const deliveryApproach = useRef<SurvivorPoint | null>(null) // approach pos (outside window)
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

  // ── Cargo pickup at base ───────────────────────────────────────────────
  // When a delivery is pending and the drone returns near base, "pick up"
  // the supplies so the orange block appears under the drone.
  const BASE_PICKUP_RANGE = 3.0
  const cargoPickedUp = useRef(false)

  useEffect(() => {
    // Only trigger when there's a pending delivery and cargo hasn't been picked up yet
    if (!deliveryTarget.current || cargoPickedUp.current) return
    if (!pendingDeliveryKey.current) return

    const distToBase = Math.sqrt(
      dronePos.x ** 2 + dronePos.y ** 2 + dronePos.z ** 2,
    )
    if (distToBase < BASE_PICKUP_RANGE) {
      cargoPickedUp.current = true
      setHasCargo(true)
      addLog('📦 Supplies collected from base')
    }
  }, [dronePos, addLog])

  // ── Cargo throw trigger ─────────────────────────────────────────────────
  // Only throw when the drone has stopped at the approach position (outside
  // the window).  Using a tight radius around the approach point prevents
  // premature throws at intermediate waypoints that happen to be within
  // SURVIVOR_SENSOR_RANGE of the survivor.
  const APPROACH_ARRIVE_RADIUS = 3.0

  useEffect(() => {
    const target = deliveryTarget.current
    const approach = deliveryApproach.current
    if (!target || !approach || activeThrow || !cargoPickedUp.current) return
    // Only throw when the drone has stopped moving (arrived at destination)
    if (droneStatus === 'MOVING') return

    const distToApproach = Math.sqrt(
      (dronePos.x - approach.x) ** 2 +
      (dronePos.y - approach.y) ** 2 +
      (dronePos.z - approach.z) ** 2,
    )
    if (distToApproach < APPROACH_ARRIVE_RADIUS) {
      cargoPickedUp.current = false
      setHasCargo(false)
      setActiveThrow({ from: dronePos.clone(), to: target })
      addLog('📦 Supply thrown to survivor')
    }
  }, [dronePos, droneStatus, activeThrow, addLog])

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
    setActiveThrow(null)
    addLog('✓ Supply delivered to survivor')
  }, [activeThrow, addLog])

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
        // Propagate server-detected survivors into discoveredSurvivors
        if (
          (event.type === 'tool_result' || event.type === 'text') &&
          event.survivors &&
          event.survivors.length > 0
        ) {
          setDiscoveredSurvivors(prev => {
            const known = new Set(prev.map(survivorKey))
            const novel = event.survivors!.filter(
              s => !known.has(survivorKey(s)),
            )
            if (novel.length === 0) return prev
            return [...prev, ...novel]
          })
        }
        if (event.type === 'done') addLog('✓ Agent responded')
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') {
        addLog('⚠ Command aborted')
      } else {
        throw e
      }
      // Clear delivery state on failure/abort
      const key = pendingDeliveryKey.current
      if (key) {
        setDeliveringTo(prev => {
          const next = new Set(prev)
          next.delete(key)
          return next
        })
        setHasCargo(false)
        cargoPickedUp.current = false
        deliveryTarget.current = null
        deliveryApproach.current = null
        pendingDeliveryKey.current = null
      }
    }
  }, [addLog])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  // ── Area scan injection ────────────────────────────────────────────────────
  // We store a pending prompt and pass it to CommandPanel via the externalPrompt
  // prop so the command appears in its input, then auto-submits.
  const [pendingScanPrompt, setPendingScanPrompt] = useState<string | null>(null)

  const handleAreaScan = useCallback(() => {
    if (!selection) return

    // Detect which named buildings overlap the selected area.
    const NAMED_BUILDINGS: { id: number; name: string }[] = [
      { id: 0, name: 'target building' },
      { id: 1, name: 'obstacle building' },
      { id: 2, name: 'balcony building' },
      { id: 3, name: 'shophouse block' },
    ]
    const overlapping = SIM_BUILDINGS.filter(b => {
      const bb = buildingBounds(b)
      // AABB overlap between selection and building footprint
      return bb.minX <= selection.maxX && bb.maxX >= selection.minX &&
             bb.minZ <= selection.maxZ && bb.maxZ >= selection.minZ
    })
    const buildingNames = overlapping
      .map(b => NAMED_BUILDINGS.find(n => n.id === b.id)?.name)
      .filter(Boolean) as string[]

    let prompt: string
    if (buildingNames.length === 1) {
      // Entire selection is dominated by one building — scan the building directly.
      prompt = `scan the ${buildingNames[0]} at coordinates (${overlapping[0].cx.toFixed(1)}, 0, ${overlapping[0].cz.toFixed(1)}) for survivors`
    } else if (buildingNames.length > 1) {
      const buildingList = overlapping
        .map(b => {
          const name = NAMED_BUILDINGS.find(n => n.id === b.id)?.name ?? `building ${b.id}`
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
    // Inject prompt into CommandPanel
    setPendingScanPrompt(prompt)
  }, [selection, addLog])

  const handleSelectionClose = useCallback(() => {
    setSelectMode(false)
    setDragStart(null)
    setDragEnd(null)
    setSelection(null)
    setShowContextMenu(false)
  }, [])

  const handleSendSupplies = useCallback((survivor: SurvivorPoint) => {
    const key = survivorKey(survivor)
    const coords = `(${survivor.x.toFixed(1)}, ${survivor.y.toFixed(1)}, ${survivor.z.toFixed(1)})`
    const approach = computeApproachPosition(survivor)
    const approachCoords = `(${approach.x.toFixed(1)}, ${approach.y.toFixed(1)}, ${approach.z.toFixed(1)})`

    setDeliveringTo(prev => new Set(prev).add(key))
    pendingDeliveryKey.current = key
    deliveryTarget.current = survivor
    deliveryApproach.current = approach
    // Cargo visibility is deferred — cargoPickedUp stays false until drone
    // returns near base, where the useEffect below flips it on.
    addLog(`Dispatching supplies to survivor at ${coords}`)

    const isInside = findBuildingAt(survivor.x, survivor.y, survivor.z) !== null
    const prompt = isInside
      ? `Deliver emergency supplies to survivor at ${coords}. ` +
        `First return to base at (0, 0, 0) to collect supplies, ` +
        `then navigate to the approach position ${approachCoords} outside the building. ` +
        `Do NOT navigate to the survivor's interior coordinates — the approach position is the drop point.`
      : `Deliver emergency supplies to survivor at ${coords}. ` +
        `First return to base at (0, 0, 0) to collect supplies, ` +
        `then navigate to ${coords} to drop supplies.`

    // Route through CommandPanel so the user sees the prompt + streaming response
    setPendingScanPrompt(prompt)
  }, [addLog])

  const scannedSurvivors = useMemo(
    () => scannedSurvivorsFromDrone(dronePos),
    [dronePos.x, dronePos.y, dronePos.z],
  )

  // Persistent intel — accumulate survivors across all scans
  const [discoveredSurvivors, setDiscoveredSurvivors] = useState<SurvivorPoint[]>([])

  useEffect(() => {
    if (scannedSurvivors.length === 0) return
    setDiscoveredSurvivors(prev => {
      const known = new Set(prev.map(survivorKey))
      const novel = scannedSurvivors.filter(s => !known.has(survivorKey(s)))
      if (novel.length === 0) return prev
      return [...prev, ...novel]
    })
  }, [scannedSurvivors])

  return (
    <div style={{
      width: '100%',
      height: '100%',
      position: 'relative',
      background: '#0d0d17',
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
        <Ground />
        <GridOverlay />
        <BasePad />
        <ObstacleBuilding />
        <TargetBuilding transparentWalls={transparentWalls} />
        <BalconyBuilding transparentWalls={transparentWalls} />
        <ShophouseBlock transparentWalls={transparentWalls} />
        <Survivors floodY={FLOOD_LEVEL} />
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
        <DroneMesh
          targetPos={dronePos}
          status={droneStatus}
          hasCargo={hasCargo}
          nearbyObstacles={telemetry?.nearby_obstacles}
          nearestObstacleDist={telemetry?.nearest_obstacle_dist}
          survivorsInRange={telemetry?.survivors_in_range}
        />
        {activeThrow && (
          <SupplyThrow
            from={activeThrow.from}
            to={activeThrow.to}
            onComplete={handleThrowComplete}
          />
        )}
        <SurvivorScanRays
          enabled={scanRaysEnabled}
          dronePos={dronePos}
          survivors={scannedSurvivors}
        />
        <SupplyCrates deliveredTo={deliveredTo} />
      </Canvas>

      <DroneStatusPanel drones={drones} />
      {!selectMode && <CoordOverlay point={hoverPt} copied={copied} />}
      <CompassLabels northAngleRef={northAngleRef} />
      <MissionLog lines={log} />
      <div style={{
        position: 'absolute',
        top: 16,
        right: 16,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        pointerEvents: 'auto',
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
        <IntelCard
          survivors={discoveredSurvivors}
          dronePos={dronePos}
          totalSurvivors={SURVIVOR_POSITIONS.length}
          deliveringTo={deliveringTo}
          deliveredTo={deliveredTo}
          onSendSupplies={handleSendSupplies}
        />
      </div>
      {showContextMenu && selection && (
        <AreaContextMenu
          selection={selection}
          onScan={handleAreaScan}
          onClose={handleSelectionClose}
        />
      )}
      <CommandPanel
        assetId={ASSET_ID}
        connected={connected}
        uplinked={uplinked}
        battery={battery}
        onCommand={handleCommand}
        onStop={handleStop}
        externalPrompt={pendingScanPrompt}
        onExternalPromptConsumed={() => setPendingScanPrompt(null)}
      />
    </div>
  )
}
