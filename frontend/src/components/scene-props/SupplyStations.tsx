'use client'

import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { SupplyStation } from '../../lib/api'

interface SupplyStationsProps {
  stations: SupplyStation[]
  selectedId: string | null
  onSelect: (id: string | null) => void
  /**
   * IDs whose parachute drop is still in flight. The pylon/platform is
   * always rendered (so the drop doesn't appear to float in mid-air), but
   * the crates and halo are hidden until the drop completes and hands off
   * to the static station render.
   */
  droppingIds?: ReadonlySet<string>
}

// Height of the concrete pylon base. Must clear the world2 flood level (1.4m)
// by enough that the crates above never look partially submerged.
export const STATION_PLATFORM_HEIGHT = 1.8
// Crate positions (centers) are measured from the top of the platform.
export const STATION_LOWER_CRATE_Y = STATION_PLATFORM_HEIGHT + 0.4
export const STATION_UPPER_CRATE_Y = STATION_PLATFORM_HEIGHT + 0.8 + 0.3
// Platform-top is where incoming parachutes land.
export const STATION_PLATFORM_TOP_Y = STATION_PLATFORM_HEIGHT

export function SupplyStations({ stations, selectedId, onSelect, droppingIds }: SupplyStationsProps) {
  // Home station is rendered separately by BasePad; filter it out here.
  const userStations = useMemo(
    () => stations.filter(s => s.id !== 'home'),
    [stations],
  )
  const haloRefs = useRef<Map<string, THREE.Mesh>>(new Map())

  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    haloRefs.current.forEach(mesh => {
      const mat = mesh.material as THREE.MeshBasicMaterial
      mat.opacity = 0.2 + 0.15 * Math.abs(Math.sin(t * 1.4))
    })
  })

  if (userStations.length === 0) return null

  return (
    <group>
      {userStations.map(s => {
        const isSelected = s.id === selectedId
        const isDropping = droppingIds?.has(s.id) ?? false
        return (
          <group
            key={s.id}
            position={[s.x, 0, s.z]}
            onClick={e => {
              e.stopPropagation()
              onSelect(isSelected ? null : s.id)
            }}
          >
            {/* Raised concrete pylon — always rendered (even during drop) so
                the landing parachute has a visible platform to touch down on. */}
            <mesh position={[0, STATION_PLATFORM_HEIGHT / 2, 0]} castShadow>
              <cylinderGeometry args={[0.85, 1.05, STATION_PLATFORM_HEIGHT, 12]} />
              <meshStandardMaterial color="#22262e" roughness={0.8} metalness={0.2} />
            </mesh>
            {/* Platform deck — the surface the crates rest on. */}
            <mesh position={[0, STATION_PLATFORM_HEIGHT + 0.05, 0]} castShadow>
              <cylinderGeometry args={[0.95, 0.95, 0.1, 16]} />
              <meshStandardMaterial color="#1a1d24" roughness={0.7} metalness={0.3} />
            </mesh>
            {/* Crates and halo appear only after the parachute drop completes. */}
            {!isDropping && (
              <>
                <mesh position={[0, STATION_LOWER_CRATE_Y, 0]} castShadow>
                  <boxGeometry args={[1.4, 0.8, 1.4]} />
                  <meshStandardMaterial
                    color="#ff8800"
                    emissive={isSelected ? '#ffdd55' : '#cc5500'}
                    emissiveIntensity={isSelected ? 0.9 : 0.45}
                  />
                </mesh>
                <mesh position={[0, STATION_UPPER_CRATE_Y, 0]} castShadow>
                  <boxGeometry args={[1.1, 0.6, 1.1]} />
                  <meshStandardMaterial
                    color="#ff8800"
                    emissive={isSelected ? '#ffdd55' : '#cc5500'}
                    emissiveIntensity={isSelected ? 0.9 : 0.45}
                  />
                </mesh>
                <mesh
                  ref={mesh => {
                    if (mesh) haloRefs.current.set(s.id, mesh)
                    else haloRefs.current.delete(s.id)
                  }}
                  rotation={[-Math.PI / 2, 0, 0]}
                  position={[0, STATION_PLATFORM_HEIGHT + 0.12, 0]}
                >
                  <ringGeometry args={[1.6, 2.1, 32]} />
                  <meshBasicMaterial color="#ff8800" transparent opacity={0.25} />
                </mesh>
              </>
            )}
          </group>
        )
      })}
    </group>
  )
}
