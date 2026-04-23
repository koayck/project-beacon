'use client'

import { useMemo } from 'react'
import * as THREE from 'three'
import {
  STATION_LOWER_CRATE_Y,
  STATION_PLATFORM_HEIGHT,
  STATION_UPPER_CRATE_Y,
} from './SupplyStations'

interface StationGhostProps {
  position: THREE.Vector3 | null
  valid: boolean
}

/**
 * Semi-transparent placement preview that follows the cursor while the
 * operator is in station-placement mode. Green = valid, red = invalid.
 * Silhouette matches the real station (raised pylon + stacked crates) so the
 * preview accurately predicts the final placement.
 */
export function StationGhost({ position, valid }: StationGhostProps) {
  const color = valid ? '#33ff66' : '#ff3344'
  const emissive = useMemo(() => new THREE.Color(color), [color])

  if (!position) return null

  return (
    <group position={[position.x, 0, position.z]}>
      {/* Pylon silhouette */}
      <mesh position={[0, STATION_PLATFORM_HEIGHT / 2, 0]}>
        <cylinderGeometry args={[0.85, 1.05, STATION_PLATFORM_HEIGHT, 12]} />
        <meshStandardMaterial
          color={color}
          emissive={emissive}
          emissiveIntensity={0.35}
          transparent
          opacity={0.4}
        />
      </mesh>
      {/* Lower crate */}
      <mesh position={[0, STATION_LOWER_CRATE_Y, 0]}>
        <boxGeometry args={[1.4, 0.8, 1.4]} />
        <meshStandardMaterial
          color={color}
          emissive={emissive}
          emissiveIntensity={0.5}
          transparent
          opacity={0.5}
        />
      </mesh>
      {/* Upper crate */}
      <mesh position={[0, STATION_UPPER_CRATE_Y, 0]}>
        <boxGeometry args={[1.1, 0.6, 1.1]} />
        <meshStandardMaterial
          color={color}
          emissive={emissive}
          emissiveIntensity={0.5}
          transparent
          opacity={0.5}
        />
      </mesh>
      {/* Ground halo hint */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[1.6, 2.1, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.35} />
      </mesh>
    </group>
  )
}
