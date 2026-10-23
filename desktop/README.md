# Desktop client (Arch Linux first)

Tauri 2 desktop frontend for the existing rag-mtst backend. The HTTP API, PostgreSQL/pgvector, and ingestion worker remain the source of truth. The original `demo/` is not modified.

## What it does

- Starts the repository's existing `docker compose up -d` stack on launch.
- Waits for the real FastAPI OpenAPI endpoint on `127.0.0.1:8000`.
- Native multiple-file selection, window-wide file drop, sequential imports and job progress.
- Search and persisted conversations with source citations; Ctrl+K focuses search, Ctrl+O imports.
- System tray (Open / Quit), Hide to tray, indexing notifications, saved repository path and generation settings.
- Keeps `RAG_API_KEY` on the Rust side. The frontend does not fetch the API directly or store the token.

It is **not** a single-binary backend: Docker, images, project files, the `.env` file, and volumes remain installed separately. The system is still trusted, single-tenant, pre-release software.

## Prerequisites on Arch

Install Rust stable (1.90+), Docker Engine with the Compose v2 plugin, and Tauri's system libraries:

```bash
sudo pacman -Syu
sudo pacman -S --needed rustup webkit2gtk-4.1 base-devel curl wget file \
  openssl appmenu-gtk-module libappindicator-gtk3 librsvg xdotool docker docker-compose
rustup default stable
cargo install tauri-cli --version '^2.0.0' --locked
```

Start Docker using your preferred rootless/daemon setup. For a typical system install:

```bash
sudo systemctl enable --now docker
docker compose version
docker info
```

If your user cannot access Docker, configure Docker permissions before launching the app. Docker group access is root-equivalent; rootless Docker is an alternative. Do **not** launch the desktop app with sudo.

## Run

From the checked-out repository root, configure the existing backend's private settings:

```bash
cp -n .env.example .env
```

Edit `.env` and set at least `RAG_API_KEY`, `OPENAI_API_KEY`, and `RAG_GENERATION_MODEL` as documented in [Run the backend](../docs/how-to/run.md). The app reads the bearer token from the selected repository's `.env`; it never stores it in the webview.

```bash
cd desktop
cargo tauri dev
```

On startup the client locates the checkout from the working directory (or parent directories), starts its Compose stack and waits for the API. On an installed desktop launch, use **Settings → Choose folder** once to select your repository root; the path is saved in your OS config directory. Alternatively set `RAG_DESKTOP_PROJECT_DIR=/absolute/path/to/rag-mtst` when launching.

To build an Arch-friendly AppImage:

```bash
cd desktop
cargo tauri build --bundles appimage
```

Build and graphical behavior have not been verified on an actual Arch machine. You may need AppImage-specific build dependencies depending on your toolchain.

## Lifecycle and safety

- Automatic launch calls `docker compose --project-directory <checkout> -f compose.yaml up -d`. Images are built if they do not already exist. Subsequent launches reuse existing services when Compose deems them current.
- The app does **not** run `down -v`, prune Docker, migrate on its own, or reset indexes. The existing `migrate` Compose service runs as designed.
- Closing/quitting the desktop app **leaves Compose running** so accepted ingestion jobs can finish.
- The **Stop** action is enabled only if no stack services were running before this desktop session started them. Stop uses `docker compose stop`, preserving containers and volumes. A partially running stack is treated as pre-existing.
- If startup fails, review `docker compose ps` and `docker compose logs --tail=100` in the checkout. Check ports 5432 and 8000, Docker permissions, provider settings, and `RAG_API_KEY`.
- The API is bound to port 8000 by the repository's existing Compose configuration, which currently publishes on all interfaces. **Restrict access to trusted networks or bind the API to loopback** before desktop use on an untrusted LAN.
- The desktop HTTP bridge only contacts `http://127.0.0.1:8000` and exposes specific API operations, never an arbitrary URL or shell command.
- Original document files are not archived. The desktop import limit is 50 MiB per file; visual extraction has the lower constraints documented in [limits](../docs/reference/limits.md).
- Visual DOCX/PPTX extraction still needs the optional `office` Compose profile and configured visual provider; the default launch does not enable it.
- The UI resumes only the most recently used conversation ID (saved locally) and displays only this session's import activity. Source deletion, conversation lists, streaming, and a full document library are not implemented.

## Troubleshooting

If the tray is absent, check your desktop environment's StatusNotifier/AppIndicator support. Some Wayland compositors require a tray host. On failure to launch, test `cargo tauri dev` from a terminal to see native errors.

If the desktop reports the backend as offline even though Docker is running, verify:

```bash
docker compose ps
curl --fail http://127.0.0.1:8000/openapi.json
```

The API must report the `rag-mtst` OpenAPI title. The UI reports request errors without automatically retrying potentially billable operations.
