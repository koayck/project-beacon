'use client'

import { Canal } from './Canal'
import { FloodWater } from './FloodWater'
import { MidRise } from './MidRise'
import { Parks } from './Parks'
import { Roads } from './Roads'
import { Shophouses } from './Shophouses'
import { Trees } from './Trees'
import { WORLD2_ENV } from '../../generated/world2Environment.generated'
import { loadWorldEnvironmentFromUrl, type ResolvedWorldEnvironment } from './worldEnvironment'
import { useEffect, useState } from 'react'

export function World2Environment({
  span,
  floorHeight,
  floorThickness,
  floodLevel,
  transparentWalls,
  runtimeWorldUrl,
}: {
  span: number
  floorHeight: number
  floorThickness: number
  floodLevel: number
  transparentWalls: boolean
  runtimeWorldUrl?: string
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
        treePositions={env.trees.positions}
        trunkColor={env.colors.trunk}
        leafColor={env.colors.leaf}
        trunkSize={env.trees.trunk_size}
        leafRadius={env.trees.leaf_radius}
        trunkY={env.trees.trunk_y}
        leafY={env.trees.leaf_y}
      />
      <Shophouses
        specs={env.shophouseSpecs}
        floorHeight={floorHeight}
        floorThickness={floorThickness}
        transparentWalls={transparentWalls}
      />
      <MidRise
        specs={env.midRiseSpecs}
        floorHeight={floorHeight}
        floorThickness={floorThickness}
        transparentWalls={transparentWalls}
      />
      <FloodWater span={span} floodLevel={floodLevel} />
    </>
  )
}
