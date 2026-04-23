#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    beacon_desktop::run();
}

fn main() {
    run();
}
