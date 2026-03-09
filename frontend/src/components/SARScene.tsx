'use client'

import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera } from '@react-three/drei'
import { useRef, useState, useEffect, useMemo, useCallback } from 'react'
import * as THREE from 'three'
import CommandPanel from './CommandPanel'
import { useTelemetry } from '@/lib/ws'
import { uplink, streamCommand, healthCheck, type AgentStreamEvent } from '@/lib/api'

// ── Constants (1:1 from test.py) ──────────────────────────────────────────────

const GRID_CELLS = 26
const GRID_SPACING = 2
const NUM_FLOORS = 4
const FLOOR_H = 3.0
const FLOOR_W = 8
const FLOOR_D = 8
const FLOOR_T = 0.20
const SURV_HOVER = 0.55

const span = GRID_CELLS * GRID_SPACING           // 52
const half = span / 2                            // 26
const total_h = NUM_FLOORS * FLOOR_H             // 12

const slabY = (n: number) => (n - 1) * FLOOR_H
const survY = (n: number) => slabY(n) + FLOOR_T / 2 + SURV_HOVER

// Mission timing (seconds) — matches Ursina T_FLY_F2, T_PAUSE, T_FLY_F4
const T1 = 3.0, T_PAUSE = 1.5, T2 = 3.0

// Drone waypoints (matches Ursina DRONE_START and leg1/leg2 targets)
const DRONE_START   = new THREE.Vector3(13, 1, 13)
const LEG1_TARGET   = new THREE.Vector3(-1.5, survY(2), 1.0 - 1.5)   // (-1.5, 3.65, -0.5)
const LEG2_TARGET   = new THREE.Vector3(1.5,  survY(4), -1.0 - 1.5)  // (1.5, 9.65, -2.5)

// Camera — matches Ursina EditorCamera (rotation_x=50, rotation_y=30, z=-55)
// Converted to Cartesian: dist=55, pitch=50°, yaw=30°
const CAM_POS: [number, number, number] = [17.7, 42.1, 30.6]

// ── Easing (Ursina curve.in_out_quad) ─────────────────────────────────────────

function easeInOutQuad(t: number): number {
  return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t
}

// ── Color data (rgb32 → hex, 1:1 from test.py) ────────────────────────────────

// Ground / roads / grid
const C_GROUND   = '#242428'
const C_ROAD     = '#303036'
const C_LINE     = '#D7CDA5'
const C_PARK     = '#286C34'
const C_GRID_MAJ = '#3A3E44'
const C_GRID_MIN = '#2A2C32'
const C_TRUNK    = '#5F4126'
const C_LEAF     = '#267632'
// Target building
const C_SLAB     = '#94A2AF'
const C_GLASS    = '#7DBCE1'
const C_GLASSBAND = '#AAD2F0'

// City buildings: [cx, cz, w, d, h, bodyHex, roofHex]
const CITY_BUILDINGS = [
  [-14,-12, 8, 8,20, '#466291', '#5A76A5'],  // blue glass tower   NW
  [ 14,-10, 7, 9,14, '#BCA580', '#CDB691'],  // warm concrete      NE
  [-16, 10, 9, 7, 9, '#C6B696', '#D4C6A8'],  // beige block        SW
  [ 16, 14, 7, 8,24, '#303E52', '#445266'],  // charcoal tower     SE
  [  0,-20,14, 6, 7, '#B2AFA5', '#C0BEB4'],  // flat white block   N
  [-22,  2, 7, 7,16, '#52769E', '#668AB2'],  // steel-blue         W
  [ 20,  0, 9, 8,12, '#A86C48', '#B9805A'],  // terracotta         E
  [  0, 22,10, 9,15, '#465562', '#5A6976'],  // slate              S
  [  8,-15, 5, 5,22, '#34486E', '#485C82'],  // cobalt slim
  [ -8, 17, 8, 6,10, '#BEAF91', '#D0C0A2'],  // limestone
  [-10, -8, 4, 4,30, '#263658', '#38486C'],  // ultra-slim skyscraper
  [ 10,  8, 6, 6,11, '#98765A', '#A8876C'],  // brick-orange
  [ -6,-18, 6, 6,18, '#374E76', '#4B628A'],  // cobalt tower
  [ 18, -6, 5, 8,16, '#768A98', '#8A9EAC'],  // silver steel
  [-18, -4, 8, 5, 8, '#CDBEA0', '#DACDAF'],  // sandstone
  [  5,-10, 4, 4,12, '#588250', '#6C9664'],  // green glass
  [-12, 14, 6, 5,14, '#94483E', '#A55A4E'],  // brick-red
  [ 15,  5, 5, 7,19, '#3C5070', '#506484'],  // dusk blue
  [-20, 18, 6, 6,10, '#628E73', '#76A287'],  // jade
  [  6, 18, 7, 5, 8, '#B2946E', '#C3A580'],  // caramel
] as const

// Trees: [x, z]
const TREE_XZ = [
  [-4,5],[-5,8],[-8,5],[-7,9],[-9,8],[-5,6],         // park 1
  [9,-9],[12,-13],[13,-10],[10,-13],                   // park 2
  [-14,-4],[-17,-8],[-15,-8],                          // park 3
  [4,3],[4,-3],[-4,3],[-4,-3],                         // street trees
  [10,3],[10,-3],[-10,3],[-10,-3],[16,3],[16,-3],
] as const

// Parks: [cx, cz, w, d]
const PARKS = [[-7,7,9,9], [11,-11,7,7], [-16,-6,6,6]] as const

// ── Scene components ──────────────────────────────────────────────────────────

function Ground() {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
      <planeGeometry args={[span, span]} />
      <meshStandardMaterial color={C_GROUND} />
    </mesh>
  )
}

function Roads() {
  return (
    <>
      {/* E-W road */}
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[span, 0.01, 5]} />
        <meshStandardMaterial color={C_ROAD} />
      </mesh>
      {/* N-S road */}
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[5, 0.01, span]} />
        <meshStandardMaterial color={C_ROAD} />
      </mesh>
      {/* E-W centre line */}
      <mesh position={[0, 0.03, 0]}>
        <boxGeometry args={[span, 0.01, 0.14]} />
        <meshStandardMaterial color={C_LINE} />
      </mesh>
      {/* N-S centre line */}
      <mesh position={[0, 0.03, 0]}>
        <boxGeometry args={[0.14, 0.01, span]} />
        <meshStandardMaterial color={C_LINE} />
      </mesh>
    </>
  )
}

function Parks() {
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

function GridOverlay() {
  // Use Three.js GridHelper for efficiency — matches the subtle city-block grid
  return (
    <>
      <gridHelper
        args={[span, GRID_CELLS, C_GRID_MAJ, C_GRID_MIN]}
        position={[0, 0.01, 0]}
      />
    </>
  )
}

function Trees() {
  return (
    <>
      {TREE_XZ.map(([tx, tz], i) => (
        <group key={i}>
          {/* Trunk */}
          <mesh position={[tx, 0.65, tz]}>
            <boxGeometry args={[0.18, 1.3, 0.18]} />
            <meshStandardMaterial color={C_TRUNK} />
          </mesh>
          {/* Canopy */}
          <mesh position={[tx, 1.7, tz]}>
            <sphereGeometry args={[0.45, 8, 6]} />
            <meshStandardMaterial color={C_LEAF} />
          </mesh>
        </group>
      ))}
    </>
  )
}

function CityBuildings() {
  return (
    <>
      {CITY_BUILDINGS.map(([cx, cz, w, d, h, bodyColor, roofColor], i) => (
        <group key={i}>
          {/* Body */}
          <mesh position={[cx, h / 2, cz]}>
            <boxGeometry args={[w, h, d]} />
            <meshStandardMaterial color={bodyColor} />
          </mesh>
          {/* Roof cap */}
          <mesh position={[cx, h + 0.08, cz]}>
            <boxGeometry args={[w, 0.16, d]} />
            <meshStandardMaterial color={roofColor} />
          </mesh>
          {/* Glass band accents on tall buildings (h >= 14) */}
          {h >= 14 && Array.from({ length: Math.floor(h / FLOOR_H) - 1 }, (_, fi) => (
            <mesh key={fi} position={[cx, (fi + 1) * FLOOR_H, cz]}>
              <boxGeometry args={[w * 0.92, 0.28, d * 0.92]} />
              <meshStandardMaterial color={C_GLASSBAND} transparent opacity={0.45} depthWrite={false} />
            </mesh>
          ))}
        </group>
      ))}
    </>
  )
}

function TargetBuilding() {
  const hw = FLOOR_W / 2
  const hd = FLOOR_D / 2

  return (
    <>
      {/* Concrete floor slabs */}
      {Array.from({ length: NUM_FLOORS + 1 }, (_, n) => (
        <mesh key={n} position={[0, n * FLOOR_H, 0]}>
          <boxGeometry args={[FLOOR_W, FLOOR_T, FLOOR_D]} />
          <meshStandardMaterial color={C_SLAB} />
        </mesh>
      ))}

      {/* Glass curtain walls — semi-transparent */}
      {[
        { pos: [0,      total_h / 2, -hd] as [number,number,number], size: [FLOOR_W, total_h, 0.12] as [number,number,number] },
        { pos: [0,      total_h / 2,  hd] as [number,number,number], size: [FLOOR_W, total_h, 0.12] as [number,number,number] },
        { pos: [-hw, total_h / 2, 0]      as [number,number,number], size: [0.12, total_h, FLOOR_D] as [number,number,number] },
        { pos: [ hw, total_h / 2, 0]      as [number,number,number], size: [0.12, total_h, FLOOR_D] as [number,number,number] },
      ].map(({ pos, size }, i) => (
        <mesh key={i} position={pos}>
          <boxGeometry args={size} />
          <meshStandardMaterial color={C_GLASS} transparent opacity={0.25} depthWrite={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </>
  )
}

function Survivors() {
  return (
    <>
      {/* Floor 2 survivor */}
      <mesh position={[-1.5, survY(2), 1.0]}>
        <sphereGeometry args={[0.325, 12, 8]} />
        <meshStandardMaterial color="#ff2222" emissive="#ff0000" emissiveIntensity={0.4} />
      </mesh>
      {/* Floor 4 survivor */}
      <mesh position={[1.5, survY(4), -1.0]}>
        <sphereGeometry args={[0.325, 12, 8]} />
        <meshStandardMaterial color="#ff2222" emissive="#ff0000" emissiveIntensity={0.4} />
      </mesh>
    </>
  )
}

// ── Drone (telemetry-driven position with smooth lerp) ────────────────────────

interface DroneProps {
  targetPos: THREE.Vector3
  status: string
}

function DroneMesh({ targetPos, status }: DroneProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const lerpPos = useRef(DRONE_START.clone())

  useFrame((_, delta) => {
    if (!meshRef.current) return
    // Smooth lerp towards latest telemetry position
    lerpPos.current.lerp(targetPos, Math.min(delta * 4, 1))
    meshRef.current.position.copy(lerpPos.current)

    const mat = meshRef.current.material as THREE.MeshStandardMaterial
    if (status === 'MOVING') {
      mat.color.setHex(0x00ff88)
      mat.emissive.setHex(0x00aa44)
    } else if (status === 'SCANNING') {
      mat.color.setHex(0xffaa00)
      mat.emissive.setHex(0xaa6600)
    } else {
      mat.color.setHex(0x00ffff)
      mat.emissive.setHex(0x00aaaa)
    }
  })

  return (
    <mesh ref={meshRef} position={DRONE_START.toArray()}>
      <boxGeometry args={[0.6, 0.6, 0.6]} />
      <meshStandardMaterial color="#00ffff" emissive="#00aaaa" emissiveIntensity={0.3} />
    </mesh>
  )
}

// ── Mission log overlay ───────────────────────────────────────────────────────

function MissionLog({ lines }: { lines: string[] }) {
  return (
    <div style={{
      position: 'absolute',
      bottom: 20,
      left: 20,
      background: 'rgba(0,0,0,0.65)',
      border: '1px solid #334',
      borderRadius: 6,
      padding: '10px 14px',
      color: '#9cf',
      fontSize: 12,
      fontFamily: 'Courier New, monospace',
      lineHeight: 1.6,
      maxWidth: 420,
      pointerEvents: 'none',
    }}>
      {lines.map((l, i) => (
        <div key={i} style={{ color: l.includes('confirmed') ? '#4f4' : '#9cf' }}>{l}</div>
      ))}
    </div>
  )
}

function Controls() {
  return (
    <div style={{
      position: 'absolute',
      top: 16,
      right: 16,
      background: 'rgba(0,0,0,0.55)',
      border: '1px solid #334',
      borderRadius: 6,
      padding: '8px 12px',
      color: '#667',
      fontSize: 11,
      fontFamily: 'Courier New, monospace',
      lineHeight: 1.8,
      pointerEvents: 'none',
    }}>
      <div style={{ color: '#99b', marginBottom: 4, letterSpacing: 1 }}>PROJECT BEACON — SAR POC</div>
      <div>Left drag  : orbit</div>
      <div>Right drag : pan</div>
      <div>Scroll     : zoom</div>
      <div style={{ marginTop: 6, color: '#4cf' }}>Enter      : send command</div>
    </div>
  )
}

// ── Main scene ────────────────────────────────────────────────────────────────

const ASSET_ID = 'BEACON-01'
const WS_URL   = 'ws://localhost:8000/ws/telemetry'

export default function SARScene() {
  const [log, setLog] = useState<string[]>(['Connecting to backend...'])
  const [connected, setConnected] = useState(false)
  const drones = useTelemetry(WS_URL)

  const telemetry = drones[ASSET_ID] ?? null
  const dronePos = useMemo(
    () => telemetry ? new THREE.Vector3(telemetry.x, telemetry.y, telemetry.z) : DRONE_START.clone(),
    [telemetry?.x, telemetry?.y, telemetry?.z]
  )
  const droneStatus = telemetry?.status ?? 'IDLE'
  const battery = telemetry?.battery ?? null

  const addLog = useCallback((msg: string) => {
    setLog(prev => [...prev.slice(-6), msg])
  }, [])

  // Auto-uplink on mount
  useEffect(() => {
    let mounted = true
    const init = async () => {
      const ok = await healthCheck()
      if (!ok || !mounted) {
        addLog('⚠ Backend offline — start FastAPI sidecar')
        return
      }
      try {
        await uplink(ASSET_ID)
        if (mounted) {
          setConnected(true)
          addLog(`✓ ${ASSET_ID} uplinked — agent ready`)
        }
      } catch {
        // Already uplinked or scan needed — still mark connected
        if (mounted) {
          setConnected(true)
          addLog(`✓ ${ASSET_ID} online`)
        }
      }
    }
    init()
    return () => { mounted = false }
  }, [])

  // Update log when telemetry reports position changes
  useEffect(() => {
    if (!telemetry) return
    if (telemetry.status === 'MOVING') {
      addLog(`→ ${ASSET_ID} moving to (${telemetry.x.toFixed(1)}, ${telemetry.y.toFixed(1)}, ${telemetry.z.toFixed(1)})`)
    }
  }, [telemetry?.status])

  const handleCommand = useCallback(async (
    prompt: string,
    onEvent: (e: AgentStreamEvent) => void,
  ): Promise<void> => {
    addLog(`⬆ ${prompt}`)
    for await (const event of streamCommand(ASSET_ID, prompt)) {
      onEvent(event)
      if (event.type === 'done') addLog('✓ Agent responded')
    }
  }, [addLog])

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', background: '#0d0d17' }}>
      <Canvas shadows>
        {/* Camera — matches Ursina EditorCamera initial angle */}
        <PerspectiveCamera makeDefault position={CAM_POS} fov={60} near={0.1} far={1000} />
        <OrbitControls
          enableDamping
          dampingFactor={0.08}
          minDistance={5}
          maxDistance={200}
          target={[0, 5, 0]}
        />

        {/* Lighting */}
        <ambientLight intensity={0.6} />
        <directionalLight position={[30, 60, 20]} intensity={1.2} castShadow />
        <hemisphereLight args={['#1a1a2e', '#0d0d0d', 0.4]} />

        {/* Scene */}
        <Ground />
        <Roads />
        <Parks />
        <GridOverlay />
        <Trees />
        <CityBuildings />
        <TargetBuilding />
        <Survivors />
        <DroneMesh targetPos={dronePos} status={droneStatus} />
      </Canvas>

      <MissionLog lines={log} />
      <Controls />
      <CommandPanel
        assetId={ASSET_ID}
        connected={connected}
        battery={battery}
        onCommand={handleCommand}
      />
    </div>
  )
}
