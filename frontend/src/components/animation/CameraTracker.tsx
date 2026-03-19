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
  controlsRef,
}: {
  enabled: boolean
  targetPos: THREE.Vector3
  controlsRef: RefObject<OrbitControlsImpl | null>
}) {
  const { camera } = useThree()
  const desiredTarget = useRef(new THREE.Vector3())
  const desiredPosition = useRef(new THREE.Vector3())

  useFrame((_, delta) => {
    if (!enabled) return

    desiredTarget.current.set(targetPos.x, targetPos.y + 1.2, targetPos.z)
    desiredPosition.current.set(
      desiredTarget.current.x + FOLLOW_CAMERA_OFFSET.x,
      desiredTarget.current.y + FOLLOW_CAMERA_OFFSET.y,
      desiredTarget.current.z + FOLLOW_CAMERA_OFFSET.z,
    )

    const alpha = Math.min(delta * 3, 1)
    camera.position.lerp(desiredPosition.current, alpha)
    camera.lookAt(desiredTarget.current)

    const controls = controlsRef.current
    if (controls) {
      controls.target.lerp(desiredTarget.current, alpha)
      controls.update()
    }
  })

  return null
}
