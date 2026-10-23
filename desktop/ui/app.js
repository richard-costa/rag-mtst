"use strict";
(() => {
  const el = (id) => document.getElementById(id);
  const invoke = window.__TAURI__?.core?.invoke;
  let ready = false;
  let busy = false;
  let conversation = null;
  let conversationKey = null;
  let restoring = false;

  function notice(message, error = false) {
    const box = el("notice");
    box.hidden = !message;
    box.classList.toggle("error", error);
    box.textContent = message || "";
  }
  function chooseView(view) {
    document.querySelectorAll(".view").forEach((node) => { node.hidden = node.id !== "view-" + view; });
    document.querySelectorAll(".nav").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
    el("page-title").textContent = {chat: "Ask & Search", import: "Import documents", settings: "Settings"}[view];
    el("new-chat").hidden = view !== "chat";
  }
  function node(tag, text, className) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function clearEmpty() {
    const empty = el("messages").querySelector(".empty-message");
    if (empty) empty.remove();
  }
  function addMessage(role, content, citations = []) {
    clearEmpty();
    const card = node("article", undefined, "message " + (role === "user" ? "user" : "assistant"));
    card.append(node("div", role === "user" ? "You" : "rag-mtst", "speaker"));
    card.append(node("div", content, "content"));
    if (citations.length) {
      for (const citation of citations) {
        const detail = node("details");
        detail.append(node("summary", "[" + citation.id + "] " + citation.source_title + " · chunk " + citation.chunk_index));
        detail.append(node("p", citation.content, "passage"));
        card.append(detail);
      }
    }
    el("messages").append(card);
    card.scrollIntoView({block: "nearest"});
    return card;
  }
  function showMatches(matches) {
    clearEmpty();
    const card = node("article", undefined, "message");
    card.append(node("div", "Search results · " + matches.length + " passages", "speaker"));
    if (!matches.length) card.append(node("p", "No matching source chunks."));
    for (const match of matches) {
      const detail = node("details");
      const score = match.score == null ? "context" : Number(match.score).toFixed(4);
      detail.append(node("summary", match.source_title + " · chunk " + match.chunk_index + " · " + score));
      detail.append(node("p", match.content, "passage"));
      card.append(detail);
    }
    el("messages").append(card);
    card.scrollIntoView({block: "nearest"});
  }
  async function refreshStatus() {
    const status = await invoke("backend_status");
    ready = status.ready;
    el("status-dot").className = "dot " + (ready ? "ready" : "error");
    el("backend-label").textContent = ready ? "Backend connected" : "Backend offline";
    el("backend-detail").textContent = ready
      ? "FastAPI is responding at 127.0.0.1:8000. Docker services are managed by your checkout."
      : "The API is unavailable. Check Docker access, .env settings, and Compose logs.";
    el("repo-path").textContent = status.projectDirectory || "Not configured";
    el("stop-backend").disabled = !status.canStop;
    return status;
  }
  async function startStack() {
    el("start-backend").disabled = true;
    el("backend-label").textContent = "Starting Docker Compose…";
    el("status-dot").className = "dot";
    notice("Starting the existing Docker Compose stack. Initial image builds may take time.");
    try {
      await invoke("start_stack");
      await refreshStatus();
      notice("");
      await restoreConversation();
    } catch (error) {
      await refreshStatus();
      notice(String(error), true);
    } finally {
      el("start-backend").disabled = false;
    }
  }
  async function selectDirectory() {
    try {
      const path = await window.__TAURI__.dialog.open({directory: true, multiple: false, title: "Choose rag-mtst checkout"});
      if (!path) return;
      const root = await invoke("set_project_directory", {path});
      el("repo-path").textContent = root;
      conversationKey = null;
      conversation = null;
      el("messages").replaceChildren();
      notice("Repository selected. Starting Docker Compose.");
      await startStack();
    } catch (error) {
      notice(String(error), true);
    }
  }
  async function restoreConversation() {
    if (!ready || restoring) return;
    const project = await invoke("project_directory");
    const key = "rag-mtst-desktop:conversation:" + project;
    if (conversationKey === key) return;
    restoring = true;
    try {
      conversationKey = key;
      conversation = localStorage.getItem(key);
      if (!conversation) return;
      const entries = await invoke("conversation_messages", {conversationId: conversation});
      el("messages").replaceChildren();
      if (Array.isArray(entries)) {
        for (const item of entries) addMessage(item.role, item.content, item.citations || []);
      }
    } catch (error) {
      // Conversation may have been deleted or belong to another database.
      if (conversationKey) localStorage.removeItem(conversationKey);
      conversation = null;
      el("messages").replaceChildren();
    } finally { restoring = false; }
  }
  async function ensureConversation() {
    if (conversation) return conversation;
    const result = await invoke("create_conversation");
    conversation = result.id;
    if (conversationKey) localStorage.setItem(conversationKey, conversation);
    return conversation;
  }
  async function runQuery(action) {
    if (!ready || busy) return notice("Backend is not ready.", true);
    const query = el("query").value.trim();
    if (!query) return;
    const provider = el("provider").value;
    const model = el("model").value.trim();
    if (action === "ask" && provider && !model) return notice("A provider override requires a model name.", true);
    busy = true;
    el("query-status").textContent = action === "ask" ? "Generating answer…" : "Retrieving passages…";
    el("query-form").querySelectorAll("button").forEach((button) => button.disabled = true);
    notice("");
    try {
      if (action === "ask") {
        const id = await ensureConversation();
        const result = await invoke("ask_question", {
          query, conversationId: id,
          generationProvider: provider || null,
          generationModel: model || null
        });
        addMessage("user", query);
        addMessage("assistant", result.answer, result.citations || []);
      } else {
        const results = await invoke("search_passages", {query, method: el("method").value});
        showMatches(results);
      }
      el("query").value = "";
      el("query-status").textContent = "Ready";
    } catch (error) {
      notice(String(error), true);
      el("query-status").textContent = "Request failed; it was not automatically retried.";
    } finally {
      busy = false;
      el("query-form").querySelectorAll("button").forEach((button) => button.disabled = false);
    }
  }
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  async function importFiles(paths) {
    if (!ready) return notice("Start the backend before importing.", true);
    chooseView("import");
    const validPaths = [...new Set(paths)].filter(Boolean);
    if (!validPaths.length) return;
    const placeholder = el("imports").querySelector(".muted");
    if (placeholder) placeholder.remove();
    const extractionMethod = el("extraction").value;
    const reindex = el("reindex").checked;
    for (const path of validPaths) {
      const name = path.split(/[\\/]/).pop();
      const row = node("div", undefined, "import-row");
      const details = node("div");
      details.append(node("strong", name));
      const info = node("small", "Waiting to submit");
      const progress = node("progress");
      progress.max = 100;
      progress.hidden = true;
      details.append(info, progress);
      const state = node("span", "Queued", "state");
      row.append(details, state);
      el("imports").prepend(row);
      try {
        state.textContent = "Submitting";
        const result = await invoke("upload_file", {path, extractionMethod, reindex});
        if (result.job_id) {
          info.textContent = "Job " + result.job_id;
          while (true) {
            const job = await invoke("job_status", {jobId: result.job_id});
            state.textContent = job.stage || job.status;
            if (job.progress != null) {
              progress.hidden = false;
              progress.value = job.progress;
            }
            if (job.status === "failed") throw new Error(job.error || "Indexing failed");
            if (job.status === "completed") break;
            await sleep(1500);
          }
        }
        state.textContent = result.job_id ? "Indexed" : "Unchanged";
        info.textContent = result.job_id ? "Ready for search" : "Already indexed";
        await invoke("notify_indexing", {success: true, fileName: name});
      } catch (error) {
        state.textContent = "Failed";
        info.textContent = String(error);
        await invoke("notify_indexing", {success: false, fileName: name}).catch(() => {});
      }
    }
  }
  async function chooseFiles() {
    try {
      const selected = await window.__TAURI__.dialog.open({
        multiple: true, directory: false, title: "Import documents",
        filters: [{name: "Documents", extensions: ["txt", "md", "markdown", "pdf", "docx", "pptx"]}]
      });
      if (selected) await importFiles(Array.isArray(selected) ? selected : [selected]);
    } catch (error) { notice(String(error), true); }
  }

  document.querySelectorAll(".nav").forEach((button) =>
    button.addEventListener("click", () => chooseView(button.dataset.view)));
  el("start-backend").addEventListener("click", startStack);
  el("choose-directory").addEventListener("click", selectDirectory);
  el("choose-files").addEventListener("click", chooseFiles);
  el("drop-zone").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); chooseFiles(); }
  });
  el("stop-backend").addEventListener("click", async () => {
    if (!confirm("Stop the services started by this desktop session? In-progress indexing may fail.")) return;
    try {
      notice(await invoke("stop_stack"));
      await refreshStatus();
    } catch (error) { notice(String(error), true); }
  });
  el("hide-window").addEventListener("click", () => invoke("hide_window").catch((e) => notice(String(e), true)));
  el("new-chat").addEventListener("click", () => {
    if (conversationKey) localStorage.removeItem(conversationKey);
    conversation = null;
    el("messages").replaceChildren();
    el("query").focus();
    notice("");
  });
  el("query-form").addEventListener("submit", (e) => {
    e.preventDefault();
    runQuery(e.submitter?.value || "ask");
  });
  el("query").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      runQuery("ask");
    }
  });
  for (const setting of ["method", "provider", "model", "extraction"]) {
    const control = el(setting);
    control.value = localStorage.getItem("rag-mtst-desktop:" + setting) || control.value;
    control.addEventListener("change", () => localStorage.setItem("rag-mtst-desktop:" + setting, control.value));
  }
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault(); chooseView("chat"); el("query").focus();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") {
      e.preventDefault(); chooseFiles();
    }
  });
  window.__TAURI__?.webview?.getCurrentWebview().onDragDropEvent((e) => {
    el("drop-zone").classList.toggle("over", e.payload.type === "enter" || e.payload.type === "over");
    if (e.payload.type === "drop") importFiles(e.payload.paths);
  }).catch((e) => notice("File-drop listener unavailable: " + String(e), true));

  (async () => {
    if (!invoke) return notice("This frontend must be opened in the Tauri desktop application.", true);
    chooseView("chat");
    try {
      const project = await invoke("project_directory");
      if (!project) {
        chooseView("settings");
        notice("Choose your rag-mtst checkout to configure automatic Docker startup.");
        await refreshStatus();
        return;
      }
      el("repo-path").textContent = project;
      await startStack();
    } catch (error) { notice(String(error), true); }
  })();
})();
