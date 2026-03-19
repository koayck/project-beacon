# Project Beacon Frontend

This frontend is a Next.js 14 + React Three Fiber tactical UI for Project Beacon. It renders the 3D mission scene, streams live telemetry, sends natural-language commands to the backend agent pipeline, and provides mission controls (scan, supply dispatch, area selection, follow camera, and world switching).

## Tech stack

- Next.js 14 (App Router, static export)
- React 18 + TypeScript
- React Three Fiber + Drei + Three.js
- Tailwind CSS (with custom CSS animations in `src/app/globals.css`)

## Frontend architecture

### Entry point

- `src/app/page.tsx` dynamically imports `src/components/scene.tsx` with `ssr: false` because Three.js requires browser APIs.
- `src/app/layout.tsx` provides root HTML shell and metadata.

### Core scene orchestration

- `src/components/scene.tsx` is the mission runtime coordinator. It handles:
  - 3D scene composition (ground, grid, buildings, drones, survivors, scan rays, supply throws)
  - Telemetry subscription (`useTelemetry`)
  - Backend integration (`streamCommand`, uplink, fleet/status/config calls)
  - Command/event activity timeline
  - Area selection workflow (scan area / dispatch supplies)
  - Auto-recall UX for low battery drones
  - World switching (`WORLD 1` / `HAT YAI`)

### Panels and overlays

- `src/components/panels/CommandPanel.tsx`:
  - chat-like command surface
  - streamed agent events (tool calls/results, text/final, heartbeat, done)
  - quick actions (`SCAN TARGET`, `SURVEY`, `STATUS`, `RTB`)
  - direct controls (fleet speed toggle, reset to base)
- `ActivityPanel.tsx` + `IntelPanel.tsx` + `DronePanel.tsx`:
  - mission log, survivor intelligence, and per-drone status cards
- `TopStatusBar.tsx`, `Controls.tsx`, `CoordOverlay.tsx`, `InteractionOverlays.tsx`, `CompassLabels.tsx`:
  - top mission status strip, scene toggles, coordinate copy overlay, area select UX, and cardinal markers

### Scene props

- `src/components/scene-props/*` contains terrain/environment/building/drone render modules.
- `World2Environment.tsx` reads generated environment config (`src/generated/world2Environment.generated.ts`) and can optionally load runtime world environment JSON via URL.

### Data/constants layer

- `constants/missionConstants.ts`:
  - world constants and camera/flood/grid parameters
  - survivor detection and line-of-sight helpers
  - building and balcony targeting helpers
  - supply-drop approach/origin calculations

### API + telemetry client layer

- `src/lib/api.ts` provides typed HTTP/SSE-style backend calls to `http://localhost:8000`.
- `src/lib/ws.ts` provides resilient telemetry WebSocket state (`ws://localhost:8000/ws/telemetry`) with reconnect behavior.

## World data and generation

The frontend uses shared world JSON data from `../shared`.

- `next.config.mjs` and `tsconfig.json` expose `@shared/*` alias.
- Build step runs:
  - `node scripts/generate-world-env.mjs --world ../shared/world2.json --out src/generated/world2Environment.generated.ts --const WORLD2_ENV`
- The generated file is checked in and used by `World2Environment.tsx`.
- Do not hand-edit generated files.

## Scripts

From `frontend/package.json`:

- `npm run dev` - start local Next dev server
- `npm run build` - generate world env file, then `next build` (static export mode)
- `npm run start` - run Next production server (only if using non-export runtime)

## Local development

From repository root:

```bash
cd frontend
npm install
npm run dev
```

Expected backend endpoints (default):

- HTTP: `http://localhost:8000`
- WebSocket telemetry: `ws://localhost:8000/ws/telemetry`

Without backend/drone-sim running, UI still renders but command/telemetry paths show offline behavior.

## User interactions

- `F` - toggle follow-camera mode
- `Ctrl+S` - enter/exit area-select mode
- `Esc` - cancel area-select mode
- Double-click ground - copy coordinates to clipboard

## Build/output behavior

- `next.config.mjs` uses:
  - `output: 'export'`
  - `trailingSlash: true`
- Static export artifacts are emitted for desktop bundling workflows.

## Troubleshooting

- If telemetry is empty, verify backend + drone simulation services are running and reachable on port `8000`.
- If world 2 environment looks outdated, rerun `npm run build` to regenerate `world2Environment.generated.ts`.
- If commands do not stream, verify `/command/stream` is available and not blocked by CORS/network policy.
