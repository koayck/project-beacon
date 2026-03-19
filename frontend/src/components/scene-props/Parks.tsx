const C_PARK = '#286C34'

type ParkRect = readonly [number, number, number, number]

const PARKS: readonly ParkRect[] = [
  [-7, 7, 9, 9],
  [11, -11, 7, 7],
  [-16, -6, 6, 6],
  [-30, 8, 12, 10],
  [28, 24, 14, 10],
  [-20, -34, 10, 8],
  [0, 36, 20, 8],
  [-44, 0, 8, 16],
] as const

interface ParksProps {
  parks?: readonly ParkRect[]
  color?: string
}

export function Parks({ parks = PARKS, color = C_PARK }: ParksProps) {
  return (
    <>
      {parks.map(([px, pz, pw, pd], i) => (
        <mesh key={i} position={[px, 0.02, pz]}>
          <boxGeometry args={[pw, 0.01, pd]} />
          <meshStandardMaterial color={color} />
        </mesh>
      ))}
    </>
  )
}
