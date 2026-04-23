mod network;
mod sidecar;

use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct DesktopStatus {
    pub runtime: &'static str,
    pub app_name: &'static str,
    pub backend_mode: &'static str,
}

pub fn desktop_status() -> DesktopStatus {
    DesktopStatus {
        runtime: "tauri",
        app_name: "Project Beacon",
        backend_mode: "external-fastapi",
    }
}

pub fn run() {
    tauri::Builder::default()
        .setup(|_app| {
            if let Err(err) = sidecar::ensure_backend_sidecar_started() {
                eprintln!("Failed to start backend sidecar: {err}");
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![network::network_status, network::start_network_watcher, network::stop_network_watcher, sidecar::start_backend_sidecar, sidecar::stop_backend_sidecar, sidecar::backend_sidecar_status])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
