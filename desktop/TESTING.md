# Tauri desktop: build and cleanup (Arch Linux)

Run these commands from the `rag-mtst` repository checkout on the `feature/tauri-desktop` branch.

## Test locally

```fish
cd ~/Documents/projects/rag-mtst/desktop
cargo tauri dev
```

The desktop app starts the existing Docker Compose stack automatically. Closing the app leaves Docker services running.

## Build an AppImage

```fish
cd ~/Documents/projects/rag-mtst/desktop
cargo tauri build --bundles appimage
```

The build output is under `desktop/src-tauri/target/release/bundle/appimage/`.

## Clean up when finished

**Stop and delete this checkout's Docker services and database:**

```fish
cd ~/Documents/projects/rag-mtst
docker compose --profile office down --volumes --rmi local --remove-orphans
```

**Remove Tauri/Rust build artifacts to reclaim disk space:**

```fish
cd ~/Documents/projects/rag-mtst
cargo clean --manifest-path desktop/src-tauri/Cargo.toml
```

**Optional: remove the extra Office image if it is still installed and not used elsewhere:**

```fish
docker image rm rag-mtst-demo-office:local
```

**Important:** `--volumes` permanently deletes this Compose project's PostgreSQL database, indexed content, and conversations. Compose resources are **shared by this checkout across Git branches**; Docker cannot distinguish the desktop branch from `main`. Do not run the Docker cleanup if you want to keep that data.

These commands do **not** run system-wide Docker pruning or uninstall Rust, Cargo, or Tauri.
