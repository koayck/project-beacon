const C_TRUNK = '#5F4126'
const C_LEAF = '#267632'

type TreePos = readonly [number, number]

const TREE_XZ: readonly TreePos[] = [
  [-4, 5], [-5, 8], [-8, 5], [-7, 9], [-9, 8], [-5, 6],
  [9, -9], [12, -13], [13, -10], [10, -13],
  [-14, -4], [-17, -8], [-15, -8],
  [4, 3], [4, -3], [-4, 3], [-4, -3],
  [10, 3], [10, -3], [-10, 3], [-10, -3], [16, 3], [16, -3],
  [-28, -5], [-28, 5], [-28, 12], [-28, -12],
  [28, -5], [28, 5], [28, 12], [28, -12],
  [-5, -28], [-12, -28], [5, -28], [12, -28],
  [-5, 28], [-12, 28], [5, 28], [12, 28],
  [-24, -36], [-34, -36], [-24, -42], [-34, -42], [-20, -44],
  [-46, 20], [-46, 10], [-46, 0], [-46, -10], [-46, -20], [-46, -30],
  [-40, 0], [-40, 18], [-40, -18], [40, 0], [40, 18], [40, -18],
  [0, -44], [0, 44], [-44, 28], [44, -28],
] as const

interface TreesProps {
  treePositions?: readonly TreePos[]
  trunkColor?: string
  leafColor?: string
  trunkSize?: readonly [number, number, number]
  leafRadius?: number
  trunkY?: number
  leafY?: number
}

export function Trees({
  treePositions = TREE_XZ,
  trunkColor = C_TRUNK,
  leafColor = C_LEAF,
  trunkSize = [0.18, 1.6, 0.18],
  leafRadius = 0.5,
  trunkY = 0.8,
  leafY = 2.1,
}: TreesProps) {
  const trunkArgs: [number, number, number] = [trunkSize[0], trunkSize[1], trunkSize[2]]

  return (
    <>
      {treePositions.map(([tx, tz], i) => (
        <group key={i}>
          <mesh position={[tx, trunkY, tz]}>
            <boxGeometry args={trunkArgs} />
            <meshStandardMaterial color={trunkColor} />
          </mesh>
          <mesh position={[tx, leafY, tz]}>
            <sphereGeometry args={[leafRadius, 8, 6]} />
            <meshStandardMaterial color={leafColor} />
          </mesh>
        </group>
      ))}
    </>
  )
}
