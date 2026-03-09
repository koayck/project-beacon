# Project Beacon

### Autonomous Edge-Compute Ground Intelligence System

## Executive Summary

**Project Beacon** is a commercial-grade, offline-first Ground Control Station (GCS) designed for autonomous drone swarms in comms-denied environments (e.g., disaster zones, search and rescue). It utilizes a "Bring Your Own Compute" (BYOC) architecture, running highly compressed local LLMs to orchestrate physical or simulated drones via military-standard gRPC protocols—requiring zero cloud connectivity.

## 🗺️ The Architecture Map: How Data Flows

When the user clicks "Deploy Swarm" on the app, here is the exact lifecycle of that command:

1. **The UI (Next.js + Tauri + React Three Fiber):** The user views the Digital Twin radar in the native desktop app and issues a command.
2. **The Brain (Google ADK + Ollama):** The Next.js frontend sends the command to the local Python sidecar. Google's Agent Development Kit (ADK) receives it, uses LiteLLM to ask the local Qwen 3.5 (4B) model to reason about the prompt, and decides on the exact coordinates.
3. **The Bridge (FastMCP + FastAPI):** ADK outputs a tool call. FastMCP translates this AI intent into a strict, executable Python function.
4. **The Network (gRPC):** The FastMCP tool fires off a highly compressed gRPC Protocol Buffer message across the local network.
5. **The Simulation (Docker + Ursina):** A Docker container (acting as the simulated drone on the MANET network) receives the gRPC command. A headless Ursina Python script updates the drone's physical $X, Y, Z$ coordinates and battery drain.
6. **The Telemetry Loop:** The Docker container blasts its new coordinates back to the Tauri Next.js frontend via UDP/WebSockets, and the 3D model on the screen moves. All mission logs are saved locally to SQLite.

## 🔧 Tech Stack Deep-Dive & Refinements

Project Beacon operates entirely off the grid using the following optimized stack:

* **Frontend: Next.js + Tauri**
* *Configuration:* Configured as a Static Site Generator (SSG) via `output: 'export'` in `next.config.mjs`. This compiles the Next.js and React Three Fiber code into plain HTML/JS/CSS that Tauri bundles flawlessly. All API logic is routed to the FastAPI Python sidecar.


* **The Brain: Google ADK + Qwen 3.5**
* *Configuration:* Google ADK is built for multi-agent workflows and uses LiteLLM natively. It creates a "Commander Agent" that routes tasks to sub-agents (e.g., a "Navigation Agent" for flight paths and a "Thermal Agent" for camera feeds) entirely locally via Ollama.


* **The Protocol: FastAPI + FastMCP + gRPC**
* *Configuration:* Standard REST/HTTP is bypassed in favor of gRPC to mirror the low-latency, bandwidth-efficient protobufs used by real radio-frequency drone swarms. FastMCP acts as the glue, translating the LLM's JSON outputs into strict gRPC payloads.


* **The Environment: Docker vs. Localhost (Offline MANET)**
* *Configuration:* A strict boundary isolates the commander from the swarm:
* **The Commander Node:** Runs the Tauri App (Next.js UI + FastAPI/ADK Sidecar + SQLite + Ollama) directly on the host machine.
* **The Swarm (Docker):** A `docker-compose.yml` spins up lightweight containers representing physically separate drones with their own isolated IP addresses, proving true network-agnostic capabilities.





## User Experience: The Dual-UI Workflow

To demonstrate the system's hardware-agnostic capabilities, the UI is split into two distinct experiences:

### 1. The Developer Spawner (Simulation Control)

A discreet backend control panel used to set up the virtual hardware environment.

* **Function:** Acts as the "power button" for the digital drones.
* **Action:** The user selects an asset class (e.g., Scout Quadcopter) and clicks **"Initialize Virtual Asset."** FastAPI silently spins up an isolated Docker container running the headless Ursina engine, which immediately begins broadcasting a UDP heartbeat on the local network.

### 2. The Tactical Pairing UX (The Commander Dashboard)

The primary, production-ready interface used by the swarm operator.

* **Discovery:** The user clicks **"Scan Local Frequencies."** The UI dims, displaying an animated Magic UI radar sweep while the system listens for network heartbeats.
* **Handshake:** Unpaired assets populate in a list (e.g., `ASSET_ID: BEACON-01 | SIGNAL: 98%`).
* **Uplink & Digital Twin Materialization:** When the user clicks **"Establish Uplink,"** FastAPI locks the gRPC channel and registers the drone in the local SQLite database. Instantly, the Next.js frontend injects a 3D drone model into the React Three Fiber canvas, mapping its real-time coordinates over the digital terrain.
