export interface MidRiseSpec {
  cx: number
  cz: number
  w: number
  d: number
  h: number
  bodyColor: string
  roofColor: string
}

interface MidRiseProps {
  specs: readonly MidRiseSpec[]
  floorHeight: number
  floorThickness: number
  transparentWalls: boolean
}

const C_SLAB = '#94A2AF'

export function MidRise({
  specs,
  floorHeight,
  floorThickness,
  transparentWalls,
}: MidRiseProps) {
  return (
    <>
      {specs.map(({ cx, cz, w, d, h, bodyColor, roofColor }, i) => {
        const stories = Math.round(h / floorHeight)
        const hw = w / 2
        const hd = d / 2
        return (
          <group key={`mr-${i}`}>
            {Array.from({ length: stories + 1 }, (_, n) => (
              <mesh key={`slab-${n}`} position={[cx, n * floorHeight, cz]}>
                <boxGeometry args={[w, floorThickness, d]} />
                <meshStandardMaterial color={C_SLAB} />
              </mesh>
            ))}
            {([
              { pos: [cx, h / 2, cz - hd] as [number, number, number], size: [w, h, 0.14] as [number, number, number] },
              { pos: [cx, h / 2, cz + hd] as [number, number, number], size: [w, h, 0.14] as [number, number, number] },
              { pos: [cx - hw, h / 2, cz] as [number, number, number], size: [0.14, h, d] as [number, number, number] },
              { pos: [cx + hw, h / 2, cz] as [number, number, number], size: [0.14, h, d] as [number, number, number] },
            ]).map(({ pos, size }, wi) => (
              <mesh key={`wall-${wi}`} position={pos}>
                <boxGeometry args={size} />
                <meshStandardMaterial
                  color={transparentWalls ? roofColor : bodyColor}
                  transparent={transparentWalls}
                  opacity={transparentWalls ? 0.22 : 1}
                  depthWrite={!transparentWalls}
                  side={transparentWalls ? 2 : 0}
                />
              </mesh>
            ))}
            <mesh position={[cx, h + 0.08, cz]}>
              <boxGeometry args={[w, 0.16, d]} />
              <meshStandardMaterial color={roofColor} />
            </mesh>
          </group>
        )
      })}
    </>
  )
}
