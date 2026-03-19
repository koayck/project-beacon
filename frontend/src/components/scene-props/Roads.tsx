const C_ROAD = '#2c2c32'
const C_LINE = '#D7CDA5'

type RoadStrip = readonly [number, number, number, number]

interface RoadsProps {
  span: number
  roadStrips?: readonly RoadStrip[]
  lineStrips?: readonly RoadStrip[]
  roadColor?: string
  lineColor?: string
}

function defaultRoadStrips(span: number): readonly RoadStrip[] {
  return [
    [0, 0, span, 7],
    [0, 0, 7, span],
    [0, -28, span, 4],
    [0, 28, span, 4],
    [-28, 0, 4, span],
    [28, 0, 4, span],
    [0, -14, span, 3],
    [0, 14, span, 3],
    [-14, 0, 3, span],
    [14, 0, 3, span],
  ] as const
}

function defaultLineStrips(span: number): readonly RoadStrip[] {
  return [
    [0, 0, span, 0.14],
    [0, 0, 0.14, span],
  ] as const
}

export function Roads({
  span,
  roadStrips = defaultRoadStrips(span),
  lineStrips = defaultLineStrips(span),
  roadColor = C_ROAD,
  lineColor = C_LINE,
}: RoadsProps) {
  return (
    <>
      {roadStrips.map(([x, z, w, d], i) => (
        <mesh key={`road-${i}`} position={[x, 0.02, z]}>
          <boxGeometry args={[w, 0.01, d]} />
          <meshStandardMaterial color={roadColor} />
        </mesh>
      ))}
      {lineStrips.map(([x, z, w, d], i) => (
        <mesh key={`line-${i}`} position={[x, 0.03, z]}>
          <boxGeometry args={[w, 0.01, d]} />
          <meshStandardMaterial color={lineColor} />
        </mesh>
      ))}
    </>
  )
}
