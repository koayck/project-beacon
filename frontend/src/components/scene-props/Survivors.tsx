'use client'

import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'
import type { SurvivorPoint } from '../../types/worldTypes'

function survivorKey(s: SurvivorPoint): string {
  return `${s.x.toFixed(1)},${s.y.toFixed(1)},${s.z.toFixed(1)}`
}

function SurvivorHuman({
  pos,
  floodY,
  index,
  supplied,
  detected,
}: {
  pos: SurvivorPoint
  floodY: number
  index: number
  supplied: boolean
  detected: boolean
}) {
  const groupRef = useRef<THREE.Group>(null)

  useFrame(({ clock }) => {
    if (!groupRef.current) return
    const t = clock.elapsedTime
    if (supplied) {
      groupRef.current.scale.setScalar(1 + Math.sin(t * 1.5 + index * 0.9) * 0.06)
    } else if (detected) {
      groupRef.current.scale.setScalar(1 + Math.sin(t * 2.5 + index * 0.9) * 0.12)
    } else {
      const submerged = pos.y < floodY - 0.2
      const speed = submerged ? 6 : 3
      const pulse = 1 + Math.sin(t * speed + index * 0.9) * 0.18
      groupRef.current.scale.setScalar(pulse)
    }

    const submerged = pos.y < floodY - 0.2
    const bodyColor = supplied ? 0x22dd66 : (detected ? 0xffd84d : (submerged ? 0xff8800 : 0xff2222))
    const emissiveColor = supplied ? 0x11aa44 : (detected ? 0xccaa11 : (submerged ? 0xcc4400 : 0xff0000))
    const emissiveIntensity = supplied ? 0.5 : (detected ? 0.6 : (submerged ? 0.7 : 0.45))
    groupRef.current.traverse(child => {
      if ((child as THREE.Mesh).isMesh) {
        const mat = (child as THREE.Mesh).material as THREE.MeshStandardMaterial
        mat.color.setHex(bodyColor)
        mat.emissive.setHex(emissiveColor)
        mat.emissiveIntensity = emissiveIntensity
      }
    })
  })

  const submerged = pos.y < floodY - 0.2
  const color = supplied ? '#22dd66' : (detected ? '#ffd84d' : (submerged ? '#ff8800' : '#ff2222'))
  const emissive = supplied ? '#11aa44' : (detected ? '#ccaa11' : (submerged ? '#cc4400' : '#ff0000'))

  return (
    <group ref={groupRef} position={[pos.x, pos.y, pos.z]}>
      <mesh position={[0, 0.33, 0]}>
        <sphereGeometry args={[0.11, 8, 6]} />
        <meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.45} />
      </mesh>
      <mesh position={[0, 0.10, 0]}>
        <boxGeometry args={[0.18, 0.26, 0.10]} />
        <meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.45} />
      </mesh>
      <mesh position={[-0.14, 0.08, 0]} rotation={[0, 0, 0.35]}>
        <boxGeometry args={[0.07, 0.22, 0.07]} />
        <meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.45} />
      </mesh>
      <mesh position={[0.14, 0.08, 0]} rotation={[0, 0, -0.35]}>
        <boxGeometry args={[0.07, 0.22, 0.07]} />
        <meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.45} />
      </mesh>
      <mesh position={[-0.06, -0.17, 0]}>
        <boxGeometry args={[0.07, 0.22, 0.08]} />
        <meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.45} />
      </mesh>
      <mesh position={[0.06, -0.17, 0]}>
        <boxGeometry args={[0.07, 0.22, 0.08]} />
        <meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.45} />
      </mesh>
    </group>
  )
}

export function Survivors({
  floodY,
  survivors,
  deliveredTo,
  detectedSurvivors,
}: {
  floodY: number
  survivors: SurvivorPoint[]
  deliveredTo?: Set<string>
  detectedSurvivors?: Set<string>
}) {
  const delivered = deliveredTo ?? new Set<string>()
  const detected = detectedSurvivors ?? new Set<string>()
  return (
    <>
      {survivors.map((pos, i) => (
        <SurvivorHuman
          key={i}
          pos={pos}
          floodY={floodY}
          index={i}
          supplied={delivered.has(survivorKey(pos))}
          detected={detected.has(survivorKey(pos))}
        />
      ))}
    </>
  )
}
