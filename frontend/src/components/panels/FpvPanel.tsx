'use client'

import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { Ground } from '../scene-props/Ground'
import { MissionBuildings } from '../scene-props/MissionBuildings'
import { Survivors } from '../scene-props/Survivors'
import type { DroneMap, TelemetryPayload } from '@/lib/ws'
import type { SurvivorPoint, WorldBuilding } from '@/types/worldTypes'
import { FLOOD_LEVEL, FLOOR_H, FLOOR_T, W2_GRID_CELLS, W2_GRID_SPACING } from '../../../constants/missionConstants'
import { World2Environment } from '../scene-props/World2Environment'

const FPV_HEAD_OFFSET_Y = 1.2
const FPV_LOOK_AHEAD_M = 20

function TelemetryMarker({ payload }: { payload: TelemetryPayload }) {
  const isSelected = payload.asset_id === 'BEACON-SCOUT'
  const color = isSelected ? '#ffd84d' : '#00d0ff'
  return (
    <mesh position={[payload.x, payload.y + 0.3, payload.z]}>
      <sphereGeometry args={[0.16, 10, 10]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.45} />
    </mesh>
  )
}

function FpvCameraRig({ telemetry }: { telemetry: TelemetryPayload }) {
  const { camera } = useThree()
  const smoothPosition = useRef(new THREE.Vector3(telemetry.x, telemetry.y, telemetry.z))
  const lastPosition = useRef(new THREE.Vector3(telemetry.x, telemetry.y, telemetry.z))
  const lastHeadingDeg = useRef<number>(typeof telemetry.heading_deg === 'number' ? telemetry.heading_deg : 0)
  const lookTarget = useRef(new THREE.Vector3())

  useFrame((_, delta) => {
    const targetPosition = new THREE.Vector3(telemetry.x, telemetry.y + FPV_HEAD_OFFSET_Y, telemetry.z)
    const headingFromMotion = (() => {
      const dx = targetPosition.x - lastPosition.current.x
      const dz = targetPosition.z - lastPosition.current.z
      if (Math.abs(dx) < 1e-4 && Math.abs(dz) < 1e-4) return null
      return (Math.atan2(dx, -dz) * 180) / Math.PI
    })()

    if (typeof telemetry.heading_deg === 'number') {
      lastHeadingDeg.current = telemetry.heading_deg
    } else if (headingFromMotion !== null) {
      lastHeadingDeg.current = headingFromMotion
    }

    lastPosition.current.copy(targetPosition)
    smoothPosition.current.lerp(targetPosition, Math.min(delta * 8, 1))
    camera.position.copy(smoothPosition.current)

    const headingRad = (lastHeadingDeg.current * Math.PI) / 180
    const tiltDeg = typeof telemetry.scan_tilt_deg === 'number' ? telemetry.scan_tilt_deg : -8
    const tiltRad = (tiltDeg * Math.PI) / 180
    const cosTilt = Math.cos(tiltRad)
    const direction = new THREE.Vector3(
      Math.sin(headingRad) * cosTilt,
      Math.sin(tiltRad),
      -Math.cos(headingRad) * cosTilt,
    ).normalize()

    lookTarget.current.copy(smoothPosition.current).addScaledVector(direction, FPV_LOOK_AHEAD_M)
    camera.lookAt(lookTarget.current)
  })

  return null
}

interface FpvPanelProps {
  drones: DroneMap
  selectedAssetId: string | null
  onSelectAsset: (assetId: string) => void
  span: number
  buildings: WorldBuilding[]
  survivors: SurvivorPoint[]
  floorHeight: number
  floorThickness: number
  transparentWalls: boolean
}

function FpvViewport({
  telemetry,
  drones,
  span,
  worldSpan,
  buildings,
  survivors,
  floorHeight,
  floorThickness,
  transparentWalls,
  heightClass,
}: {
  telemetry: TelemetryPayload
  drones: TelemetryPayload[]
  span: number
  worldSpan: number
  buildings: WorldBuilding[]
  survivors: SurvivorPoint[]
  floorHeight: number
  floorThickness: number
  transparentWalls: boolean
  heightClass: string
}) {
  return (
    <div className={`${heightClass} w-full`}>
      <Canvas camera={{ fov: 90, near: 0.1, far: 600 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[20, 30, 10]} intensity={1.0} />
        <hemisphereLight args={['#19253d', '#0b0f16', 0.45]} />
        <Ground span={span} />
        <World2Environment
          span={worldSpan}
          floorHeight={FLOOR_H}
          floorThickness={FLOOR_T}
          floodLevel={FLOOD_LEVEL}
          transparentWalls={transparentWalls}
          exploredSectors={undefined}
        />
        <MissionBuildings
          buildings={buildings}
          transparentWalls={transparentWalls}
          floorHeight={floorHeight}
          floorThickness={floorThickness}
          survivorStatsByBuilding={{}}
          showSurvivorStats={false}
        />
        <Survivors
          floodY={0}
          survivors={survivors}
          deliveredTo={new Set<string>()}
          detectedSurvivors={new Set<string>()}
        />
        {drones
          .filter((drone) => drone.asset_id !== telemetry.asset_id)
          .map((drone) => (
            <TelemetryMarker key={drone.asset_id} payload={drone} />
          ))}
        <FpvCameraRig telemetry={telemetry} />
      </Canvas>
    </div>
  )
}

export function FpvPanel({
  drones,
  selectedAssetId,
  onSelectAsset,
  span,
  buildings,
  survivors,
  floorHeight,
  floorThickness,
  transparentWalls,
}: FpvPanelProps) {
  const [fullMode, setFullMode] = useState(false)
  const gridCells  = W2_GRID_CELLS
  const gridSpacing = W2_GRID_SPACING
  const worldSpan  = gridCells * gridSpacing

  const droneList = useMemo(
    () => Object.values(drones).sort((a, b) => a.asset_id.localeCompare(b.asset_id)),
    [drones],
  )

  const selectedTelemetry = selectedAssetId ? (drones[selectedAssetId] ?? null) : null

  useEffect(() => {
    if (selectedAssetId && drones[selectedAssetId]) return
    const fallback = droneList[0]?.asset_id
    if (fallback) onSelectAsset(fallback)
  }, [droneList, drones, onSelectAsset, selectedAssetId])

  useEffect(() => {
    if (!fullMode) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [fullMode])

  return (
    <>
      <div className="pointer-events-auto min-w-[300px] overflow-hidden rounded-lg border border-[rgba(70,155,210,0.28)] bg-[linear-gradient(135deg,rgba(5,12,20,0.94),rgba(4,8,16,0.92))] p-[8px] font-mono shadow-[0_10px_26px_rgba(0,0,0,0.5)] backdrop-blur-[10px]">
        <div className="mb-2 flex items-center justify-between tracking-[1px] text-[#99c4e8]">
          <span className="text-[12px] font-bold">FPV FEED</span>
          <button
            onClick={() => setFullMode(true)}
            className="cursor-pointer rounded border border-[rgba(120,170,220,0.35)] bg-[rgba(10,20,35,0.55)] px-2 py-[3px] text-[10px] text-[#b8d7ef]"
          >
            FULL MODE
          </button>
        </div>

        {droneList.length === 0 && (
          <div className="rounded border border-[rgba(90,120,150,0.25)] bg-[rgba(8,12,22,0.45)] px-2 py-[6px] text-[11px] text-[#7f93a8]">
            No drone telemetry available.
          </div>
        )}

        {droneList.length > 0 && (
          <>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {droneList.map((d) => {
                const active = d.asset_id === selectedAssetId
                return (
                  <button
                    key={d.asset_id}
                    onClick={() => onSelectAsset(d.asset_id)}
                    className={`cursor-pointer rounded border px-2 py-[3px] text-[10px] tracking-[0.4px] ${
                      active
                        ? 'border-[#5fc6ff] bg-[rgba(28,82,122,0.55)] text-[#d6efff]'
                        : 'border-[rgba(106,142,173,0.35)] bg-[rgba(10,20,35,0.5)] text-[#9cb8ce]'
                    }`}
                  >
                    {d.asset_id}
                  </button>
                )
              })}
            </div>

            <div className="overflow-hidden rounded-md border border-[rgba(80,130,180,0.35)] bg-[#060b13]">
              {selectedTelemetry ? (
                <FpvViewport
                  telemetry={selectedTelemetry}
                  drones={droneList}
                  span={span}
                  worldSpan={worldSpan}
                  buildings={buildings}
                  survivors={survivors}
                  floorHeight={floorHeight}
                  floorThickness={floorThickness}
                  transparentWalls={transparentWalls}
                  heightClass="h-[190px]"
                />
              ) : (
                <div className="flex h-[190px] w-full items-center justify-center text-[11px] text-[#6e89a1]">
                  Selected drone is offline.
                </div>
              )}
            </div>

            {selectedTelemetry && (
              <div className="mt-2 flex items-center justify-between text-[10px] text-[#8eaec8]">
                <span>{selectedTelemetry.asset_id}</span>
                <span>{selectedTelemetry.status}</span>
                <span>{Math.round(selectedTelemetry.battery)}%</span>
              </div>
            )}
          </>
        )}
      </div>

      {fullMode && (
        <div
          className="fixed inset-0 z-[90] flex items-center justify-center bg-[rgba(1,4,10,0.72)] p-4"
          onClick={() => setFullMode(false)}
        >
          <div
            className="max-h-[92vh] w-[min(1200px,96vw)] overflow-hidden rounded-xl border border-[rgba(90,150,210,0.45)] bg-[linear-gradient(140deg,rgba(4,10,18,0.96),rgba(3,7,14,0.95))] p-3 shadow-[0_18px_80px_rgba(0,0,0,0.65)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between text-[#a5cff1]">
              <div className="text-xs font-bold tracking-[1px]">CONTROL ROOM FPV WALL</div>
              <button
                onClick={() => setFullMode(false)}
                className="cursor-pointer rounded border border-[rgba(120,170,220,0.45)] bg-[rgba(10,20,35,0.65)] px-2 py-[3px] text-[10px] text-[#c9e4f9]"
              >
                CLOSE
              </button>
            </div>

            <div className="max-h-[calc(92vh-52px)] overflow-y-auto">
              <div className="mt-2 rounded-md border border-[rgba(80,130,180,0.35)] bg-[#060b13] p-2">
                <div className="mb-2 text-[10px] font-bold tracking-[0.8px] text-[#9bc9ee]">
                  SURVEILLANCE WALL
                </div>
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  {droneList.map((telemetry) => (
                    <div
                      key={`wall-${telemetry.asset_id}`}
                      className="overflow-hidden rounded border border-[rgba(92,132,170,0.4)] bg-[rgba(2,6,12,0.9)]"
                    >
                      <FpvViewport
                        telemetry={telemetry}
                        drones={droneList}
                        span={span}
                        worldSpan={worldSpan}
                        buildings={buildings}
                        survivors={survivors}
                        floorHeight={floorHeight}
                        floorThickness={floorThickness}
                        transparentWalls={transparentWalls}
                        heightClass="h-[170px]"
                      />
                      <div className="flex items-center justify-between border-t border-[rgba(92,132,170,0.28)] bg-[rgba(7,12,20,0.92)] px-2 py-1 text-[10px] text-[#9fc0d9]">
                        <span>{telemetry.asset_id}</span>
                        <span>{telemetry.status}</span>
                        <span>{Math.round(telemetry.battery)}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
