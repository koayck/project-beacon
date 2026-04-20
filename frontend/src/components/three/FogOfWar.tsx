import { useRef, useState, useEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { FOG_PLANE_Y, type SectorBounds } from '@/lib/fogOfWar'

// ── Animated fog tile ──────────────────────────────────────────────────────────

const FOG_BASE_OPACITY = 0.92
const FOG_SHIMMER_AMPLITUDE = 0.03

interface SectorFogProps {
  sector: SectorBounds
  explored: boolean
}

function SectorFog({ sector, explored }: SectorFogProps) {
  const matRef = useRef<THREE.MeshBasicMaterial>(null)
  const targetOpacity = explored ? 0 : FOG_BASE_OPACITY
  const fadeStateRef = useRef<'settled' | 'animating'>('settled')

  useFrame((state, delta) => {
    if (!matRef.current) return
    const current = matRef.current.opacity
    const diff = targetOpacity - current
    const fadeSpeed = explored ? 2.5 : 5

    if (Math.abs(diff) < 0.003) {
      // Snap to target, then apply shimmer as an additive offset so the
      // opacity doesn't drift downward over time.
      if (!explored) {
        const t = state.clock.elapsedTime
        const shimmer = Math.sin(t * 0.4 + sector.col * 1.5 + sector.row * 2.3) * FOG_SHIMMER_AMPLITUDE
        matRef.current.opacity = targetOpacity + shimmer
      } else {
        matRef.current.opacity = targetOpacity
      }
      matRef.current.visible = matRef.current.opacity > 0.01
      fadeStateRef.current = 'settled'
      return
    }

    fadeStateRef.current = 'animating'
    matRef.current.opacity = current + diff * Math.min(delta * fadeSpeed, 1)
    matRef.current.visible = matRef.current.opacity > 0.01
  })

  const cx = (sector.minX + sector.maxX) / 2
  const cz = (sector.minZ + sector.maxZ) / 2
  const w = sector.maxX - sector.minX
  const d = sector.maxZ - sector.minZ

  return (
    <mesh
      position={[cx, FOG_PLANE_Y, cz]}
      rotation={[-Math.PI / 2, 0, 0]}
      renderOrder={999}
    >
      <planeGeometry args={[w, d]} />
      <meshBasicMaterial
        ref={matRef}
        color="#06080e"
        transparent
        opacity={FOG_BASE_OPACITY}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  )
}

// ── Reveal pulse ring ──────────────────────────────────────────────────────────

interface RevealPulseProps {
  sector: SectorBounds
}

function RevealPulse({ sector }: RevealPulseProps) {
  const ringRef = useRef<THREE.Mesh>(null)
  const matRef = useRef<THREE.MeshBasicMaterial>(null)
  const progressRef = useRef(0)

  const cx = (sector.minX + sector.maxX) / 2
  const cz = (sector.minZ + sector.maxZ) / 2
  const maxRadius = Math.max(sector.maxX - sector.minX, sector.maxZ - sector.minZ) * 0.6

  useFrame((_, delta) => {
    if (!ringRef.current || !matRef.current) return
    progressRef.current += delta * 1.8 // ~0.55s animation
    const p = Math.min(progressRef.current, 1)

    const eased = 1 - Math.pow(1 - p, 3) // ease-out cubic
    const scale = 0.2 + eased * 0.8
    ringRef.current.scale.set(scale, scale, 1)
    matRef.current.opacity = (1 - p) * 0.6

    if (p >= 1) {
      ringRef.current.visible = false
    }
  })

  return (
    <mesh
      ref={ringRef}
      position={[cx, FOG_PLANE_Y + 0.05, cz]}
      rotation={[-Math.PI / 2, 0, 0]}
      renderOrder={1001}
    >
      <ringGeometry args={[maxRadius * 0.85, maxRadius, 32]} />
      <meshBasicMaterial
        ref={matRef}
        color="#20c0e0"
        transparent
        opacity={0.6}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  )
}

// ── Explored sector border glow ────────────────────────────────────────────────

interface SectorBorderGlowProps {
  sectors: SectorBounds[]
  exploredSectors: Set<string>
}

function SectorBorderGlow({ sectors, exploredSectors }: SectorBorderGlowProps) {
  const geometry = useMemo(() => {
    const points: THREE.Vector3[] = []
    const gridY = FOG_PLANE_Y + 0.02

    for (const s of sectors) {
      if (!exploredSectors.has(s.id)) continue
      points.push(
        new THREE.Vector3(s.minX, gridY, s.minZ),
        new THREE.Vector3(s.maxX, gridY, s.minZ),
        new THREE.Vector3(s.maxX, gridY, s.minZ),
        new THREE.Vector3(s.maxX, gridY, s.maxZ),
        new THREE.Vector3(s.maxX, gridY, s.maxZ),
        new THREE.Vector3(s.minX, gridY, s.maxZ),
        new THREE.Vector3(s.minX, gridY, s.maxZ),
        new THREE.Vector3(s.minX, gridY, s.minZ),
      )
    }

    if (points.length === 0) return null
    return new THREE.BufferGeometry().setFromPoints(points)
  }, [sectors, exploredSectors])

  // Dispose the previous GPU buffer when a new geometry takes its place.
  useEffect(() => {
    return () => {
      geometry?.dispose()
    }
  }, [geometry])

  if (!geometry) return null

  return (
    <lineSegments geometry={geometry} renderOrder={1000}>
      <lineBasicMaterial color="#2090b0" opacity={0.35} transparent linewidth={1} />
    </lineSegments>
  )
}

// ── Main FogOfWar component ────────────────────────────────────────────────────

interface FogOfWarProps {
  sectors: SectorBounds[]
  exploredSectors: Set<string>
  lastRevealedSector?: string | null
}

export function FogOfWar({ sectors, exploredSectors, lastRevealedSector }: FogOfWarProps) {
  // Track which sectors have had their pulse animation played.
  const [pulsingIds, setPulsingIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!lastRevealedSector) return
    setPulsingIds(prev => {
      if (prev.has(lastRevealedSector)) return prev
      const next = new Set(prev)
      next.add(lastRevealedSector)
      return next
    })
  }, [lastRevealedSector])

  return (
    <group>
      {sectors.map(sector => (
        <SectorFog
          key={sector.id}
          sector={sector}
          explored={exploredSectors.has(sector.id)}
        />
      ))}

      {sectors
        .filter(s => pulsingIds.has(s.id))
        .map(sector => (
          <RevealPulse key={`pulse-${sector.id}`} sector={sector} />
        ))}

      <SectorBorderGlow sectors={sectors} exploredSectors={exploredSectors} />
    </group>
  )
}
