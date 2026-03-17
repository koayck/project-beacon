# World Model — `world.json`

Single source of truth for all scene geometry shared between the Python backend
(`backend/world/model.py`) and the TypeScript frontend (`SARScene.tsx`).

Edit **only this file** to change building positions, window layouts, survivor
placements, or scene constants. Both sides read from it at load time.

---

## Top-level structure

```
world.json
├── scene       — global simulation constants
├── buildings   — array of 5 functional buildings (id 0–4)
├── survivors   — array of survivor positions
└── trees       — array of tree positions (XZ only)
```

---

## `scene` — Global constants

| Key | Type | Description |
|-----|------|-------------|
| `floor_height_m` | `number` | Height of one storey in metres (used for floor-slab Y positions and window sill calculations) |
| `floor_slab_thickness_m` | `number` | Thickness of each concrete floor slab in metres |
| `flood_level_m` | `number` | Y elevation of the rising floodwater. Survivors below this minus 0.2 m are considered submerged |
| `surv_hover_m` | `number` | Vertical offset added on top of a floor slab to position a survivor's feet above the slab |
| `window_scan_standoff_m` | `number` | Distance in metres that a drone hovers outside a window during a thermal window-scan waypoint |
| `building_proximity_margin_m` | `number` | XZ edge margin used by `building_near_xz()` to detect whether a drone is "near" a building |

---

## `buildings` — Building array

Each entry describes one **functional** building: a structure the drone
navigates around or scans. Decorative city buildings are defined only in the
frontend and have no backend equivalent.

### Building object

| Key | Type | Description |
|-----|------|-------------|
| `id` | `number` | Stable integer ID (0–4). Used as the building index in all agent tools (`find_buildings_in_area`, `resolve_scan_target`, etc.) |
| `name` | `string` | Human-readable label for documentation / debugging |
| `cx` | `number` | Centre X coordinate of the building footprint (Three.js / world X axis) |
| `cz` | `number` | Centre Z coordinate of the building footprint (Three.js / world Z axis, not Y) |
| `w` | `number` | Building width along the X axis in metres |
| `d` | `number` | Building depth along the Z axis in metres |
| `h` | `number` | Total building height in metres (Y axis). Must be a multiple of `floor_height_m` for correct floor-slab rendering |
| `windows` | `Window[]` | Array of window apertures on the facades (empty `[]` for solid/windowless buildings) |
| `balcony` | `Balcony \| null` | Exterior balcony descriptor, or `null` if none |

### Building IDs

| ID | Name | Description |
|----|------|-------------|
| 0 | `target` | Primary SAR target — 4-floor building at (−15, −20). The drone swarm is sent here to scan for survivors |
| 1 | `obstacle` | Solid windowless block at (−7, −10) that sits on the direct line from home base (0,0,0) to the target. Forces navigation detour |
| 2 | `balcony_building` | 3-floor residential building at (20, −20) with an exterior south-face balcony on floor 3 |
| 3 | `shophouse` | Twin shophouse block at (12, −27) — two adjoined 3-floor units sharing a party wall, with south-face windows on floors 2 and 3 |
| 4 | `nw_tower` | 7-floor tower at (−23, −28) whose SE corner overlaps the NW corner of the target building by ~1 m on each axis |

---

## `windows` — Window aperture array

Each entry describes one vertical rectangular opening cut into a building facade.

| Key | Type | Description |
|-----|------|-------------|
| `floor` | `number` | 1-based floor number. Floor 1 is at ground level (Y = 0). Used to compute `sill_y = (floor − 1) × floor_height_m + sill` |
| `face` | `"north" \| "south" \| "west" \| "east"` | Which facade the window is on. **North** = −Z direction; **South** = +Z; **West** = −X; **East** = +X |
| `offset` | `number` | Offset from building centre along the **face's parallel axis**. For north/south faces the offset is along X; for west/east faces it is along Z. Positive = right when facing outward |
| `width` | `number` | Window width in metres (along the face's parallel axis) |
| `height` | `number` | Window height in metres (vertical) |
| `sill` | `number` | Height in metres from the floor slab to the bottom of the window opening |

### Axis convention

```
           −Z (north)
               ↑
   −X (west) ←  → +X (east)
               ↓
           +Z (south)
```

- A **north-face** window at `offset: 2.0` is centred at `cx + 2.0` on the X axis, flush with `min_z` of the building.
- A **west-face** window at `offset: −1.5` is centred at `cz − 1.5` on the Z axis, flush with `min_x` of the building.

---

## `balcony` — Exterior balcony descriptor

`null` for buildings without a balcony.

| Key | Type | Description |
|-----|------|-------------|
| `floor` | `number` | 1-based floor the balcony slab sits at. The slab Y = `(floor − 1) × floor_height_m` |
| `face` | `"north" \| "south" \| "west" \| "east"` | Which facade the balcony protrudes from |
| `depth` | `number` | How far the balcony extends outward from the facade in metres |
| `width` | `number` | Width of the balcony slab in metres (along the facade) |

---

## `survivors` — Survivor positions

Each entry is an absolute 3-D world position.

| Key | Type | Description |
|-----|------|-------------|
| `x` | `number` | World X position |
| `y` | `number` | World Y position. Computed as `(floor − 1) × floor_height_m + floor_slab_thickness_m / 2 + surv_hover_m` |
| `z` | `number` | World Z position |
| `note` | `string` | Human-readable description (ignored at runtime) |

> **Y formula:** `survY(n) = (n − 1) × 3.0 + 0.10 + 0.55 = (n − 1) × 3.0 + 0.65`

---

## `trees` — Tree positions

Currently empty. Each entry would have `{ "x": number, "z": number }`.

---

## Coordinate system

The world uses Three.js / OpenGL conventions:

- **+X** → East  
- **+Y** → Up  
- **+Z** → South  
- Home base / drone launch pad: **(0, 0, 0)**  
- All building positions are specified as centre (cx, cz) in the XZ plane, with Y = 0 as ground level.

---

## Adding or modifying geometry

1. Edit `shared/world.json` only.
2. Restart the FastAPI backend (`uv run python -m backend.app`) — it reloads the JSON at startup.
3. Rebuild the frontend (`cd frontend && npm run build`) — the JSON is bundled at build time.

No other files need editing.
