interface CanalProps {
  span: number
  width?: number
  position?: readonly [number, number, number]
  color?: string
  opacity?: number
  horizontal?: boolean
}

export function Canal({
  span,
  width = 6,
  position = [-47, 0.06, 0],
  color = '#1a4a7a',
  opacity = 0.9,
  horizontal = false,
}: CanalProps) {
  const args: [number, number] = horizontal ? [span, width] : [width, span]
  return (
    <mesh position={position} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={args} />
      <meshStandardMaterial color={color} transparent opacity={opacity} depthWrite={false} />
    </mesh>
  )
}
