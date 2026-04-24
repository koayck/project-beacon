use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, OnceLock};

#[derive(Debug, Clone, Serialize)]
pub struct NetworkStatus {
    pub watcher_running: bool,
    pub target_ssid: String,
    pub note: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct WatcherConfig {
    pub target_ssid: String,
    pub check_interval_seconds: u32,
}

impl Default for WatcherConfig {
    fn default() -> Self {
        Self {
            target_ssid: "Starlink".to_string(),
            check_interval_seconds: 3,
        }
    }
}

static WATCHER_CHILD: OnceLock<Mutex<Option<Child>>> = OnceLock::new();
static WATCHER_CONFIG: OnceLock<Mutex<WatcherConfig>> = OnceLock::new();

fn watcher_child_lock() -> &'static Mutex<Option<Child>> {
    WATCHER_CHILD.get_or_init(|| Mutex::new(None))
}

fn watcher_config_lock() -> &'static Mutex<WatcherConfig> {
    WATCHER_CONFIG.get_or_init(|| Mutex::new(WatcherConfig::default()))
}

fn child_is_running(child: &mut Child) -> bool {
    match child.try_wait() {
        Ok(None) => true,
        Ok(Some(_)) => false,
        Err(_) => false,
    }
}

fn resolve_script_path(script_name: &str) -> Result<PathBuf, String> {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));

    let dev_path = manifest_dir
        .parent()
        .and_then(Path::parent)
        .map(|root| root.join("scripts").join(script_name));

    if let Some(ref path) = dev_path {
        if path.exists() {
            return Ok(path.clone());
        }
    }

    #[cfg(target_os = "linux")]
    {
        if let Ok(exe) = std::env::current_exe() {
            let resource_path = exe
                .parent()
                .map(|p| p.join("scripts").join(script_name));

            if let Some(ref path) = resource_path {
                if path.exists() {
                    return Ok(path.clone());
                }
            }

            let lib_resource = exe
                .parent()
                .and_then(Path::parent)
                .map(|p| p.join("lib").join("project-beacon").join("scripts").join(script_name));

            if let Some(ref path) = lib_resource {
                if path.exists() {
                    return Ok(path.clone());
                }
            }
        }
    }

    #[cfg(target_os = "macos")]
    {
        if let Ok(exe) = std::env::current_exe() {
            let resource_path = exe
                .parent()
                .and_then(Path::parent)
                .map(|p| p.join("Resources").join("scripts").join(script_name));

            if let Some(ref path) = resource_path {
                if path.exists() {
                    return Ok(path.clone());
                }
            }
        }
    }

    Err(format!(
        "Could not find script '{}'. Checked: {:?}",
        script_name, dev_path
    ))
}

fn spawn_watcher(config: &WatcherConfig) -> Result<Child, String> {
    let watcher_script = resolve_script_path("watch_starlink_wifi.sh")?;

    let watcher_dir = watcher_script
        .parent()
        .ok_or_else(|| "Cannot determine script directory".to_string())?;

    Command::new("bash")
        .arg(&watcher_script)
        .env("TARGET_SSID", &config.target_ssid)
        .env("CHECK_INTERVAL_SECONDS", config.check_interval_seconds.to_string())
        .current_dir(watcher_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("Failed to spawn network watcher: {err}"))
}

#[tauri::command]
pub fn network_status() -> Result<NetworkStatus, String> {
    let lock = watcher_child_lock();
    let mut guard = lock
        .lock()
        .map_err(|_| "Failed to lock watcher state".to_string())?;

    let running = guard.as_mut().is_some_and(child_is_running);
    if !running {
        *guard = None;
    }

    let config = watcher_config_lock()
        .lock()
        .map_err(|_| "Failed to lock config")?;

    Ok(NetworkStatus {
        watcher_running: running,
        target_ssid: config.target_ssid.clone(),
        note: if running {
            format!("Watching for '{}' WiFi connection", config.target_ssid)
        } else {
            "Network watcher is not running".to_string()
        },
    })
}

#[tauri::command]
pub fn start_network_watcher(target_ssid: Option<String>) -> Result<String, String> {
    let lock = watcher_child_lock();
    let mut guard = lock
        .lock()
        .map_err(|_| "Failed to lock watcher state".to_string())?;

    if let Some(child) = guard.as_mut() {
        if child_is_running(child) {
            return Ok("Network watcher already running".to_string());
        }
    }

    *guard = None;

    let mut config = watcher_config_lock()
        .lock()
        .map_err(|_| "Failed to lock config")?;

    if let Some(ssid) = target_ssid {
        config.target_ssid = ssid;
    }

    let child = spawn_watcher(&config)?;
    drop(config);

    let config = watcher_config_lock()
        .lock()
        .map_err(|_| "Failed to lock config")?;

    *guard = Some(child);

    Ok(format!(
        "Network watcher started, monitoring for '{}'",
        config.target_ssid
    ))
}

#[tauri::command]
pub fn stop_network_watcher() -> Result<String, String> {
    let lock = watcher_child_lock();
    let mut guard = lock
        .lock()
        .map_err(|_| "Failed to lock watcher state".to_string())?;

    let Some(child) = guard.as_mut() else {
        return Ok("Network watcher was not running".to_string());
    };

    child
        .kill()
        .map_err(|err| format!("Failed to stop network watcher: {err}"))?;
    let _ = child.wait();
    *guard = None;

    Ok("Network watcher stopped".to_string())
}
