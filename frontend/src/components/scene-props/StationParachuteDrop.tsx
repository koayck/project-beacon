'use client'

import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'
import { STATION_LOWER_CRATE_Y } from './SupplyStations'

interface StationParachuteDropProps {
  x: number
  z: number
  /** Called once the crate touches down on the platform. */
  onComplete: () => void
}

const DROP_START_Y = 28.0
// Seconds of descent + parachute fade.
const DESCENT_SECONDS = 2.2
const FADE_SECONDS = 0.45
// Horizontal sway amplitude as the parachute descends.
const SWAY_AMPLITUDE = 0.5

/**
 * One-shot air-drop animation: a crate with a rounded parachute canopy falls
 * from the sky onto the station platform, then the canopy fades away. After
 * fade-out, `onComplete` fires so the controller can reveal the static
 * station in its place.
 */
export function StationParachuteDrop({ x, z, onComplete }: StationParachuteDropProps) {
  const groupRef = useRef<THREE.Group>(null)
  const canopyRef = useRef<THREE.Mesh>(null)
  const stringsRef = useRef<THREE.Group>(null)
  const startTimeRef = useRef<number | null>(null)
  const completedRef = useRef(false)

  useFrame(({ clock }) => {
    if (!groupRef.current) return
    if (startTimeRef.current === null) startTimeRef.current = clock.elapsedTime
    const elapsed = clock.elapsedTime - startTimeRef.current

    // Position: linear descent then settle on the platform-top crate seat.
    const descentT = Math.min(elapsed / DESCENT_SECONDS, 1.0)
    // Ease out (decelerate) so the crate feels like it's being caught by the
    // parachute rather than free-falling the whole way.
    const easedT = 1 - Math.pow(1 - descentT, 2)
    const y = DROP_START_Y + (STATION_LOWER_CRATE_Y - DROP_START_Y) * easedT
    // Gentle sway that dampens as it lands.
    const swayFactor = (1 - descentT) * SWAY_AMPLITUDE
    const sway = Math.sin(elapsed * 2.2) * swayFactor
    groupRef.current.position.set(x + sway, y, z)

    // Fade the parachute canopy + strings after touchdown.
    if (descentT >= 1.0) {
      const fadeT = Math.min((elapsed - DESCENT_SECONDS) / FADE_SECONDS, 1.0)
      const opacity = 1 - fadeT
      if (canopyRef.current) {
        const mat = canopyRef.current.material as THREE.MeshStandardMaterial
        mat.opacity = 0.85 * opacity
      }
      if (stringsRef.current) {
        stringsRef.current.children.forEach(child => {
          const mesh = child as THREE.Mesh
          const mat = mesh.material as THREE.MeshBasicMaterial
          mat.opacity = opacity
        })
      }
      if (fadeT >= 1.0 && !completedRef.current) {
        completedRef.current = true
        onComplete()
      }
    }
  })

  // Four strings from canopy rim down to the crate top corners.
  const stringOffsets: [number, number][] = [
    [-0.5, -0.5],
    [ 0.5, -0.5],
    [-0.5,  0.5],
    [ 0.5,  0.5],
  ]
  // Strings visually connect canopy (y ≈ crateCenter + 2.1) to crate top (crateCenter + 0.4).
  const STRING_LENGTH = 1.7
  const STRING_MID_Y = 0.4 + STRING_LENGTH / 2 + 0.1  // crate-top + half string

  return (
    <group ref={groupRef}>
      {/* Crate (same silhouette as the station's lower crate) */}
      <mesh castShadow>
        <boxGeometry args={[1.4, 0.8, 1.4]} />
        <meshStandardMaterial
          color="#ff8800"
          emissive="#cc5500"
          emissiveIntensity={0.55}
        />
      </mesh>

      {/* Parachute strings */}
      <group ref={stringsRef}>
        {stringOffsets.map(([sx, sz], i) => (
          <mesh key={i} position={[sx, STRING_MID_Y, sz]}>
            <cylinderGeometry args={[0.02, 0.02, STRING_LENGTH, 6]} />
            <meshBasicMaterial color="#d8d0c0" transparent opacity={1} />
          </mesh>
        ))}
      </group>

      {/* Parachute canopy (hemispheric dome) */}
      <mesh
        ref={canopyRef}
        position={[0, 0.4 + STRING_LENGTH + 0.1, 0]}
      >
        <sphereGeometry args={[1.3, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial
          color="#ff9944"
          emissive="#cc5500"
          emissiveIntensity={0.3}
          side={THREE.DoubleSide}
          transparent
          opacity={0.85}
        />
      </mesh>
      {/* Canopy rim — subtle darker band for definition */}
      <mesh
        position={[0, 0.4 + STRING_LENGTH + 0.1, 0]}
        rotation={[-Math.PI / 2, 0, 0]}
      >
        <ringGeometry args={[1.25, 1.32, 20]} />
        <meshBasicMaterial color="#aa4400" side={THREE.DoubleSide} transparent opacity={0.6} />
      </mesh>

      {/* Glowing halo under the crate as it lands */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.4, 0]}>
        <ringGeometry args={[0.8, 1.2, 20]} />
        <meshBasicMaterial color="#ffaa44" transparent opacity={0.35} />
      </mesh>
    </group>
  )
}

