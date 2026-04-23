'use client'

import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { SupplyStation } from '../../lib/api'

interface SupplyStationsProps {
  stations: SupplyStation[]
  selectedId: string | null
  onSelect: (id: string | null) => void
}

export function SupplyStations({ stations, selectedId, onSelect }: SupplyStationsProps) {
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
        return (
          <group
            key={s.id}
            position={[s.x, 0, s.z]}
            onClick={e => {
              e.stopPropagation()
              onSelect(isSelected ? null : s.id)
            }}
          >
            {/* Lower crate */}
            <mesh position={[0, 0.4, 0]} castShadow>
              <boxGeometry args={[1.4, 0.8, 1.4]} />
              <meshStandardMaterial
                color="#ff8800"
                emissive={isSelected ? '#ffdd55' : '#cc5500'}
                emissiveIntensity={isSelected ? 0.9 : 0.45}
              />
            </mesh>
            {/* Upper crate */}
            <mesh position={[0, 1.2, 0]} castShadow>
              <boxGeometry args={[1.1, 0.6, 1.1]} />
              <meshStandardMaterial
                color="#ff8800"
                emissive={isSelected ? '#ffdd55' : '#cc5500'}
                emissiveIntensity={isSelected ? 0.9 : 0.45}
              />
            </mesh>
            {/* Pulsing halo ring at ground level */}
            <mesh
              ref={mesh => {
                if (mesh) haloRefs.current.set(s.id, mesh)
                else haloRefs.current.delete(s.id)
              }}
              rotation={[-Math.PI / 2, 0, 0]}
              position={[0, 0.02, 0]}
            >
              <ringGeometry args={[1.6, 2.1, 32]} />
              <meshBasicMaterial color="#ff8800" transparent opacity={0.25} />
            </mesh>
          </group>
        )
      })}
    </group>
  )
}
