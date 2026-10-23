#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod api;

use std::{sync::{Mutex, atomic::AtomicBool}, time::Duration};
use tauri::{
    menu::{Menu, MenuItem}, tray::TrayIconBuilder, Manager,
};
use tokio::sync::Mutex as AsyncMutex;
use backend::DesktopState;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            let project = backend::initial_project(&app.handle());
            app.manage(DesktopState {
                project: Mutex::new(project),
                owned_project: Mutex::new(None),
                lifecycle: AsyncMutex::new(()),
                client: reqwest::Client::builder().timeout(Duration::from_secs(240))
                    .build().expect("HTTP client"),
                starting: AtomicBool::new(false),
            });
            let show = MenuItem::with_id(app, "show", "Open rag-mtst", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            let icon = app.default_window_icon().ok_or("Missing app icon")?.clone();
            TrayIconBuilder::new().icon(icon).menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    },
                    "quit" => app.exit(0),
                    _ => (),
                })
                .build(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend::project_directory,
            backend::set_project_directory,
            backend::backend_status,
            backend::start_stack,
            backend::stop_stack,
            api::upload_file,
            api::job_status,
            api::search_passages,
            api::create_conversation,
            api::conversation_messages,
            api::ask_question,
            api::hide_window,
            api::notify_indexing,
        ])
        .run(tauri::generate_context!())
        .expect("Failed to run rag-mtst desktop");
}
