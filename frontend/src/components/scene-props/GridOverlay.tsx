const C_GRID_MAJ = '#363a40'
const C_GRID_MIN = '#26282e'

export function GridOverlay({ span, gridCells }: { span: number; gridCells: number }) {
  return (
    <gridHelper
      args={[span, gridCells, C_GRID_MAJ, C_GRID_MIN]}
      position={[0, 0.01, 0]}
    />
  )
}
