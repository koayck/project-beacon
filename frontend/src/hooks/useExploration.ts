import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import type { SectorReveal } from '@/lib/ws'
import type { WorldBuilding, SurvivorPoint } from '@/types/worldTypes'
import {
  getAllSectors,
  positionToSectorId,
  type SectorBounds,
} from '@/lib/fogOfWar'

export interface SectorRevealInfo {
  sector: SectorBounds
  buildingCount: number
  maxHeight: number
  thermalAnomalies: boolean
  survivorCount: number
}

export interface ExplorationState {
  exploredSectors: Set<string>
  lastRevealedSector: string | null
  lastRevealInfo: SectorRevealInfo | null
  sectors: SectorBounds[]
  visibleBuildings: WorldBuilding[]
  visibleSurvivors: SurvivorPoint[]
  reset: () => void
}

/**
 * Tracks fog-of-war exploration state.
 * Reads explored sectors from the backend (via WS telemetry) rather than
 * computing locally, so we never miss a sector the scout passes through.
 */
export function useExploration(
  backendExploredSectors: Set<string>,
  backendReveals: SectorReveal[],
  buildings: WorldBuilding[],
  survivors: SurvivorPoint[],
): ExplorationState {
  const [lastRevealedSector, setLastRevealedSector] = useState<string | null>(null)
  const [lastRevealInfo, setLastRevealInfo] = useState<SectorRevealInfo | null>(null)
  const prevSizeRef = useRef(0)

  const sectors = useMemo(() => getAllSectors(), [])

  // Detect new reveals from backend events.
  useEffect(() => {
    if (backendReveals.length === 0) return

    const latest = backendReveals[backendReveals.length - 1]
    const sector = sectors.find(s => s.id === latest.sector_id)
    if (!sector) return

    setLastRevealedSector(latest.sector_id)
    setLastRevealInfo({
      sector,
      buildingCount: latest.building_count,
      maxHeight: latest.max_height,
      thermalAnomalies: latest.thermal_anomalies,
      survivorCount: latest.survivor_count,
    })
  }, [backendReveals, sectors])

  // Fallback: detect reveals from the explored set growing.
  useEffect(() => {
    if (backendExploredSectors.size <= prevSizeRef.current) {
      prevSizeRef.current = backendExploredSectors.size
      return
    }
    prevSizeRef.current = backendExploredSectors.size
  }, [backendExploredSectors])

  const visibleBuildings = useMemo(() => {
    if (backendExploredSectors.size === 0) return []
    return buildings.filter(b => {
      const sid = positionToSectorId(b.cx, b.cz)
      return sid != null && backendExploredSectors.has(sid)
    })
  }, [backendExploredSectors, buildings])

  const visibleSurvivors = useMemo(() => {
    if (backendExploredSectors.size === 0) return []
    return survivors.filter(s => {
      const sid = positionToSectorId(s.x, s.z)
      return sid != null && backendExploredSectors.has(sid)
    })
  }, [backendExploredSectors, survivors])

  const reset = useCallback(() => {
    setLastRevealedSector(null)
    setLastRevealInfo(null)
    prevSizeRef.current = 0
  }, [])

  return {
    exploredSectors: backendExploredSectors,
    lastRevealedSector,
    lastRevealInfo,
    sectors,
    visibleBuildings,
    visibleSurvivors,
    reset,
  }
}