'use client'

import { Html } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef, type MutableRefObject, type RefObject } from 'react'
import * as THREE from 'three'
import { SurvivorPoint } from '../../types/worldTypes'


const THROW_DURATION = 1.2

export function SupplyThrow({
  from,
  to,
  onComplete,
}: {
  from: THREE.Vector3
  to: SurvivorPoint
  onComplete: () => void
}) {
  const meshRef = useRef<THREE.Mesh>(null)
  const progress = useRef(0)
  const startPos = useRef(from.clone())

  useFrame((_, delta) => {
    if (!meshRef.current) return
    progress.current += delta / THROW_DURATION
    const t = Math.min(progress.current, 1)

    const x = startPos.current.x + (to.x - startPos.current.x) * t
    const z = startPos.current.z + (to.z - startPos.current.z) * t
    const arc = 4 * t * (1 - t) * 1.2
    const y = startPos.current.y + (to.y - startPos.current.y) * t + arc

    meshRef.current.position.set(x, y, z)
    meshRef.current.rotation.x += delta * 5
    meshRef.current.rotation.z += delta * 3

    if (t >= 1) onComplete()
  })

  return (
    <mesh ref={meshRef} position={startPos.current.toArray()}>
      <boxGeometry args={[0.35, 0.28, 0.35]} />
      <meshStandardMaterial color="#ff8800" emissive="#cc5500" emissiveIntensity={0.5} />
    </mesh>
  )
}

