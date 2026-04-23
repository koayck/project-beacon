use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, OnceLock};

#[derive(Debug, Clone, Serialize)]
pub struct SidecarStatus {
    pub backend_running: bool,
    pub note: String,
}

static BACKEND_CHILD: OnceLock<Mutex<Option<Child>>> = OnceLock::new();

fn backend_child_lock() -> &'static Mutex<Option<Child>> {
    BACKEND_CHILD.get_or_init(|| Mutex::new(None))
}

fn backend_repo_root() -> Result<PathBuf, String> {
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let root = manifest_dir
        .parent()
        .and_then(Path::parent)
        .ok_or_else(|| "Unable to resolve repository root from src-tauri path".to_string())?;
    Ok(root.to_path_buf())
}

fn child_is_running(child: &mut Child) -> bool {
    match child.try_wait() {
        Ok(None) => true,
        Ok(Some(_)) => false,
        Err(_) => false,
    }
}

fn spawn_with_uv(repo_root: &Path) -> Result<Child, String> {
    let mut candidates = vec!["uv".to_string()];
    if let Ok(home) = std::env::var("HOME") {
        candidates.push(format!("{home}/.local/bin/uv"));
        candidates.push(format!("{home}/.cargo/bin/uv"));
    }

    let mut errors: Vec<String> = Vec::new();
    for candidate in candidates {
        match Command::new(&candidate)
            .args(["run", "python", "-m", "backend.app"])
            .current_dir(repo_root)
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn()
        {
            Ok(child) => return Ok(child),
            Err(err) => errors.push(format!("{candidate}: {err}")),
        }
    }

    Err(format!(
        "Failed to spawn backend via uv candidates: {}",
        errors.join("; ")
    ))
}

fn spawn_with_python(repo_root: &Path) -> Result<Child, String> {
    Command::new("python3")
        .args(["-m", "backend.app"])
        .current_dir(repo_root)
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|err| format!("Failed to spawn backend via python3: {err}"))
}

fn spawn_backend(repo_root: &Path) -> Result<Child, String> {
    match spawn_with_uv(repo_root) {
        Ok(child) => Ok(child),
        Err(uv_err) => match spawn_with_python(repo_root) {
            Ok(child) => Ok(child),
            Err(py_err) => Err(format!("{uv_err}; {py_err}")),
        },
    }
}

pub fn ensure_backend_sidecar_started() -> Result<(), String> {
    start_backend_sidecar().map(|_| ())
}

#[tauri::command]
pub fn backend_sidecar_status() -> Result<SidecarStatus, String> {
    let lock = backend_child_lock();
    let mut guard = lock
        .lock()
        .map_err(|_| "Failed to lock backend sidecar state".to_string())?;

    let running = guard
        .as_mut()
        .is_some_and(child_is_running);
    if !running {
        *guard = None;
    }

    Ok(SidecarStatus {
        backend_running: running,
        note: if running {
            "Backend sidecar is running".to_string()
        } else {
            "Backend sidecar is not running".to_string()
        },
    })
}

#[tauri::command]
pub fn start_backend_sidecar() -> Result<String, String> {
    let repo_root = backend_repo_root()?;
    let lock = backend_child_lock();
    let mut guard = lock
        .lock()
        .map_err(|_| "Failed to lock backend sidecar state".to_string())?;

    if let Some(child) = guard.as_mut() {
        if child_is_running(child) {
            return Ok("Backend sidecar already running".to_string());
        }
    }

    *guard = None;
    let child = spawn_backend(&repo_root)?;
    *guard = Some(child);

    Ok(format!(
        "Backend sidecar started from {}",
        repo_root.display()
    ))
}

#[tauri::command]
pub fn stop_backend_sidecar() -> Result<String, String> {
    let lock = backend_child_lock();
    let mut guard = lock
        .lock()
        .map_err(|_| "Failed to lock backend sidecar state".to_string())?;

    let Some(child) = guard.as_mut() else {
        return Ok("Backend sidecar was not running".to_string());
    };

    child
        .kill()
        .map_err(|err| format!("Failed to stop backend sidecar: {err}"))?;
    let _ = child.wait();
    *guard = None;
    Ok("Backend sidecar stopped".to_string())
}
