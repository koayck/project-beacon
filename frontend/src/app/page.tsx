import dynamic from 'next/dynamic'

const SARScene = dynamic(() => import('@/components/scene'), { ssr: false })
const AppShell = dynamic(() => import('@/components/AppShell').then(m => ({ default: m.AppShell })), { ssr: false })

export default function Home() {
  return (
    <AppShell>
      <main style={{ width: '100vw', height: '100vh' }}>
        <SARScene />
      </main>
    </AppShell>
  )
}
