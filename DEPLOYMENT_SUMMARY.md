# Deployment Summary

## Docker Setup Created

### Files Added
- `backend/Dockerfile` - Multi-stage build for FastAPI service
- `frontend/Dockerfile` - Next.js SSG build + static server
- `docker-compose.prod.yml` - Orchestration for both services

### Quick Deployment

```bash
# Build all images
docker-compose -f docker-compose.prod.yml build

# Start services
docker-compose -f docker-compose.prod.yml up -d

# View logs
docker-compose -f docker-compose.prod.yml logs -f

# Stop services
docker-compose -f docker-compose.prod.yml down
```

### Service Endpoints
- **Backend API**: http://localhost:8000
- **Frontend UI**: http://localhost:3000
- **Health check**: http://localhost:8000/health

---

## watch_starlink_wifi.sh Packaging for Consumer

### Problem
Cannot containerize watch_starlink because it:
- Detects host WiFi via `nmcli` (NetworkManager)
- Runs `docker exec` to modify drone containers
- Requires host file system access for `.starlink-mock-status`

### Solution: Tauri Sidecar (Desktop App)

Include watch_starlink in Tauri as a managed sidecar process:

1. **Bundle Script**: Copy `scripts/watch_starlink_wifi.sh` and `scripts/toggle_starlink_tc.sh` into Tauri app resources
2. **Rust Wrapper**: Create Tauri command to spawn and manage watcher process
3. **Frontend UI**: Add toggle in network panel to start/stop watcher
4. **Permissions**: Request user approval for Docker + nmcli access on first run

```rust
// Example Tauri command
#[tauri::command]
async fn start_network_watcher(target_ssid: String) -> Result<(), String> {
    // Extract script from app resources
    // Spawn as sidecar process (Tauri managed)
    // Stream output to frontend
    Ok(())
}
```

### Benefits
✅ User launches desktop app once, everything runs  
✅ Script isolated/sandboxed by Tauri  
✅ Automatic updates with app  
✅ Works offline (no cloud dependency)  
✅ Cross-platform (Windows/macOS/Linux binaries)

### See Full Guide
→ Read `DEPLOYMENT.md` for detailed Tauri integration roadmap

---

## Environment Variables (Production)

### Backend
```bash
OLLAMA_HOST=host.docker.internal:11434  # Local Ollama for LLM
PYTHONUNBUFFERED=1                      # Real-time logs
```

### Frontend
```bash
NEXT_PUBLIC_API_URL=http://backend:8000  # Backend endpoint (Docker network)
```

---

## Next Steps

1. **Test Docker builds**:
   ```bash
   docker-compose -f docker-compose.prod.yml build
   ```

2. **Test local deployment**:
   ```bash
   docker-compose -f docker-compose.prod.yml up
   # Visit http://localhost:3000
   ```

3. **When ready for consumer packaging**:
   - Initialize Tauri in frontend
   - Create network sidecar module
   - Bundle watch_starlink scripts
   - Build signed installers for distribution

---

## Troubleshooting

### Backend health check fails
```bash
# Check backend logs
docker-compose -f docker-compose.prod.yml logs backend

# Verify Ollama is running
ollama serve  # On your host machine
```

### Frontend can't reach backend
```bash
# Ensure backend is healthy
curl http://localhost:8000/health

# Check frontend network in compose
docker network ls
docker network inspect beacon
```

### watch_starlink permissions denied
Will be handled by Tauri permission dialogs when integrated. For now, ensure user can:
- Access Docker socket: `ls -la /var/run/docker.sock`
- Run nmcli: `nmcli --version`
