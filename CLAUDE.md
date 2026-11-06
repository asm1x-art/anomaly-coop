# CLAUDE.md — anomaly-coop

Co-op and multiplayer for S.T.A.L.K.E.R. Anomaly, built on themrdemonized's xray-monolith engine.
Personal notes (project state, decisions, test stands) live in a separate private repo; this file only covers what anyone working on the code needs.

## Branches and worktrees
Each branch is checked out as its own git worktree next to this folder (`xray-monolith-<branch>`; `coop` sits in `xray-monolith`).
- `main` — upstream `themrdemonized/xray-monolith`, branch `all-in-one-vs2022-wpo`. Never commit here.
- `coop` — the one main branch, everything that works goes here: engine networking in `src/xrGame/coop/`, Lua sync in `gamedata/scripts/coop_sync.script`, DLTX in `gamedata/configs/mod_system_coop.ltx`, Node server in `coop-server/` (protocol 25), plus all of the merged branches below. Since 2026-11-05 it holds `shelter` (with `raid`), `timesync` (the server's clock), `launcher` (build id in HELLO, `-coop_auto`), `multiplayer` and `render`.
- `integrate` — where `shelter`, `launcher` and `multiplayer` were brought together before going into `coop` (2026-11-05); merged.
- `raid` — the Limansk raid: six level copies in one spawn pack (`tools/raid/`), scripted transitions. Merged into `coop` (via `shelter`).
- `shelter` — the group's own hideout on top of coop and raid: questline, floors and lifts, laptop apps, bar, trade, perimeter, AI vision. Merged into `coop`.
- `timesync`, `launcher` — the world's clock on the server; the launcher's game side (`launcher` is `timesync` plus it). Merged into `coop`.
- `multiplayer` — headless host (the sim master), joins from the journal, character saves, exit saves, one offline world, packaged server + bot, F10 admin window. Docs: `docs/coop/multiplayer.md`. Merged into `coop`.
- `render` — engine/render performance: render scale, `prof_spikes`, Lua GC step, optional PGO build (`tools/pgo/pgo.ps1`). Docs: `docs/coop/render.md`. Merged into `coop`.
- `dlss` — NVIDIA DLSS (`r__dlss_mode`): jitter, motion vectors, NGX; the SDK is fetched by `tools/dlss/get_dlss_sdk.ps1` (not in the repo). Docs: `docs/coop/render.md` §6. Not merged yet.
- `weapons` — weapon pack plan (`docs/coop/weapons.md`), no code yet.
- `rebalance` — hard-mode balance, no code yet.

## Docs
- Plans, design, progress and test orders live in Notion, "Документация проекта" (https://app.notion.com/p/40ed89dbf39d81f68103c6060dceae0b). It is private, in the project owner's workspace; agents with Notion access use it.
- Code-bound docs stay in `docs/coop/`: `multiplayer.md`, `weapons.md`, `render.md`.
- New user-facing docs go to Notion, not into new `.md` files in the repo.

## Build
- A fresh worktree needs `git submodule update --init` (`src/3rd party/optick-git`) first, otherwise C1083 in optick/coop_logs.
- From `<worktree>\src`: `MSBuild.exe engine-vs2022.sln /m /p:Configuration=DX11 /p:Platform=x64` → `_build\_game\bin_dbg\AnomalyDX11.exe`.
- Copy exe + pdb into the game's `bin` (and `bin2` for the second instance); copy changed `gamedata` files into the game's `gamedata`. The games must be closed.
- Server: `coop-server/` — Node 24, no dependencies, `npm test`, port 7777, world data in `coop-server/data` (delete it to start the world over; back it up before tests).

## Code rules
- `.script` files are cp1251. Read and write them in that encoding.
- Anything tunable (balance, timings, radii) goes into `.ltx` so it can be changed during tests without a rebuild.
- DXML patches of `map_spots` must cover both `map_spots.xml` and `map_spots_16.xml`.
- Shelter UIs use the modern dark style from `ui_shelter_style.script`, never a retro look.
- New debug logging goes behind the existing co-op debug flag: one switch logs everything.

## Engine and script gotchas
- Frames (seqFrame) don't run while a level loads: per-frame networking is dead then; use `coop::wait_for_messages`.
- During level teardown the actor's whole inventory is detached: guard on `g_pGameLevel->bReady`.
- `Actor()` goes through `Level().game`, which is null while loading: use `g_actor`.
- Anomaly writes `.scoc` after the engine save hook.
- `-load` only works in a running game; use `start server(<save>/single/alife/load) client(localhost)`, with `main_menu off` first when in the menu.
- Players may stand off the AI grid: `level_graph().vertex_id()` is invalid then; use `vertex(u32(-1), pos)` (nearest, O(N)).
- Never call `getFS():file_list_open_ex` on a recursive path (`$game_data$`, `$game_meshes$`, `$game_shaders$`, `$game_textures$`...): it rescans and drops all loose subfolders from the FS. `fs:exist` is safe.
- An anomaly zone made by `alife_create` alone has no shape and crashes in `CCustomZone::CalcDistanceTo`. Give it a shape via `utils_stpk.get_anom_zone_data` / `set_anom_zone_data` (as `bind_anomaly_field.dyn_anomalies_spawn`), outside `coop.begin_shared`.
- After a crash Anomaly writes `fatal_ctd_save_N` as the newest save: don't load it, load the last real save.

## Testing
- Lua syntax without the game: compile each `.script` with `lupa.luajit21` `loadstring` (decode cp1251).
- Engine self-test: `tools/coop_selftest.script`, copied into the game and run with `-coop_selftest`.
- Two instances on one PC need two exe folders (`bin`, `bin2` + `fsgame2.ltx` with its own appdata): the single-instance mutex is per exe folder.
- Test user.ltx: `g_always_active on`, `keypress_on_start off`, otherwise the games wait for a key and actor updates never run.
- Logs are buffered: run `flush` in the console, or close the game with CloseMainWindow, not by killing it.
- A game that finished loading in the background can stick on "Пауза": Esc twice.
- Never close or overwrite a game instance or saves the user is playing with; back up saves before tests.

## Git
- Commit as the configured git user. No AI attribution anywhere: no Co-Authored-By trailers, no "Generated with" lines, no AI mention in messages, PRs or branch names.
- Commit subjects follow the existing style: `Area: what changed, in plain words` (Engine, Co-op, Shelter, Server, Docs...).
