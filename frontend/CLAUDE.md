# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Project Beacon Frontend** is a Tauri desktop app combining Next.js (SSG) and React Three Fiber for a 3D Ground Control Station (GCS). It communicates with a FastAPI backend sidecar via HTTP and WebSocket, receiving real-time drone telemetry and sending commands to a swarm of simulated drones.

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Desktop shell | Tauri | Native window, file access, sidecar management |
| Static export | Next.js 14 (SSG, `output: 'export'`) | Pre-built HTML/JS/CSS bundled into Tauri |
| 3D visualization | React Three Fiber + Three.js | Digital twin radar, drone model rendering, camera controls |
| Styling | Tailwind CSS | Utility-first CSS for UI panels |
| Type safety | TypeScript | Strict mode enabled |
| State management | React hooks | useTelemetry, useState, useRef patterns |
| Backend API | HTTP/REST + WebSocket | FastAPI sidecar on localhost |
| Tauri integration | @tauri-apps/api | Invoke backend commands, filesystem access |

## Build & Development Commands

```bash
# Install dependencies
npm install
# or
bun install

# Development server (Next.js)
npm run dev               # Starts on localhost:3000

# Tauri desktop app (development mode)
npm run tauri:dev         # Launches Tauri window with hot reload

# Production build
npm run build             # Generates SSG export in ./out/
npm run tauri:build       # Packages into distributable .exe/.dmg/.AppImage

# Type checking
npx tsc --noEmit          # Run TypeScript compiler without emitting
```

## Directory Structure

```
src/
├── app/
│   ├── layout.tsx        # Root layout (Tailwind + global styles)
│   └── page.tsx          # Entry point (dynamically imports Scene)
├── components/
│   ├── scene.tsx         # Main Canvas + Three.js orchestration
│   ├── scene-props/      # 3D geometry (buildings, ground, survivors)
│   ├── animation/        # Camera tracking, supply drop animations
│   └── panels/           # HUD overlays (CommandPanel, DronePanel, TopStatusBar, etc.)
├── hooks/
│   └── useExploration.ts # Exploration state and sector tracking
├── lib/
│   ├── api.ts            # HTTP client for FastAPI (sendCommand, scan, getFleet, etc.)
│   ├── backend.ts        # Configuration (BACKEND_HTTP_BASE, TELEMETRY_WS_URL)
│   ├── ws.ts             # WebSocket hook (useTelemetry) — receives drone telemetry & system events
│   ├── tauri.ts          # Tauri runtime detection and command invocation
│   └── fogOfWar.ts       # Exploration mechanics
├── types/
│   └── worldTypes.ts     # World geometry and asset definitions
└── generated/
    └── world2Environment.generated.ts # Compiled world data (auto-generated)

src-tauri/
├── src/                  # Rust source (Tauri boilerplate)
├── tauri.conf.json       # Tauri config (window size, sidecar, CSP)
└── Cargo.toml

scripts/
└── generate-world-env.mjs # Build script: transforms world JSON → TypeScript

.
├── next.config.mjs       # Next.js config (output: 'export', Tailwind, webpack alias for @shared)
├── tailwind.config.ts    # Tailwind setup
├── tsconfig.json         # TypeScript config (strict, path aliases: @/*, @shared/*)
└── package.json
```

## Key Integration Points

### 1. API Layer (`src/lib/api.ts`)

All backend communication goes through this module:

```typescript
// Command streaming (agent response + tool calls)
const stream = streamCommand(assetId, prompt, simulationId)
for await (const event of stream) {
  // Handle AgentStreamEvent: tool_call, tool_result, thinking, text, final, error, done
}

// One-shot responses
const response = await sendCommand(assetId, prompt)

// Fleet management
const { fleet, count, active_count } = await getFleet()
const { discovered } = await scan()

// Simulation state
const sim = await getSimulation(simulationId)
await syncSimulationState(simulationId, scannedBuildings)
```

Key interfaces: `AgentStreamEvent`, `CommandResponse`, `SimulationState`, `FleetDrone`, `TelemetryPayload`

### 2. WebSocket Telemetry (`src/lib/ws.ts`)

Real-time drone position, battery, status updates via `useTelemetry` hook:

```typescript
const { drones, exploredSectors, latestReveals } = useTelemetry(
  TELEMETRY_WS_URL,
  onSystemEvent
)
// drones is a DroneMap: Record<string, TelemetryPayload>
// Updates continuously as drone heartbeats arrive
```

Stale drones (no heartbeat for 3s) are marked `OFFLINE`.

### 3. Tauri Integration (`src/lib/tauri.ts`)

Detect runtime and invoke backend commands:

```typescript
if (isTauriRuntime()) {
  const status = await invokeTauriCommand<DesktopStatus>('get_status')
}
```

Used for file access, sidecar lifecycle, and desktop-specific features.

### 4. Scene Orchestration (`src/components/scene.tsx`)

The main Canvas component:
- Initializes React Three Fiber with `<Canvas>`
- Sets up `OrbitControls` for camera interaction
- Renders 3D world: ground, buildings, survivors, drone models
- Manages command streaming UI (CommandPanel)
- Handles drone telemetry updates from WebSocket
- Tracks camera follow modes (free orbit, follow beacon, FPV)

Large component (~800 lines) — consider splitting further if adding more features.

## Code Organization Patterns

### State Management

Use React hooks for local state; avoid global state unless sharing across many unrelated components:

```typescript
// Good: Component-local state
const [drones, setDrones] = useState<DroneMap>({})
const [selectedDrone, setSelectedDrone] = useState<string | null>(null)

// WebSocket subscription via hook
const { drones } = useTelemetry(url)
```

### Panels (UI Overlays)

All HUD panels are rendered overlays on top of the Canvas:
- `TopStatusBar` — mission timer, world selector, network mock status
- `CommandPanel` — natural language input + streaming agent response
- `DronePanel` — selected drone info, controls
- `FpvPanel` — first-person view from selected drone
- `CoordOverlay` — mouse cursor coordinates
- `InteractionOverlays` — area selection, context menus, ground probes

Panels use absolute positioning (`absolute` CSS) and Tailwind utilities.

### 3D Components

Geometry and animation components in `src/components/`:
- `SceneStructures` — Ground, GridOverlay, Buildings, Survivors
- `World2Environment` — Dynamically loaded world props
- `CameraTracker` — Follow modes (fixed, beacon, FPV)
- `ThrowAnimation` — Supply drop visual effect

Each is a Three.js mesh or group. Leverage Three.js documentation for transforms, geometry, and animations.

### Type Safety

All API responses, WebSocket messages, and component props are typed:

```typescript
// api.ts exports interfaces for every endpoint
export interface CommandResponse { ... }
export interface AgentStreamEvent { ... }

// ws.ts exports telemetry types
export interface TelemetryPayload { ... }
```

Keep types in the files they're used; move to `types/` only if reused in 3+ places.

## Next.js + Tauri Special Considerations

### SSG Build

Next.js builds to static HTML/JS in `./out/`, which Tauri bundles. This means:
- **No API routes** in Next.js — all API calls go to the FastAPI sidecar
- **No server-side rendering** — `output: 'export'` in `next.config.mjs`
- **Dynamic imports required for Three.js** — Use `dynamic(() => import(...), { ssr: false })`

```typescript
// CORRECT: Dynamic import with ssr:false for browser-only code
const Scene = dynamic(() => import('@/components/scene'), { ssr: false })

// WRONG: Direct import of React Three Fiber in SSG context
import Scene from '@/components/scene' // Will fail in build
```

### Tauri Build Flow

From `tauri.conf.json`:
1. `beforeDevCommand`: `npm run dev -- --hostname 0.0.0.0` (starts Next.js dev server)
2. `beforeBuildCommand`: `npm run build` (SSG build → `./out/`)
3. Tauri points to `./out` as `frontendDist`

### Backend Connection

Frontend connects to FastAPI backend via `localhost` (or configured IP):
- HTTP: `BACKEND_HTTP_BASE` from `src/lib/backend.ts`
- WebSocket: `TELEMETRY_WS_URL` from `src/lib/backend.ts`

When running in Tauri, the backend sidecar is expected to be running.

## Development Workflow

### Adding a New Feature (e.g., new drone control)

1. **Plan** the UI layout and API integration
2. **Create/update types** in `src/lib/api.ts` if needed
3. **Add API function** in `src/lib/api.ts` that calls the backend endpoint
4. **Create panel component** (or update existing) in `src/components/panels/`
5. **Integrate into scene** — pass handlers from `scene.tsx` to the panel
6. **Test in dev**: `npm run tauri:dev` and verify via browser DevTools + Tauri window
7. **Type check**: `npx tsc --noEmit` before committing

### Debugging

- **Browser DevTools**: In Tauri dev mode, right-click → "Inspect" or Ctrl+Shift+I
- **Network tab**: Verify HTTP requests to backend; check WebSocket connection
- **Three.js DevTools**: Browser extension for inspecting scene graph
- **Console errors**: Check for ssr issues, missing dynamic imports, or runtime errors
- **Hot reload**: Next.js dev mode auto-reloads; Tauri watches `out/` directory

### Common Pitfalls

- **Forgetting `ssr: false`** on Three.js imports → SSG fails
- **Using `console.log` in production code** → Use proper logging instead (configured via hooks)
- **Hardcoding backend URL** → Use `BACKEND_HTTP_BASE` config
- **Mutating state directly** → Always use `setState` or spread operator for immutability
- **WebSocket connection logic in main component** → Use `useTelemetry` hook and manage cleanup

## Performance

- Large scenes with many drones: use Three.js instancing or LOD (level of detail) to reduce draw calls
- Avoid re-renders of the Canvas via memoization and `useCallback`
- WebSocket updates are frequent — batch state updates when possible
- Tailwind CSS is built at compile time; no runtime overhead

## Testing

Currently no E2E tests configured. When adding critical flows (e.g., mission execution), use:
- **Playwright** (recommended via `e2e-runner` agent)
- Or **Cypress** for DOM testing
- Unit tests for utility functions (fogOfWar logic, state reducers)

## Related Documentation

- **Project Beacon** root `CLAUDE.md` — Architecture, ADK agents, backend structure
- **Tauri docs**: https://tauri.app/
- **React Three Fiber**: https://docs.pmnd.rs/react-three-fiber/
- **Three.js**: https://threejs.org/docs/
- **Next.js**: https://nextjs.org/docs

## Hard Constraints

- **SSG only** — No API routes in Next.js
- **Offline-first** — All features work without internet
- **Type-safe** — Strict TypeScript, no `any`
- **Zero mutation** — Return new objects, never modify existing ones
- **No hardcoded secrets** — Use environment variables (none expected in frontend currently)
