'use client'

import { useMemo } from 'react'
import { Canal } from './Canal'
import { FloodWater } from './FloodWater'
import { MidRise } from './MidRise'
import { Parks } from './Parks'
import { Roads } from './Roads'
import { Shophouses } from './Shophouses'
import { Trees } from './Trees'
import { WORLD2_ENV } from '../../generated/world2Environment.generated'
import { loadWorldEnvironmentFromUrl, type ResolvedWorldEnvironment } from './worldEnvironment'
import { positionToSectorId } from '@/lib/fogOfWar'
import { useEffect, useState } from 'react'

export function World2Environment({
  span,
  floorHeight,
  floorThickness,
  floodLevel,
  transparentWalls,
  runtimeWorldUrl,
  exploredSectors,
}: {
  span: number
  floorHeight: number
  floorThickness: number
  floodLevel: number
  transparentWalls: boolean
  runtimeWorldUrl?: string
  exploredSectors?: Set<string>
}) {
  const [runtimeEnv, setRuntimeEnv] = useState<ResolvedWorldEnvironment | null>(null)

  useEffect(() => {
    if (!runtimeWorldUrl) {
      setRuntimeEnv(null)
      return
    }

    let cancelled = false
    loadWorldEnvironmentFromUrl(runtimeWorldUrl)
      .then((env) => {
        if (!cancelled) setRuntimeEnv(env)
      })
      .catch(() => {
        if (!cancelled) setRuntimeEnv(null)
      })

    return () => {
      cancelled = true
    }
  }, [runtimeWorldUrl])

  const env = runtimeEnv ?? WORLD2_ENV

  // Filter buildings by explored sectors when fog-of-war is active.
  const visibleShophouses = useMemo(() => {
    if (!exploredSectors) return env.shophouseSpecs
    return env.shophouseSpecs.filter(s => {
      const sid = positionToSectorId(s.cx, s.cz)
      return sid != null && exploredSectors.has(sid)
    })
  }, [env.shophouseSpecs, exploredSectors])

  const visibleMidRise = useMemo(() => {
    if (!exploredSectors) return env.midRiseSpecs
    return env.midRiseSpecs.filter(s => {
      const sid = positionToSectorId(s.cx, s.cz)
      return sid != null && exploredSectors.has(sid)
    })
  }, [env.midRiseSpecs, exploredSectors])

  const visibleTrees = useMemo(() => {
    if (!exploredSectors) return env.trees.positions
    return env.trees.positions.filter((p: readonly [number, number]) => {
      const sid = positionToSectorId(p[0], p[1])
      return sid != null && exploredSectors.has(sid)
    })
  }, [env.trees.positions, exploredSectors])

  return (
    <>
      <Roads
        span={span}
        roadStrips={env.roads.strips}
        lineStrips={env.roads.lane_strips}
        roadColor={env.colors.road}
        lineColor={env.colors.line}
      />
      <Canal
        span={span}
        width={env.canal.width}
        position={env.canal.position}
        color={env.colors.canal}
        opacity={env.canal.opacity}
        horizontal={env.canal.horizontal}
      />
      <Parks parks={env.parks} color={env.colors.park} />
      <Trees
        treePositions={visibleTrees}
        trunkColor={env.colors.trunk}
        leafColor={env.colors.leaf}
        trunkSize={env.trees.trunk_size}
        leafRadius={env.trees.leaf_radius}
        trunkY={env.trees.trunk_y}
        leafY={env.trees.leaf_y}
      />
      <Shophouses
        specs={visibleShophouses}
        floorHeight={floorHeight}
        floorThickness={floorThickness}
        transparentWalls={transparentWalls}
      />
      <MidRise
        specs={visibleMidRise}
        floorHeight={floorHeight}
        floorThickness={floorThickness}
        transparentWalls={transparentWalls}
      />
      <FloodWater span={span} floodLevel={floodLevel} />
    </>
  )
}