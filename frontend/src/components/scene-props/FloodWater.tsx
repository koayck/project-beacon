'use client'

import { useFrame } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import * as THREE from 'three'

interface FloodWaterProps {
  span: number
  floodLevel: number
  segments?: number
}

export function FloodWater({ span, floodLevel, segments = 50 }: FloodWaterProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const geoRef = useRef<THREE.PlaneGeometry>(null)
  const timeRef = useRef(0)

  useEffect(() => {
    if (meshRef.current) meshRef.current.raycast = () => {}
  }, [])

  useFrame((_, delta) => {
    timeRef.current += delta
    const t = timeRef.current

    if (geoRef.current) {
      const pos = geoRef.current.attributes.position as THREE.BufferAttribute
      for (let i = 0; i < pos.count; i++) {
        const vx = pos.getX(i)
        const vy = pos.getY(i)
        const wave =
          Math.sin(vx * 0.18 + t * 1.4) * 0.10 +
          Math.sin(vy * 0.14 + t * 1.1) * 0.08 +
          Math.sin((vx - vy) * 0.10 + t * 0.7) * 0.05
        pos.setZ(i, wave)
      }
      pos.needsUpdate = true
      geoRef.current.computeVertexNormals()
    }
  })

  return (
    <mesh ref={meshRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, floodLevel, 0]} renderOrder={2}>
      <planeGeometry ref={geoRef} args={[span, span, segments, segments]} />
      <meshStandardMaterial
        color="#1a5a9e"
        transparent
        opacity={0.68}
        roughness={0.06}
        metalness={0.2}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  )
}
