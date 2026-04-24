'use client'

import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'
import { DRONE_START } from '../../../constants/missionConstants'

interface DroneProps {
  targetPos: THREE.Vector3
  status: string
  hasCargo: boolean
  nearbyObstacles?: number
  nearestObstacleDist?: number
  survivorsInRange?: number
  assetId?: string
  headingDeg?: number
  scanTiltDeg?: number
  battery?: number
}

export function DroneMesh({
  targetPos,
  status,
  hasCargo,
  nearbyObstacles = 0,
  nearestObstacleDist = 999,
  survivorsInRange = 0,
  assetId = '',
  headingDeg = 0,
  scanTiltDeg = 0,
  battery,
}: DroneProps) {
  const isScout = assetId === 'BEACON-SCOUT'

  void nearbyObstacles
  void nearestObstacleDist
  void survivorsInRange

  const groupRef = useRef<THREE.Group>(null)
  const cargoRef = useRef<THREE.Mesh>(null)
  const coneRef = useRef<THREE.Mesh>(null)
  const spotlightRef = useRef<THREE.Group>(null)
  const lerpPos = useRef(DRONE_START.clone())

  // Scout spotlight shows only once the drone reaches cruise altitude
  // (SCOUT_ALTITUDE = 35m in backend/services/scout.py). 28m ≈ 80% climb.
  const SCOUT_SPOTLIGHT_MIN_Y = 28

  const statusRef = useRef(status)
  const headingDegRef = useRef(headingDeg)
  const scanTiltDegRef = useRef(scanTiltDeg)
  statusRef.current = status
  headingDegRef.current = headingDeg
  scanTiltDegRef.current = scanTiltDeg

  const inScanSessionRef = useRef(false)
  if (status === 'SCANNING') inScanSessionRef.current = true
  if (status === 'IDLE' || status === 'RETURNING' || status === 'BLOCKED' || status === 'ERROR') {
    inScanSessionRef.current = false
  }

  const scanFovHalfDeg = 30
  const scanFovRange = 3
  const coneRadius = scanFovRange * Math.tan((scanFovHalfDeg * Math.PI) / 180)

  useFrame((_, delta) => {
    if (!groupRef.current) return
    lerpPos.current.lerp(targetPos, Math.min(delta * 4, 1))
    groupRef.current.position.copy(lerpPos.current)

    if (coneRef.current) {
      const headingRad = (headingDegRef.current * Math.PI) / 180
      const tiltRad = (scanTiltDegRef.current * Math.PI) / 180
      const cosT = Math.cos(tiltRad)
      const scanDirX = Math.sin(headingRad) * cosT
      const scanDirY = Math.sin(tiltRad)
      const scanDirZ = -Math.cos(headingRad) * cosT

      const half = scanFovRange / 2
      coneRef.current.position.set(
        lerpPos.current.x + scanDirX * half,
        lerpPos.current.y + scanDirY * half,
        lerpPos.current.z + scanDirZ * half,
      )
      const baseDir = new THREE.Vector3(scanDirX, scanDirY, scanDirZ)
      if (baseDir.lengthSq() > 1e-6) {
        coneRef.current.quaternion.setFromUnitVectors(
          new THREE.Vector3(0, -1, 0),
          baseDir.normalize(),
        )
      }
      coneRef.current.visible = inScanSessionRef.current
    }

    if (cargoRef.current) {
      cargoRef.current.position.set(0, -0.55, 0)
      cargoRef.current.visible = hasCargo
    }

    if (spotlightRef.current) {
      spotlightRef.current.visible = isScout && lerpPos.current.y >= SCOUT_SPOTLIGHT_MIN_Y
    }

    let bodyColor: number
    let emissiveColor: number
    if (isScout) {
      bodyColor = 0xffcc00
      emissiveColor = 0xaa8800
    } else if (status === 'BLOCKED') {
      bodyColor = 0xff2200
      emissiveColor = 0x880000
    } else if (status === 'MOVING') {
      bodyColor = 0x00ff88
      emissiveColor = 0x00aa44
    } else if (status === 'SCANNING') {
      bodyColor = 0xffaa00
      emissiveColor = 0xaa6600
    } else {
      bodyColor = 0x00ffff
      emissiveColor = 0x00aaaa
    }

    groupRef.current.traverse(child => {
      const mesh = child as THREE.Mesh
      if (!mesh.isMesh) return
      const mat = mesh.material as THREE.Material
      // Only recolour drone body meshes (MeshStandardMaterial). Helpers like
      // the scout spotlight use MeshBasicMaterial which has no `emissive`.
      if (!(mat as THREE.MeshStandardMaterial).isMeshStandardMaterial) return
      const std = mat as THREE.MeshStandardMaterial
      std.color.setHex(bodyColor)
      std.emissive.setHex(emissiveColor)
    })
  })

  const rotorPositions: [number, number, number][] = [
    [0.48, 0.06, 0], [-0.48, 0.06, 0],
    [0, 0.06, 0.48], [0, 0.06, -0.48],
  ]

  return (
    <>
      <group ref={groupRef} position={DRONE_START.toArray()}>
        <mesh>
          <boxGeometry args={[0.38, 0.10, 0.38]} />
          <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} />
        </mesh>
        <mesh ref={cargoRef} position={[0, -0.55, 0]} visible={false}>
          <boxGeometry args={[0.4, 0.3, 0.4]} />
          <meshStandardMaterial color="#ff8800" emissive="#cc5500" emissiveIntensity={0.4} />
        </mesh>
        <mesh>
          <boxGeometry args={[0.96, 0.05, 0.07]} />
          <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} />
        </mesh>
        <mesh>
          <boxGeometry args={[0.07, 0.05, 0.96]} />
          <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} />
        </mesh>
        {rotorPositions.map((pos, i) => (
          <mesh key={i} position={pos} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.19, 0.19, 0.025, 12]} />
            <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} transparent opacity={0.75} />
          </mesh>
        ))}
        {assetId && (
          <Html position={[0, 0.9, 0]} center distanceFactor={14} zIndexRange={[0, 0]}>
            <div className="pointer-events-none whitespace-nowrap rounded-[3px] border border-[rgba(0,255,255,0.4)] bg-[rgba(0,16,24,0.82)] px-[7px] py-[2px] font-mono text-[48px] font-bold tracking-[0.05em] text-[#00ffff]">
              {isScout ? 'SCOUT' : (assetId ?? 'BEACON-01')}
              {battery !== undefined && (
                <span className={`ml-[8px] text-[36px] font-normal ${
                  battery > 50 ? 'text-[#44cc66]' : battery > 20 ? 'text-[#ffcc00]' : 'text-[#ff3333]'
                }`}>
                  {Math.round(battery)}%
                </span>
              )}
            </div>
          </Html>
        )}
        {/* Scout spotlight — a wide downward cone reaching the ground from
            the scout's cruise altitude (~35m). Lives inside the drone group
            so it translates with the scout. */}
        {isScout && (
          <group ref={spotlightRef} position={[0, -17.5, 0]} visible={false}>
            <mesh>
              <coneGeometry args={[14, 35, 32, 1, true]} />
              <meshBasicMaterial
                color="#ffcc00"
                transparent
                opacity={0.08}
                side={THREE.DoubleSide}
                depthWrite={false}
              />
            </mesh>
            {/* Inner bright core for visual definition */}
            <mesh>
              <coneGeometry args={[5, 35, 24, 1, true]} />
              <meshBasicMaterial
                color="#fff0b0"
                transparent
                opacity={0.05}
                side={THREE.DoubleSide}
                depthWrite={false}
              />
            </mesh>
          </group>
        )}
      </group>
      <mesh ref={coneRef} position={DRONE_START.toArray()} visible={false}>
        <coneGeometry args={[coneRadius, scanFovRange, 32, 1, true]} />
        <meshStandardMaterial
          color="#ffaa00"
          transparent
          opacity={0.35}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
    </>
  )
}