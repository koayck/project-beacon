import type { WorldBuilding, SurvivorPoint } from '@/types/worldTypes'

// Grid covering the full World 2 (Hat Yai) ground plane (200x200, centered at origin).
// Origin is the corner with most negative X and Z.
export const FOG_GRID = {
  originX: -100,
  originZ: -100,
  width: 200,   // X span: -100 to 100
  depth: 200,   // Z span: -100 to 100
  cols: 5,
  rows: 5,
} as const

export const SCOUT_ASSET_ID = 'BEACON-SCOUT'
export const SCOUT_ALTITUDE = 35.0  // above tallest building (h=30)
export const FOG_PLANE_Y = 0.15  // just above ground

export interface SectorBounds {
  id: string
  col: number
  row: number
  minX: number
  maxX: number
  minZ: number
  maxZ: number
}

export function getSectorId(col: number, row: number): string {
  return `${String.fromCharCode(65 + row)}${col + 1}`
}

export function getAllSectors(): SectorBounds[] {
  const cellW = FOG_GRID.width / FOG_GRID.cols
  const cellD = FOG_GRID.depth / FOG_GRID.rows
  const sectors: SectorBounds[] = []
  for (let row = 0; row < FOG_GRID.rows; row++) {
    for (let col = 0; col < FOG_GRID.cols; col++) {
      sectors.push({
        id: getSectorId(col, row),
        col,
        row,
        minX: FOG_GRID.originX + col * cellW,
        maxX: FOG_GRID.originX + (col + 1) * cellW,
        minZ: FOG_GRID.originZ + row * cellD,
        maxZ: FOG_GRID.originZ + (row + 1) * cellD,
      })
    }
  }
  return sectors
}

export function positionToSectorId(x: number, z: number): string | null {
  const cellW = FOG_GRID.width / FOG_GRID.cols
  const cellD = FOG_GRID.depth / FOG_GRID.rows
  const col = Math.floor((x - FOG_GRID.originX) / cellW)
  const row = Math.floor((z - FOG_GRID.originZ) / cellD)
  if (col < 0 || col >= FOG_GRID.cols || row < 0 || row >= FOG_GRID.rows) return null
  return getSectorId(col, row)
}

export function buildingsInSector(buildings: WorldBuilding[], sector: SectorBounds): WorldBuilding[] {
  return buildings.filter(b =>
    b.cx >= sector.minX && b.cx < sector.maxX &&
    b.cz >= sector.minZ && b.cz < sector.maxZ
  )
}

export function survivorsInSector(survivors: SurvivorPoint[], sector: SectorBounds): SurvivorPoint[] {
  return survivors.filter(s =>
    s.x >= sector.minX && s.x < sector.maxX &&
    s.z >= sector.minZ && s.z < sector.maxZ
  )
}

export interface SectorRevealInfo {
  sector: SectorBounds
  buildingCount: number
  maxHeight: number
  thermalAnomalies: boolean
  survivorCount: number
}

export function computeSectorRevealInfo(
  sector: SectorBounds,
  buildings: WorldBuilding[],
  survivors: SurvivorPoint[],
): SectorRevealInfo {
  const sectorBuildings = buildingsInSector(buildings, sector)
  const sectorSurvivors = survivorsInSector(survivors, sector)
  return {
    sector,
    buildingCount: sectorBuildings.length,
    maxHeight: sectorBuildings.reduce((max, b) => Math.max(max, b.h), 0),
    thermalAnomalies: sectorSurvivors.length > 0,
    survivorCount: sectorSurvivors.length,
  }
}