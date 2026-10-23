"use strict";

const element = (id) => document.getElementById(id);

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}

function status(id, message, error = false) {
  const target = element(id);
  target.textContent = message;
  target.classList.toggle("error", error);
}

async function request(path, options = {}) {
  const token = element("token").value.trim();
  if (!/^[\x21-\x7e]+$/.test(token)) throw new Error("Enter an API token without spaces.");
  const response = await fetch(path, {
    ...options,
    credentials: "omit",
    redirect: "error",
    headers: { ...options.headers, Authorization: `Bearer ${token}` },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(`${response.status}: ${typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : response.statusText}`);
  }
  if (payload === null) throw new Error("The API returned an unreadable response.");
  return payload;
}

function matches(target, items) {
  if (!items.length) {
    target.append(node("p", "No matching source chunks.", "empty"));
    return;
  }
  items.forEach((match, index) => {
    const entry = node("details");
    entry.open = index === 0;
    const score = match.score === null ? "context" : `score ${Number(match.score).toFixed(6)}`;
    entry.append(node("summary", `${index + 1}. ${match.source_title} | chunk ${match.chunk_index} | ${score}`));
    entry.append(node("p", `Source ${match.source_id}`, "metadata"));
    entry.append(node("div", match.content, "passage"));
    target.append(entry);
  });
}

async function run(form, statusId, action) {
  element("controls").disabled = true;
  form.setAttribute("aria-busy", "true");
  try {
    await action();
  } catch (error) {
    status(statusId, error.message, true);
  } finally {
    element("controls").disabled = false;
    form.removeAttribute("aria-busy");
  }
}

element("upload-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const file = element("document").files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  const params = new URLSearchParams({
    extraction_method: document.querySelector('input[name="extraction"]:checked').value,
    reindex: String(element("reindex").checked),
  });
  run(event.currentTarget, "upload-status", async () => {
    element("progress").hidden = true;
    element("upload-source").textContent = "";
    status("upload-status", `Submitting ${file.name}...`);
    const result = await request(`/sources/file?${params}`, { method: "POST", body: formData });
    element("upload-source").textContent = `Source ${result.id}${result.job_id ? ` | Job ${result.job_id}` : ""}`;
    status("upload-status", `${file.name}: ${result.status}`);
    if (!result.job_id) return;
    while (true) {
      const job = await request(`/jobs/${encodeURIComponent(result.job_id)}`);
      const parts = [file.name, job.status, job.stage];
      if (job.processed != null && job.total != null) parts.push(`${job.processed} / ${job.total}`);
      status("upload-status", parts.filter(Boolean).join(" | "));
      element("progress").hidden = job.progress == null;
      if (job.progress != null) element("progress").value = job.progress;
      if (job.status === "failed") throw new Error(job.error || "Indexing failed.");
      if (job.status === "completed") return;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  });
});

element("query-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const action = event.submitter?.value || "search";
  const query = element("query").value.trim();
  run(event.currentTarget, "query-status", async () => {
    const target = element("results");
    target.replaceChildren();
    if (!query) throw new Error("Enter a query or question.");
    status("query-status", action === "search" ? "Searching..." : "Generating answer...");
    const payload = { query };
    if (action === "ask") {
      const provider = element("answer-provider").value;
      const model = element("answer-model").value.trim();
      if (provider) payload.generation_provider = provider;
      if (model) payload.generation_model = model;
    }
    const result = await request(`/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    if (action === "search") {
      matches(target, result);
      status("query-status", `${result.length} matches returned`);
      return;
    }
    target.append(node("h3", "Answer"), node("div", result.answer, "answer"), node("h3", "Cited sources"));
    if (!result.citations.length) target.append(node("p", "No sources cited.", "metadata"));
    for (const citation of result.citations) {
      const entry = node("details");
      entry.append(node("summary", `[${citation.id}] ${citation.source_title} | chunk ${citation.chunk_index}`));
      entry.append(node("p", `Source ${citation.source_id} | ${citation.source_locator}${citation.truncated ? " | Truncated" : ""}`, "metadata"));
      entry.append(node("div", citation.content, "passage"));
      target.append(entry);
    }
    target.append(node("h3", "Retrieved matches"));
    matches(target, result.matches);
    status("query-status", "Answer received");
  });
});