use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct NetworkStatus {
    pub watcher_enabled: bool,
    pub backend_attached: bool,
    pub note: &'static str,
}

#[tauri::command]
pub fn network_status() -> NetworkStatus {
    NetworkStatus {
        watcher_enabled: false,
        backend_attached: false,
        note: "Tauri shell scaffold installed; network watcher wiring is next.",
    }
}

#[tauri::command]
pub fn start_network_watcher() -> Result<String, String> {
    Ok("Network watcher command stubbed for the initial Tauri scaffold.".to_string())
}

#[tauri::command]
pub fn stop_network_watcher() -> Result<String, String> {
    Ok("Network watcher stop command stubbed for the initial Tauri scaffold.".to_string())
}
