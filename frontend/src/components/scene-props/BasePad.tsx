'use client'

import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'

export function BasePad() {
  const beaconRef = useRef<THREE.Mesh>(null)
  const perimeterLightsRef = useRef<THREE.Group>(null)

  const PAD_RADIUS = 5
  const PAD_HEIGHT = 0.15
  const PLATFORM_HEIGHT = 1.8 // raised above flood level (1.4m)
  const topY = PLATFORM_HEIGHT + PAD_HEIGHT

  useFrame(({ clock }) => {
    const t = clock.elapsedTime

    if (beaconRef.current) {
      // Sharp rotating-beacon pulse (like an aviation obstruction light)
      const pulse = Math.pow(Math.sin(t * 2.2) * 0.5 + 0.5, 6)
      ;(beaconRef.current.material as THREE.MeshStandardMaterial).emissiveIntensity =
        0.3 + pulse * 2.2
    }

    if (perimeterLightsRef.current) {
      perimeterLightsRef.current.children.forEach((child, i) => {
        const mesh = child as THREE.Mesh
        const glow = 0.85 + 0.15 * Math.sin(t * 1.3 + i * 0.6)
        ;(mesh.material as THREE.MeshStandardMaterial).emissiveIntensity = glow
      })
    }
  })

  const NUM_LIGHTS = 12
  const perimeterPositions: [number, number][] = Array.from({ length: NUM_LIGHTS }, (_, i) => {
    const angle = (i / NUM_LIGHTS) * Math.PI * 2
    return [Math.cos(angle) * (PAD_RADIUS - 0.3), Math.sin(angle) * (PAD_RADIUS - 0.3)]
  })

  // "H" marking geometry (painted on the deck)
  const H_HEIGHT = 3.2
  const H_WIDTH = 2.4
  const H_STROKE = 0.45
  const H_Y = topY + 0.015
  const H_OFFSET_X = H_WIDTH / 2 - H_STROKE / 2

  return (
    <group position={[0, 0, 0]}>
      {/* Raised concrete pedestal */}
      <mesh position={[0, PLATFORM_HEIGHT / 2, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[PAD_RADIUS + 0.5, PAD_RADIUS + 0.9, PLATFORM_HEIGHT, 32]} />
        <meshStandardMaterial color="#6a6a6a" roughness={0.95} metalness={0.05} />
      </mesh>

      {/* Concrete landing deck */}
      <mesh position={[0, PLATFORM_HEIGHT + PAD_HEIGHT / 2, 0]} receiveShadow>
        <cylinderGeometry args={[PAD_RADIUS, PAD_RADIUS, PAD_HEIGHT, 48]} />
        <meshStandardMaterial color="#3f3f3f" roughness={0.9} metalness={0.02} />
      </mesh>

      {/* Outer painted ring (FATO boundary) */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, topY + 0.005, 0]}>
        <ringGeometry args={[PAD_RADIUS - 0.35, PAD_RADIUS - 0.2, 64]} />
        <meshStandardMaterial
          color="#e8e8e8"
          roughness={0.85}
          metalness={0}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Inner painted ring (TLOF boundary) */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, topY + 0.008, 0]}>
        <ringGeometry args={[PAD_RADIUS - 1.55, PAD_RADIUS - 1.45, 64]} />
        <meshStandardMaterial
          color="#d8d8d8"
          roughness={0.85}
          metalness={0}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Painted "H" — left leg */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[-H_OFFSET_X, H_Y, 0]}>
        <planeGeometry args={[H_STROKE, H_HEIGHT]} />
        <meshStandardMaterial
          color="#f0f0f0"
          roughness={0.85}
          metalness={0}
          side={THREE.DoubleSide}
        />
      </mesh>
      {/* Painted "H" — right leg */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[H_OFFSET_X, H_Y, 0]}>
        <planeGeometry args={[H_STROKE, H_HEIGHT]} />
        <meshStandardMaterial
          color="#f0f0f0"
          roughness={0.85}
          metalness={0}
          side={THREE.DoubleSide}
        />
      </mesh>
      {/* Painted "H" — crossbar */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, H_Y, 0]}>
        <planeGeometry args={[H_WIDTH - H_STROKE * 2 + 0.04, H_STROKE]} />
        <meshStandardMaterial
          color="#f0f0f0"
          roughness={0.85}
          metalness={0}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Green perimeter heliport lights */}
      <group ref={perimeterLightsRef} position={[0, topY + 0.06, 0]}>
        {perimeterPositions.map(([x, z], i) => (
          <mesh key={`perim-${i}`} position={[x, 0, z]}>
            <sphereGeometry args={[0.09, 10, 10]} />
            <meshStandardMaterial
              color="#a6ffb4"
              emissive="#2cff5c"
              emissiveIntensity={1.0}
              toneMapped={false}
            />
          </mesh>
        ))}
      </group>

      {/* Aviation obstruction light mast (offset to corner) */}
      <group position={[PAD_RADIUS * 0.82, 0, PAD_RADIUS * 0.82]}>
        <mesh position={[0, PLATFORM_HEIGHT + 1.15, 0]}>
          <cylinderGeometry args={[0.05, 0.06, 2.3, 8]} />
          <meshStandardMaterial color="#cfcfcf" roughness={0.5} metalness={0.7} />
        </mesh>
        <mesh ref={beaconRef} position={[0, PLATFORM_HEIGHT + 2.35, 0]}>
          <sphereGeometry args={[0.14, 12, 12]} />
          <meshStandardMaterial
            color="#ff3b3b"
            emissive="#ff0020"
            emissiveIntensity={1.2}
            toneMapped={false}
          />
        </mesh>
      </group>
    </group>
  )
}
