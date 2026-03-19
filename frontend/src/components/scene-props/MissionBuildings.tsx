'use client'

import { Html } from '@react-three/drei'
import * as THREE from 'three'
import type { WorldBalconyLayout, WorldBuilding } from '../../types/worldTypes'

const C_SLAB = '#94A2AF'
const C_GLASS = '#7DBCE1'

export function MissionBuildings({
  buildings,
  transparentWalls,
  floorHeight,
  floorThickness,
  survivorStatsByBuilding = {},
}: {
  buildings: WorldBuilding[]
  transparentWalls: boolean
  floorHeight: number
  floorThickness: number
  survivorStatsByBuilding?: Record<number, { detected: number; supplied: number }>
}) {
  const palettes = [
    { solid: '#5f6b77', transparent: '#7d9ab1' },
    { solid: '#7a8a72', transparent: '#9ab1a8' },
    { solid: '#C49870', transparent: '#b1a08a' },
    { solid: '#8899aa', transparent: '#8899bb' },
    { solid: '#6f7288', transparent: '#8d93b0' },
  ] as const

  const balconyLayout = (
    building: WorldBuilding,
    balcony: WorldBalconyLayout,
    halfWidth: number,
    halfDepth: number,
  ) => {
    const y = (balcony.floor - 1) * floorHeight
    if (balcony.face === 'north') {
      return {
        position: [building.cx, y, building.cz - halfDepth - balcony.depth / 2] as [number, number, number],
        size: [balcony.width, floorThickness, balcony.depth] as [number, number, number],
      }
    }
    if (balcony.face === 'south') {
      return {
        position: [building.cx, y, building.cz + halfDepth + balcony.depth / 2] as [number, number, number],
        size: [balcony.width, floorThickness, balcony.depth] as [number, number, number],
      }
    }
    if (balcony.face === 'west') {
      return {
        position: [building.cx - halfWidth - balcony.depth / 2, y, building.cz] as [number, number, number],
        size: [balcony.depth, floorThickness, balcony.width] as [number, number, number],
      }
    }
    return {
      position: [building.cx + halfWidth + balcony.depth / 2, y, building.cz] as [number, number, number],
      size: [balcony.depth, floorThickness, balcony.width] as [number, number, number],
    }
  }

  const balconyRailings = (
    building: WorldBuilding,
    balcony: WorldBalconyLayout,
    halfWidth: number,
    halfDepth: number,
  ) => {
    const railY = (balcony.floor - 1) * floorHeight + 0.5
    if (balcony.face === 'north') {
      return [
        { position: [building.cx, railY, building.cz - halfDepth - balcony.depth] as [number, number, number], size: [balcony.width, 1.0, 0.06] as [number, number, number] },
        { position: [building.cx - balcony.width / 2, railY, building.cz - halfDepth - balcony.depth / 2] as [number, number, number], size: [0.08, 1.0, balcony.depth] as [number, number, number] },
        { position: [building.cx + balcony.width / 2, railY, building.cz - halfDepth - balcony.depth / 2] as [number, number, number], size: [0.08, 1.0, balcony.depth] as [number, number, number] },
      ]
    }
    if (balcony.face === 'south') {
      return [
        { position: [building.cx, railY, building.cz + halfDepth + balcony.depth] as [number, number, number], size: [balcony.width, 1.0, 0.06] as [number, number, number] },
        { position: [building.cx - balcony.width / 2, railY, building.cz + halfDepth + balcony.depth / 2] as [number, number, number], size: [0.08, 1.0, balcony.depth] as [number, number, number] },
        { position: [building.cx + balcony.width / 2, railY, building.cz + halfDepth + balcony.depth / 2] as [number, number, number], size: [0.08, 1.0, balcony.depth] as [number, number, number] },
      ]
    }
    if (balcony.face === 'west') {
      return [
        { position: [building.cx - halfWidth - balcony.depth, railY, building.cz] as [number, number, number], size: [0.06, 1.0, balcony.width] as [number, number, number] },
        { position: [building.cx - halfWidth - balcony.depth / 2, railY, building.cz - balcony.width / 2] as [number, number, number], size: [balcony.depth, 1.0, 0.08] as [number, number, number] },
        { position: [building.cx - halfWidth - balcony.depth / 2, railY, building.cz + balcony.width / 2] as [number, number, number], size: [balcony.depth, 1.0, 0.08] as [number, number, number] },
      ]
    }
    return [
      { position: [building.cx + halfWidth + balcony.depth, railY, building.cz] as [number, number, number], size: [0.06, 1.0, balcony.width] as [number, number, number] },
      { position: [building.cx + halfWidth + balcony.depth / 2, railY, building.cz - balcony.width / 2] as [number, number, number], size: [balcony.depth, 1.0, 0.08] as [number, number, number] },
      { position: [building.cx + halfWidth + balcony.depth / 2, railY, building.cz + balcony.width / 2] as [number, number, number], size: [balcony.depth, 1.0, 0.08] as [number, number, number] },
    ]
  }

  return (
    <>
      {buildings.map((building, idx) => {
        const halfWidth = building.w / 2
        const halfDepth = building.d / 2
        const numFloors = Math.round(building.h / floorHeight)
        const palette = palettes[idx % palettes.length]
        const wallColor = transparentWalls ? palette.transparent : palette.solid
        const wallOpacity = transparentWalls ? 0.22 : 1
        const wallDepthWrite = !transparentWalls
        const wallPanels = [
          { pos: [building.cx, building.h / 2, building.cz - halfDepth] as [number, number, number], size: [building.w, building.h, 0.14] as [number, number, number] },
          { pos: [building.cx, building.h / 2, building.cz + halfDepth] as [number, number, number], size: [building.w, building.h, 0.14] as [number, number, number] },
          { pos: [building.cx - halfWidth, building.h / 2, building.cz] as [number, number, number], size: [0.14, building.h, building.d] as [number, number, number] },
          { pos: [building.cx + halfWidth, building.h / 2, building.cz] as [number, number, number], size: [0.14, building.h, building.d] as [number, number, number] },
        ]
        const shopAwnings = building.windows.filter(
          (window) => window.face === 'south' && window.floor === 2,
        )
        const shouldRenderShopAwnings = shopAwnings.length >= 2
        const survivorStats = survivorStatsByBuilding[building.id] ?? { detected: 0, supplied: 0 }
        return (
          <group key={building.id}>
            {Array.from({ length: numFloors + 1 }, (_, floorIdx) => (
              <mesh key={`slab-${building.id}-${floorIdx}`} position={[building.cx, floorIdx * floorHeight, building.cz]}>
                <boxGeometry args={[building.w, floorThickness, building.d]} />
                <meshStandardMaterial color={C_SLAB} />
              </mesh>
            ))}
            {wallPanels.map(({ pos, size }, panelIdx) => (
              <mesh key={`wall-${building.id}-${panelIdx}`} position={pos}>
                <boxGeometry args={size} />
                <meshStandardMaterial
                  color={wallColor}
                  transparent={transparentWalls}
                  opacity={wallOpacity}
                  depthWrite={wallDepthWrite}
                  side={THREE.DoubleSide}
                />
              </mesh>
            ))}
            {building.windows.map((window, windowIdx) => {
              const y = (window.floor - 1) * floorHeight + window.sill + window.height / 2
              if (window.face === 'north') {
                return (
                  <mesh key={`window-${building.id}-${windowIdx}`} position={[building.cx + window.offset, y, building.cz - halfDepth - 0.07]}>
                    <boxGeometry args={[window.width, window.height, 0.10]} />
                    <meshStandardMaterial color={C_GLASS} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide} />
                  </mesh>
                )
              }
              if (window.face === 'south') {
                return (
                  <mesh key={`window-${building.id}-${windowIdx}`} position={[building.cx + window.offset, y, building.cz + halfDepth + 0.07]}>
                    <boxGeometry args={[window.width, window.height, 0.10]} />
                    <meshStandardMaterial color={C_GLASS} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide} />
                  </mesh>
                )
              }
              if (window.face === 'west') {
                return (
                  <mesh key={`window-${building.id}-${windowIdx}`} position={[building.cx - halfWidth - 0.07, y, building.cz + window.offset]}>
                    <boxGeometry args={[0.10, window.height, window.width]} />
                    <meshStandardMaterial color={C_GLASS} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide} />
                  </mesh>
                )
              }
              return (
                <mesh key={`window-${building.id}-${windowIdx}`} position={[building.cx + halfWidth + 0.07, y, building.cz + window.offset]}>
                  <boxGeometry args={[0.10, window.height, window.width]} />
                  <meshStandardMaterial color={C_GLASS} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide} />
                </mesh>
              )
            })}
            {building.balcony ? (() => {
              const { position, size } = balconyLayout(building, building.balcony, halfWidth, halfDepth)
              const rails = balconyRailings(building, building.balcony, halfWidth, halfDepth)
              return (
                <>
                  <mesh key={`balcony-${building.id}`} position={position}>
                    <boxGeometry args={size} />
                    <meshStandardMaterial color="#99aabb" />
                  </mesh>
                  {rails.map((rail, railIdx) => (
                    <mesh key={`balcony-rail-${building.id}-${railIdx}`} position={rail.position}>
                      <boxGeometry args={rail.size} />
                      <meshStandardMaterial color="#aabbcc" transparent opacity={0.6} />
                    </mesh>
                  ))}
                </>
              )
            })() : null}
            {shouldRenderShopAwnings ? shopAwnings.map((window, awningIdx) => (
              <mesh
                key={`awning-${building.id}-${awningIdx}`}
                position={[
                  building.cx + window.offset,
                  (window.floor - 1) * floorHeight - 0.4,
                  building.cz + halfDepth + 0.6,
                ]}
                rotation={[-0.4, 0, 0]}
              >
                <boxGeometry args={[Math.max(2.8, window.width * 2.2), 0.06, 1.2]} />
                <meshStandardMaterial color="#c44830" />
              </mesh>
            )) : null}
            <Html position={[building.cx + halfWidth - 0.8, building.h + 1.6, building.cz - halfDepth + 0.8]} center distanceFactor={20} zIndexRange={[0, 0]}>
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 2,
                background: 'rgba(4, 10, 16, 0.86)',
                border: '1px solid rgba(120, 180, 240, 0.35)',
                borderRadius: 4,
                padding: '3px 7px',
                fontFamily: 'Courier New, monospace',
                fontSize: '34px',
                lineHeight: 1.1,
                letterSpacing: '0.05em',
                pointerEvents: 'none',
                whiteSpace: 'nowrap',
              }}>
                <span style={{ color: '#ffd84d' }}>DET {survivorStats.detected}</span>
                <span style={{ color: '#22dd66' }}>SUP {survivorStats.supplied}</span>
              </div>
            </Html>
          </group>
        )
      })}
    </>
  )
}
