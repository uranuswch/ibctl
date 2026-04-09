# ibctl

Drop-in replacement for [IBC](https://github.com/IbcAlpha/IBC) (deprecated Sept 2026).
Automates IB Gateway/TWS login, 2FA, session management via a **Rust supervisor + Java
agent** architecture. The agent walks Swing component trees inside the Gateway JVM —
no xdotool, no pixel coordinates, no screen scraping. See `README.md` for user-facing
docs and `docs/architecture.md` for the full design.

## Repository layout

This is a multi-language monorepo. There are four top-level components, each with its
own toolchain:

- **`ibctl/`** — Rust binary (`cargo` workspace member). The supervisor: launches the
  Gateway JVM with `-javaagent:`, runs the state machine, drives dialog handlers,
  hosts the IBC-compatible TCP command server.
- **`agent/`** — Java agent, built with plain `javac` + `jar`. Injected into the
  Gateway JVM. Exposes HTTP+JSON over Unix domain socket (`/tmp/ibctl.sock`) using
  JDK 17's built-in `UnixDomainSocketAddress`. Target: JDK 17. Note: `agent/pom.xml`
  exists but is **not used by any build path** (root Dockerfile, `docker/build.sh`,
  and both CI workflows all invoke `javac` + `jar` directly). Treat the pom as dead
  unless you intentionally migrate the whole toolchain to Maven.
- **`dashboard/`** — FastAPI web dashboard + REST API (Python 3.12+, uv/pip). Provides
  a UI for managing instances, alerts, and configuration. Runs alongside the
  supervisor in the container.
- **`docker/`** — entrypoint, config templates, and a separate dev/test Dockerfile.
  See the "Two Dockerfiles" section below — they are not interchangeable.

Top-level `Cargo.toml` is a workspace with `ibctl/` as the only member. Rust toolchain
pinned via `rust-toolchain.toml`. Workspace-wide lints: `unsafe_code = "deny"`,
`unwrap_used = "warn"`, `dbg_macro = "deny"`.

## Rust crate internals (`ibctl/src/`)

- `main.rs` — entry point. Loads config (defaults → TOML → env), sets env vars
  **before** starting the Tokio runtime (multi-threaded `std::env::set_var` is UB —
  SEC-04 fix, don't move this).
- `config.rs` — TOML + env var loading. Precedence: env > TOML > defaults. Passwords
  and TOTP secrets are **env-var only** (with `_FILE` suffix for Docker secrets);
  never put them in the TOML file.
- `supervisor.rs` — launches/monitors/restarts the Gateway JVM process.
- `agent_client.rs` — HTTP+JSON client over UDS to `ibctl-agent.jar`.
- `state_machine/` — `INIT → LAUNCHING → LOGIN → 2FA → POPUPS → CONNECTED`, plus
  `ReconnectingSession` for silent session-loss recovery. `types.rs` defines states;
  `queries.rs` polls the agent; `socat.rs` tracks TCP port state for silent-loss
  detection.
- `handlers/` — one file per Swing dialog. Each handler is idempotent: it queries the
  UI, acts only if the target dialog is present, and verifies success via agent
  readback. New dialogs should follow the same pattern and register in `mod.rs`.
- `command_server.rs` — line-based TCP protocol, wire-compatible with IBC. Commands:
  `STOP`, `RESTART`, `RECONNECTDATA`, `RECONNECTACCOUNT`, `ENABLEAPI`, `STATUS`,
  `EXIT`. Protocol: `COMMAND\n` → `OK msg\n` / `ERROR msg\n` / `INFO msg\n`.
- `cold_restart.rs` — Sunday weekly full re-auth (mirrors IBC's `ColdRestartTime`).
- `totp.rs` — TOTP generators. `BuiltinProvider` (default) is an in-process RFC 6238 implementation via `totp-lite`; `OathtoolProvider` is a legacy fallback, opt-in via `TOTP_PROVIDER=oathtool`.
- `signals.rs` — SIGTERM/SIGINT graceful shutdown.

Logging is JSON Lines via `env_logger` with a custom format (see `main.rs`). Log level
comes from config and is exported as `RUST_LOG=ibctl=<level>`.

## Build & test

**Rust (from repo root):**
```bash
cargo build                  # debug
cargo build --release        # release (LTO, strip, panic=abort)
cargo test
cargo clippy --all-targets   # warnings are meaningful; unwrap/todo warn, dbg denies
cargo fmt
```

**Java agent (from `agent/`):**
```bash
mkdir -p target/classes
javac --release 17 -d target/classes src/main/java/ibctl/agent/*.java
jar cfm target/ibctl-agent.jar src/main/resources/META-INF/MANIFEST.MF -C target/classes .
```

**Dashboard (from `dashboard/`):**
```bash
pip install -e '.[dev]'      # or uv pip install
pytest                       # tests in dashboard/tests, asyncio_mode=auto
```

### Two Dockerfiles — pick the right one

There are **two** Dockerfiles in this repo and they are not interchangeable:

1. **`./Dockerfile`** (repo root) — **production image**, used by
   `.github/workflows/docker-publish.yml` (context `.`, default Dockerfile). Fully
   self-contained multi-stage build: `setup` (downloads and installs IB Gateway) →
   `prebuilt-downloader` → `rust-builder` + `java-builder` → final Ubuntu 24.04
   image. Stage 2a short-circuits source builds when `IBCTL_VERSION` is set, so you
   can opt into a pre-built release binary:
   ```bash
   docker build -t ibctl .                                    # from source
   docker build --build-arg IBCTL_VERSION=v0.1.0 -t ibctl .   # pre-built release
   ```
   This is what the README and CI use. Default build also compiles with `thin` LTO
   (fast) instead of release's `fat` LTO.

2. **`docker/Dockerfile`** — **local dev/test image only**. Layers on
   `ghcr.io/gnzsnz/ib-gateway:latest` and expects pre-built artifacts (`ibctl`,
   `ibctl-agent.jar`, etc.) to already be sitting in the `docker/` directory. It is
   driven by `docker/build.sh`, which runs `cargo build` (**debug**, not release),
   builds the Java agent, copies the artifacts into `docker/`, and builds the image
   as `ibctl-test`. Use this for fast local iteration; do not ship it.

   ```bash
   ./docker/build.sh            # produces the `ibctl-test` image
   ```

Never copy production changes into `docker/Dockerfile` or vice versa — they're
intentionally different.

## Key invariants & gotchas

- **Verify, don't assume.** Every UI action goes agent → Swing readback → confirm.
  Don't add handlers that fire input blindly — that's the xdotool failure mode ibctl
  exists to avoid.
- **No `unsafe`, no `unwrap()` in new code.** Clippy lints enforce this; don't paper
  over them with `#[allow]`.
- **Secrets are env-only.** `TWS_PASSWORD`, `TWOFACTOR_CODE`, etc. must never land in
  `ibctl.toml`. `_FILE` suffix reads from Docker secrets — preserve this for any new
  secret-bearing variable.
- **IBC wire compatibility matters.** The TCP command server is a drop-in replacement;
  existing tooling (gnzsnz scripts, Sentio processors, etc.) depends on the exact
  `OK/ERROR/INFO` response format. Don't change it.
- **Dual mode runs two Gateway JVMs.** `TRADING_MODE=both` starts live + paper
  simultaneously on ports 4001 and 4002. Handlers must be instance-scoped.
- **`std::env::set_var` before Tokio starts.** See `main.rs` — moving env var setup
  into async code is unsound on multi-threaded runtimes.
- **Target runtime:** `ghcr.io/gnzsnz/ib-gateway:latest`, Zulu OpenJDK 17.0.16,
  Gateway 10.43.1b+. The agent depends on JDK 17 UDS support — don't downgrade.

## Conventions

- Rust 2021 edition. `thiserror` for error types, `tokio` for async, `secrecy` for
  sensitive strings, `jiff` (not `chrono`) for time.
- Handlers are idempotent and query-before-act. See `handlers/login.rs` as the
  reference implementation.
- When adding env vars, update `README.md`'s tables, `.env.example`, and
  `ibctl.toml.example` together.
- Commit messages use Conventional Commits style (`feat:`, `fix:`, `refactor:`).
  See recent log for examples.
