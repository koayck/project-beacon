# Project Beacon - Deployment Guide

## Docker Setup (Backend + Frontend)

### Quick Start

```bash
# Build and run with Docker Compose
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d

# Services available at:
# - Backend API: http://localhost:8000
# - Frontend: http://localhost:3000
```

### Individual Builds

```bash
# Backend only
docker build -f backend/Dockerfile -t beacon-backend:latest .
docker run -p 8000:8000 -e OLLAMA_HOST=host.docker.internal:11434 beacon-backend:latest

# Frontend only
docker build -f frontend/Dockerfile -t beacon-frontend:latest ./frontend
docker run -p 3000:3000 beacon-frontend:latest
```

### Architecture

```
┌─────────────────────────────────────┐
│ Host Machine (Consumer/Operator)    │
│                                     │
│ ┌──────────────────────────────┐   │
│ │ Tauri Desktop App            │   │
│ │ ├─ Next.js SSG UI (3000)     │   │
│ │ ├─ FastAPI Sidecar (8000)    │   │
│ │ └─ watch_starlink (sidecar)  │   │
│ └──────────────────────────────┘   │
│         │                           │
│    ┌────┴─────────────────┐         │
│    │                      │         │
│    ▼                      ▼         │
│  nmcli                docker exec   │
│  (NetworkManager)      (tc commands)│
└─────────────────────────────────────┘
         │
    ┌────▼──────────────┐
    │ Docker Network    │
    │ ├─ beacon-01      │
    │ ├─ beacon-02      │
    │ └─ scout          │
    └───────────────────┘
```

---

## watch_starlink Packaging Strategy

### ⚠️ Why NOT Docker for watch_starlink

The `scripts/watch_starlink_wifi.sh` script **cannot run in a container** because:

1. **Host WiFi detection**: Uses `nmcli` to detect actual host WiFi SSIDs (not container-limited)
2. **Host file system**: Writes `.starlink-mock-status` to repo root (host-level)
3. **Docker exec**: Needs to run `docker exec` commands FROM the host to modify drone containers
4. **Privilege requirement**: Needs access to `docker` socket and NetworkManager

### Recommended: Tauri Sidecar + System Service

**For Consumer Distribution:**

```
Beacon Desktop App (Tauri)
├── Frontend (SSG) ─ built into app
├── Backend (FastAPI) ─ sidecar
└─ Network Manager (watch_starlink)
   ├─ Bundled in Tauri binary
   ├─ Runs as host service
   ├─ Detects WiFi via nmcli
   └─ Manages drone Docker containers
```

### Implementation Approach

#### 1. **Tauri Application Structure**

```
src-tauri/
├── src/
│   ├── main.rs           # Tauri entry point
│   ├── sidecar.rs        # FastAPI sidecar manager
│   └── network.rs        # watch_starlink wrapper
├── Cargo.toml
└── tauri.conf.json
```

#### 2. **Tauri Commands (Rust → Shell)**

Create Tauri commands that invoke watch_starlink safely:

```rust
// src-tauri/src/network.rs
#[tauri::command]
async fn start_network_watcher(target_ssid: String) -> Result<(), String> {
    // 1. Extract watch_starlink from app resources
    let script_path = app.path_resolver()
        .resolve_resource("scripts/watch_starlink_wifi.sh")
        .ok_or("Script not found")?;
    
    // 2. Invoke as sidecar process (managed by Tauri)
    let (rx, mut _child) = tauri::api::process::Command::new_sidecar("watch_starlink")
        .args(&[&target_ssid])
        .spawn()
        .map_err(|e| e.to_string())?;
    
    // 3. Monitor output via channel
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => println!("Watcher: {}", line),
                CommandEvent::Exit(_) => println!("Watcher stopped"),
                _ => {}
            }
        }
    });
    
    Ok(())
}
```

#### 3. **Frontend Integration (React)**

```typescript
// frontend/src/components/NetworkManager.tsx
import { invoke } from '@tauri-apps/api/tauri'

export function NetworkManager() {
  const startWatcher = async () => {
    try {
      await invoke('start_network_watcher', { targetSsid: 'Starlink' })
      console.log('Watcher started')
    } catch (err) {
      console.error('Failed to start watcher:', err)
    }
  }

  return <button onClick={startWatcher}>Start Network Watcher</button>
}
```

#### 4. **Package watch_starlink as Binary**

```bash
# In Tauri build process:
# 1. Copy scripts to Tauri resources
cp scripts/watch_starlink_wifi.sh src-tauri/tauri-plugin-network-watcher/resources/

# 2. Include toggle_starlink_tc.sh as dependency
cp scripts/toggle_starlink_tc.sh src-tauri/tauri-plugin-network-watcher/resources/

# 3. Mark executable
chmod +x src-tauri/tauri-plugin-network-watcher/resources/watch_starlink_wifi.sh
```

#### 5. **Permissions & Elevation**

On first run, request user approval for:
- Docker access (read `/var/run/docker.sock`)
- NetworkManager access (via PolicyKit for `nmcli`)

```rust
// Request elevated permissions via system dialog
#[tauri::command]
async fn request_network_permissions() -> Result<(), String> {
    // Use system auth dialog to request:
    // - Docker socket access
    // - tc (traffic control) capability
    Ok(())
}
```

---

## Deployment Checklist

### Docker (Cloud/Server)

- [ ] Backend Dockerfile builds without errors
- [ ] Frontend SSG generates correctly (`out/` folder)
- [ ] docker-compose.prod.yml orchestrates both services
- [ ] Health checks pass (backend health endpoint)
- [ ] Environment variables configured (OLLAMA_HOST, etc.)
- [ ] Volumes mounted for persistent data

### Tauri (Consumer Desktop)

- [ ] Frontend SSG builds and is bundled into Tauri
- [ ] FastAPI sidecar auto-launches with app
- [ ] watch_starlink script included in app resources
- [ ] Permissions dialog shows on first launch
- [ ] Network watcher can be toggled from UI
- [ ] App auto-starts on system boot (optional)

### Testing

```bash
# Docker test
docker-compose -f docker-compose.prod.yml up
curl http://localhost:8000/health
curl http://localhost:3000

# Local Tauri test
cd frontend
npm install
npm run tauri dev

# watch_starlink manual test
TARGET_SSID=Starlink bash scripts/watch_starlink_wifi.sh
```

---

## Next Steps for Full Consumer Packaging

1. **Initialize Tauri** in frontend:
   ```bash
   cd frontend
   npm install @tauri-apps/cli
   npx tauri init
   ```

2. **Create network sidecar module** to wrap watch_starlink

3. **Add Tauri command handlers** for:
   - Start/stop watcher
   - Get current WiFi status
   - Set target SSID
   - View watcher logs

4. **Build for distribution**:
   ```bash
   npm run tauri build  # Creates installer for Windows/macOS/Linux
   ```

5. **Sign & notarize** for each OS (macOS requires notarization)

---

## Security Notes

- watch_starlink requires elevated privileges (Docker, nmcli)
- Never include Docker credentials in the app
- Request minimum necessary permissions at runtime
- Log all network operations for audit
- Consider implementing permission scope limiting via PolicyKit
