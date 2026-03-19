'use client'

import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

// ── Colors ──────────────────────────────────────────────────────────────────────

const C_ROAD      = '#2c2c32'
const C_LINE      = '#D7CDA5'
const C_PARK      = '#286C34'
const C_TRUNK     = '#5F4126'
const C_LEAF      = '#267632'
const C_CANAL     = '#1a4a7a'
const C_SLAB      = '#94A2AF'
const C_GLASSBAND = '#AAD2F0'

// ── Shophouses (Thai pastel colors, 4m wide, 12m deep, 3–4 stories) ────────────
//
// Mission building clearance zones (3m buffer):
//   B0: x[-23,-7]  z[-25.5,-4.5]   B1: x[19.5,40.5] z[-34,-16]
//   B2: x[-38,-12] z[9.5,30.5]     B3: x[11,29]     z[17,33]
//   B4: x[-45,-25] z[-40,-20]      B5: x[3,17]       z[-17,-3]
//
// Each entry: [cx, cz, w, d, h, bodyColor, roofColor]

const SHOPHOUSES: readonly (readonly [number, number, number, number, number, string, string])[] = [
  // ── Row A: z=38, east side only (west side blocked by B2/B3) ──────────────────
  [ 34, 38, 4, 12,  9, '#F5E6C8', '#E8D5B0'],
  [ 38, 38, 4, 12, 12, '#B5D4E8', '#A0C4D8'],
  [-42, 38, 4, 12, 12, '#F0E0A8', '#F5E8A0'],
  [-46, 38, 4, 12,  9, '#E8B5B0', '#D4A09A'],
  [-50, 38, 4, 12, 12, '#B0D8C0', '#A0C8B0'],

  // ── Row B: z=-42, avoiding B1 (x 19.5–40.5) and B4 (x -45–-25) ──────────────
  [ -6, -42, 4, 12, 12, '#C2DDE8', '#B5D4E8'],
  [-10, -42, 4, 12,  9, '#F5E6C8', '#E8D5B0'],
  [-14, -42, 4, 12, 12, '#E8B5B0', '#D4A09A'],
  [-18, -42, 4, 12,  9, '#F5E8A0', '#E8DC90'],
  [-22, -42, 4, 12, 12, '#B0D8C0', '#A0C8B0'],
  [  6, -42, 4, 12,  9, '#E8E4E0', '#D8D4D0'],
  [ 10, -42, 4, 12, 12, '#C89478', '#B88468'],
  [ 14, -42, 4, 12,  9, '#F0C4BE', '#E8B5B0'],
  [ 18, -42, 4, 12, 12, '#D4A09A', '#C89488'],

  // ── Row C: x=42, N-S oriented (12m wide, 4m deep), clear of all ──────────────
  [ 42, -12, 12, 4,  9, '#F5E6C8', '#E8D5B0'],
  [ 42,  -8, 12, 4, 12, '#B5D4E8', '#A0C4D8'],
  [ 42,  -4, 12, 4,  9, '#F5E8A0', '#E8DC90'],
  [ 42,   0, 12, 4, 12, '#E8B5B0', '#D4A09A'],
  [ 42,   4, 12, 4,  9, '#B0D8C0', '#A0C8B0'],
  [ 42,   8, 12, 4, 12, '#E8E4E0', '#D8D4D0'],
  [ 42,  12, 12, 4,  9, '#C89478', '#B88468'],

  // ── Row D: x=-50, N-S oriented, clear of all ─────────────────────────────────
  [-50, -12, 12, 4, 12, '#C2DDE8', '#B5D4E8'],
  [-50,  -8, 12, 4,  9, '#F0C4BE', '#E8B5B0'],
  [-50,  -4, 12, 4, 12, '#F0E0A8', '#F5E8A0'],
  [-50,   0, 12, 4,  9, '#D4A09A', '#C89488'],
  [-50,   4, 12, 4, 12, '#C0E0D0', '#B0D8C0'],
  [-50,   8, 12, 4,  9, '#F0ECE8', '#E8E4E0'],

  // ── Row E: z=52 (secondary road), wide spread ────────────────────────────────
  [  6, 52, 4, 12,  9, '#F5E6C8', '#E8D5B0'],
  [ 10, 52, 4, 12, 12, '#B5D4E8', '#A0C4D8'],
  [ 14, 52, 4, 12,  9, '#E8B5B0', '#D4A09A'],
  [ 18, 52, 4, 12, 12, '#F5E8A0', '#E8DC90'],
  [ 22, 52, 4, 12,  9, '#B0D8C0', '#A0C8B0'],
  [ -6, 52, 4, 12, 12, '#E8E4E0', '#D8D4D0'],
  [-10, 52, 4, 12,  9, '#F0C4BE', '#E8B5B0'],
  [-14, 52, 4, 12, 12, '#C2DDE8', '#B5D4E8'],

  // ── Row F: z=-52 (secondary road south) ───────────────────────────────────────
  [ -6, -52, 4, 12, 12, '#C89478', '#B88468'],
  [-10, -52, 4, 12,  9, '#E8E4E0', '#D8D4D0'],
  [-14, -52, 4, 12, 12, '#F0C4BE', '#E8B5B0'],
  [-18, -52, 4, 12,  9, '#D4A09A', '#C89488'],
  [ 42, -52, 4, 12,  9, '#F5E6C8', '#E8D5B0'],
  [ 46, -52, 4, 12, 12, '#B5D4E8', '#A0C4D8'],
] as const  // 41 shophouses

// ── Mid-rise commercial / residential (5–10 stories, 15–30m) ────────────────────
// All placed well outside mission building clearance zones.

const MIDRISE_BUILDINGS: readonly (readonly [number, number, number, number, number, string, string])[] = [
  // Perimeter anchors
  [ 55,  45, 16, 14, 24, '#466291', '#5A76A5'],   // 8-story hotel NE
  [-55, -50, 14, 14, 21, '#374E76', '#4B628A'],   // 7-story commercial SW
  [ 50, -50, 14, 14, 30, '#303E52', '#445266'],   // 10-story condo SE
  [-55,  45, 16, 14, 21, '#52769E', '#668AB2'],   // 7-story office NW
  [ 60,   0, 14, 16, 15, '#A86C48', '#B9805A'],   // 5-story mixed-use E
  [-60,   0, 14, 16, 18, '#34486E', '#485C82'],   // 6-story residential W
  [  0,  60, 18, 14, 18, '#768A98', '#8A9EAC'],   // 6-story north anchor
  [  0, -62, 16, 12, 15, '#CDBEA0', '#DACDAF'],   // 5-story south anchor

  // Corner fills
  [ 65,  25, 12, 12, 18, '#94483E', '#A55A4E'],   // 6-story NE
  [-65, -25, 10, 12, 21, '#3C5070', '#506484'],   // 7-story W
  [ 65, -25, 12, 12, 15, '#628E73', '#76A287'],   // 5-story SE
  [-65,  25, 12, 10, 15, '#B2946E', '#C3A580'],   // 5-story NW

  // Outer perimeter low-rise
  [ 75,   0, 10, 10, 12, '#C6B696', '#D4C6A8'],
  [-75,   0, 10, 10, 12, '#B2AFA5', '#C0BEB4'],
] as const  // 14 mid-rise

// ── Street trees (only along roads and parks, clear of buildings) ────────────────

const TREE_POSITIONS: readonly (readonly [number, number])[] = [
  // Main E-W road median/sidewalk (z=±5) — skip zones near mission buildings
  [-38, 5], [-30, 5], [-6, 5], [22, 5], [30, 5], [38, 5],
  [-38,-5], [-30,-5], [-6,-5], [22,-5], [30,-5], [38,-5],

  // Main N-S road (x=±5) — skip near B5 (z -17 to -3) and B3 (z 17-33)
  [5, -38], [5, -30], [5, 38],
  [-5,-38], [-5,-30], [-5, 38],

  // Secondary z=±45 road edges
  [-20, 43], [-10, 43], [10, 43], [20, 43], [30, 43],
  [-20,-47], [-10,-47], [10,-47], [20,-47],

  // Secondary x=±45 road edges
  [47, -12], [47, 0], [47, 12],
  [-47,-12], [-47, 0], [-47, 12],

  // Park trees (north park area z=66, east park x=65)
  [-6, 64], [0, 66], [6, 64],
  [64, -6], [66, 0], [64, 6],

  // Scattered perimeter
  [-70, 20], [-70,-20], [70, 20], [70,-20],
  [0, 78], [0,-78],
] as const  // 46 trees

// ── Parks ───────────────────────────────────────────────────────────────────────

const PARKS: readonly (readonly [number, number, number, number])[] = [
  [  0,  66, 18, 10],   // North park
  [ 65,   0, 10, 18],   // East park
  [-65,  40,  8,  8],   // West garden
  [  0, -70, 14,  8],   // South park
] as const

// ── Exported Components ─────────────────────────────────────────────────────────

export function World2Roads({ span }: { span: number }) {
  return (
    <>
      {/* Main E-W road (8m wide at z=0) */}
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[span, 0.01, 8]} />
        <meshStandardMaterial color={C_ROAD} />
      </mesh>
      {/* Main N-S road (8m wide at x=0) */}
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[8, 0.01, span]} />
        <meshStandardMaterial color={C_ROAD} />
      </mesh>

      {/* Secondary E-W roads at z=±45 (5m wide) */}
      {([-45, 45] as number[]).map(z => (
        <mesh key={`ew-sec-${z}`} position={[0, 0.02, z]}>
          <boxGeometry args={[span, 0.01, 5]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
      {/* Secondary N-S roads at x=±45 (5m wide) */}
      {([-45, 45] as number[]).map(x => (
        <mesh key={`ns-sec-${x}`} position={[x, 0.02, 0]}>
          <boxGeometry args={[5, 0.01, span]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}

      {/* Center lane markings on main roads */}
      <mesh position={[0, 0.03, 0]}>
        <boxGeometry args={[span, 0.01, 0.14]} />
        <meshStandardMaterial color={C_LINE} />
      </mesh>
      <mesh position={[0, 0.03, 0]}>
        <boxGeometry args={[0.14, 0.01, span]} />
        <meshStandardMaterial color={C_LINE} />
      </mesh>
    </>
  )
}

export function World2Canal({ span }: { span: number }) {
  return (
    <mesh position={[0, 0.06, -88]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[span, 6]} />
      <meshStandardMaterial color={C_CANAL} transparent opacity={0.9} depthWrite={false} />
    </mesh>
  )
}

export function World2Parks() {
  return (
    <>
      {PARKS.map(([px, pz, pw, pd], i) => (
        <mesh key={i} position={[px, 0.02, pz]}>
          <boxGeometry args={[pw, 0.01, pd]} />
          <meshStandardMaterial color={C_PARK} />
        </mesh>
      ))}
    </>
  )
}

export function World2Trees() {
  return (
    <>
      {TREE_POSITIONS.map(([tx, tz], i) => (
        <group key={i}>
          <mesh position={[tx, 1.2, tz]}>
            <boxGeometry args={[0.2, 2.4, 0.2]} />
            <meshStandardMaterial color={C_TRUNK} />
          </mesh>
          <mesh position={[tx, 3.0, tz]}>
            <sphereGeometry args={[0.8, 8, 6]} />
            <meshStandardMaterial color={C_LEAF} />
          </mesh>
        </group>
      ))}
    </>
  )
}

export function World2Shophouses({
  floorHeight,
  floorThickness,
  transparentWalls,
}: {
  floorHeight: number
  floorThickness: number
  transparentWalls: boolean
}) {
  return (
    <>
      {SHOPHOUSES.map(([cx, cz, w, d, h, bodyColor, roofColor], i) => {
        const stories = Math.round(h / floorHeight)
        const hw = w / 2
        const hd = d / 2
        return (
          <group key={`sh-${i}`}>
            {/* Floor slabs */}
            {Array.from({ length: stories + 1 }, (_, n) => (
              <mesh key={`slab-${n}`} position={[cx, n * floorHeight, cz]}>
                <boxGeometry args={[w, floorThickness, d]} />
                <meshStandardMaterial color={C_SLAB} />
              </mesh>
            ))}
            {/* Wall panels (4 sides) */}
            {([
              { pos: [cx, h / 2, cz - hd] as [number, number, number], size: [w, h, 0.14] as [number, number, number] },
              { pos: [cx, h / 2, cz + hd] as [number, number, number], size: [w, h, 0.14] as [number, number, number] },
              { pos: [cx - hw, h / 2, cz] as [number, number, number], size: [0.14, h, d] as [number, number, number] },
              { pos: [cx + hw, h / 2, cz] as [number, number, number], size: [0.14, h, d] as [number, number, number] },
            ]).map(({ pos, size }, wi) => (
              <mesh key={`wall-${wi}`} position={pos}>
                <boxGeometry args={size} />
                <meshStandardMaterial
                  color={transparentWalls ? roofColor : bodyColor}
                  transparent={transparentWalls}
                  opacity={transparentWalls ? 0.22 : 1}
                  depthWrite={!transparentWalls}
                  side={transparentWalls ? 2 : 0}
                />
              </mesh>
            ))}
            {/* Ground floor awning */}
            {d < w ? (
              <mesh position={[cx - hw - 0.6, 2.7, cz]} rotation={[0, 0, 0.35]}>
                <boxGeometry args={[1.0, 0.05, d * 0.9]} />
                <meshStandardMaterial color="#c44830" />
              </mesh>
            ) : (
              <mesh position={[cx, 2.7, cz + hd + 0.6]} rotation={[-0.35, 0, 0]}>
                <boxGeometry args={[w * 0.9, 0.05, 1.0]} />
                <meshStandardMaterial color="#c44830" />
              </mesh>
            )}
          </group>
        )
      })}
    </>
  )
}

export function World2MidRise({
  floorHeight,
  floorThickness,
  transparentWalls,
}: {
  floorHeight: number
  floorThickness: number
  transparentWalls: boolean
}) {
  return (
    <>
      {MIDRISE_BUILDINGS.map(([cx, cz, w, d, h, bodyColor, roofColor], i) => {
        const stories = Math.round(h / floorHeight)
        const hw = w / 2
        const hd = d / 2
        return (
          <group key={`mr-${i}`}>
            {/* Floor slabs */}
            {Array.from({ length: stories + 1 }, (_, n) => (
              <mesh key={`slab-${n}`} position={[cx, n * floorHeight, cz]}>
                <boxGeometry args={[w, floorThickness, d]} />
                <meshStandardMaterial color={C_SLAB} />
              </mesh>
            ))}
            {/* Wall panels */}
            {([
              { pos: [cx, h / 2, cz - hd] as [number, number, number], size: [w, h, 0.14] as [number, number, number] },
              { pos: [cx, h / 2, cz + hd] as [number, number, number], size: [w, h, 0.14] as [number, number, number] },
              { pos: [cx - hw, h / 2, cz] as [number, number, number], size: [0.14, h, d] as [number, number, number] },
              { pos: [cx + hw, h / 2, cz] as [number, number, number], size: [0.14, h, d] as [number, number, number] },
            ]).map(({ pos, size }, wi) => (
              <mesh key={`wall-${wi}`} position={pos}>
                <boxGeometry args={size} />
                <meshStandardMaterial
                  color={transparentWalls ? roofColor : bodyColor}
                  transparent={transparentWalls}
                  opacity={transparentWalls ? 0.22 : 1}
                  depthWrite={!transparentWalls}
                  side={transparentWalls ? 2 : 0}
                />
              </mesh>
            ))}
            {/* Roof cap */}
            <mesh position={[cx, h + 0.08, cz]}>
              <boxGeometry args={[w, 0.16, d]} />
              <meshStandardMaterial color={roofColor} />
            </mesh>
          </group>
        )
      })}
    </>
  )
}

export function World2FloodWater({ span, floodLevel }: { span: number; floodLevel: number }) {
  const meshRef = useRef<THREE.Mesh>(null)
  const geoRef  = useRef<THREE.PlaneGeometry>(null)
  const timeRef = useRef(0)

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
    <mesh
      ref={meshRef}
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, floodLevel, 0]}
      renderOrder={2}
      onUpdate={(self) => { self.raycast = () => {} }}
    >
      <planeGeometry ref={geoRef} args={[span, span, 50, 50]} />
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

/** Renders the full World 2 (Hat Yai township) decorative environment */
export function World2Environment({
  span,
  floorHeight,
  floorThickness,
  floodLevel,
  transparentWalls,
}: {
  span: number
  floorHeight: number
  floorThickness: number
  floodLevel: number
  transparentWalls: boolean
}) {
  return (
    <>
      <World2Roads span={span} />
      <World2Canal span={span} />
      <World2Parks />
      <World2Trees />
      <World2Shophouses floorHeight={floorHeight} floorThickness={floorThickness} transparentWalls={transparentWalls} />
      <World2MidRise floorHeight={floorHeight} floorThickness={floorThickness} transparentWalls={transparentWalls} />
      <World2FloodWater span={span} floodLevel={floodLevel} />
    </>
  )
}
