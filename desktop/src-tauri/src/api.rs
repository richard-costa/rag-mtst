use std::path::PathBuf;
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, State};
use tauri_plugin_notification::NotificationExt;
use uuid::Uuid;

use crate::backend::{DesktopState, API_URL, project_root, token, read_json, request_json};

const MAX_UPLOAD_BYTES: u64 = 50 * 1024 * 1024;

fn uuid_path(id: &str) -> Result<String, String> {
    Ok(Uuid::parse_str(id).map_err(|_| "Invalid identifier".to_owned())?.to_string())
}

#[tauri::command]
pub async fn upload_file(
    state: State<'_, DesktopState>, path: String, extraction_method: String, reindex: bool,
) -> Result<Value, String> {
    let root = project_root(&state)?;
    let key = token(&root)?;
    if extraction_method != "parser" && extraction_method != "visual" {
        return Err("Invalid extraction mode".into());
    }
    let file = PathBuf::from(&path);
    let ext = file.extension().and_then(|s| s.to_str()).unwrap_or("").to_ascii_lowercase();
    if !["txt", "md", "markdown", "pdf", "docx", "pptx"].contains(&ext.as_str()) {
        return Err("Unsupported document type".into());
    }
    let metadata = tokio::fs::metadata(&file).await
        .map_err(|_| "Cannot access selected file".to_owned())?;
    if !metadata.is_file() || metadata.len() > MAX_UPLOAD_BYTES {
        return Err("Choose a regular file no larger than 50 MiB.".into());
    }
    let content = tokio::fs::read(&file).await
        .map_err(|_| "Cannot read selected file".to_owned())?;
    if content.len() as u64 > MAX_UPLOAD_BYTES {
        return Err("File exceeded the 50 MiB desktop upload limit.".into());
    }
    let filename = file.file_name().and_then(|s| s.to_str())
        .ok_or("Invalid filename")?.to_owned();
    let form = reqwest::multipart::Form::new().part(
        "file", reqwest::multipart::Part::bytes(content).file_name(filename),
    );
    let request = state.client.post(format!("{API_URL}/sources/file"))
        .query(&[("extraction_method", extraction_method), ("reindex", reindex.to_string())])
        .bearer_auth(key).multipart(form);
    read_json(request.send().await.map_err(|e| format!("Upload failed: {e}"))?).await
}

#[tauri::command]
pub async fn job_status(state: State<'_, DesktopState>, job_id: String) -> Result<Value, String> {
    let id = uuid_path(&job_id)?;
    request_json(&state, reqwest::Method::GET, &format!("/jobs/{id}"), None).await
}

#[tauri::command]
pub async fn search_passages(
    state: State<'_, DesktopState>, query: String, method: String,
) -> Result<Value, String> {
    if query.trim().is_empty() { return Err("Enter a query.".into()); }
    if !["window", "cosine", "lexical", "hybrid"].contains(&method.as_str()) {
        return Err("Invalid retrieval method.".into());
    }
    request_json(&state, reqwest::Method::POST, "/search",
        Some(json!({"query": query, "method": method}))).await
}

#[tauri::command]
pub async fn create_conversation(state: State<'_, DesktopState>) -> Result<Value, String> {
    request_json(&state, reqwest::Method::POST, "/conversations", None).await
}

#[tauri::command]
pub async fn conversation_messages(
    state: State<'_, DesktopState>, conversation_id: String,
) -> Result<Value, String> {
    let id = uuid_path(&conversation_id)?;
    request_json(&state, reqwest::Method::GET,
        &format!("/conversations/{id}/messages"), None).await
}

#[tauri::command]
pub async fn ask_question(
    state: State<'_, DesktopState>, query: String, conversation_id: Option<String>,
    generation_provider: Option<String>, generation_model: Option<String>,
) -> Result<Value, String> {
    if query.trim().is_empty() { return Err("Enter a question.".into()); }
    let endpoint = if let Some(id) = conversation_id {
        format!("/conversations/{}/messages", uuid_path(&id)?)
    } else {
        "/ask".to_owned()
    };
    let mut body = json!({"query": query});
    if let Some(provider) = generation_provider.filter(|v| !v.trim().is_empty()) {
        if !["openai", "deepseek", "ollama", "anthropic"].contains(&provider.as_str()) {
            return Err("Invalid generation provider.".into());
        }
        body["generation_provider"] = json!(provider);
    }
    if let Some(model) = generation_model.filter(|v| !v.trim().is_empty()) {
        body["generation_model"] = json!(model);
    }
    request_json(&state, reqwest::Method::POST, &endpoint, Some(body)).await
}

#[tauri::command]
pub fn hide_window(app: AppHandle) -> Result<(), String> {
    app.get_webview_window("main").ok_or("Window not found")?
        .hide().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn notify_indexing(app: AppHandle, success: bool, file_name: String) {
    let short_name: String = file_name.chars().take(80).collect();
    let _ = app.notification().builder()
        .title(if success { "Indexing completed" } else { "Indexing failed" })
        .body(format!("{short_name}: {}",
            if success { "ready to search" } else { "check the import queue" }))
        .show();
}
