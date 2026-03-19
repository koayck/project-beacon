export function Ground({ span }: { span: number }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
      <planeGeometry args={[span, span]} />
      <meshStandardMaterial color="#1e1e22" />
    </mesh>
  )
}
