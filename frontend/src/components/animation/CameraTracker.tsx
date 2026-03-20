import { useFrame, useThree } from "@react-three/fiber"
import { MutableRefObject, RefObject, useRef } from "react"
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'

const FOLLOW_CAMERA_OFFSET = new THREE.Vector3(18, 14, 18)

export function CameraTracker({ northAngleRef }: { northAngleRef: MutableRefObject<number> }) {
  const { camera } = useThree()
  const dirRef = useRef(new THREE.Vector3())

  useFrame(() => {
    dirRef.current.set(0, 0, -1).transformDirection(camera.matrixWorldInverse)
    northAngleRef.current = Math.atan2(dirRef.current.x, dirRef.current.y)
  })

  return null
}

export function FollowBeaconCamera({
  enabled,
  targetPos,
  followAssetId,
  controlsRef,
}: {
  enabled: boolean
  targetPos: THREE.Vector3
  followAssetId: string | null
  controlsRef: RefObject<OrbitControlsImpl | null>
}) {
  const { camera } = useThree()
  const anchorTarget = useRef(new THREE.Vector3())
  const desiredTarget = useRef(new THREE.Vector3())
  const desiredPosition = useRef(new THREE.Vector3())
  const panOffset = useRef(new THREE.Vector3())
  const cameraOffset = useRef(new THREE.Vector3())
  const initialized = useRef(false)
  const wasEnabled = useRef(false)
  const lastFollowAssetId = useRef<string | null>(null)

  useFrame((_, delta) => {
    if (!enabled) {
      wasEnabled.current = false
      initialized.current = false
      return
    }

    anchorTarget.current.set(targetPos.x, targetPos.y + 1.2, targetPos.z)

    const controls = controlsRef.current
    const justEnabled = !wasEnabled.current
    const retargeted = lastFollowAssetId.current !== followAssetId
    if (justEnabled || retargeted) {
      // Preserve legacy UX: entering follow snaps camera near the selected drone.
      panOffset.current.set(0, 0, 0)
      cameraOffset.current.copy(FOLLOW_CAMERA_OFFSET)
      desiredTarget.current.copy(anchorTarget.current)
      desiredPosition.current.copy(desiredTarget.current).add(cameraOffset.current)

      camera.position.copy(desiredPosition.current)
      if (controls) {
        controls.target.copy(desiredTarget.current)
        controls.update()
      } else {
        camera.lookAt(desiredTarget.current)
      }

      initialized.current = true
      wasEnabled.current = true
      lastFollowAssetId.current = followAssetId
      return
    }

    if (!initialized.current) {
      panOffset.current.set(0, 0, 0)
      cameraOffset.current.copy(FOLLOW_CAMERA_OFFSET)
      initialized.current = true
    } else if (controls) {
      // Capture user-driven pan/orbit/zoom changes while keeping a moving follow anchor.
      panOffset.current.copy(controls.target).sub(anchorTarget.current)
      cameraOffset.current.copy(camera.position).sub(controls.target)
    }

    desiredTarget.current.copy(anchorTarget.current).add(panOffset.current)
    desiredPosition.current.copy(desiredTarget.current).add(cameraOffset.current)

    const alpha = Math.min(delta * 3, 1)
    camera.position.lerp(desiredPosition.current, alpha)

    if (controls) {
      controls.target.lerp(desiredTarget.current, alpha)
      controls.update()
    } else {
      camera.lookAt(desiredTarget.current)
    }

    wasEnabled.current = true
    lastFollowAssetId.current = followAssetId
  })

  return null
}
