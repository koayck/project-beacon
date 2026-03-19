'use client'

import { Line } from '@react-three/drei'
import * as THREE from 'three'
import type { SurvivorPoint } from '../../types/worldTypes'

export function SurvivorScanRays({
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
