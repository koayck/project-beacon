'use client'

import { Line } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import * as THREE from 'three'

interface WorldWindowLayout {
  floor: number
  face: 'north' | 'south' | 'west' | 'east' | 'top'
  offset: number
  width: number
  height: number
  sill: number
}

interface WorldBalconyLayout {
  floor: number
  face: 'north' | 'south' | 'west' | 'east' | 'top'
  depth: number
  width: number
}

interface WorldBuilding {
  id: number
  name: string
  cx: number
  cz: number
  w: number
  d: number
  h: number
  windows: WorldWindowLayout[]
  balcony: WorldBalconyLayout | null
}

interface SurvivorPoint {
  x: number
  y: number
  z: number
}

const C_GROUND    = '#1e1e22'
const C_ROAD      = '#2c2c32'
const C_LINE      = '#D7CDA5'
const C_PARK      = '#286C34'
const C_GRID_MAJ  = '#363a40'
const C_GRID_MIN  = '#26282e'
const C_TRUNK     = '#5F4126'
const C_LEAF      = '#267632'
const C_SLAB      = '#94A2AF'
const C_GLASS     = '#7DBCE1'
const C_GLASSBAND = '#AAD2F0'
const C_CANAL     = '#1a4a7a'

const CITY_BUILDINGS = [
  [-14,-12, 8, 8,20, '#466291', '#5A76A5'],
  [ 14,-10, 7, 9,14, '#BCA580', '#CDB691'],
  [-16, 10, 9, 7, 9, '#C6B696', '#D4C6A8'],
  [ 16, 14, 7, 8,24, '#303E52', '#445266'],
  [  0,-20,14, 6, 7, '#B2AFA5', '#C0BEB4'],
  [-22,  2, 7, 7,16, '#52769E', '#668AB2'],
  [ 20,  0, 9, 8,12, '#A86C48', '#B9805A'],
  [  0, 22,10, 9,15, '#465562', '#5A6976'],
  [  8,-15, 5, 5,22, '#34486E', '#485C82'],
  [ -8, 17, 8, 6,10, '#BEAF91', '#D0C0A2'],
  [-10, -8, 4, 4,30, '#263658', '#38486C'],
  [ 10,  8, 6, 6,11, '#98765A', '#A8876C'],
  [ -6,-18, 6, 6,18, '#374E76', '#4B628A'],
  [ 18, -6, 5, 8,16, '#768A98', '#8A9EAC'],
  [-18, -4, 8, 5, 8, '#CDBEA0', '#DACDAF'],
  [  5,-10, 4, 4,12, '#588250', '#6C9664'],
  [-12, 14, 6, 5,14, '#94483E', '#A55A4E'],
  [ 15,  5, 5, 7,19, '#3C5070', '#506484'],
  [-20, 18, 6, 6,10, '#628E73', '#76A287'],
  [  6, 18, 7, 5, 8, '#B2946E', '#C3A580'],
  [-32,-27, 6, 4,10, '#D4A87C', '#C49870'],
  [-24,-27, 6, 4,10, '#C89E74', '#B88E64'],
  [-16,-27, 6, 4,12, '#D0A882', '#C09876'],
  [  0,-27, 8, 4, 8, '#BCA880', '#ACA070'],
  [ 24,-27, 6, 4,10, '#C8A47A', '#B89468'],
  [ 32,-27, 6, 4,10, '#CCA882', '#BC9870'],
  [-32,  0,10, 8,14, '#C46040', '#B45030'],
  [-38,-14, 8, 6,20, '#3A5878', '#4A688A'],
  [-38, 14, 9, 7, 6, '#D0C8A8', '#C0B898'],
  [-44, -6, 7, 7,16, '#5A8496', '#6A94A6'],
  [-44,  8, 6, 6,10, '#9A7860', '#AA8870'],
  [ 30,-20, 9, 8,18, '#4A6E9E', '#5A7EAE'],
  [ 38,-14, 7, 7,26, '#303848', '#404858'],
  [ 30, -6, 6, 8,12, '#A87E58', '#B88E68'],
  [ 38,  4, 8, 6, 8, '#C0B090', '#D0C0A0'],
  [ 30, 14, 7, 9,22, '#46607E', '#56708E'],
  [ 38, 22, 6, 6,14, '#888060', '#989070'],
  [ 30, 30, 9, 7, 9, '#C0785A', '#D0886A'],
  [-24, 30,10, 8, 7, '#A8C490', '#B8D4A0'],
  [ -8, 30, 7, 7,16, '#5A4A7E', '#6A5A8E'],
  [  8, 30, 8, 6,13, '#B86848', '#C87858'],
  [ 24, 30, 7, 8,20, '#304858', '#405868'],
  [-30,-40,20,14, 5, '#F0EAD0', '#E4DEC4'],
  [-26,-38, 8, 8,22, '#D4A020', '#EAB830'],
  [-36,-38, 6, 6,14, '#C89820', '#DCA820'],
  [-30,-44,14, 4, 6, '#EEE8C8', '#E0DAB8'],
  [-20,-42, 6, 8, 8, '#F4EED8', '#E8E0C8'],
  [ 30,-38,12,12,40, '#2A3C58', '#384C68'],
  [ 42,-38, 8, 8,32, '#36507A', '#46608A'],
  [ 42,-26, 7, 7,24, '#3E5E82', '#4E6E92'],
  [ 30,-50,14, 8, 8, '#A0A8B0', '#B0B8C0'],
  [ -8,-38, 8, 6, 5, '#C8A060', '#D8B070'],
  [  4,-38, 7, 5, 5, '#C09050', '#D0A060'],
  [ 14,-38, 6, 6, 6, '#B88840', '#C89850'],
  [-16,-46, 9, 7, 4, '#C8B888', '#D8C898'],
  [  0,-46, 8, 6, 5, '#C0B070', '#D0C080'],
  [ 14,-46, 7, 7, 6, '#B8A860', '#C8B870'],
] as const

const TREE_XZ = [
  [-4,5],[-5,8],[-8,5],[-7,9],[-9,8],[-5,6],
  [9,-9],[12,-13],[13,-10],[10,-13],
  [-14,-4],[-17,-8],[-15,-8],
  [4,3],[4,-3],[-4,3],[-4,-3],
  [10,3],[10,-3],[-10,3],[-10,-3],[16,3],[16,-3],
  [-28,-5],[-28,5],[-28,12],[-28,-12],
  [28,-5],[28,5],[28,12],[28,-12],
  [-5,-28],[-12,-28],[5,-28],[12,-28],
  [-5,28],[-12,28],[5,28],[12,28],
  [-24,-36],[-34,-36],[-24,-42],[-34,-42],[-20,-44],
  [-46,20],[-46,10],[-46,0],[-46,-10],[-46,-20],[-46,-30],
  [-40,0],[-40,18],[-40,-18],[40,0],[40,18],[40,-18],
  [0,-44],[0,44],[-44,28],[44,-28],
] as const

const PARKS = [
  [-7,  7,  9, 9],
  [11,-11,  7, 7],
  [-16, -6, 6, 6],
  [-30,  8, 12,10],
  [ 28, 24, 14,10],
  [-20,-34, 10, 8],
  [  0, 36, 20, 8],
  [-44,  0,  8,16],
] as const

export function Ground({ span }: { span: number }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
      <planeGeometry args={[span, span]} />
      <meshStandardMaterial color={C_GROUND} />
    </mesh>
  )
}

export function Roads({ span }: { span: number }) {
  return (
    <>
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[span, 0.01, 7]} />
        <meshStandardMaterial color={C_ROAD} />
      </mesh>
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[7, 0.01, span]} />
        <meshStandardMaterial color={C_ROAD} />
      </mesh>
      {([-28, 28] as number[]).map(z => (
        <mesh key={`ew${z}`} position={[0, 0.02, z]}>
          <boxGeometry args={[span, 0.01, 4]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
      {([-28, 28] as number[]).map(x => (
        <mesh key={`ns${x}`} position={[x, 0.02, 0]}>
          <boxGeometry args={[4, 0.01, span]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
      {([-14, 14] as number[]).map(z => (
        <mesh key={`t-ew${z}`} position={[0, 0.02, z]}>
          <boxGeometry args={[span, 0.01, 3]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
      {([-14, 14] as number[]).map(x => (
        <mesh key={`t-ns${x}`} position={[x, 0.02, 0]}>
          <boxGeometry args={[3, 0.01, span]} />
          <meshStandardMaterial color={C_ROAD} />
        </mesh>
      ))}
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

export function Canal({ span }: { span: number }) {
  return (
    <mesh position={[-47, 0.06, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[6, span]} />
      <meshStandardMaterial color={C_CANAL} transparent opacity={0.9} depthWrite={false} />
    </mesh>
  )
}

export function Parks() {
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

export function GridOverlay({ span, gridCells }: { span: number; gridCells: number }) {
  return (
    <gridHelper
      args={[span, gridCells, C_GRID_MAJ, C_GRID_MIN]}
      position={[0, 0.01, 0]}
    />
  )
}

export function Trees() {
  return (
    <>
      {TREE_XZ.map(([tx, tz], i) => (
        <group key={i}>
          <mesh position={[tx, 0.8, tz]}>
            <boxGeometry args={[0.18, 1.6, 0.18]} />
            <meshStandardMaterial color={C_TRUNK} />
          </mesh>
          <mesh position={[tx, 2.1, tz]}>
            <sphereGeometry args={[0.5, 8, 6]} />
            <meshStandardMaterial color={C_LEAF} />
          </mesh>
        </group>
      ))}
    </>
  )
}

export function CityBuildings({ floorHeight }: { floorHeight: number }) {
  return (
    <>
      {CITY_BUILDINGS.map(([cx, cz, w, d, h, bodyColor, roofColor], i) => (
        <group key={i}>
          <mesh position={[cx, h / 2, cz]}>
            <boxGeometry args={[w, h, d]} />
            <meshStandardMaterial color={bodyColor} />
          </mesh>
          <mesh position={[cx, h + 0.08, cz]}>
            <boxGeometry args={[w, 0.16, d]} />
            <meshStandardMaterial color={roofColor} />
          </mesh>
          {h >= 14 && Array.from({ length: Math.floor(h / floorHeight) - 1 }, (_, fi) => (
            <mesh key={fi} position={[cx, (fi + 1) * floorHeight, cz]}>
              <boxGeometry args={[w * 0.92, 0.28, d * 0.92]} />
              <meshStandardMaterial color={C_GLASSBAND} transparent opacity={0.45} depthWrite={false} />
            </mesh>
          ))}
        </group>
      ))}
    </>
  )
}

function TargetBuilding({
  building,
  transparentWalls,
  floorHeight,
  floorThickness,
}: {
  building: WorldBuilding
  transparentWalls: boolean
  floorHeight: number
  floorThickness: number
}) {
  const hw = building.w / 2
  const hd = building.d / 2
  const numFloors = Math.round(building.h / floorHeight)

  const wallPanels = [
    { pos: [building.cx,      building.h / 2, building.cz - hd] as [number, number, number], size: [building.w, building.h, 0.14] as [number, number, number] },
    { pos: [building.cx,      building.h / 2, building.cz + hd] as [number, number, number], size: [building.w, building.h, 0.14] as [number, number, number] },
    { pos: [building.cx - hw, building.h / 2, building.cz]      as [number, number, number], size: [0.14, building.h, building.d] as [number, number, number] },
    { pos: [building.cx + hw, building.h / 2, building.cz]      as [number, number, number], size: [0.14, building.h, building.d] as [number, number, number] },
  ]

  const windowPanels = building.windows.map((window) => {
    const y = (window.floor - 1) * floorHeight + window.sill + window.height / 2
    if (window.face === 'north') {
      return {
        key: `${window.face}-${window.floor}-${window.offset}`,
        pos: [building.cx + window.offset, y, building.cz - hd - 0.07] as [number, number, number],
        size: [window.width, window.height, 0.10] as [number, number, number],
      }
    }
    if (window.face === 'south') {
      return {
        key: `${window.face}-${window.floor}-${window.offset}`,
        pos: [building.cx + window.offset, y, building.cz + hd + 0.07] as [number, number, number],
        size: [window.width, window.height, 0.10] as [number, number, number],
      }
    }
    if (window.face === 'west') {
      return {
        key: `${window.face}-${window.floor}-${window.offset}`,
        pos: [building.cx - hw - 0.07, y, building.cz + window.offset] as [number, number, number],
        size: [0.10, window.height, window.width] as [number, number, number],
      }
    }
    return {
      key: `${window.face}-${window.floor}-${window.offset}`,
      pos: [building.cx + hw + 0.07, y, building.cz + window.offset] as [number, number, number],
      size: [0.10, window.height, window.width] as [number, number, number],
    }
  })

  return (
    <>
      {Array.from({ length: numFloors + 1 }, (_, n) => (
        <mesh key={n} position={[building.cx, n * floorHeight, building.cz]}>
          <boxGeometry args={[building.w, floorThickness, building.d]} />
          <meshStandardMaterial color={C_SLAB} />
        </mesh>
      ))}
      {wallPanels.map(({ pos, size }, i) => (
        <mesh key={i} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial
            color={transparentWalls ? '#7d9ab1' : '#5f6b77'}
            transparent={transparentWalls}
            opacity={transparentWalls ? 0.22 : 1}
            depthWrite={!transparentWalls}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
      {windowPanels.map(({ key, pos, size }) => (
        <mesh key={key} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial color={C_GLASS} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </>
  )
}

function ObstacleBuilding({ building }: { building: WorldBuilding }) {
  return (
    <mesh position={[building.cx, building.h / 2, building.cz]}>
      <boxGeometry args={[building.w, building.h, building.d]} />
      <meshStandardMaterial color="#5a4a3a" />
    </mesh>
  )
}

function BalconyBuilding({
  building,
  transparentWalls,
  floorHeight,
  floorThickness,
}: {
  building: WorldBuilding
  transparentWalls: boolean
  floorHeight: number
  floorThickness: number
}) {
  const hw = building.w / 2
  const hd = building.d / 2
  const balcony = building.balcony
  if (!balcony || balcony.face !== 'south') {
    return null
  }
  const balconyY = (balcony.floor - 1) * floorHeight
  const numFloors = Math.round(building.h / floorHeight)

  const wallPanels = [
    { pos: [building.cx, building.h / 2, building.cz - hd] as [number, number, number], size: [building.w, building.h, 0.14] as [number, number, number] },
    { pos: [building.cx, building.h / 2, building.cz + hd] as [number, number, number], size: [building.w, building.h, 0.14] as [number, number, number] },
    { pos: [building.cx - hw, building.h / 2, building.cz] as [number, number, number], size: [0.14, building.h, building.d] as [number, number, number] },
    { pos: [building.cx + hw, building.h / 2, building.cz] as [number, number, number], size: [0.14, building.h, building.d] as [number, number, number] },
  ]

  return (
    <>
      {Array.from({ length: numFloors + 1 }, (_, n) => (
        <mesh key={n} position={[building.cx, n * floorHeight, building.cz]}>
          <boxGeometry args={[building.w, floorThickness, building.d]} />
          <meshStandardMaterial color={C_SLAB} />
        </mesh>
      ))}
      {wallPanels.map(({ pos, size }, i) => (
        <mesh key={i} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial
            color={transparentWalls ? '#9ab1a8' : '#7a8a72'}
            transparent={transparentWalls}
            opacity={transparentWalls ? 0.22 : 1}
            depthWrite={!transparentWalls}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
      <mesh position={[building.cx, balconyY, building.cz + hd + balcony.depth / 2]}>
        <boxGeometry args={[balcony.width, floorThickness, balcony.depth]} />
        <meshStandardMaterial color={C_SLAB} />
      </mesh>
      <mesh position={[building.cx, balconyY + 0.5, building.cz + hd + balcony.depth]}>
        <boxGeometry args={[balcony.width, 1.0, 0.08]} />
        <meshStandardMaterial color="#5a6a5a" />
      </mesh>
      <mesh position={[building.cx - balcony.width / 2, balconyY + 0.5, building.cz + hd + balcony.depth / 2]}>
        <boxGeometry args={[0.08, 1.0, balcony.depth]} />
        <meshStandardMaterial color="#5a6a5a" />
      </mesh>
      <mesh position={[building.cx + balcony.width / 2, balconyY + 0.5, building.cz + hd + balcony.depth / 2]}>
        <boxGeometry args={[0.08, 1.0, balcony.depth]} />
        <meshStandardMaterial color="#5a6a5a" />
      </mesh>
    </>
  )
}

function ShophouseBlock({
  building,
  transparentWalls,
  floorHeight,
  floorThickness,
}: {
  building: WorldBuilding
  transparentWalls: boolean
  floorHeight: number
  floorThickness: number
}) {
  const hw = building.w / 2
  const hd = building.d / 2
  const numFloors = Math.round(building.h / floorHeight)
  const southWindows = building.windows.filter((window) => window.face === 'south')
  const awningOffsets = Array.from(
    new Set(
      southWindows
        .filter((window) => window.floor === 2)
        .map((window) => window.offset),
    ),
  )

  const wallPanels = [
    { pos: [building.cx, building.h / 2, building.cz - hd] as [number, number, number], size: [building.w, building.h, 0.14] as [number, number, number] },
    { pos: [building.cx, building.h / 2, building.cz + hd] as [number, number, number], size: [building.w, building.h, 0.14] as [number, number, number] },
    { pos: [building.cx - hw, building.h / 2, building.cz] as [number, number, number], size: [0.14, building.h, building.d] as [number, number, number] },
    { pos: [building.cx + hw, building.h / 2, building.cz] as [number, number, number], size: [0.14, building.h, building.d] as [number, number, number] },
  ]

  return (
    <>
      {Array.from({ length: numFloors + 1 }, (_, n) => (
        <mesh key={n} position={[building.cx, n * floorHeight, building.cz]}>
          <boxGeometry args={[building.w, floorThickness, building.d]} />
          <meshStandardMaterial color={C_SLAB} />
        </mesh>
      ))}
      {wallPanels.map(({ pos, size }, i) => (
        <mesh key={i} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial
            color={transparentWalls ? '#b1a08a' : '#C49870'}
            transparent={transparentWalls}
            opacity={transparentWalls ? 0.22 : 1}
            depthWrite={!transparentWalls}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
      <mesh position={[building.cx, building.h / 2, building.cz]}>
        <boxGeometry args={[0.14, building.h, building.d]} />
        <meshStandardMaterial color="#8a7a6a" />
      </mesh>
      {southWindows.map(({ floor, offset, width, height, sill }, i) => (
        <mesh key={i} position={[building.cx + offset, (floor - 1) * floorHeight + sill + (height / 2), building.cz + hd + 0.07]}>
          <boxGeometry args={[width, height, 0.10]} />
          <meshStandardMaterial color={C_GLASS} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
      {(awningOffsets.length > 0 ? awningOffsets : [-2.5, 2.5]).map((offset, i) => (
        <mesh key={`awning-${i}`} position={[building.cx + offset, 2.6, building.cz + hd + 0.6]} rotation={[-0.4, 0, 0]}>
          <boxGeometry args={[4, 0.06, 1.2]} />
          <meshStandardMaterial color="#c44830" />
        </mesh>
      ))}
    </>
  )
}

function NWTowerBuilding({
  building,
  transparentWalls,
  floorHeight,
  floorThickness,
}: {
  building: WorldBuilding
  transparentWalls: boolean
  floorHeight: number
  floorThickness: number
}) {
  const hw = building.w / 2
  const hd = building.d / 2
  const numFloors = Math.round(building.h / floorHeight)
  const balcony = building.balcony
  if (!balcony || balcony.face !== 'south') {
    return null
  }
  const balconyY = (balcony.floor - 1) * floorHeight + 0.06
  const balconyZ = building.cz + hd + balcony.depth / 2

  const wallPanels = [
    { pos: [building.cx,      building.h / 2, building.cz - hd] as [number,number,number], size: [building.w, building.h, 0.14] as [number,number,number] },
    { pos: [building.cx,      building.h / 2, building.cz + hd] as [number,number,number], size: [building.w, building.h, 0.14] as [number,number,number] },
    { pos: [building.cx - hw, building.h / 2, building.cz]      as [number,number,number], size: [0.14, building.h, building.d] as [number,number,number] },
    { pos: [building.cx + hw, building.h / 2, building.cz]      as [number,number,number], size: [0.14, building.h, building.d] as [number,number,number] },
  ]

  return (
    <>
      {Array.from({ length: numFloors + 1 }, (_, i) => (
        <mesh key={`slab-${i}`} position={[building.cx, i * floorHeight + floorThickness / 2, building.cz]}>
          <boxGeometry args={[building.w, floorThickness, building.d]} />
          <meshStandardMaterial color="#b0b8c8" />
        </mesh>
      ))}
      {wallPanels.map(({ pos, size }, i) => (
        <mesh key={`wall-${i}`} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial
            color={transparentWalls ? '#8899bb' : '#8899aa'}
            transparent={transparentWalls}
            opacity={transparentWalls ? 0.22 : 1}
            depthWrite={!transparentWalls}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
      {building.windows.map(({ floor, face, offset, width, height, sill }, i) => {
        const cx = face === 'north' || face === 'south' ? building.cx + offset : building.cx
        const cz = face === 'east'  || face === 'west'  ? building.cz + offset : building.cz
        const x  = face === 'east'  ? building.cx + hw + 0.07 : face === 'west' ? building.cx - hw - 0.07 : cx
        const z  = face === 'south' ? building.cz + hd + 0.07 : face === 'north' ? building.cz - hd - 0.07 : cz
        const ry = face === 'east' || face === 'west' ? Math.PI / 2 : 0
        return (
          <mesh key={i} position={[x, (floor - 1) * floorHeight + floorThickness + sill + height / 2, z]} rotation={[0, ry, 0]}>
            <boxGeometry args={[width, height, 0.10]} />
            <meshStandardMaterial
              color={C_GLASS} transparent opacity={0.2}
              depthWrite={false} side={THREE.DoubleSide}
            />
          </mesh>
        )
      })}
      <mesh position={[building.cx, balconyY, balconyZ]}>
        <boxGeometry args={[balcony.width, floorThickness, balcony.depth]} />
        <meshStandardMaterial color="#99aabb" />
      </mesh>
      <mesh position={[building.cx, balconyY + 0.55, balconyZ + balcony.depth / 2]}>
        <boxGeometry args={[balcony.width, 1.1, 0.06]} />
        <meshStandardMaterial color="#aabbcc" transparent opacity={0.6} />
      </mesh>
    </>
  )
}

export function MissionBuildings({
  buildings,
  transparentWalls,
  floorHeight,
  floorThickness,
}: {
  buildings: WorldBuilding[]
  transparentWalls: boolean
  floorHeight: number
  floorThickness: number
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
          </group>
        )
      })}
    </>
  )
}

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

function survivorKey(s: SurvivorPoint): string {
  return `${s.x.toFixed(2)}|${s.y.toFixed(2)}|${s.z.toFixed(2)}`
}

function SurvivorHuman({
  pos,
  floodY,
  index,
  supplied,
}: {
  pos: SurvivorPoint
  floodY: number
  index: number
  supplied: boolean
}) {
  const groupRef = useRef<THREE.Group>(null)

  useFrame(({ clock }) => {
    if (!groupRef.current) return
    const t = clock.elapsedTime
    if (supplied) {
      groupRef.current.scale.setScalar(1 + Math.sin(t * 1.5 + index * 0.9) * 0.06)
    } else {
      const submerged = pos.y < floodY - 0.2
      const speed = submerged ? 6 : 3
      const pulse = 1 + Math.sin(t * speed + index * 0.9) * 0.18
      groupRef.current.scale.setScalar(pulse)
    }

    const submerged = pos.y < floodY - 0.2
    const bodyColor = supplied ? 0x22dd66 : (submerged ? 0xff8800 : 0xff2222)
    const emissiveColor = supplied ? 0x11aa44 : (submerged ? 0xcc4400 : 0xff0000)
    const emissiveIntensity = supplied ? 0.5 : (submerged ? 0.7 : 0.45)
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
  const color = supplied ? '#22dd66' : (submerged ? '#ff8800' : '#ff2222')
  const emissive = supplied ? '#11aa44' : (submerged ? '#cc4400' : '#ff0000')

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
}: {
  floodY: number
  survivors: SurvivorPoint[]
  deliveredTo?: Set<string>
}) {
  const delivered = deliveredTo ?? new Set<string>()
  return (
    <>
      {survivors.map((pos, i) => (
        <SurvivorHuman
          key={i}
          pos={pos}
          floodY={floodY}
          index={i}
          supplied={delivered.has(survivorKey(pos))}
        />
      ))}
    </>
  )
}

export function SurvivorScanRays({
  enabled,
  dronePos,
  survivors,
}: {
  enabled: boolean
  dronePos: THREE.Vector3
  survivors: SurvivorPoint[]
}) {
  if (!enabled || survivors.length === 0) return null
  return (
    <>
      {survivors.map((survivor, index) => (
        <Line
          key={`scan-ray-${index}-${survivor.x}-${survivor.y}-${survivor.z}`}
          points={[
            [dronePos.x, dronePos.y, dronePos.z],
            [survivor.x, survivor.y, survivor.z],
          ]}
          color="#ff4466"
          lineWidth={1.2}
          transparent
          opacity={0.9}
          depthTest={false}
          depthWrite={false}
        />
      ))}
    </>
  )
}
