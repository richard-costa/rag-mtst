use std::{
    env, fs,
    path::{Path, PathBuf},
    sync::{Mutex, atomic::{AtomicBool, Ordering}},
    time::Duration,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager, State};
use tokio::{process::Command, sync::Mutex as AsyncMutex, time::sleep};

pub const API_URL: &str = "http://127.0.0.1:8000";

pub struct DesktopState {
    pub project: Mutex<Option<PathBuf>>,
    pub owned_project: Mutex<Option<PathBuf>>,
    pub lifecycle: AsyncMutex<()>,
    pub client: reqwest::Client,
    pub starting: AtomicBool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopStatus {
    project_directory: Option<String>,
    ready: bool,
    can_stop: bool,
    starting: bool,
}

#[derive(Deserialize, Serialize)]
struct Preferences {
    project_directory: PathBuf,
}

pub fn validate_project(path: &Path) -> Result<PathBuf, String> {
    let root = path.canonicalize()
        .map_err(|_| "The selected directory does not exist.".to_owned())?;
    if !root.join("compose.yaml").is_file() || !root.join("app/api/main.py").is_file() {
        return Err("Select a rag-mtst checkout containing compose.yaml and app/api/main.py.".into());
    }
    Ok(root)
}

fn find_checkout() -> Option<PathBuf> {
    if let Some(value) = env::var_os("RAG_DESKTOP_PROJECT_DIR") {
        return validate_project(Path::new(&value)).ok();
    }
    let mut candidates = Vec::new();
    if let Ok(cwd) = env::current_dir() { candidates.push(cwd); }
    if let Ok(exe) = env::current_exe() {
        if let Some(parent) = exe.parent() { candidates.push(parent.to_path_buf()); }
    }
    for start in candidates {
        for ancestor in start.ancestors() {
            if let Ok(root) = validate_project(ancestor) { return Some(root); }
        }
    }
    None
}

fn settings_file(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().app_config_dir().map_err(|e| e.to_string())?;
    Ok(dir.join("desktop.json"))
}

pub fn initial_project(app: &AppHandle) -> Option<PathBuf> {
    if let Ok(file) = settings_file(app) {
        if let Ok(content) = fs::read_to_string(file) {
            if let Ok(prefs) = serde_json::from_str::<Preferences>(&content) {
                if let Ok(root) = validate_project(&prefs.project_directory) {
                    return Some(root);
                }
            }
        }
    }
    find_checkout()
}

pub fn project_root(state: &DesktopState) -> Result<PathBuf, String> {
    state.project.lock().map_err(|e| e.to_string())?.clone()
        .ok_or_else(|| "Choose your rag-mtst checkout in Settings first.".into())
}

pub fn token(root: &Path) -> Result<String, String> {
    if let Ok(value) = env::var("RAG_API_KEY") {
        if !value.is_empty() { return Ok(value); }
    }
    let values = dotenvy::from_path_iter(root.join(".env"))
        .map_err(|_| "Create a .env file in your repository and configure RAG_API_KEY.".to_owned())?;
    for item in values {
        let (key, value) = item.map_err(|_| "Could not parse .env.".to_owned())?;
        if key == "RAG_API_KEY" && !value.is_empty() { return Ok(value); }
    }
    Err("Set RAG_API_KEY in the repository .env file.".into())
}

pub async fn read_json(response: reqwest::Response) -> Result<Value, String> {
    let status = response.status();
    let data: Value = response.json().await
        .map_err(|_| "The backend returned an invalid JSON response.".to_owned())?;
    if status.is_success() { return Ok(data); }
    let message = data.get("detail").and_then(Value::as_str).unwrap_or("Request failed");
    Err(format!("Backend HTTP {}: {}", status.as_u16(),
        message.chars().take(300).collect::<String>()))
}

pub async fn request_json(
    state: &DesktopState, method: reqwest::Method, endpoint: &str, body: Option<Value>,
) -> Result<Value, String> {
    let root = project_root(state)?;
    let key = token(&root)?;
    let mut request = state.client.request(method, format!("{API_URL}{endpoint}")).bearer_auth(key);
    if let Some(body) = body { request = request.json(&body); }
    read_json(request.send().await.map_err(|e| format!("Cannot reach backend: {e}"))?).await
}

async fn healthy(client: &reqwest::Client) -> bool {
    let Ok(response) = client.get(format!("{API_URL}/openapi.json"))
        .timeout(Duration::from_secs(2)).send().await else { return false; };
    if !response.status().is_success() { return false; }
    response.json::<Value>().await.ok()
        .and_then(|value| value.get("info")?.get("title")?.as_str().map(|s| s == "rag-mtst"))
        .unwrap_or(false)
}

async fn compose(root: &Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new("docker")
        .arg("compose").arg("--project-directory").arg(root)
        .arg("-f").arg(root.join("compose.yaml"))
        .args(args).current_dir(root).output().await
        .map_err(|e| format!("Cannot run docker compose: {e}. Check Docker installation and permissions."))?;
    if output.status.success() {
        return Ok(String::from_utf8_lossy(&output.stdout).to_string());
    }
    let error = String::from_utf8_lossy(&output.stderr);
    let last_lines = error.lines().rev().take(5).collect::<Vec<_>>()
        .into_iter().rev().collect::<Vec<_>>().join("\n");
    Err(format!("Docker Compose failed: {}", last_lines.chars().take(800).collect::<String>()))
}

#[tauri::command]
pub fn project_directory(state: State<'_, DesktopState>) -> Result<Option<String>, String> {
    Ok(state.project.lock().map_err(|e| e.to_string())?
        .as_ref().map(|p| p.to_string_lossy().into_owned()))
}

#[tauri::command]
pub fn set_project_directory(
    app: AppHandle, state: State<'_, DesktopState>, path: String,
) -> Result<String, String> {
    let root = validate_project(Path::new(&path))?;
    let file = settings_file(&app)?;
    fs::create_dir_all(file.parent().ok_or("Invalid config directory")?)
        .map_err(|e| e.to_string())?;
    let content = serde_json::to_vec_pretty(&Preferences { project_directory: root.clone() })
        .map_err(|e| e.to_string())?;
    fs::write(file, content).map_err(|e| e.to_string())?;
    *state.project.lock().map_err(|e| e.to_string())? = Some(root.clone());
    Ok(root.to_string_lossy().into_owned())
}

#[tauri::command]
pub async fn backend_status(state: State<'_, DesktopState>) -> Result<DesktopStatus, String> {
    let project = project_root(&state).ok();
    let owned = state.owned_project.lock().map_err(|e| e.to_string())?.clone();
    Ok(DesktopStatus {
        can_stop: project.is_some() && project == owned,
        project_directory: project.map(|p| p.to_string_lossy().into_owned()),
        ready: healthy(&state.client).await,
        starting: state.starting.load(Ordering::SeqCst),
    })
}

#[tauri::command]
pub async fn start_stack(state: State<'_, DesktopState>) -> Result<String, String> {
    let _lock = state.lifecycle.lock().await;
    let root = project_root(&state)?;
    state.starting.store(true, Ordering::SeqCst);
    let result = async {
        let previous = compose(&root, &["ps", "--services", "--status", "running"]).await?;
        let already_running = previous.lines().any(|s| matches!(s, "app" | "worker" | "db"));
        // Compose reuse is non-destructive; no prune, reset, or volume deletion.
        compose(&root, &["up", "-d"]).await?;
        if !already_running {
            *state.owned_project.lock().map_err(|e| e.to_string())? = Some(root.clone());
        }
        for _ in 0..60 {
            if healthy(&state.client).await { return Ok("Backend ready".to_owned()); }
            sleep(Duration::from_secs(1)).await;
        }
        Err("Containers started, but the API did not become ready at 127.0.0.1:8000. Inspect Docker Compose logs.".into())
    }.await;
    state.starting.store(false, Ordering::SeqCst);
    result
}

#[tauri::command]
pub async fn stop_stack(state: State<'_, DesktopState>) -> Result<String, String> {
    let _lock = state.lifecycle.lock().await;
    let root = project_root(&state)?;
    if state.owned_project.lock().map_err(|e| e.to_string())?.as_ref() != Some(&root) {
        return Err("This stack was not started by this desktop session. Stop it manually if needed.".into());
    }
    compose(&root, &["stop"]).await?;
    *state.owned_project.lock().map_err(|e| e.to_string())? = None;
    Ok("Services stopped. Docker volumes were preserved.".into())
}

#[cfg(test)]
mod tests {
    use super::validate_project;
    #[test]
    fn refuses_arbitrary_directory() {
        assert!(validate_project(std::path::Path::new("/")).is_err());
    }
}
