# Опись: что ванильные скрипты Anomaly 1.5.3 хранят на актёре

Источник: `G:\stalker-test\anomaly-unpacked\scripts` и `\configs` (только чтение). Искал: все вызовы `save_var/load_var/save_ctime/load_ctime` с первым аргументом `db.actor` или локальным `actor` (других псевдонимов актёра в вызовах нет), `se_save_var/se_load_var` (на id актёра — ни одного вызова), прямой доступ к `db.storage[0|AC_ID]`, функции `xr_effects`/`xr_conditions`, которые берут имя переменной из параметра (`inc_counter`, `dec_counter`, `set_counter`, `counter_equal`, `counter_greater`, `kill_count_ge`, `pstor_set`, `pstor_reset`, `erase_pstor_ctime`, задачи с `p[1]` = id задания) — для них имена собраны по `configs`, плюс то, что сохраняет биндер актёра (`actor_binder:save_state`), и значения движка, которые меняют скрипты.

Где это физически лежит: pstor актёра (`db.storage[0].pstor`) и `pstor_ctime` при сохранении уходят в `m_data.game_object[0].pstor_all` / `.pstor_ctime` (файл `.scoc` мира, `alife_storage_manager`), поля биндера — в `m_data.game_object[0].actor_binder`. Значит, всё ниже сейчас приходит каждому игроку из сохранения мастера.

Колонка «Где»: **pstor** — `save_var/load_var` на актёре; **ctime** — `save_ctime/load_ctime` на актёре; **биндер** — поле `state.actor_binder.*` или таблица `m_data.*`, которую пишет `actor_binder:save_state`; **движок** — значение самого актёра в движке.

Категории: **ЛИЧНОЕ** — про этого игрока, идёт за игроком; **МИР** — общее состояние мира, просто лежит на актёре; **МИР+СИНХР** — общее, и его меняет игра не-мастера, изменения нужно рассылать; **ВРЕМЕННОЕ** — кеш/производное/мёртвое, можно не переносить; **СПОРНОЕ** — неясно или смешано.

Шаблоны: `<task_id>` — id задания из `configs\misc\task\tm_*.ltx` (например `simulation_task_50`, `esc_m_trader_task_1`), `<giver_id>` — id NPC или его отряда, `<npc_id>` — id NPC, `<f1>`/`<f2>` — группировки (в т. ч. `actor_<f>`).

---

## МИР+СИНХР

| Имя | Где | Модули | Что значит | Кто меняет у не-мастера |
|---|---|---|---|---|
| `drx_df_<f1>_<f2>_relations` | pstor | game_relations (save_relation/load_relation, on_game_load), ui_mm_faction_select, warfare, warfare_faction_control, xr_effects (stalker_ceasefire), gameplay_disguise | отношение группировки f1 к f2 (−5000…5000); для каждой пары пишутся три варианта: `f1/f2`, `actor_f1/f2`, `f1/actor_f2` (т. е. и отношение к «группировке игрока»); при загрузке переносится в relation_registry (если `m_data.new_game_relations`) | смерть NPC от любого игрока (dynamic relations: game_relations.npc_on_death_callback → change_faction_relations, срабатывает на игре, где обработана смерть), разоблачение маскировки игрока (gameplay_disguise.expose_actor), сюжетный эффект `=stalker_ceasefire`, Warfare «объявить войну» на ПДА, Warfare all-out-war, старт новой игры (ISG vs наёмники −4000) |

## МИР

| Имя | Где | Модули | Что значит | Замечание |
|---|---|---|---|---|
| `next_clean` | pstor | release_npc_inventory | игровой день следующей чистки инвентарей NPC (раз в 3 дня) | запускается из `actor_on_update` на каждой игре и делает `alife_release` предметов NPC — должно работать только у мастера |
| `simulation_started` | биндер | bind_stalker, sim_board | флаг «симуляция запущена» (SIMBOARD) | |
| `m_data.weather_manager`, `m_data.SurgeManager`, `m_data.PsiStormManager` | биндер | level_weathers, surge_manager, psi_storm_manager | погода, расписание и состояние выброса / пси-шторма | пишутся вызовом из `actor_binder:save_state`, но это состояние мира |

## СПОРНОЕ

| Имя | Где | Модули | Что значит | Почему спорное |
|---|---|---|---|---|
| `surge_immuned` | pstor | xr_effects (`=actor_surge_immuned`, из tm_dynamic.ltx и yan_smart_terrain_6_4_base_defense_quest.ltx), surge_manager, psi_storm_manager, level_environment, xr_conditions | игрок защищён от выброса на время задания «оборона базы» | флаг личного задания, но у мастера он ещё и не даёт выбросу закончиться и отключает убийство NPC выбросом/штормом (`kill_objects_at_pos`, `kill_all_unhided`) — влияет на мир для всех |
| `task_target_anomaly`, `task_target_anomaly_level`, `task_target_anomaly_analyzed` | pstor | xr_effects (setup/reset_task_target_anomaly), task_functor, xr_conditions, axr_beh | целевая аномалия задания «сопроводить учёного к аномалии» (Warfare — уровень и статус замера) | данные личного задания, но их читает логика сопровождаемого NPC (axr_beh, условия в логике NPC), т. е. на игре, где крутится NPC, — из pstor её актёра |
| Счётчики сцен по действиям игрока: `zat_b38_cop_abuse`, `pri_a28_friendly_hit`, `pas_b400_actor_sokolov_hit`, `pas_b400_actor_vano_hit`, `pas_b400_actor_zulus_hit`, `pas_b400_actor_wanderer_hit`, `lx8_documents` | pstor | xr_effects inc_counter/set_counter + xr_conditions counter_equal/greater, из `configs\scripts\zaton\zat_b38_stalker_cop.ltx`, `evac\pri_a28_*.ltx`, `underpass\pas_b400_general.ltx`, `labx8\lx8_*.ltx` | сколько раз игрок ударил копа (Затон b38) / союзников на эвакуации / спутников в тоннеле; найденные документы в X8 | по смыслу личное (сюжет), но пишется из логики NPC/рестрикторов — в pstor той игры, где эта логика исполняется (`hit_by_actor` там — свой актёр) |
| Счётчики сцен по событиям: `stalker_death`, `bandits_death`, `killer_death`, `pri_a28_heli_mono_cnt`, `jup_b205_death_count`, `jup_b47_bunker_guard_dead`, `jup_b6_anom_2_st_count`, `jup_b6_anom_2_count_1`…`_4`, `zat_a23_zombied_death`, `zat_a23_zombied_attack` (только читается), `zat_b14_reaction`, `zat_b57_terminated`, `mon_destroy_generator`, `mon_clear_control_room` | pstor | то же, из `zat_b5_*.ltx`, `zat_b7_*_b5.ltx`, `pri_a28_*.ltx`, `jup_b205_tushkano.ltx`, `jup_b47_*.ltx`, `jup_b6_stalker_anom_2.ltx`, `zat_a23_zombie.ltx`, `zat_b14_stalker_3.ltx`, `zat_b38_sleeper_bloodsuckers.ltx`, `warlab_monolith_gen*.ltx`, `mon_stalker_monolith_2x.ltx` | счётчики смертей/волн/таймеров в сюжетных сценах (перестрелка у торговца b5, волны Монолита на эвакуации, тушканы, охрана бункера, замер учёных, генераторы) | это состояние общей сцены (МИР), но хранится как личный сюжетный счётчик; меняется логикой NPC на игре хозяина NPC |
| `yan_ecolog_semenov_task_1_tissue_count` | pstor | xr_corpse_detection, task_status_functor, xr_effects pstor_reset | сколько образцов тканей собрано для Семёнова | счётчик личного задания, но растёт, когда **любой NPC** разделывает мутанта (логика NPC, на игре хозяина NPC), а не игрок |
| `jup_b200_tech_materials_brought_counter` | pstor | dialogs_jupiter (`jupiter_b200_tech_materials_relocate`), xr_effects inc_counter | сколько тех. материалов (провод, ацетон, текстолит, транзистор, конденсатор) сдано технику на Юпитере | технику сдаются уникальные сюжетные предметы мира; по правилу «инструменты техников — общие» скорее МИР, по правилу «сюжет личный» — ЛИЧНОЕ |
| `game_difficulty` | биндер | bind_stalker | сложность; при загрузке применяется консольной командой `g_game_difficulty` | одно значение в сохранении мира у всех; влияет на урон по актёру (личное) |
| `m_data.RepairItemList` | биндер | inventory_upgrades | вещи, оставленные у техника на отложенный ремонт/апгрейд: техник → id предмета → время | заявка игрока, но вещь — объект мира у техника |
| Личное отношение NPC к актёру (`force_set_goodwill(…, actor)`, relation registry по id 0) | движок | xr_effects (`=actor_enemy`, `=actor_neutral`, `=actor_friend`, `=set_speaker_as_enemy`, `=set_gulag_relation_actor`, `set_squad_goodwill_to_npc`), dialogs*, game_relations, sim_squad_scripted | отношение конкретного NPC к игроку | лежит в сохранении мира у NPC; ATTACK/KILL в коопе уже не пишутся (grudges), но сюжетные эффекты и диалоги по-прежнему пишут его в мир — одно на всех |
| Инфопоршни актёра (`has_alife_info`/`give_info`) | движок | везде | сюжетные флаги, тиры техников `<техник>_upgrade_tier_N`, `jup_b217_tech_instrument_N_brought`, `zat_b3_tech_instrument_N_brought`, режимы `story_mode_disabled`, `ironman_flag_off/died`, `awr_<npc>_access`, `tourist_achievement_delay` | смешаны личное и мир; нужна отдельная опись (в плане: сюжет — личное, инструменты техников — общее) |

## ЛИЧНОЕ

### Линии DRX (сюжет «встретить лидера → … → Исполнитель желаний»)

| Имя | Где | Модули | Что значит |
|---|---|---|---|
| `drx_sl_current_honcho` | pstor | xr_effects, dialogs, axr_task_manager | лидер, к которому сейчас ведёт линия |
| `drx_sl_current_task` | pstor | xr_effects, dialogs | id текущего задания линии |
| `drx_sl_current_task_number` | pstor | ui_mm_faction_select, xr_effects, dialogs | сколько заданий «встретить лидера» пройдено |
| `drx_sl_total_task_number` | pstor | ui_mm_faction_select, xr_effects, dialogs | сколько нужно пройти (случайно 8–12 на прохождение) до Исполнителя желаний |
| `drx_sl_start_task` | pstor | xr_effects, dialogs | стартовое задание линии (по нему тексты концовки) |
| `drx_sl_task_giver_<giver_id>` | pstor | dialogs, xr_effects | сколько незакрытых заданий линии выдал этот NPC/отряд (пока >0 — новых не даёт) |
| `drx_sl_hostage_giver_<giver_id>` | pstor | dialogs, xr_effects, dialogs_axr_companion | у этого заказчика активно задание со спасением заложника |
| `drx_sl_hostage_giver_needed` | pstor | dialogs, axr_companions | следующему заказчику линии нужен заложник |

### Задания

| Имя | Где | Модули | Что значит |
|---|---|---|---|
| `<task_id>` (таблица) | pstor | tasks_bounty, tasks_delivery, tasks_fate, tasks_assault, tasks_dominance, tasks_smart_control, tasks_agent_rescue, tasks_measure, tasks_stash, tasks_top_10, tasks_anomaly_scanner, xr_effects (prepare_reward_money/item, give_reward, remove_quest_item, unlock_smart, reward_random_money_by_dist), axr_companions, xr_meet, task_manager (стирает по завершении), axr_task_manager (чистит при смене уровня) | данные динамического задания: цель (`target_id`, `target_comm`), уровни, отряд/смарт (`squad_id`, `smart_id`), квестовые предметы и тайник, список топ-10, выбранная аномалия, `companion_squad_id`, заготовленная награда (`reward_money`, `reward_item`); ссылается на объекты мира, созданные под задание |
| `<task_id>_fetch` | pstor | tasks_fetch, xr_effects (pstor_set/pstor_reset, drx_sl_money_task_payment, reward_item_cost_mult_and_remove), task_status_functor, dialogs | что принести (секция предмета) — задания торговцев, медиков, техников (`*_mechanic_*_task_N_fetch`) и т. п.; у `drx_sl_*_cf_task_1_fetch` — цена перехода в группировку (деньги, `=pstor_set(…:12000)`) |
| `<task_id>_fetch_count` | pstor | tasks_fetch | сколько штук принести |
| `yan_ecolog_semenov_task_1_tissue_need` | pstor | `=pstor_set` из конфигов, xr_corpse_detection, task_status_functor | сколько образцов тканей нужно Семёнову (5) |
| `impending_doom_timer` | ctime | dialogs_lostzone, task_status_functor, xr_effects.erase_pstor_ctime | LTTZ: начало отсчёта на защиту Чудо-машины/Выжигателя (опоздал → `too_late`) |
| `yan_stalker_sakharov_psi_helmet_upgrade` | ctime | dialogs_yantar, task_status_functor | когда Сахаров принял заказ на апгрейд пси-шлема (ожидание готовности) |
| `base_defense_level` | pstor | xr_effects (setup_base_defense_fail_conditions), xr_conditions | уровень, где идёт задание «оборона базы» (ушёл — провал) |
| `warfare_escort_task_smart` | pstor | axr_companions, xr_effects, task_functor, dialogs_darkvalley/jupiter/marsh | Warfare: смарт, где появился сопровождаемый отряд |

### Техники и награды

| Имя | Где | Модули | Что значит |
|---|---|---|---|
| `toolkit_reward_count` | pstor | task_manager (+1 за каждое выполненное задание), treasure_manager | заданий выполнено с последней награды-инструментов; после порога в помеченном тайнике может появиться набор инструментов |
| `toolkit_reward_last` | pstor | treasure_manager | какой набор инструментов выдан последним (ротация по `stash_rare.reward_bonus`) |

### Сюжетные диалоги CoP

| Имя | Где | Модули | Что значит |
|---|---|---|---|
| `zat_b33_items` | pstor | dialogs_zaton | Затон b33: остаток «очков» на выбор награды (ставится 10, выбор тратит 2/4/8) |
| `jup_b25_frase` | pstor | dialogs_jupiter | Юпитер b25: счётчик реплик (только пишется) |

### Тело, вещи, внешность

| Имя | Где | Модули | Что значит |
|---|---|---|---|
| `drug_psy_blockade_expiration`, `drug_radioprotector_expiration`, `drug_antidot_expiration` (`<sec>_expiration`) | pstor | bind_stalker_ext, surge_manager | до какого времени действует защита препарата (пси / радиация / хим. ожог) при выбросе и пси-шторме |
| `itm_sleepbag_id` | pstor | item_tent | id стартового спального мешка (метка «уже выдан») |
| `character_icon` | биндер | bind_stalker, ui_mm_faction_select, gamemode_azazel, bind_stalker_ext | портрет, выбранный при создании (база для портрета от костюма) |
| `active_slot` | биндер | bind_stalker | активный слот оружия при загрузке |

### Прогресс, сохраняемый биндером актёра

| Имя | Где | Модули | Что значит |
|---|---|---|---|
| `m_data.game_statistics` | биндер | game_statistics, game_achievements, ui_pda_encyclopedia_tab, game_fast_travel | достижения (`actor_achievements`), статистика (`actor_statistics`: убийства, задания, тайники…), посещённые уровни и смарты (по ним быстрое перемещение), найденные артефакты, карты аномалий, `actual_rank/rept`; сюда же энциклопедия пишет `actor_articles` и `actor_notes` (заметки, рецепты) |
| `m_data.task_info`, `m_data.task_objects` | биндер | task_manager | все задания игрока и их стадии |

### Значения движка

| Имя | Где | Кто меняет | Что значит |
|---|---|---|---|
| ранг (`character_rank`) | движок | game_statistics.increment_rank (статистика, достижения, убийства), gamemode_azazel (`set_rank`), debug | ранг игрока |
| репутация (`character_reputation`) | движок | game_statistics.increment_reputation (в т. ч. разоблачение маскировки), dialogs_zaton, gamemode_azazel, debug | репутация |
| отношение группировок к игроку (`relation_registry.set/change_community_goodwill(f, AC_ID)`) | движок | xr_effects (`=inc_faction_goodwill_to_actor`, `=dec_faction_goodwill_to_actor`, `=inc_goodwill_by_tasker_comm` — награды заданий), ui_mm_faction_select (обнуление), game_relations.reset_goodwill (при объявлении войны между группировками), set_community_goodwill_for_faction (Azazel), set_level_faction_community | goodwill группировки к актёру; часть изменений запускают события мира (война → сброс) |
| деньги | движок | награды, торговля, диалоги, debt, Azazel | деньги |
| имя, профиль, иконка (`set_character_name`, `set_profile_name`, `set_character_icon`) | движок | ui_mm_faction_select, gamemode_azazel, bind_stalker_ext (портрет от костюма) | персонаж |
| группировка (`set_character_community("actor_<f>")`) | движок | ui_mm_faction_select, set_actor_true_community (смена фракции DRX/LTTZ), gameplay_disguise (маскировка), arszi_psy (зомбирование), gamemode_azazel | текущая группировка; истинная — в `m_data.default_faction` |
| состояние тела (`health`, `power`, `radiation`, `bleeding`, `psy_health`, `satiety` = голод) | движок | dialogs (лечение у медиков), ui_sleep_dialog, gamemode_azazel, warfare_faction_control, xr_effects | здоровье, выносливость, радиация, кровотечение, пси, сытость |

## ВРЕМЕННОЕ

| Имя | Где | Модули | Что значит |
|---|---|---|---|
| `heli_enemy_flag` | pstor | bind_heli, heli_combat, axr_radio_in_heli, axr_companions, bind_stalker, surge_manager, ui_sleep_dialog | игрок стрелял по вертолёту симуляции — вертолёты враждебны; сбрасывается при смене уровня, выбросе, сне |
| `grw_in_water` | pstor | gameplay_radioactive_water | игрок стоит в радиоактивной воде (обновляется каждым шагом) |
| `drx_sl_npc_stored_task_<npc_id>` + ctime `drx_sl_npc_stored_task_time_<npc_id>` | pstor + ctime | axr_task_manager, xr_effects | кеш «какое задание сейчас предлагает этот NPC» на 1,5 игровых часа; ключ на каждого NPC, с кем говорил, почти не чистится |
| `s_kill_count` | pstor | xr_motivator | счётчик убийств сталкера; актёр проходит через `IsStalker`, но значение никогда не растёт (баг) |
| `companion_<n>` | pstor | axr_companions | старый формат компаньонов, стирается при загрузке |
| `disable_debug_draw`, `debug_warpall`, `force_all_talk`, имена из `pstor_test` | pstor | debug_cmd_list, xr_meet, xrs_debug_tools | отладка |
| `disable_input_time`, `xr_sound` (состояние звуков актёра), `m_data.PsyAntenna` | биндер | bind_stalker, xr_sound, sr_psy_antenna | блокировка ввода, звуковые темы, эффект пси-поля |
| `last_detective_achievement_spawn_time`, `last_mutant_hunter_achievement_spawn_time` | биндер | bind_stalker | остатки CoP, нигде не используются |
| Мёртвые чтения: `<task_id>_target_id`, `<task_id>_id`, `mar_smart_terrain_doc_2_target_id` … `jup_b219_target_id`, `esc_m_trader_task_1_target_id`, `merc_pri_grifon_mlr_task_3_target_id`, `drx_sl_endgame_task`, `task_companion_slot_1`, `<p>_count` (kill_count_ge, в конфигах не используется), `<task_id>_count` (чистка в axr_task_manager, реальное имя `_fetch_count`) | pstor | task_functor, tasks_faction_control, tasks_fetch, dialogs_mlr, axr_task_manager, xr_conditions, xrs_debug_tools | читаются, но никто не пишет |
| Мёртвые счётчики CoP: `jup_b10_ufo_counter`, `zat_b30_days_cnt` (только обнуляется), `jup_a9_way_gates_counter`, `zat_a9_way_to_pripyat_counter`, `jup_b15_full_drunk_count`, `jup_b218_squad_members_count`, `jup_b221_played_main_theme`, `jup_b200_tech_materials_found_counter` | pstor | xr_effects, dialogs_zaton, dialogs_jupiter | функции не подключены в конфигах или никто не увеличивает |
| `actor_marked_by_zone_cnt`, `cc_npc`, `cc_vrb`, `cc_icc` | pstor | surge_manager (закомментировано), closecaption (`read_cc_ini` нигде не вызывается) | мёртвый код |

---

## Не на актёре, но из списка внимания (где лежит)

| Что | Где | Категория |
|---|---|---|
| Сон, жажда | `m_data.sleep` (actor_status_sleep), `m_data.drink` (actor_status_thirst); голод — `satiety` движка | ЛИЧНОЕ |
| Пси-здоровье, зомбирование | `m_data.psy_table` (arszi_psy) | ЛИЧНОЕ |
| Маскировка, истинная фракция | `m_data.disguise_state`, `disguise_highest_suspicion`, `disguise_npcs_memory`; `m_data.default_faction` | ЛИЧНОЕ |
| Компаньоны | `m_data.non_task_companions`, `companion_squads`, `companion_assigned_items`, `companion_states`, `m_data.paid_companions`; se-переменные на NPC `companion`, `companion_cannot_dismiss`, `companion_cannot_teleport` | ЛИЧНОЕ (этап 3) |
| Известные переходы | `m_data.mlr.routes_<level>`, `m_data.mlr.routes_faction` (txr_routes через `mlr_utils.save_var`) | ЛИЧНОЕ |
| Быстрое перемещение | `game_statistics.actor_visited_smarts` + метки `fast_travel` на карте (движок) | ЛИЧНОЕ |
| Рецепты, заметки, энциклопедия | `m_data.game_statistics.actor_notes` (рецепт = заметка `encyclopedia__notes_<sec>`), `actor_articles` | ЛИЧНОЕ |
| Контакты ПДА | `m_data.actor_contacts[npc_id]` (pda.script, при разговоре) | ЛИЧНОЕ |
| Метки на карте | движок (map locations) | ЛИЧНОЕ |
| Долги торговцам | `m_data.mlr.debt_<npc_id>` (dialogs_mlr) | ЛИЧНОЕ |
| Купленное перемирие | `m_data.bribe` (xr_bribe: группировка → перемирие с игроком) | ЛИЧНОЕ |
| Предложения fetch-заданий в диалоге | `m_data.tasks_fetch_ids` (tasks_fetch), `bounties_by_id`, `hostages_by_id` (axr_task_manager), `multifetch_data`, `jobs_guide` | ЛИЧНОЕ |
| Верстак техника (AWR) | `m_data.workshop` (bind_awr) + инфо `awr_<npc>_access` | СПОРНОЕ |
| Торговцы (пополнение) | `m_data.trade_manager` | МИР |
| Режимы игры | `m_data.enable_azazel_mode`, `enable_survival_mode`, `enable_conditions_mode`, `enable_timer_mode`, `enable_campfire_mode`, `enable_warfare_mode`, `m_data.ironman`; инфо `story_mode_disabled`, `ironman_flag_off`, `ironman_flag_died` | МИР (смерть в ironman — СПОРНОЕ) |
| Данные предметов | `m_data.se_object[<item_id>]`: `parts` (состояние деталей), `unpatched` (нашивки маскировки), `strapped_item`, `info` (прочитанные ПДА) | идут за предметом; если личный инвентарь пересоздаётся с новыми id, их надо переносить вместе с ним |

## Что удивило

1. `se_save_var` на id актёра нет ни одного: всё личное на актёре — это pstor (`m_data.game_object[0].pstor_all`) плюс `pstor_ctime` и поля биндера.
2. `drx_df_*` хранит не только пары группировок, но и пары с `actor_<f>`, то есть отношение мира к «группировке игрока». При игроках разных фракций это всё равно общий мир, но при смене фракции игрока важны именно эти ключи.
3. `surge_immuned` одного игрока (у мастера) отключает гибель NPC от выброса и не даёт выбросу закончиться — для всех.
4. Сюжетные счётчики сцен (`inc_counter` из логики NPC/рестрикторов) лежат в pstor актёра, но пишутся на той игре, где исполняется логика (NPC — у хозяина). Не-мастер, ударивший копа или союзника на эвакуации, может не попасть в счётчик вовсе: там проверяется `hit_by_actor` (`hit.who == actor:id()`, т. е. id 0 — свой актёр той игры).
5. `next_clean` (чистка инвентарей NPC) запускается из `actor_on_update` на каждой игре и делает `alife_release` — мировая операция, которую сейчас может выполнить и не-мастер.
6. Наборы инструментов приходят ещё и как награда: `toolkit_reward_count`/`toolkit_reward_last` подкладывают их в тайники после N заданий — ещё один источник наборов для правила «один комплект на уровень у техника».
7. `game_relations.reset_goodwill`: условие `character_community(db.actor) == faction_1 or ("actor_" .. faction_1)` всегда истинно, так что при объявлении войны между любыми двумя группировками (опция `war_goodwill_reset`) обнуляется goodwill игрока к faction_2. Событие мира меняет личное значение каждого игрока.
8. Личное отношение NPC к игроку (id 0) по-прежнему пишется в мир сюжетными эффектами (`=actor_enemy`, `=set_gulag_relation_actor` и др.), не только атакой/убийством.
9. `drx_sl_npc_stored_task_<npc_id>` (+ ctime) создаёт по ключу на каждого NPC, с которым игрок говорил, и почти не чистится — pstor мастера растёт.
10. Сложность (`game_difficulty`) хранится в состоянии биндера актёра и при загрузке применяется консолью — у всех сложность мастера.
