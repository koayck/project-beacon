'use client'

import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { survivorKey } from '../../../constants/missionConstants'
import type { SurvivorPoint } from '../../types/worldTypes'

interface SupplyCratesProps {
  deliveredTo: Set<string>
  survivors: SurvivorPoint[]
}

export function SupplyCrates({ deliveredTo, survivors }: SupplyCratesProps) {
  const crates = useMemo(() => {
    return survivors
      .filter(s => deliveredTo.has(survivorKey(s)))
      .map(s => ({ x: s.x, y: s.y, z: s.z }))
  }, [deliveredTo, survivors])

  const groupRef = useRef<THREE.Group>(null)

  useFrame(({ clock }) => {
    if (!groupRef.current) return
    const t = clock.elapsedTime
    groupRef.current.children.forEach((child, i) => {
      child.position.y = crates[i].y - 0.6 + Math.sin(t * 1.5 + i * 2.1) * 0.08
      child.rotation.y = t * 0.4 + i * 1.2
    })
  })

  if (crates.length === 0) return null

  return (
    <group ref={groupRef}>
      {crates.map((pos, i) => (
        <group key={i} position={[pos.x, pos.y - 0.6, pos.z]}>
          <mesh castShadow>
            <boxGeometry args={[0.5, 0.4, 0.5]} />
            <meshStandardMaterial color="#ff8800" emissive="#cc5500" emissiveIntensity={0.4} />
          </mesh>
          <mesh position={[0, 0.01, 0]}>
            <boxGeometry args={[0.52, 0.06, 0.12]} />
            <meshStandardMaterial color="#ffffff" emissive="#aaaaaa" emissiveIntensity={0.3} />
          </mesh>
          <mesh position={[0, 0.01, 0]}>
            <boxGeometry args={[0.12, 0.06, 0.52]} />
            <meshStandardMaterial color="#ffffff" emissive="#aaaaaa" emissiveIntensity={0.3} />
          </mesh>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.19, 0]}>
            <ringGeometry args={[0.35, 0.5, 16]} />
            <meshBasicMaterial color="#ff8800" transparent opacity={0.25} />
          </mesh>
        </group>
      ))}
    </group>
  )
}
