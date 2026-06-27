use std::{
    fs::{self, OpenOptions},
    io::Write,
    net::{TcpStream, ToSocketAddrs},
    path::PathBuf,
    sync::Mutex,
    time::{Duration, SystemTime},
};

use tauri::{Manager, WindowEvent};
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

struct BackendState(Mutex<Option<CommandChild>>);

fn log_path() -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    base.join("PaperRadar").join("logs").join("local-search-service.log")
}

fn write_service_log(message: impl AsRef<str>) {
    let path = log_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{:?} {}", SystemTime::now(), message.as_ref());
    }
}

fn service_is_reachable() -> bool {
    let Ok(mut addrs) = "127.0.0.1:8765".to_socket_addrs() else {
        return false;
    };
    let Some(addr) = addrs.next() else {
        return false;
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(350)).is_ok()
}

fn stop_backend(app: &tauri::AppHandle) {
    let state = app.state::<BackendState>();
    if let Ok(mut child) = state.0.lock() {
        if let Some(process) = child.take() {
            let _ = process.kill();
            write_service_log("stopped managed local search service");
        }
    };
}

fn start_backend(app: &tauri::AppHandle, force_restart: bool) -> Result<(), String> {
    if service_is_reachable() {
        write_service_log("local search service already reachable");
        return Ok(());
    }

    {
        let state = app.state::<BackendState>();
        let already_starting = state.0.lock().map(|child| child.is_some()).unwrap_or(false);
        if already_starting && !force_restart {
            write_service_log("managed local search service is already starting");
            return Ok(());
        }
    }

    if force_restart {
        stop_backend(app);
    }

    let command = app
        .shell()
        .sidecar("paperradar-backend")
        .map_err(|error| {
            let message = format!("resolve sidecar failed: {error}");
            write_service_log(&message);
            message
        })?
        .env("PAPERRADAR_PARENT_PID", std::process::id().to_string());

    let (mut rx, child) = command.spawn().map_err(|error| {
        let message = format!("start sidecar failed: {error}");
        write_service_log(&message);
        message
    })?;

    write_service_log("started managed local search service");

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => write_service_log(format!("stdout: {}", String::from_utf8_lossy(&line))),
                CommandEvent::Stderr(line) => write_service_log(format!("stderr: {}", String::from_utf8_lossy(&line))),
                CommandEvent::Terminated(payload) => write_service_log(format!("terminated: {:?}", payload)),
                other => write_service_log(format!("event: {:?}", other)),
            }
        }
    });

    let state = app.state::<BackendState>();
    if let Ok(mut backend) = state.0.lock() {
        *backend = Some(child);
    }

    Ok(())
}

#[tauri::command]
fn restart_local_service(app: tauri::AppHandle) -> Result<(), String> {
    start_backend(&app, true)
}

#[tauri::command]
fn ensure_local_service(app: tauri::AppHandle) -> Result<(), String> {
    start_backend(&app, false)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![restart_local_service, ensure_local_service])
        .setup(|app| {
            if let Err(error) = start_backend(&app.handle(), false) {
                write_service_log(format!("setup start failed: {error}"));
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed) {
                stop_backend(&window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building PaperRadar")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                stop_backend(app);
            }
        });
}