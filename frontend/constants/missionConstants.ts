import * as THREE from 'three'
import WORLD from '@shared/world.json'
import WORLD2 from '@shared/world2.json'
import type { WorldBuilding } from '../src/types/worldTypes'

const SURV_HOVER = WORLD.scene.surv_hover_m
const RAILING_H = 1.0

export const FLOOR_H = WORLD.scene.floor_height_m
export const FLOOR_T = WORLD.scene.floor_slab_thickness_m
export const FLOOD_LEVEL = WORLD.scene.flood_level_m

const slabY = (n: number) => (n - 1) * FLOOR_H
const survY = (n: number) => slabY(n) + FLOOR_T / 2 + SURV_HOVER

export const W1_GRID_CELLS = 50
export const W1_GRID_SPACING = 2
export const W1_CAM_POS: [number, number, number] = [45, 95, 70]
export const W1_FOG: [number, number] = [90, 260]
export const W1_BUILDINGS = [...(WORLD.buildings as WorldBuilding[])].sort((a, b) => a.id - b.id)
export const W1_SURVIVORS = WORLD.survivors.map(s => ({ x: s.x, y: s.y, z: s.z }))

export const W2_GRID_CELLS = 200
export const W2_GRID_SPACING = 1
export const W2_CAM_POS: [number, number, number] = [90, 180, 140]
export const W2_FOG: [number, number] = [160, 450]
export const W2_BUILDINGS = [...(WORLD2.buildings as WorldBuilding[])].sort((a, b) => a.id - b.id)
export const W2_SURVIVORS = WORLD2.survivors.map(s => ({ x: s.x, y: s.y, z: s.z }))

export const BASE_Y = 2.0
export const DRONE_START = new THREE.Vector3(0, BASE_Y, 0)
export const FOLLOW_CAMERA_OFFSET = new THREE.Vector3(18, 14, 18)

export const SURVIVOR_SENSOR_RANGE = 5.0
export const SWEEP_SCAN_SENSOR_RANGE = SURVIVOR_SENSOR_RANGE
export const SUPPLY_DISPATCH_TARGET_TOLERANCE = 0.8
export const ROUTE_ARRIVAL_TOLERANCE = 2.0
export const BASE_PICKUP_RANGE = 3.0
const LOS_SAMPLE_COUNT = 30
const APPROACH_OFFSET = 2.5
const BALCONY_SURVIVOR_Y_TOLERANCE = 0.8
const BALCONY_EDGE_TOLERANCE = 0.35
const ROOFTOP_THROW_CLEARANCE = 2.5

function buildSimBuildings(worldBuildings: WorldBuilding[]) {
  const result = []
  let nextId = worldBuildings.length > 0
    ? Math.max(...worldBuildings.map(b => b.id)) + 100
    : 100

  for (const building of worldBuildings) {
    result.push({
      id: building.id,
      name: building.name,
      parentBuildingId: building.id,
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
    })

    if (building.balcony) {
      const bal = building.balcony
      const hw = building.w / 2
      const hd = building.d / 2
      const balconyY = (bal.floor - 1) * FLOOR_H

      let encCx = building.cx
      let encCz = building.cz
      let encW = bal.width
      let encD = bal.depth

      if (bal.face === 'south') {
        encCz = building.cz + hd + bal.depth / 2
      } else if (bal.face === 'north') {
        encCz = building.cz - hd - bal.depth / 2
      } else if (bal.face === 'east') {
        encCx = building.cx + hw + bal.depth / 2
        encW = bal.depth
        encD = bal.width
      } else if (bal.face === 'west') {
        encCx = building.cx - hw - bal.depth / 2
        encW = bal.depth
        encD = bal.width
      }

      result.push({
        id: nextId++,
        name: `${building.name} balcony`,
        parentBuildingId: building.id,
        cx: encCx,
        cz: encCz,
        w: encW,
        d: encD,
        minY: balconyY,
        h: balconyY + RAILING_H,
        windows: [{
          face: 'top',
          axisCenter: encCx,
          width: encW,
          sillY: encCz - encD / 2,
          height: encD,
        }],
      })
    }
  }

  return result
}

export const W1_SIM_BUILDINGS = buildSimBuildings(W1_BUILDINGS)
export const W2_SIM_BUILDINGS = buildSimBuildings(W2_BUILDINGS)

export function buildingPromptName(building: { id: number; name: string }): string {
  const normalized = (building.name || '').trim().replace(/[_-]+/g, ' ')
  if (normalized.length > 0) return normalized
  return `building ${building.id}`
}

export function buildingBounds(b: { cx: number; cz: number; w: number; d: number }) {
  return {
    minX: b.cx - b.w / 2,
    maxX: b.cx + b.w / 2,
    minZ: b.cz - b.d / 2,
    maxZ: b.cz + b.d / 2,
  }
}

function containsPoint(
  b: { cx: number; cz: number; w: number; d: number; h: number; minY?: number },
  x: number,
  y: number,
  z: number,
): boolean {
  const { minX, maxX, minZ, maxZ } = buildingBounds(b)
  const bottomY = b.minY ?? 0
  return minX <= x && x <= maxX && bottomY <= y && y <= b.h && minZ <= z && z <= maxZ
}

function containsFloorSlabPoint(
  b: { cx: number; cz: number; w: number; d: number; h: number; minY?: number; windows: Array<{ face: string }> },
  x: number,
  y: number,
  z: number,
): boolean {
  if (!containsPoint(b, x, y, z)) return false
  const epsilon = 1e-6
  const half = FLOOR_T / 2
  const bottomY = b.minY ?? 0

  let level = 0.0
  while (level <= b.h + epsilon) {
    if (level >= bottomY && level - half - epsilon <= y && y <= level + half + epsilon) return true
    level += FLOOR_H
  }
  const hasTopAperture = b.windows.some(w => w.face === 'top')
  if (!hasTopAperture && b.h - half - epsilon <= y && y <= b.h + half + epsilon) return true
  return false
}

export function findBuildingAt<T extends { id: number; cx: number; cz: number; w: number; d: number; h: number; minY?: number }>(
  simBuildings: T[],
  x: number,
  y: number,
  z: number,
): T | null {
  for (const b of simBuildings) {
    if (containsPoint(b, x, y, z)) return b
  }
  return null
}

function segmentIntersectsWindow(
  building: { cx: number; cz: number; w: number; d: number; h: number },
  window: { face: string; axisCenter: number; sillY: number; width: number; height: number },
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

  if (window.face === 'top') {
    if (Math.abs(dy) <= epsilon) return false
    const planeY = building.h
    const t = (planeY - fromY) / dy
    if (t <= epsilon || t >= 1.0 - epsilon) return false
    const hitX = fromX + dx * t
    const hitZ = fromZ + dz * t
    return (
      minAxis - epsilon <= hitX && hitX <= maxAxis + epsilon &&
      minY - epsilon <= hitZ && hitZ <= maxY + epsilon
    )
  }

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
  building: { cx: number; cz: number; w: number; d: number; h: number; windows: Array<{ face: string; axisCenter: number; sillY: number; width: number; height: number }> },
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
  simBuildings: Array<{ id: number; cx: number; cz: number; w: number; d: number; h: number; minY?: number; windows: Array<{ face: string }> }>,
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

    for (const b of simBuildings) {
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

export function distance3D(
  fromX: number,
  fromY: number,
  fromZ: number,
  toX: number,
  toY: number,
  toZ: number,
): number {
  const dx = toX - fromX
  const dy = toY - fromY
  const dz = toZ - fromZ
  return Math.sqrt(dx * dx + dy * dy + dz * dz)
}

export function distance2D(fromX: number, fromZ: number, toX: number, toZ: number): number {
  const dx = toX - fromX
  const dz = toZ - fromZ
  return Math.sqrt(dx * dx + dz * dz)
}

export function distanceBetweenPoints(a: { x: number; y: number; z: number }, b: { x: number; y: number; z: number }): number {
  return distance3D(a.x, a.y, a.z, b.x, b.y, b.z)
}

export function survivorDistance(from: { x: number; y: number; z: number }, target: { x: number; y: number; z: number }): number {
  return distance3D(from.x, from.y, from.z, target.x, target.y, target.z)
}

function survivorVisibleFromDrone(
  simBuildings: Array<{ id: number; cx: number; cz: number; w: number; d: number; h: number; minY?: number; windows: Array<{ face: string; axisCenter: number; sillY: number; width: number; height: number }> }>,
  dronePos: THREE.Vector3,
  survivor: { x: number; y: number; z: number },
): boolean {
  const survivorBuilding = findBuildingAt(simBuildings, survivor.x, survivor.y, survivor.z)
  if (!survivorBuilding) {
    return lineOfSightClear(simBuildings, dronePos.x, dronePos.y, dronePos.z, survivor.x, survivor.y, survivor.z)
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
    simBuildings,
    dronePos.x,
    dronePos.y,
    dronePos.z,
    survivor.x,
    survivor.y,
    survivor.z,
    new Set([survivorBuilding.id]),
  )
}

export function scannedSurvivorsFromDrone(
  simBuildings: Array<{ id: number; cx: number; cz: number; w: number; d: number; h: number; minY?: number; windows: Array<{ face: string; axisCenter: number; sillY: number; width: number; height: number }> }>,
  survivors: Array<{ x: number; y: number; z: number }>,
  dronePos: THREE.Vector3,
  range: number = SURVIVOR_SENSOR_RANGE,
) {
  return survivors.filter((survivor) => {
    if (survivorDistance(dronePos, survivor) > range) return false
    return survivorVisibleFromDrone(simBuildings, dronePos, survivor)
  })
}

function nearbySurvivorsFromDrone(
  survivors: Array<{ x: number; y: number; z: number }>,
  dronePos: THREE.Vector3,
  range: number = SURVIVOR_SENSOR_RANGE,
) {
  return survivors
    .filter((survivor) => survivorDistance(dronePos, survivor) <= range)
    .sort((a, b) => survivorDistance(dronePos, a) - survivorDistance(dronePos, b))
}

export function survivorKey(s: { x: number; y: number; z: number }): string {
  return `${s.x.toFixed(1)},${s.y.toFixed(1)},${s.z.toFixed(1)}`
}

export function detectedSurvivorsFromTelemetryEntry(
  simBuildings: Array<{ id: number; cx: number; cz: number; w: number; d: number; h: number; minY?: number; windows: Array<{ face: string; axisCenter: number; sillY: number; width: number; height: number }> }>,
  survivors: Array<{ x: number; y: number; z: number }>,
  telemetryEntry: { status: string; x: number; y: number; z: number; survivors_in_range?: number },
) {
  const isScanning = telemetryEntry.status === 'SCANNING'
  const detectionRange = isScanning ? SWEEP_SCAN_SENSOR_RANGE : SURVIVOR_SENSOR_RANGE
  const dronePos = new THREE.Vector3(telemetryEntry.x, telemetryEntry.y, telemetryEntry.z)
  const losMatches = scannedSurvivorsFromDrone(simBuildings, survivors, dronePos, detectionRange)
  if (isScanning && losMatches.length > 0) return losMatches

  const visibleCount = Math.max(0, Math.floor(telemetryEntry.survivors_in_range ?? 0))
  if (visibleCount <= 0) return []
  if (losMatches.length >= visibleCount) return losMatches

  const fallback = nearbySurvivorsFromDrone(survivors, dronePos, detectionRange).filter((survivor) => {
    return !losMatches.some((match) => survivorKey(match) === survivorKey(survivor))
  })
  return [...losMatches, ...fallback.slice(0, Math.max(0, visibleCount - losMatches.length))]
}

export function computeApproachPosition(
  simBuildings: Array<{ id: number; cx: number; cz: number; w: number; d: number; h: number; minY?: number; windows: Array<{ face: string; axisCenter: number; sillY: number; width: number; height: number }> }>,
  survivor: { x: number; y: number; z: number },
) {
  const building = findBuildingAt(simBuildings, survivor.x, survivor.y, survivor.z)
  if (!building) return survivor

  const bounds = buildingBounds(building)

  if (building.windows.length > 0) {
    let bestWindow: { face: string; axisCenter: number; sillY: number; width: number; height: number } | null = null
    let bestDist = Infinity

    for (const w of building.windows) {
      if (w.face === 'top') {
        bestWindow = w
        bestDist = 0
        break
      }
      const windowCenterY = w.sillY + w.height / 2
      const yDist = Math.abs(survivor.y - windowCenterY)
      let wx: number
      let wz: number
      if (w.face === 'north') { wx = w.axisCenter; wz = bounds.minZ }
      else if (w.face === 'south') { wx = w.axisCenter; wz = bounds.maxZ }
      else if (w.face === 'west') { wx = bounds.minX; wz = w.axisCenter }
      else { wx = bounds.maxX; wz = w.axisCenter }

      const xzDist = distance2D(survivor.x, survivor.z, wx, wz)
      const totalDist = yDist * 2 + xzDist
      if (totalDist < bestDist) {
        bestDist = totalDist
        bestWindow = w
      }
    }

    if (bestWindow) {
      if (bestWindow.face === 'top') {
        return { x: survivor.x, y: building.h + APPROACH_OFFSET, z: survivor.z }
      }
      const wy = bestWindow.sillY + bestWindow.height / 2
      if (bestWindow.face === 'west') return { x: bounds.minX - APPROACH_OFFSET, y: wy, z: bestWindow.axisCenter }
      if (bestWindow.face === 'east') return { x: bounds.maxX + APPROACH_OFFSET, y: wy, z: bestWindow.axisCenter }
      if (bestWindow.face === 'north') return { x: bestWindow.axisCenter, y: wy, z: bounds.minZ - APPROACH_OFFSET }
      return { x: bestWindow.axisCenter, y: wy, z: bounds.maxZ + APPROACH_OFFSET }
    }
  }

  const distToWest = survivor.x - bounds.minX
  const distToEast = bounds.maxX - survivor.x
  const distToNorth = survivor.z - bounds.minZ
  const distToSouth = bounds.maxZ - survivor.z
  const minDist = Math.min(distToWest, distToEast, distToNorth, distToSouth)

  if (minDist === distToWest) return { x: bounds.minX - APPROACH_OFFSET, y: survivor.y, z: survivor.z }
  if (minDist === distToEast) return { x: bounds.maxX + APPROACH_OFFSET, y: survivor.y, z: survivor.z }
  if (minDist === distToNorth) return { x: survivor.x, y: survivor.y, z: bounds.minZ - APPROACH_OFFSET }
  return { x: survivor.x, y: survivor.y, z: bounds.maxZ + APPROACH_OFFSET }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function worldBuildingBounds(building: { cx: number; cz: number; w: number; d: number }) {
  return {
    minX: building.cx - building.w / 2,
    maxX: building.cx + building.w / 2,
    minZ: building.cz - building.d / 2,
    maxZ: building.cz + building.d / 2,
  }
}

export function findBalconyHostBuilding(
  worldBuildings: Array<{ id: number; name: string; cx: number; cz: number; w: number; d: number; h: number; balcony: null | { floor: number; face: string; depth: number; width: number } }>,
  survivor: { x: number; y: number; z: number },
) {
  for (const building of worldBuildings) {
    if (!building.balcony) continue
    const balcony = building.balcony
    const bounds = worldBuildingBounds(building)
    const expectedY = survY(balcony.floor)
    if (Math.abs(survivor.y - expectedY) > BALCONY_SURVIVOR_Y_TOLERANCE) continue

    let minX = bounds.minX
    let maxX = bounds.maxX
    let minZ = bounds.minZ
    let maxZ = bounds.maxZ
    if (balcony.face === 'south') {
      minX = building.cx - balcony.width / 2
      maxX = building.cx + balcony.width / 2
      minZ = bounds.maxZ
      maxZ = bounds.maxZ + balcony.depth
    } else if (balcony.face === 'north') {
      minX = building.cx - balcony.width / 2
      maxX = building.cx + balcony.width / 2
      minZ = bounds.minZ - balcony.depth
      maxZ = bounds.minZ
    } else if (balcony.face === 'east') {
      minX = bounds.maxX
      maxX = bounds.maxX + balcony.depth
      minZ = building.cz - balcony.width / 2
      maxZ = building.cz + balcony.width / 2
    } else {
      minX = bounds.minX - balcony.depth
      maxX = bounds.minX
      minZ = building.cz - balcony.width / 2
      maxZ = building.cz + balcony.width / 2
    }

    if (
      survivor.x >= minX - BALCONY_EDGE_TOLERANCE
      && survivor.x <= maxX + BALCONY_EDGE_TOLERANCE
      && survivor.z >= minZ - BALCONY_EDGE_TOLERANCE
      && survivor.z <= maxZ + BALCONY_EDGE_TOLERANCE
    ) {
      const insideShell = (
        survivor.x >= bounds.minX
        && survivor.x <= bounds.maxX
        && survivor.y >= 0
        && survivor.y <= building.h
        && survivor.z >= bounds.minZ
        && survivor.z <= bounds.maxZ
      )
      if (!insideShell) return building
    }
  }
  return null
}

export function survivorAssociatedBuildingId(
  simBuildings: Array<{ id: number; parentBuildingId?: number; cx: number; cz: number; w: number; d: number; h: number; minY?: number }>,
  worldBuildings: Array<{ id: number; name: string; cx: number; cz: number; w: number; d: number; h: number; balcony: null | { floor: number; face: string; depth: number; width: number } }>,
  survivor: { x: number; y: number; z: number },
): number | null {
  const inside = findBuildingAt(simBuildings, survivor.x, survivor.y, survivor.z)
  if (inside) return inside.parentBuildingId ?? inside.id
  const balconyHost = findBalconyHostBuilding(worldBuildings, survivor)
  return balconyHost ? balconyHost.id : null
}

export function computeSupplyThrowOrigin(
  simBuildings: Array<{ id: number; cx: number; cz: number; w: number; d: number; h: number; minY?: number; windows: Array<{ face: string; axisCenter: number; sillY: number; width: number; height: number }> }>,
  worldBuildings: Array<{ id: number; name: string; cx: number; cz: number; w: number; d: number; h: number; balcony: null | { floor: number; face: string; depth: number; width: number } }>,
  target: { x: number; y: number; z: number },
  fallback: THREE.Vector3,
) {
  const balconyHost = findBalconyHostBuilding(worldBuildings, target)
  if (balconyHost) {
    const bounds = worldBuildingBounds(balconyHost)
    const roofY = balconyHost.h + ROOFTOP_THROW_CLEARANCE
    if (balconyHost.balcony?.face === 'south') {
      return new THREE.Vector3(clamp(target.x, bounds.minX, bounds.maxX), roofY, bounds.maxZ)
    }
    if (balconyHost.balcony?.face === 'north') {
      return new THREE.Vector3(clamp(target.x, bounds.minX, bounds.maxX), roofY, bounds.minZ)
    }
    if (balconyHost.balcony?.face === 'east') {
      return new THREE.Vector3(bounds.maxX, roofY, clamp(target.z, bounds.minZ, bounds.maxZ))
    }
    return new THREE.Vector3(bounds.minX, roofY, clamp(target.z, bounds.minZ, bounds.maxZ))
  }

  const insideBuilding = findBuildingAt(simBuildings, target.x, target.y, target.z)
  if (insideBuilding) {
    const windowPoint = computeApproachPosition(simBuildings, target)
    return new THREE.Vector3(windowPoint.x, windowPoint.y, windowPoint.z)
  }

  return fallback.clone()
}

export function mergeUniqueSurvivors<T extends { x: number; y: number; z: number }>(
  existing: T[],
  incoming: T[],
): T[] {
  if (incoming.length === 0) return existing
  const merged = new Map<string, T>()
  for (const survivor of existing) merged.set(survivorKey(survivor), survivor)
  for (const survivor of incoming) merged.set(survivorKey(survivor), survivor)
  return [...merged.values()]
}

export function parseArrivedCoords(text: string): { x: number; y: number; z: number } | null {
  const match = text.match(/arrived at \(([^,]+),\s*([^,]+),\s*([^)]+)\)/i)
  if (!match) return null
  const x = Number(match[1])
  const y = Number(match[2])
  const z = Number(match[3])
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null
  return { x, y, z }
}

export function parseSupplyLoopAssetId(toolName: string): string | null {
  const match = toolName.match(/^process_next_supply_target_(.+)$/)
  if (!match) return null
  return match[1].replace(/_/g, '-').toUpperCase()
}
