'use client'

import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'

export function BasePad() {
  const groupRef = useRef<THREE.Group>(null)
  const ringsRef = useRef<THREE.Group>(null)
  const scanRef = useRef<THREE.Mesh>(null)
  const beaconRefs = useRef<THREE.Mesh[]>([])

  const PAD_RADIUS = 5
  const PAD_HEIGHT = 0.12
  const PYLON_HEIGHT = 2.2
  const PYLON_RADIUS = 0.15
  const NUM_PULSE_RINGS = 3

  useFrame(({ clock }) => {
    const t = clock.elapsedTime

    if (scanRef.current) {
      scanRef.current.rotation.set(-Math.PI / 2, 0, t * 0.6)
    }

    beaconRefs.current.forEach((mesh, i) => {
      if (!mesh) return
      const phase = t * 2.0 + i * (Math.PI / 2)
      const pulse = 0.4 + 0.6 * Math.abs(Math.sin(phase))
      ;(mesh.material as THREE.MeshStandardMaterial).emissiveIntensity = pulse
    })

    if (ringsRef.current) {
      ringsRef.current.children.forEach((child, i) => {
        const mesh = child as THREE.Mesh
        const phase = (t * 0.5 + i * (1.0 / NUM_PULSE_RINGS)) % 1.0
        const scale = 0.3 + phase * 1.0
        mesh.scale.set(scale, 1, scale)
        ;(mesh.material as THREE.MeshStandardMaterial).opacity = 0.35 * (1.0 - phase)
      })
    }
  })

  const pylonOffset = PAD_RADIUS * 0.72
  const pylonPositions: [number, number, number][] = [
    [-pylonOffset, 0, -pylonOffset],
    [ pylonOffset, 0, -pylonOffset],
    [-pylonOffset, 0,  pylonOffset],
    [ pylonOffset, 0,  pylonOffset],
  ]

  const PLATFORM_HEIGHT = 1.8  // raised above flood level (1.4m)
  const topY = PLATFORM_HEIGHT + PAD_HEIGHT  // surface level for decals and rings

  return (
    <group ref={groupRef} position={[0, 0, 0]}>
      {/* Raised concrete platform to keep pad above flood */}
      <mesh position={[0, PLATFORM_HEIGHT / 2, 0]}>
        <cylinderGeometry args={[PAD_RADIUS + 0.6, PAD_RADIUS + 1.0, PLATFORM_HEIGHT, 8]} />
        <meshStandardMaterial color="#22262e" roughness={0.8} metalness={0.2} />
      </mesh>
      {/* Landing surface */}
      <mesh position={[0, PLATFORM_HEIGHT + PAD_HEIGHT / 2, 0]}>
        <cylinderGeometry args={[PAD_RADIUS, PAD_RADIUS, PAD_HEIGHT, 8]} />
        <meshStandardMaterial color="#1a1d24" roughness={0.7} metalness={0.3} />
      </mesh>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, topY + 0.02, 0]}>
        <ringGeometry args={[2.6, 3.4, 32]} />
        <meshStandardMaterial
          color="#0e1118"
          emissive="#1a3a5a"
          emissiveIntensity={0.15}
          side={THREE.DoubleSide}
        />
      </mesh>

      {[0, Math.PI / 2].map((rot, i) => (
        <mesh key={`cross-${i}`} position={[0, topY + 0.03, 0]} rotation={[-Math.PI / 2, rot, 0]}>
          <planeGeometry args={[4.8, 0.12]} />
          <meshStandardMaterial
            color="#2a5a7a"
            emissive="#3a8abf"
            emissiveIntensity={0.5}
            side={THREE.DoubleSide}
            transparent
            opacity={0.8}
          />
        </mesh>
      ))}

      <mesh position={[0, topY + 0.06, 0]}>
        <cylinderGeometry args={[0.35, 0.35, 0.06, 16]} />
        <meshStandardMaterial
          color="#00ccff"
          emissive="#00ccff"
          emissiveIntensity={1.2}
        />
      </mesh>

      {[1.6, 3.8].map((r, i) => (
        <mesh key={`ring-${i}`} rotation={[-Math.PI / 2, 0, 0]} position={[0, topY + 0.025, 0]}>
          <ringGeometry args={[r - 0.04, r + 0.04, 48]} />
          <meshStandardMaterial
            color="#1e4060"
            emissive="#2060a0"
            emissiveIntensity={0.3}
            side={THREE.DoubleSide}
            transparent
            opacity={0.7}
          />
        </mesh>
      ))}

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, topY + 0.025, 0]}>
        <ringGeometry args={[4.95, 5.05, 64]} />
        <meshStandardMaterial
          color="#355a7a"
          emissive="#3a7bb4"
          emissiveIntensity={0.35}
          side={THREE.DoubleSide}
          transparent
          opacity={0.65}
        />
      </mesh>

      <mesh ref={scanRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, topY + 0.04, 0]}>
        <ringGeometry args={[0.9, 1.15, 40]} />
        <meshStandardMaterial
          color="#6ec8ff"
          emissive="#3aa8ff"
          emissiveIntensity={0.65}
          transparent
          opacity={0.45}
          side={THREE.DoubleSide}
        />
      </mesh>

      {pylonPositions.map(([x, y, z], i) => (
        <group key={`pylon-${i}`} position={[x, y + PLATFORM_HEIGHT, z]}>
          <mesh
            ref={el => {
              if (el) beaconRefs.current[i] = el
            }}
            position={[0, PAD_HEIGHT + PYLON_HEIGHT / 2, 0]}
          >
            <cylinderGeometry args={[PYLON_RADIUS, PYLON_RADIUS, PYLON_HEIGHT, 10]} />
            <meshStandardMaterial
              color="#88d8ff"
              emissive="#33bbff"
              emissiveIntensity={0.4}
              metalness={0.25}
              roughness={0.35}
            />
          </mesh>
        </group>
      ))}

      <group ref={ringsRef} position={[0, topY + 0.03, 0]}>
        {Array.from({ length: NUM_PULSE_RINGS }, (_, i) => (
          <mesh key={`pulse-${i}`} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[2.8, 2.95, 48]} />
            <meshStandardMaterial
              color="#5ac8ff"
              emissive="#3ab8ff"
              emissiveIntensity={0.2}
              transparent
              opacity={0.25}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        ))}
      </group>
    </group>
  )
}
