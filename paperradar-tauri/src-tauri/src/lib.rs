use std::sync::Mutex;

use tauri::{Manager, WindowEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

struct BackendState(Mutex<Option<CommandChild>>);

fn stop_backend(app: &tauri::AppHandle) {
    let state = app.state::<BackendState>();
    if let Ok(mut child) = state.0.lock() {
        if let Some(process) = child.take() {
            let _ = process.kill();
        }
    };
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState(Mutex::new(None)))
        .setup(|app| {
            match app.shell().sidecar("paperradar-backend") {
                Ok(command) => match command
                    .env("PAPERRADAR_PARENT_PID", std::process::id().to_string())
                    .spawn()
                {
                    Ok((_rx, child)) => {
                        let state = app.state::<BackendState>();
                        if let Ok(mut backend) = state.0.lock() {
                            *backend = Some(child);
                        };
                    }
                    Err(error) => eprintln!("failed to start PaperRadar backend sidecar: {error}"),
                },
                Err(error) => eprintln!("failed to resolve PaperRadar backend sidecar: {error}"),
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

