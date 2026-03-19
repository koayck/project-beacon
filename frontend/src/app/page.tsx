import dynamic from 'next/dynamic'

// Dynamic import with ssr:false — Three.js requires browser APIs
const SARScene = dynamic(() => import('@/components/scene'), { ssr: false })

export default function Home() {
  return (
    <main style={{ width: '100vw', height: '100vh' }}>
      <SARScene />
    </main>
  )
}
