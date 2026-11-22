# CLAUDE.md — anomaly-coop

Co-op and multiplayer for S.T.A.L.K.E.R. Anomaly, built on themrdemonized's xray-monolith engine.
Personal notes (project state, decisions, test stands) live in a separate private repo; this file only covers what anyone working on the code needs.

## Branches and worktrees
Each branch is checked out as its own git worktree next to this folder (`xray-monolith-<branch>`; `coop` sits in `xray-monolith`).
- `main` — upstream `themrdemonized/xray-monolith`, branch `all-in-one-vs2022-wpo`. Never commit here.
- `coop` — the one main branch, everything that works goes here: engine networking in `src/xrGame/coop/`, Lua sync in `gamedata/scripts/coop_sync.script`, DLTX in `gamedata/configs/mod_system_coop.ltx`, Node server in `coop-server/` (protocol 27), plus all of the merged branches below. Since 2026-11-05 it holds `shelter` (with `raid`), `timesync` (the server's clock), `launcher` (build id in HELLO, `-coop_auto`), `multiplayer` and `render`.
- `integrate` — where `shelter`, `launcher` and `multiplayer` were brought together before going into `coop` (2026-11-05); merged.
- `raid` — the Limansk raid: six level copies in one spawn pack (`tools/raid/`), scripted transitions. Merged into `coop` (via `shelter`).
- `shelter` — the group's own hideout on top of coop and raid: questline, floors and lifts, laptop apps, bar, trade, perimeter, AI vision. Merged into `coop`.
- `timesync`, `launcher` — the world's clock on the server; the launcher's game side (`launcher` is `timesync` plus it). Merged into `coop`.
- `multiplayer` — headless host (the sim master), joins from the journal, character saves, exit saves, one offline world, packaged server + bot, F10 admin window. Docs: `docs/coop/multiplayer.md`. Merged into `coop`.
- `render` — engine/render performance: render scale, `prof_spikes`, Lua GC step, optional PGO build (`tools/pgo/pgo.ps1`). Docs: `docs/coop/render.md`. Merged into `coop`.
- `dlss` — NVIDIA DLSS (`r__dlss_mode`): jitter, motion vectors, NGX; the SDK is fetched by `tools/dlss/get_dlss_sdk.ps1` (not in the repo). Docs: `docs/coop/render.md` §6. Merged into `coop` (its fixes via `fix-dlss`).
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
- A HUD item model built in Blender from an imported vanilla armature inherits its motion refs (`OGF_S_MOTION_REFS`): the engine then loads the refs and ignores the embedded motions → FATAL "model has no motion [idle]" on draw. Clear `obj.xray.motionrefs_collection` before export; before launching, check that every `anm_*` motion of the hud section exists in the deployed `.omf` and item `.ogf` (`tools/spectrum_x/check_motions.py`).
- Bones made with `edit_bones.new()` come in quaternion rotation mode: keying `rotation_euler` after setting `matrix_basis` keys stale zeros and the exported bone never turns. Set `pose_bone.rotation_mode` (the imported rigs use `ZXY`) before baking.
- Script methods that are our engine additions (e.g. `CArtefact:IsVisible`) are missing in older exes a stand may run: calling one is a FATAL Lua error. Guard them (`af.IsVisible and af:IsVisible()`).
- luabind userdata (`Frect`, `vector2`...) have no `==`: `a ~= b` on two of them is a FATAL Lua error in the game (script mocks with tables don't show it). Compare identity with `rawequal`, or the numbers.
- Text (`CGameFont`) is not drawn in an item's 3D UI (`custom_ui_func`): fonts are flushed later in screen space. Draw text there as textured glyph statics.

## Testing
- Lua syntax without the game: compile each `.script` with `lupa.luajit21` `loadstring` (decode cp1251).
- Engine self-test: `tools/coop_selftest.script`, copied into the game and run with `-coop_selftest`.
- Automated runs: always start players with `-coop_pick_save exit|personal|newest` (`ui_coop_saves.script`), otherwise a character with an exit save and one of its own waits on the "which save" window for a click.
- Two instances on one PC need two exe folders (`bin`, `bin2` + `fsgame2.ltx` with its own appdata): the single-instance mutex is per exe folder.
- Test user.ltx: `g_always_active on`, `keypress_on_start off`, otherwise the games wait for a key and actor updates never run.
- Logs are buffered: run `flush` in the console, or close the game with CloseMainWindow, not by killing it.
- A game that finished loading in the background can stick on "Пауза": Esc twice.
- Never close or overwrite a game instance or saves the user is playing with; back up saves before tests.
- A save only loads with the spawn overlay packs and levels it was made with ("Saved game doesn't correspond to the spawn: DELETE SAVED GAME!"). When a stand's packs or levels change, its old saves die: check a save's spawn GUID before launching (`tools/spectrum_x/save_guid.py` reads it from the `.scop`) and re-make test saves from one that matches, instead of `ignore_save_incompatibility`.
- After every scripted launch watch the log for `FATAL` / `[error]` and end the crashed game yourself: a FATAL dialog otherwise stays on the screen, and the `fatal_ctd_save_N` it writes must be deleted before the next auto-load.
- A background test script stopped from the harness can leave its `bash` children running (still sending commands to the game): check for leftover processes before the next launch.
- A vanilla hold copied onto another device (the tablet put where the PDA sits) fits only that device's size and grip style: the thumb went through the edge, the fingers curled under it. Place the hand by its own measured axes (wrist→knuckle, knuckle line, palm side) on the device (`tools/spectrum_x/hud_rig.py` `SIDE_GRIP`), lay the thumb out explicitly (`thumb_aim`), then check clearance. A pure depth test passes a finger that wraps round an edge onto the device's face: test the face too.
- Take a thumb's pad anatomically (the skin on the side its last joint bends to), not as the skin nearest a surface: a turned thumb then reports its side or nail as the "pad" and the search lays it through the device. Turning the thumb also drags the palm's skin weighted to `l_hand` (the thenar): check the palm again after posing the thumb.
- When one pose needs the hands elsewhere on the device than the others (both hands lower on the edges), move the device bone in the hand for that pose (`build_hud.py` `D`) instead of changing the device's bind.
- Solve and check HUD grips against every arms model a player may wear, the thick exoskeleton sleeves included (`hud_rig.HAND_SETS`, `check_hud.py --hands`); render previews with them and at both hud_fov values in use (console default 0.64, players often 0.45).
- A hand mirrored from the other one about a device is only as good as the device's symmetry: keep parts the fingers reach (sockets, ports) on its middle line.
- Low-poly HUD meshes shaded all-smooth streak dark across big flat faces: mark edges over ~40° sharp (blender-xray exports the split normals) and bake the normal map on the same normals.
- A near-black gradient in a DXT1 texture turns into big blue / green streaks in game (5:6:5 steps, then the HUD lighting brightens them); Blender previews don't show it. Keep near-black surfaces (a switched-off screen) one flat colour, and look at dark textures in game.
- Blender's bundled Python has no PIL: draw textures in a system-Python step and call it from the Blender script (`tablet_prints.py`).

## Git
- Commit as the configured git user. No AI attribution anywhere: no Co-Authored-By trailers, no "Generated with" lines, no AI mention in messages, PRs or branch names.
- Commit subjects follow the existing style: `Area: what changed, in plain words` (Engine, Co-op, Shelter, Server, Docs...).
