'use client'

import { Canvas } from '@react-three/fiber'
import { OrbitControls, PerspectiveCamera } from '@react-three/drei'
import { useRef, useState, useEffect, useMemo, useCallback } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import CommandPanel from './panels/CommandPanel'
import { useTelemetry } from '@/lib/ws'
import {
  uplink,
  streamCommand,
  healthCheck,
  getFleet, switchWorld,
  getAutoRecallConfig,
  getNetworkMockStatus,
  resetDroneToBase,
  type AgentStreamEvent,
  type NetworkMockStatus,
  type SupplyDispatchEvent,
} from '@/lib/api'
import { BasePad, GridOverlay, Ground, MissionBuildings, Survivors } from './scene-props/SceneStructures'
import { World2Environment } from './scene-props/World2Environment'
import {
  AreaContextMenu,
  AreaHighlight,
  AreaSelectProbe,
  GroundCursor,
  GroundProbe,
  type AreaSelection,
} from './panels/InteractionOverlays'
import {
  CompassLabels,
} from './panels/CompassLabels'
import { Controls } from './panels/Controls'
import { CoordOverlay } from './panels/CoordOverlay'
import { DroneStatusPanel } from './panels/DronePanel'
import { TopStatusBar } from './panels/TopStatusBar'
import { CameraTracker, FollowBeaconCamera } from './animation/CameraTracker'
import { SupplyThrow } from './animation/ThrowAnimation'
import {
  BASE_PICKUP_RANGE,
  BASE_Y,
  DRONE_START,
  FLOOR_H,
  FLOOR_T,
  FLOOD_LEVEL,
  ROUTE_ARRIVAL_TOLERANCE,
  SUPPLY_DISPATCH_TARGET_TOLERANCE,
  W1_BUILDINGS,
  W1_CAM_POS,
  W1_FOG,
  W1_GRID_CELLS,
  W1_GRID_SPACING,
  W1_SIM_BUILDINGS,
  W1_SURVIVORS,
  W2_BUILDINGS,
  W2_CAM_POS,
  W2_FOG,
  W2_GRID_CELLS,
  W2_GRID_SPACING,
  W2_SIM_BUILDINGS,
  W2_SURVIVORS,
  buildingBounds,
  buildingPromptName,
  computeApproachPosition,
  computeSupplyThrowOrigin,
  detectedSurvivorsFromTelemetryEntry,
  distance2D,
  distance3D,
  distanceBetweenPoints,
  findBalconyHostBuilding,
  findBuildingAt,
  mergeUniqueSurvivors,
  parseArrivedCoords,
  parseSupplyLoopAssetId,
  scannedSurvivorsFromDrone,
  survivorAssociatedBuildingId,
  survivorKey,
} from '../../constants/missionConstants'
import { ActivityFeed, IntelCard, nextActivityId, parseEventToActivity, type ActivityCategory, type ActivityItem } from './panels/StatPanel'
import { MetricsPanel } from './panels/MetricsPanel'
import { DroneMesh } from './scene-props/Drone'
import { SupplyCrates } from './scene-props/SupplyCrate'
import type { SurvivorPoint, WorldBuilding } from '../types/worldTypes'
import { FogOfWar } from './three/FogOfWar'
import { useExploration } from '@/hooks/useExploration'
import { SCOUT_ASSET_ID } from '@/lib/fogOfWar'

// ── Main scene ────────────────────────────────────────────────────────────────

const ASSET_ID = 'BEACON-01'
const WS_URL   = 'ws://localhost:8000/ws/telemetry'
const AUTO_RECALL_UI_DELAY_MS = 5000

export default function SARScene() {
  const [activeWorld, setActiveWorld] = useState<1 | 2>(1)

  // ── Per-world derived data ──────────────────────────────────────────────────
  const worldBuildings = activeWorld === 1 ? W1_BUILDINGS : W2_BUILDINGS
  const simBuildings   = activeWorld === 1 ? W1_SIM_BUILDINGS : W2_SIM_BUILDINGS
  const survivorPositions = activeWorld === 1 ? W1_SURVIVORS : W2_SURVIVORS
  const gridCells  = activeWorld === 1 ? W1_GRID_CELLS : W2_GRID_CELLS
  const gridSpacing = activeWorld === 1 ? W1_GRID_SPACING : W2_GRID_SPACING
  const worldSpan  = gridCells * gridSpacing
  const camPos     = activeWorld === 1 ? W1_CAM_POS : W2_CAM_POS
  const fogRange   = activeWorld === 1 ? W1_FOG : W2_FOG

  const [log, setLog]       = useState<string[]>(['Connecting to backend...'])
  const [uplinked, setUplinked] = useState(false)
  const [hoverPt, setHoverPt]     = useState<THREE.Vector3 | null>(null)
  const [copied, setCopied]       = useState(false)
  const [followBeacon, setFollowBeacon] = useState(false)
  const [followedAssetId, setFollowedAssetId] = useState<string | null>(ASSET_ID)
  const [transparentWalls, setTransparentWalls] = useState(false)
  const [deliveredTo, setDeliveredTo] = useState<Set<string>>(new Set())
  const [deliveringTo, setDeliveringTo] = useState<Set<string>>(new Set())
  const deliveredToRef = useRef<Set<string>>(new Set())
  const deliveringToRef = useRef<Set<string>>(new Set())
  const processedSupplyDispatchKeysRef = useRef<Set<string>>(new Set())
  const [activities, setActivities] = useState<ActivityItem[]>([])
  const [agentBusy, setAgentBusy] = useState(false)
  const [hasCargo, setHasCargo] = useState(false)
  const [cargoByDrone, setCargoByDrone] = useState<Set<string>>(new Set())
  const [activeThrow, setActiveThrow] = useState<{ from: THREE.Vector3; to: SurvivorPoint } | null>(null)
  const throwQueueRef = useRef<Array<{ from: THREE.Vector3; to: SurvivorPoint }>>([])
  const detectedSurvivorsRef = useRef<SurvivorPoint[]>([])
  const detectedSurvivorKeysRef = useRef<Set<string>>(new Set())
  const pendingSupplyPickupRef = useRef<Set<string>>(new Set())
  const supplyInFlightByAssetRef = useRef<Record<string, number>>({})
  const backendSupplyDispatchSeenRef = useRef(false)
  const deliveryTarget = useRef<SurvivorPoint | null>(null)
  const deliveryApproach = useRef<SurvivorPoint | null>(null)
  const deliveryThrowOrigin = useRef<SurvivorPoint | null>(null)
  const [routeArrived, setRouteArrived] = useState(false)
  const [autoRecallThreshold, setAutoRecallThreshold] = useState<number | null>(null)
  const [networkMockStatus, setNetworkMockStatus] = useState<NetworkMockStatus | null>(null)
  const [autoRecallPrompt, setAutoRecallPrompt] = useState<{ assetId: string; battery: number } | null>(null)
  const [autoRecallCountdown, setAutoRecallCountdown] = useState(5)
  const autoRecallDismissedRef = useRef<Set<string>>(new Set())
  const autoRecallTriggeredRef = useRef<Set<string>>(new Set())
  const autoRecallInFlightRef = useRef<Set<string>>(new Set())
  // ── Performance metrics state ──────────────────────────────────────────────
  const [missionStartTs, setMissionStartTs] = useState<number | null>(null)
  const [lastTtftMs, setLastTtftMs] = useState<number | null>(null)
  const survivorDetectionTsRef = useRef<Map<string, number>>(new Map())
  const [survivorDetectionTimestamps, setSurvivorDetectionTimestamps] = useState<Map<string, number>>(new Map())
  const [survivorDeliveryTimestamps, setSurvivorDeliveryTimestamps] = useState<Map<string, number>>(new Map())
  // ── Area selection state ─────────────────────────────────────────────────────
  const [selectMode, setSelectMode]       = useState(false)
  const [dragStart, setDragStart]         = useState<THREE.Vector3 | null>(null)
  const [dragEnd, setDragEnd]             = useState<THREE.Vector3 | null>(null)
  const [selection, setSelection]         = useState<AreaSelection | null>(null)
  const [showContextMenu, setShowContextMenu] = useState(false)
  // ─────────────────────────────────────────────────────────────────────────────
  const copiedTimer               = useRef<ReturnType<typeof setTimeout> | null>(null)
  const orbitRef                  = useRef<OrbitControlsImpl | null>(null)
  const northAngleRef             = useRef<number>(0)

  const clearAreaSelectionPreview = useCallback(() => {
    setShowContextMenu(false)
    setSelection(null)
  }, [])

  const clearAreaSelectionState = useCallback(() => {
    setSelectMode(false)
    setDragStart(null)
    setDragEnd(null)
    clearAreaSelectionPreview()
  }, [clearAreaSelectionPreview])

  const handleGroundClick = useCallback((pt: THREE.Vector3) => {
    const text = `${pt.x.toFixed(1)}, ${pt.y.toFixed(1)}, ${pt.z.toFixed(1)}`
    navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    if (copiedTimer.current) clearTimeout(copiedTimer.current)
    copiedTimer.current = setTimeout(() => setCopied(false), 1500)
  }, [])
  const { drones, exploredSectors, latestReveals } = useTelemetry(WS_URL)

  // ── Fog-of-war exploration state ──────────────────────────────────────────
  const exploration = useExploration(exploredSectors, latestReveals, worldBuildings, survivorPositions)

  const handleWorldChange = useCallback((world: 1 | 2) => {
    setActiveWorld(world)
    switchWorld(world).catch(() => {})  // notify backend + drones
    exploration.reset()
  }, [exploration.reset])

  const activeDroneAssetIds = useMemo(
    () => Object.values(drones).map(entry => entry.asset_id).sort((a, b) => a.localeCompare(b)),
    [drones]
  )

  const defaultFollowAssetId = useMemo(() => {
    if (activeDroneAssetIds.includes(ASSET_ID)) return ASSET_ID
    return activeDroneAssetIds[0] ?? null
  }, [activeDroneAssetIds])

  const telemetry = drones[ASSET_ID] ?? null
  const dronePos = useMemo(
    () => telemetry ? new THREE.Vector3(telemetry.x, telemetry.y, telemetry.z) : DRONE_START.clone(),
    [telemetry?.x, telemetry?.y, telemetry?.z]
  )
  const followedTelemetry = followedAssetId ? (drones[followedAssetId] ?? null) : null
  const followTargetPos = useMemo(
    () => followedTelemetry
      ? new THREE.Vector3(followedTelemetry.x, followedTelemetry.y, followedTelemetry.z)
      : DRONE_START.clone(),
    [followedTelemetry?.x, followedTelemetry?.y, followedTelemetry?.z]
  )
  const droneStatus = telemetry?.status ?? 'IDLE'
  const battery   = telemetry?.battery ?? null
  const connected = telemetry !== null

  const addLog = useCallback((msg: string) => {
    setLog(prev => [...prev.slice(-6), msg])
  }, [])

  const markSupplyLoopStart = useCallback((assetId: string) => {
    const next = { ...supplyInFlightByAssetRef.current }
    next[assetId] = (next[assetId] ?? 0) + 1
    supplyInFlightByAssetRef.current = next
    pendingSupplyPickupRef.current.add(assetId)
  }, [])

  const markSupplyLoopEnd = useCallback((assetId: string) => {
    const next = { ...supplyInFlightByAssetRef.current }
    const remaining = (next[assetId] ?? 0) - 1
    if (remaining <= 0) {
      delete next[assetId]
      pendingSupplyPickupRef.current.delete(assetId)
      setCargoByDrone(prev => {
        if (!prev.has(assetId)) return prev
        const updated = new Set(prev)
        updated.delete(assetId)
        return updated
      })
    } else {
      next[assetId] = remaining
    }
    supplyInFlightByAssetRef.current = next
  }, [])

  const queueSupplyThrow = useCallback((from: THREE.Vector3, to: SurvivorPoint) => {
    setActiveThrow(prev => {
      if (!prev) return { from, to }
      throwQueueRef.current.push({ from, to })
      return prev
    })
  }, [])

  const queueSupplyDispatchAnimations = useCallback((dispatches: SupplyDispatchEvent[]) => {
    const reservedKeys = new Set<string>()
    let queued = 0
    for (const dispatch of dispatches) {
      const dispatchKey = `${dispatch.survivor.x.toFixed(3)},${dispatch.survivor.y.toFixed(3)},${dispatch.survivor.z.toFixed(3)}`
      if (processedSupplyDispatchKeysRef.current.has(dispatchKey)) {
        continue
      }
      const dispatchSurvivor: SurvivorPoint = {
        x: dispatch.survivor.x,
        y: dispatch.survivor.y,
        z: dispatch.survivor.z,
      }
      const nearestBuilding = dispatch.building
        ? worldBuildings.reduce((best, candidate) => {
          const dist = distance2D(candidate.cx, candidate.cz, dispatch.building!.x, dispatch.building!.z)
          if (best === null || dist < best.dist) return { building: candidate, dist }
          return best
        }, null as { building: WorldBuilding; dist: number } | null)
        : null

      // Exact coordinate match: allow re-matching survivors already in deliveringTo
      // so that deliveries initiated by handleSendSupplies complete their throw animation
      // when the backend supply dispatch arrives for the same survivor.
      const exactDetectedTarget = detectedSurvivorsRef.current.find((survivor) => {
        const key = survivorKey(survivor)
        return (
          !deliveredTo.has(key)
          && !reservedKeys.has(key)
          && distanceBetweenPoints(survivor, dispatchSurvivor) <= 0.8
        )
      })

      // For building-based and fallback matching, exclude deliveringTo to prevent
      // double dispatches to the same survivor from different triggers.
      const availableDetected = detectedSurvivorsRef.current.filter((survivor) => {
        const key = survivorKey(survivor)
        return (
          !deliveredToRef.current.has(key)
          && !deliveringToRef.current.has(key)
          && !reservedKeys.has(key)
        )
      })
      const availableKnown = survivorPositions.filter((survivor) => {
        const key = survivorKey(survivor)
        return (
          !deliveredToRef.current.has(key)
          && !deliveringToRef.current.has(key)
          && !reservedKeys.has(key)
        )
      })

      const exactKnownTarget = availableKnown.find(
        (survivor) => distanceBetweenPoints(survivor, dispatchSurvivor) <= SUPPLY_DISPATCH_TARGET_TOLERANCE
      )
      const targetByBuilding = nearestBuilding
        ? availableDetected.find((survivor) => (
          survivorAssociatedBuildingId(simBuildings, worldBuildings, survivor) === nearestBuilding.building.id
        ))
        : null
      const knownTargetByBuilding = nearestBuilding
        ? availableKnown.find((survivor) => (
          survivorAssociatedBuildingId(simBuildings, worldBuildings, survivor) === nearestBuilding.building.id
        ))
        : null
      const fallbackTarget = availableDetected[0]
      const fallbackKnownTarget = availableKnown[0]
      const target = (
        exactDetectedTarget
        ?? exactKnownTarget
        ?? targetByBuilding
        ?? knownTargetByBuilding
        ?? fallbackTarget
        ?? fallbackKnownTarget
        ?? dispatchSurvivor
      )
      if (!target) continue

      const key = survivorKey(target)
      reservedKeys.add(key)
      setDeliveringTo(prev => {
        const next = new Set(prev)
        next.add(key)
        deliveringToRef.current = next
        return next
      })
      processedSupplyDispatchKeysRef.current.add(dispatchKey)

      const telemetryEntry = drones[dispatch.asset_id]
      const fallbackFrom = (
        Number.isFinite(dispatch.drop_point.x)
        && Number.isFinite(dispatch.drop_point.y)
        && Number.isFinite(dispatch.drop_point.z)
      )
        ? new THREE.Vector3(dispatch.drop_point.x, dispatch.drop_point.y, dispatch.drop_point.z)
        : telemetryEntry
          ? new THREE.Vector3(telemetryEntry.x, telemetryEntry.y, telemetryEntry.z)
          : DRONE_START.clone()
      const from = computeSupplyThrowOrigin(simBuildings, worldBuildings, target, fallbackFrom)
      queueSupplyThrow(from, target)
      queued += 1
    }

    if (queued > 0) {
      addLog(`📦 Visualizing ${queued} supply drop${queued === 1 ? '' : 's'}`)
    } else if (dispatches.length > 0) {
      addLog('ℹ No detected survivors available for supply visualization')
    }
  }, [addLog, drones, queueSupplyThrow, simBuildings, survivorPositions, worldBuildings])

  useEffect(() => {
    deliveredToRef.current = deliveredTo
  }, [deliveredTo])

  useEffect(() => {
    deliveringToRef.current = deliveringTo
  }, [deliveringTo])

  useEffect(() => {
    if (activeThrow || throwQueueRef.current.length === 0) return
    const next = throwQueueRef.current.shift()
    if (next) setActiveThrow(next)
  }, [activeThrow])

  // ── Scout activity feed messages ──────────────────────────────────────────
  // Track which sectors have already been logged to prevent duplicates when
  // React re-runs the effect (strict mode, re-render on same reveal batch, etc.)
  const loggedRevealSectorsRef = useRef<Set<string>>(new Set())

  // Reset the dedup set whenever the world switches or exploration resets.
  useEffect(() => {
    if (exploration.exploredSectors.size === 0) {
      loggedRevealSectorsRef.current.clear()
    }
  }, [exploration.exploredSectors])

  useEffect(() => {
    if (activeWorld !== 2) return
    if (latestReveals.length === 0) return

    const items: ActivityItem[] = []
    for (const reveal of latestReveals) {
      if (loggedRevealSectorsRef.current.has(reveal.sector_id)) continue
      loggedRevealSectorsRef.current.add(reveal.sector_id)

      items.push({
        id: nextActivityId(),
        icon: '◎',
        label: `Sector ${reveal.sector_id} mapped`,
        detail: reveal.building_count > 0
          ? `${reveal.building_count} building${reveal.building_count > 1 ? 's' : ''} detected, max height ${reveal.max_height}m`
          : 'Clear — no structures',
        ts: Date.now(),
        status: 'done',
        category: 'scout' as ActivityCategory,
      })

      if (reveal.thermal_anomalies) {
        items.push({
          id: nextActivityId(),
          icon: '⚠',
          label: `Thermal anomalies — Sector ${reveal.sector_id}`,
          detail: 'Heat signatures suggest survivors in area',
          ts: Date.now(),
          status: 'active',
          category: 'scout' as ActivityCategory,
        })
      }
    }

    if (items.length > 0) {
      setActivities(prev => [...prev, ...items])
    }
  }, [latestReveals, activeWorld])

  const executeAutoRecall = useCallback(async (assetId: string, batteryPct: number) => {
    setAutoRecallPrompt(current => (current?.assetId === assetId ? null : current))
    autoRecallDismissedRef.current.add(assetId)
    autoRecallTriggeredRef.current.add(assetId)
    autoRecallInFlightRef.current.add(assetId)
    addLog(`⚠ ${assetId} battery ${batteryPct.toFixed(1)}% — auto recall initiated`)
    try {
      await resetDroneToBase(assetId)
      addLog(`⌂ ${assetId} returning to base`)
    } catch {
      autoRecallTriggeredRef.current.delete(assetId)
      addLog(`⚠ Auto recall failed for ${assetId}`)
    } finally {
      autoRecallInFlightRef.current.delete(assetId)
    }
  }, [addLog])

  const cancelAutoRecall = useCallback(() => {
    if (!autoRecallPrompt) return
    autoRecallDismissedRef.current.add(autoRecallPrompt.assetId)
    setAutoRecallPrompt(null)
    addLog(`⏸ Auto recall cancelled for ${autoRecallPrompt.assetId}`)
  }, [autoRecallPrompt, addLog])

  const toggleFollowBeacon = useCallback(() => {
    if (followBeacon) {
      setFollowBeacon(false)
      addLog('👁 Follow mode disabled')
      return
    }

    const nextAssetId = defaultFollowAssetId
    setFollowedAssetId(nextAssetId)
    setFollowBeacon(true)
    addLog(nextAssetId ? `👁 Following ${nextAssetId}` : '👁 Follow mode enabled (no active drones)')
  }, [addLog, defaultFollowAssetId, followBeacon])

  const handleOrbitStart = useCallback(() => {
    // Keep hook for future control-state based interactions.
  }, [])

  const handleScenePointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    // Right mouse button begins pan in our control mapping.
    if (!followBeacon) return
    if (event.button !== 2) return
    setFollowBeacon(false)
    addLog('👁 Follow mode disabled by manual pan')
  }, [addLog, followBeacon])

  const cycleFollowTarget = useCallback((direction: 1 | -1) => {
    if (!followBeacon || activeDroneAssetIds.length === 0) return

    const currentId = (
      followedAssetId && activeDroneAssetIds.includes(followedAssetId)
        ? followedAssetId
        : defaultFollowAssetId
    )
    if (!currentId) return

    const currentIndex = activeDroneAssetIds.indexOf(currentId)
    const nextIndex = (currentIndex + direction + activeDroneAssetIds.length) % activeDroneAssetIds.length
    const nextId = activeDroneAssetIds[nextIndex]
    setFollowedAssetId(nextId)
    addLog(`👁 Following ${nextId}`)
  }, [activeDroneAssetIds, addLog, defaultFollowAssetId, followBeacon, followedAssetId])

  const followPreviousBeacon = useCallback(() => {
    cycleFollowTarget(-1)
  }, [cycleFollowTarget])

  const followNextBeacon = useCallback(() => {
    cycleFollowTarget(1)
  }, [cycleFollowTarget])

  const toggleWallTransparency = useCallback(() => {
    setTransparentWalls(prev => {
      const next = !prev
      addLog(next ? '🧱 Target walls set to transparent' : '🧱 Target walls set to solid')
      return next
    })
  }, [addLog])

  const [fogEnabled, setFogEnabled] = useState(true)
  const toggleFog = useCallback(() => {
    setFogEnabled(prev => {
      const next = !prev
      addLog(next ? '🌫 Fog-of-war enabled' : '👁 Fog-of-war disabled — full vision')
      return next
    })
  }, [addLog])

  // Auto-uplink all active drones on mount
  useEffect(() => {
    let mounted = true
    const init = async () => {
      const ok = await healthCheck()
      if (!ok || !mounted) {
        addLog('⚠ Backend offline — start FastAPI sidecar')
        return
      }
      try {
        const config = await getAutoRecallConfig()
        if (mounted) setAutoRecallThreshold(config.battery_threshold)
      } catch {
        addLog('⚠ Failed to load auto-recall config')
      }
      let fleet: Awaited<ReturnType<typeof getFleet>>
      try {
        fleet = await getFleet()
      } catch {
        addLog('⚠ Failed to fetch fleet')
        return
      }
      if (!mounted) return
      const active = fleet.fleet.filter(d => d.active)
      if (active.length === 0) {
        addLog('⚠ No active drones found — start drone containers first')
        return
      }
      let anyUplinked = false
      await Promise.all(active.map(async d => {
        try {
          await uplink(d.asset_id)
          if (mounted) addLog(`✓ ${d.asset_id} uplinked — agent ready`)
          anyUplinked = true
        } catch {
          // Already uplinked or unreachable — check current status
          if (d.uplinked) {
            if (mounted) addLog(`✓ ${d.asset_id} registered with commander`)
            anyUplinked = true
          } else {
            if (mounted) addLog(`⚠ ${d.asset_id} not discoverable yet`)
          }
        }
      }))
      if (mounted && anyUplinked) setUplinked(true)
    }
    init()
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    let mounted = true
    const loadNetworkStatus = async () => {
      try {
        const status = await getNetworkMockStatus()
        if (mounted) setNetworkMockStatus(status)
      } catch {
        if (mounted) setNetworkMockStatus(null)
      }
    }

    void loadNetworkStatus()
    const interval = setInterval(() => {
      void loadNetworkStatus()
    }, 3000)

    return () => {
      mounted = false
      clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    if (!telemetry) return
    if (telemetry.status === 'MOVING') {
      addLog(`→ ${ASSET_ID} moving to (${telemetry.x.toFixed(1)}, ${telemetry.y.toFixed(1)}, ${telemetry.z.toFixed(1)})`)
    }
  }, [telemetry?.status])

  useEffect(() => {
    if (activeDroneAssetIds.length === 0) {
      if (followedAssetId !== null) setFollowedAssetId(null)
      return
    }
    if (followedAssetId && activeDroneAssetIds.includes(followedAssetId)) return
    setFollowedAssetId(defaultFollowAssetId)
  }, [activeDroneAssetIds, defaultFollowAssetId, followedAssetId])

  useEffect(() => {
    if (autoRecallThreshold === null) return
    const lowBatteryIdle = Object.values(drones)
      .filter(entry => entry.status === 'IDLE' && entry.battery <= autoRecallThreshold)
      .sort((a, b) => a.asset_id.localeCompare(b.asset_id))
    const lowBatteryIdleIds = new Set(lowBatteryIdle.map(entry => entry.asset_id))

    for (const assetId of [...autoRecallDismissedRef.current]) {
      if (!lowBatteryIdleIds.has(assetId)) autoRecallDismissedRef.current.delete(assetId)
    }
    // NOTE: do NOT clear autoRecallTriggeredRef — once a drone has been
    // auto-recalled it must never re-trigger the popup in this session.

    if (autoRecallPrompt && !lowBatteryIdleIds.has(autoRecallPrompt.assetId)) {
      setAutoRecallPrompt(null)
      return
    }
    if (autoRecallPrompt) return

    const nextPrompt = lowBatteryIdle.find(entry =>
      !autoRecallDismissedRef.current.has(entry.asset_id)
      && !autoRecallTriggeredRef.current.has(entry.asset_id)
      && !autoRecallInFlightRef.current.has(entry.asset_id)
    )
    if (nextPrompt) {
      setAutoRecallPrompt({ assetId: nextPrompt.asset_id, battery: nextPrompt.battery })
    }
  }, [drones, autoRecallPrompt, autoRecallThreshold])

  useEffect(() => {
    if (!autoRecallPrompt) return
    const deadline = Date.now() + AUTO_RECALL_UI_DELAY_MS
    setAutoRecallCountdown(Math.ceil(AUTO_RECALL_UI_DELAY_MS / 1000))

    const interval = setInterval(() => {
      const remainingMs = Math.max(0, deadline - Date.now())
      setAutoRecallCountdown(Math.ceil(remainingMs / 1000))
    }, 200)

    const timeout = setTimeout(() => {
      void executeAutoRecall(autoRecallPrompt.assetId, autoRecallPrompt.battery)
    }, AUTO_RECALL_UI_DELAY_MS)

    return () => {
      clearInterval(interval)
      clearTimeout(timeout)
    }
  }, [autoRecallPrompt, executeAutoRecall])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const tag = target?.tagName
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable

      // F key — follow toggle (skip if in input)
      if (!event.repeat && event.key.toLowerCase() === 'f' && !inInput) {
        event.preventDefault()
        toggleFollowBeacon()
        return
      }

      // Ctrl+S — toggle area select mode (always prevent browser save)
      if (event.ctrlKey && event.key.toLowerCase() === 's') {
        event.preventDefault()
        if (inInput) return
        setSelectMode(prev => {
          const next = !prev
          if (!next) clearAreaSelectionState()
          return next
        })
        return
      }

      // Escape — exit select mode
      if (event.key === 'Escape' && selectMode) {
        clearAreaSelectionState()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [clearAreaSelectionState, toggleFollowBeacon, selectMode])

  const abortRef = useRef<AbortController | null>(null)
  const pendingDeliveryKey = useRef<string | null>(null)
  const deliveryDroneId = useRef<string | null>(null)

  // ── Cargo pickup at base ──────────────────────────────────────────────────
  const cargoPickedUp = useRef(false)
  useEffect(() => {
    if (pendingSupplyPickupRef.current.size === 0) return
    const reachedBase: string[] = []
    for (const assetId of pendingSupplyPickupRef.current) {
      const telemetryEntry = drones[assetId]
      if (!telemetryEntry) continue
      const distToBase = distance3D(telemetryEntry.x, telemetryEntry.y, telemetryEntry.z, 0, 0, 0)
      if (distToBase < BASE_PICKUP_RANGE) reachedBase.push(assetId)
    }
    if (reachedBase.length === 0) return

    setCargoByDrone(prev => {
      const next = new Set(prev)
      for (const assetId of reachedBase) next.add(assetId)
      return next
    })
  }, [drones])

  useEffect(() => {
    if (backendSupplyDispatchSeenRef.current) return
    if (!deliveryTarget.current || cargoPickedUp.current) return
    if (!pendingDeliveryKey.current || !deliveryDroneId.current) return

    const t = drones[deliveryDroneId.current]
    if (!t) return

    const distToBase = distance3D(t.x, t.y, t.z, 0, BASE_Y, 0)
    if (distToBase < BASE_PICKUP_RANGE) {
      cargoPickedUp.current = true
      setHasCargo(true)
      addLog(`📦 Supplies collected from base (${deliveryDroneId.current})`)
    }
  }, [drones, addLog])

  // ── Cargo throw trigger ───────────────────────────────────────────────────

  useEffect(() => {
    if (backendSupplyDispatchSeenRef.current) return
    const target = deliveryTarget.current
    if (!target || activeThrow || !cargoPickedUp.current) return
    if (!routeArrived || !deliveryDroneId.current) return

    const t = drones[deliveryDroneId.current]
    if (!t) return

    cargoPickedUp.current = false
    setHasCargo(false)
    setRouteArrived(false)
    const from = deliveryThrowOrigin.current
      ? new THREE.Vector3(deliveryThrowOrigin.current.x, deliveryThrowOrigin.current.y, deliveryThrowOrigin.current.z)
      : computeSupplyThrowOrigin(simBuildings, worldBuildings, target, new THREE.Vector3(t.x, t.y, t.z))
    queueSupplyThrow(from, target)
    addLog('📦 Supply thrown to survivor')
  }, [routeArrived, drones, activeThrow, addLog, queueSupplyThrow])



  const handleCommand = useCallback(async (
    prompt: string,
    onEvent: (e: AgentStreamEvent) => void,
    assetIdOverride?: string,
  ): Promise<void> => {
    const ac = new AbortController()
    abortRef.current = ac
    backendSupplyDispatchSeenRef.current = false
    addLog(`⬆ ${prompt}`)
    setAgentBusy(true)
    setMissionStartTs(prev => prev ?? Date.now())
    setActivities(prev => [...prev, { id: nextActivityId(), icon: '◆', label: prompt.length > 50 ? prompt.slice(0, 47) + '...' : prompt, ts: Date.now(), status: 'done', category: 'dispatch' as ActivityCategory }])
    const effectiveAssetId = assetIdOverride ?? ASSET_ID
    try {
      for await (const event of streamCommand(effectiveAssetId, prompt, ac.signal)) {
        onEvent(event)
        if (event.type === 'tool_call') {
          const supplyAssetId = parseSupplyLoopAssetId(event.name)
          if (supplyAssetId) markSupplyLoopStart(supplyAssetId)
        }
        if (event.type === 'tool_result') {
          const supplyAssetId = parseSupplyLoopAssetId(event.name)
          if (supplyAssetId) markSupplyLoopEnd(supplyAssetId)
          setActivities(prev => {
            const idx = [...prev].reverse().findIndex(a => a.status === 'active')
            if (idx === -1) return prev
            const realIdx = prev.length - 1 - idx
            const updated = [...prev]
            updated[realIdx] = { ...updated[realIdx], status: event.success ? 'done' : 'error' }
            return updated
          })
        }
        const activity = parseEventToActivity(event)
        if (activity) {
          setActivities(prev => {
            // Aggregate thinking into a single entry
            if (activity.category === 'reasoning' && activity.thinkingLines && prev.length > 0) {
              const last = prev[prev.length - 1]
              if (last.category === 'reasoning' && last.thinkingLines) {
                const merged = [...last.thinkingLines, ...activity.thinkingLines]
                const updated = [...prev]
                updated[updated.length - 1] = { ...last, thinkingLines: merged, label: `Agent reasoning` }
                return updated
              }
            }
            if (activity.label === 'Moving to waypoint' && prev.length > 0) {
              const last = prev[prev.length - 1]
              if (last.label === 'Moving to waypoint') {
                const updated = [...prev]
                updated[updated.length - 1] = { ...activity, id: last.id }
                return updated
              }
            }
            return [...prev, activity]
          })
        }
        if (
          (event.type === 'tool_result' || event.type === 'text') &&
          event.survivors &&
          event.survivors.length > 0
        ) {
          setDiscoveredSurvivors(prev => mergeUniqueSurvivors(prev, event.survivors!))
        }
        if (
          event.type === 'tool_result' &&
          event.supply_dispatches &&
          event.supply_dispatches.length > 0
        ) {
          backendSupplyDispatchSeenRef.current = true
          setRouteArrived(false)
          setHasCargo(false)
          cargoPickedUp.current = false
          queueSupplyDispatchAnimations(event.supply_dispatches)
        }
        // Detect final route arrival — agent emits "BEACON-XX arrived at (x,y,z)"
        // only after ALL waypoints are complete, so this gates the supply throw.
        if (
          (event.type === 'text' || event.type === 'final') &&
          deliveryTarget.current &&
          !backendSupplyDispatchSeenRef.current &&
          /arrived at \(/.test(event.text)
        ) {
          const arrived = parseArrivedCoords(event.text)
          const expected = deliveryThrowOrigin.current ?? deliveryApproach.current ?? deliveryTarget.current
          if (arrived && expected && distanceBetweenPoints(arrived, expected) <= ROUTE_ARRIVAL_TOLERANCE) {
            setRouteArrived(true)
          }
        }
        if (event.type === 'done') {
          addLog('✓ Agent responded')
          if (event.ttft_ms !== null && event.ttft_ms !== undefined) {
            setLastTtftMs(event.ttft_ms)
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') {
        addLog('⚠ Command aborted')
        pendingSupplyPickupRef.current.clear()
        supplyInFlightByAssetRef.current = {}
        setCargoByDrone(new Set())
        setActivities(prev => [...prev, { id: nextActivityId(), icon: '✗', label: 'Aborted', ts: Date.now(), status: 'error', category: 'error' as ActivityCategory }])
      } else {
        throw e
      }
      const key = pendingDeliveryKey.current
      if (key) {
        setDeliveringTo(prev => {
          const next = new Set(prev)
          next.delete(key)
          return next
        })
        setHasCargo(false)
        cargoPickedUp.current = false
        setRouteArrived(false)
        deliveryTarget.current = null
        deliveryApproach.current = null
        deliveryThrowOrigin.current = null
        deliveryDroneId.current = null
        pendingDeliveryKey.current = null
      }
    } finally {
      setAgentBusy(false)
    }
  }, [addLog, markSupplyLoopEnd, markSupplyLoopStart, queueSupplyDispatchAnimations])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  // ── Area scan injection ────────────────────────────────────────────────────
  // We store a pending prompt and pass it to CommandPanel via the externalPrompt
  // prop so the command appears in its input, then auto-submits.
  const [pendingScanPrompt, setPendingScanPrompt] = useState<string | null>(null)
  const [pendingScanAssetId, setPendingScanAssetId] = useState<string | null>(null)

  const handleAreaScan = useCallback(() => {
    if (!selection) return

    // Detect which named buildings overlap the selected area.
    // Exclude balcony enclosures — they are sub-parts of their parent building.
    const overlapping = simBuildings.filter(b => {
      if (b.name.endsWith(' balcony')) return false
      const bb = buildingBounds(b)
      return bb.minX <= selection.maxX && bb.maxX >= selection.minX &&
             bb.minZ <= selection.maxZ && bb.maxZ >= selection.minZ
    })
    const buildingNames = overlapping
      .map(buildingPromptName)
      .filter(Boolean)

    let prompt: string
    if (buildingNames.length === 1) {
      // Entire selection is dominated by one building — scan the building directly.
      prompt = `scan the ${buildingNames[0]} at coordinates (${overlapping[0].cx.toFixed(1)}, 0, ${overlapping[0].cz.toFixed(1)}) for survivors`
    } else if (buildingNames.length > 1) {
      const buildingList = overlapping
        .map(b => {
          const name = buildingPromptName(b)
          return `${name} at (${b.cx.toFixed(1)}, 0, ${b.cz.toFixed(1)})`
        })
        .join('; ')
      prompt = `scan for survivors in each of the following buildings: ${buildingList}. Do not ask for coordinates — they are provided above. Scan each building in sequence.`
    } else {
      prompt = `scan area from (${selection.minX}, ${selection.minZ}) to (${selection.maxX}, ${selection.maxZ}) for survivors`
    }

    addLog(`📐 Area scan: (${selection.minX},${selection.minZ}) → (${selection.maxX},${selection.maxZ})`)
    clearAreaSelectionState()
    // Inject prompt into CommandPanel; use "auto" asset for multi-building so the
    // fleet assigner picks the closest available drones.
    setPendingScanAssetId(buildingNames.length > 1 ? 'auto' : null)
    setPendingScanPrompt(prompt)
  }, [selection, addLog, clearAreaSelectionState])

  const handleAreaSupplyDispatch = useCallback(() => {
    if (!selection) return

    const width = selection.maxX - selection.minX
    const depth = selection.maxZ - selection.minZ
    const centerX = (selection.minX + selection.maxX) / 2
    const centerZ = (selection.minZ + selection.maxZ) / 2
    const radius = Math.max(width, depth) / 2
    const prompt =
      `send emergency supplies in parallel to all buildings within ${radius.toFixed(1)}m ` +
      `of (${centerX.toFixed(1)}, ${centerZ.toFixed(1)}). ` +
      `Target area bounds: (${selection.minX}, ${selection.minZ}) to (${selection.maxX}, ${selection.maxZ}).`

    addLog(`📦 Area supply dispatch: (${selection.minX},${selection.minZ}) → (${selection.maxX},${selection.maxZ})`)
    clearAreaSelectionState()
    setPendingScanAssetId('auto')
    setPendingScanPrompt(prompt)
  }, [selection, addLog, clearAreaSelectionState])

  const handleThrowComplete = useCallback(() => {
    if (!activeThrow) return
    const key = survivorKey(activeThrow.to)
    setDeliveredTo(prev => new Set(prev).add(key))
    setSurvivorDeliveryTimestamps(prev => new Map(prev).set(key, Date.now()))
    setDeliveringTo(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
    deliveryTarget.current = null
    deliveryApproach.current = null
    deliveryThrowOrigin.current = null
    deliveryDroneId.current = null
    setActiveThrow(null)
    addLog('✓ Supply delivered to survivor')
  }, [activeThrow, addLog])

  const handleSelectionClose = useCallback(() => {
    clearAreaSelectionState()
  }, [clearAreaSelectionState])

  const scannedSurvivors = useMemo(
    () => scannedSurvivorsFromDrone(simBuildings, survivorPositions, dronePos),
    [dronePos.x, dronePos.y, dronePos.z, simBuildings, survivorPositions],
  )
  const fleetScannedSurvivors = useMemo(() => {
    const merged = new Map<string, SurvivorPoint>()
    for (const telemetryEntry of Object.values(drones)) {
      for (const survivor of detectedSurvivorsFromTelemetryEntry(simBuildings, survivorPositions, telemetryEntry)) {
        merged.set(survivorKey(survivor), survivor)
      }
    }
    return [...merged.values()]
  }, [drones, simBuildings, survivorPositions])

  const handleSendSupplies = useCallback((survivor: SurvivorPoint) => {
    const key = survivorKey(survivor)
    if (!detectedSurvivorKeysRef.current.has(key)) {
      addLog('⚠ Supplies can only be dispatched to detected survivors')
      return
    }
    const coords = `(${survivor.x.toFixed(1)}, ${survivor.y.toFixed(1)}, ${survivor.z.toFixed(1)})`
    const approach = computeApproachPosition(simBuildings, survivor)
    const approachCoords = `(${approach.x.toFixed(1)}, ${approach.y.toFixed(1)}, ${approach.z.toFixed(1)})`

    // Pick the drone closest to base (0,0,0) — it minimises total trip since
    // the drone must return to base first to collect supplies.
    const droneEntries = Object.values(drones)
    let chosenId = ASSET_ID  // fallback
    if (droneEntries.length > 0) {
      let bestDist = Infinity
      for (const d of droneEntries) {
        const dist = distance3D(d.x, d.y, d.z, 0, 0, 0)
        if (dist < bestDist) {
          bestDist = dist
          chosenId = d.asset_id
        }
      }
    }

    setDeliveringTo(prev => new Set(prev).add(key))
    pendingDeliveryKey.current = key
    deliveryDroneId.current = chosenId
    deliveryTarget.current = survivor
    deliveryApproach.current = approach
    const throwOrigin = computeSupplyThrowOrigin(
      simBuildings,
      worldBuildings,
      survivor,
      new THREE.Vector3(approach.x, approach.y, approach.z),
    )
    deliveryThrowOrigin.current = { x: throwOrigin.x, y: throwOrigin.y, z: throwOrigin.z }
    const throwOriginCoords = `(${throwOrigin.x.toFixed(1)}, ${throwOrigin.y.toFixed(1)}, ${throwOrigin.z.toFixed(1)})`
    setRouteArrived(false)
    addLog(`Dispatching ${chosenId} with supplies to survivor at ${coords}`)

    const balconyHost = findBalconyHostBuilding(worldBuildings, survivor)
    const balconyName = balconyHost?.name?.trim() || (balconyHost ? `building ${balconyHost.id}` : '')
    const isInside = findBuildingAt(simBuildings, survivor.x, survivor.y, survivor.z) !== null
    const prompt = balconyHost
      ? `Deliver emergency supplies to survivor at balcony coordinates ${coords}. ` +
        `First return to base at (0, 0, 0) to collect supplies, ` +
        `then navigate to drop waypoint ${throwOriginCoords} above the rooftop edge of ${balconyName} ` +
        `and drop supplies downward to the balcony target from that exact waypoint.`
      : isInside
      ? `Deliver emergency supplies to survivor at ${coords}. ` +
        `First return to base at (0, 0, 0) to collect supplies, ` +
        `then navigate to exact window drop waypoint ${approachCoords} outside the building and drop from there. ` +
        `Do NOT navigate to the survivor's interior coordinates.`
      : `Deliver emergency supplies to survivor at ${coords}. ` +
        `First return to base at (0, 2, 0) to collect supplies, ` +
        `then navigate to ${coords} to drop supplies.`

    setPendingScanPrompt(prompt)
    setPendingScanAssetId(chosenId)
  }, [addLog, drones, simBuildings, worldBuildings])

  const handleRetryDelivery = useCallback((survivor: SurvivorPoint) => {
    const key = survivorKey(survivor)
    setDeliveringTo(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
    setHasCargo(false)
    cargoPickedUp.current = false
    setRouteArrived(false)
    deliveryTarget.current = null
    deliveryApproach.current = null
    deliveryThrowOrigin.current = null
    deliveryDroneId.current = null
    pendingDeliveryKey.current = null
    setActiveThrow(null)
    addLog(`↻ Retrying delivery to survivor at (${survivor.x.toFixed(1)}, ${survivor.y.toFixed(1)}, ${survivor.z.toFixed(1)})`)
    setTimeout(() => handleSendSupplies(survivor), 0)
  }, [addLog, handleSendSupplies])

  // Persistent intel — accumulate survivors across all scans
  const [discoveredSurvivors, setDiscoveredSurvivors] = useState<SurvivorPoint[]>([])
  const intelSurvivors = useMemo(
    () => mergeUniqueSurvivors(discoveredSurvivors, fleetScannedSurvivors),
    [discoveredSurvivors, fleetScannedSurvivors],
  )
  const detectedSurvivorKeys = useMemo(
    () => new Set(intelSurvivors.map(survivorKey)),
    [intelSurvivors],
  )

  useEffect(() => {
    detectedSurvivorsRef.current = intelSurvivors
    detectedSurvivorKeysRef.current = detectedSurvivorKeys
    // Record detection timestamps for new survivors
    const now = Date.now()
    let changed = false
    for (const s of intelSurvivors) {
      const key = survivorKey(s)
      if (!survivorDetectionTsRef.current.has(key)) {
        survivorDetectionTsRef.current.set(key, now)
        changed = true
      }
    }
    if (changed) setSurvivorDetectionTimestamps(new Map(survivorDetectionTsRef.current))
  }, [intelSurvivors, detectedSurvivorKeys])
  const survivorStatsByBuilding = useMemo(() => {
    const stats: Record<number, { detected: number; supplied: number }> = {}
    for (const building of worldBuildings) {
      stats[building.id] = { detected: 0, supplied: 0 }
    }
    for (const survivor of survivorPositions) {
      const buildingId = survivorAssociatedBuildingId(simBuildings, worldBuildings, survivor)
      if (buildingId === null || stats[buildingId] === undefined) continue
      const key = survivorKey(survivor)
      if (detectedSurvivorKeys.has(key)) {
        stats[buildingId].detected += 1
      }
      if (deliveredTo.has(key)) {
        stats[buildingId].supplied += 1
      }
    }
    return stats
  }, [deliveredTo, detectedSurvivorKeys, simBuildings, survivorPositions, worldBuildings])

  useEffect(() => {
    if (fleetScannedSurvivors.length === 0) return
    setDiscoveredSurvivors(prev => mergeUniqueSurvivors(prev, fleetScannedSurvivors))
  }, [fleetScannedSurvivors])

  return (
    <div
      className={`relative h-full w-full bg-[#0a0a14] ${selectMode ? 'cursor-crosshair' : 'cursor-default'}`}
      onPointerDown={handleScenePointerDown}
    >
      <Canvas shadows key={activeWorld}>
        <fog attach="fog" args={['#0d0d1f', fogRange[0], fogRange[1]]} />
        <PerspectiveCamera makeDefault position={camPos} fov={60} near={0.1} far={1000} />
        <OrbitControls
          ref={orbitRef}
          enabled={!selectMode}
          onStart={handleOrbitStart}
          enableDamping
          dampingFactor={0.08}
          enablePan
          enableRotate
          mouseButtons={{
            LEFT: THREE.MOUSE.ROTATE,
            MIDDLE: THREE.MOUSE.DOLLY,
            RIGHT: THREE.MOUSE.PAN,
          }}
          touches={{
            ONE: THREE.TOUCH.ROTATE,
            TWO: followBeacon ? THREE.TOUCH.DOLLY_ROTATE : THREE.TOUCH.DOLLY_PAN,
          }}
          minDistance={5}
          maxDistance={400}
          target={[0, 5, 0]}
        />
        <FollowBeaconCamera
          enabled={followBeacon}
          targetPos={followTargetPos}
          followAssetId={followedAssetId}
          controlsRef={orbitRef}
        />
        <CameraTracker northAngleRef={northAngleRef} />

        {/* Lighting */}
        <ambientLight intensity={0.55} />
        <directionalLight position={[50, 100, 40]} intensity={1.2} castShadow />
        <hemisphereLight args={['#1a1a2e', '#0d0d0d', 0.4]} />

        {/* Scene */}
        <Ground span={worldSpan} />
        <GridOverlay span={worldSpan} gridCells={gridCells} />
        <BasePad />
        {activeWorld === 2 && fogEnabled && (
          <FogOfWar
            sectors={exploration.sectors}
            exploredSectors={exploration.exploredSectors}
            lastRevealedSector={exploration.lastRevealedSector}
          />
        )}
        {activeWorld === 2 && (
          <World2Environment
            span={worldSpan}
            floorHeight={FLOOR_H}
            floorThickness={FLOOR_T}
            floodLevel={FLOOD_LEVEL}
            transparentWalls={transparentWalls}
            exploredSectors={fogEnabled ? exploration.exploredSectors : undefined}
          />
        )}
        <MissionBuildings
          buildings={activeWorld === 2 && fogEnabled ? exploration.visibleBuildings : worldBuildings}
          transparentWalls={transparentWalls}
          floorHeight={FLOOR_H}
          floorThickness={FLOOR_T}
          survivorStatsByBuilding={survivorStatsByBuilding}
        />
        <Survivors
          floodY={FLOOD_LEVEL}
          survivors={activeWorld === 2 && fogEnabled ? exploration.visibleSurvivors : survivorPositions}
          deliveredTo={deliveredTo}
          detectedSurvivors={detectedSurvivorKeys}
        />
        {selectMode ? (
          <AreaSelectProbe
            worldSpan={worldSpan}
            gridSpacing={gridSpacing}
            onDragUpdate={(start, end) => {
              setDragStart(start)
              setDragEnd(end)
              clearAreaSelectionPreview()
            }}
            onDragEnd={sel => {
              setSelection(sel)
              setShowContextMenu(true)
            }}
          />
        ) : (
          <>
            <GroundProbe worldSpan={worldSpan} onMove={setHoverPt} onDoubleClick={handleGroundClick} />
            <GroundCursor point={hoverPt} />
          </>
        )}
        {dragStart && dragEnd && (
          <AreaHighlight start={dragStart} end={dragEnd} finalised={showContextMenu} gridSpacing={gridSpacing} />
        )}
        {Object.values(drones).map(t => (
          <DroneMesh
            key={t.asset_id}
            targetPos={new THREE.Vector3(t.x, t.y, t.z)}
            status={t.status}
            hasCargo={(hasCargo && deliveryDroneId.current === t.asset_id) || cargoByDrone.has(t.asset_id)}
            nearbyObstacles={t.nearby_obstacles}
            nearestObstacleDist={t.nearest_obstacle_dist}
            survivorsInRange={t.survivors_in_range}
            assetId={t.asset_id}
            headingDeg={t.heading_deg}
            scanTiltDeg={t.scan_tilt_deg}
            battery={t.battery}
          />
        ))}
        {activeThrow && (
          <SupplyThrow
            from={activeThrow.from}
            to={activeThrow.to}
            onComplete={handleThrowComplete}
          />
        )}
        <SupplyCrates deliveredTo={deliveredTo} survivors={survivorPositions} />
      </Canvas>

      {/* Top Status Bar */}
      <TopStatusBar
        selectMode={selectMode}
        floodLevel={FLOOD_LEVEL}
        survivors={survivorPositions}
        activeWorld={activeWorld}
        onWorldChange={handleWorldChange}
        networkMockStatus={networkMockStatus}
      />

      {/* Left panel — Mission Log + Metrics */}
      <div className="pointer-events-auto absolute left-4 top-[60px] flex max-h-[calc(100%-180px)] flex-col gap-2">
        <ActivityFeed items={activities} busy={agentBusy} onClear={() => setActivities([])} />
        <MetricsPanel
          missionStartTs={missionStartTs}
          activities={activities}
          detectedCount={intelSurvivors.length}
          rescuedCount={deliveredTo.size}
          totalSurvivors={survivorPositions.length}
          drones={drones}
          lastTtftMs={lastTtftMs}
          survivorDetectionTimestamps={survivorDetectionTimestamps}
          survivorDeliveryTimestamps={survivorDeliveryTimestamps}
        />
      </div>
      {!selectMode && <CoordOverlay point={hoverPt} copied={copied} />}
      <CompassLabels northAngleRef={northAngleRef} />
      <div className="pointer-events-auto absolute right-4 top-[60px] flex max-h-[calc(100%-180px)] flex-col gap-2">
        <Controls
          followBeacon={followBeacon}
          onToggleFollow={toggleFollowBeacon}
          transparentWalls={transparentWalls}
          onToggleWalls={toggleWallTransparency}
          fogEnabled={fogEnabled}
          onToggleFog={toggleFog}
          showFogToggle={activeWorld === 2}
          followedAssetId={followedAssetId}
          activeAssetIds={activeDroneAssetIds}
          onFollowPrevious={followPreviousBeacon}
          onFollowNext={followNextBeacon}
          selectMode={selectMode}
        />
        <DroneStatusPanel drones={drones} />
        <IntelCard
          survivors={intelSurvivors}
          dronePos={dronePos}
          totalSurvivors={survivorPositions.length}
          deliveringTo={deliveringTo}
          deliveredTo={deliveredTo}
          onSendSupplies={handleSendSupplies}
          onRetryDelivery={handleRetryDelivery}
        />
      </div>
      {showContextMenu && selection && (
        <AreaContextMenu
          selection={selection}
          onScan={handleAreaScan}
          onSendSupply={handleAreaSupplyDispatch}
          onClose={handleSelectionClose}
        />
      )}
      {autoRecallPrompt && (
        <div className="pointer-events-auto absolute inset-0 z-40 flex items-center justify-center bg-[rgba(2,4,10,0.55)]">
          <div className="w-[420px] rounded-lg border border-l-[3px] border-[rgba(255,90,90,0.5)] border-l-[#ff4d4d] bg-[linear-gradient(135deg,rgba(20,7,7,0.96),rgba(12,3,3,0.95))] p-[14px_16px] font-mono text-[#ffd2d2] shadow-[0_12px_48px_rgba(0,0,0,0.55)]">
            <div className="mb-2 font-bold tracking-[1.2px] text-[#ff8a8a]">
              LOW BATTERY AUTO RECALL
            </div>
            <div className="text-[13px] leading-[1.5] text-[#ffb1b1]">
              {autoRecallPrompt.assetId} is IDLE at {autoRecallPrompt.battery.toFixed(1)}% battery.
            </div>
            <div className="mt-1.5 text-xs text-[#ff8a8a]">
              Auto recall in {autoRecallCountdown}s unless cancelled.
            </div>
            <div className="mt-3 flex justify-end">
              <button
                onClick={cancelAutoRecall}
                className="cursor-pointer rounded border border-[rgba(255,110,110,0.45)] bg-[rgba(255,70,70,0.12)] px-3 py-1 font-inherit text-xs tracking-[0.6px] text-[#ffd2d2]"
              >
                CANCEL
              </button>
            </div>
          </div>
        </div>
      )}
      <CommandPanel
        assetId={ASSET_ID}
        connected={connected}
        uplinked={uplinked}
        battery={battery}
        onCommand={handleCommand}
        onStop={handleStop}
        externalPrompt={pendingScanPrompt}
        externalAssetId={pendingScanAssetId}
        onExternalPromptConsumed={() => {
          setPendingScanPrompt(null)
          setPendingScanAssetId(null)
        }}
        scoutAvailable={activeWorld === 2}
      />
    </div>
  )
}