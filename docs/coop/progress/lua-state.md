# Lua-состояние сейва (`m_data`, файл .scoc): инвентаризация ключей верхнего уровня

Источник: vanilla Anomaly 1.5.3, `G:\stalker-test\anomaly-unpacked\scripts` (папка плоская, 414 скриптов). Найдены все записи в `m_data` в обработчиках `save_state`, включая обработчики с параметром `md`, `m`, `mdata` или `data`, а также прямые записи через `alife_storage_manager.get_state().<ключ>`. Всего **97 настоящих ключей верхнего уровня**: ЛИЧНОЕ 34, МИР 18, МИР+СИНХР 24, ВРЕМЕННОЕ 4, СПОРНОЕ 17. Ключи, которые vanilla на верхний уровень на самом деле не пишет, вынесены во вторую таблицу.

Что надо помнить при чтении:
- `m_data` пишет только тот, кто сохраняет мир, то есть мастер. Всё ЛИЧНОЕ у не-мастера сейчас просто берётся из сейва мастера.
- «id» означает id объекта A-Life. «task_id» означает id задания (строку).
- Метка «Смешанное» значит, что данные принадлежат одному игроку (обычно это данные задания), но ссылаются на мировые объекты.

## Основная таблица

| Ключ | Модуль(и) | Что хранит | Категория | Примечание (смешанное / кто меняет / проблема) |
|---|---|---|---|---|
| `actor_contacts` | pda (пишет), alife_storage_manager (init), ui_pda_contacts_tab | id NPC, с которыми актёр говорил (контакты PDA) | ЛИЧНОЕ | ссылки на мировые id NPC |
| `azazel_death` | gamemode_azazel, warfare_faction_control | флаг «актёр умер в режиме Azazel»; на следующей загрузке лечение, эффект, сообщение | ЛИЧНОЕ | одноразовый, снимается при загрузке |
| `bolt_first` | ui_mm_faction_select, gamemode_azazel, warfare_faction_control; читает itms_manager | секция болта, которую выдать актёру на первом апдейте (новая игра или перерождение) | ЛИЧНОЕ | одноразовый, спавнит предмет актёру |
| `bolt_slot` | itms_manager | секция болта в слоте актёра | ЛИЧНОЕ | при **каждой** загрузке спавнится актёру |
| `bolts` | itms_manager | число болтов по секциям в инвентаре актёра (болты не хранятся в A-Life) | ЛИЧНОЕ | при каждой загрузке спавнятся локальному актёру, поэтому не-мастер получает болты мастера |
| `bounties_by_id` | axr_task_manager (save), tasks_bounty (пишет) | task_id → id NPC-цели заказа | ЛИЧНОЕ | смешанное: задание личное, цель — мировой NPC |
| `bribe` | xr_bribe | купленные актёром перемирия: фракция → {start, duration, distance, last_warning} | ЛИЧНОЕ | |
| `companion_states` | axr_companions | режимы колеса компаньонов (бой, движение, скрытность, лут, дистанция) | ЛИЧНОЕ | настройка игрока |
| `default_faction` | ui_mm_faction_select, gameplay_disguise | родная фракция актёра (для маскировки и сброса) | ЛИЧНОЕ | |
| `detector_was_active` | actor_effects | был ли у актёра в руках детектор (после загрузки достаётся снова) | ЛИЧНОЕ | |
| `disguise_highest_suspicion` | gameplay_disguise | максимальное подозрение среди NPC {value, id NPC} | ЛИЧНОЕ | ссылка на id NPC |
| `disguise_npcs_memory` | gameplay_disguise | id NPC → что NPC запомнил о маскировке актёра | ЛИЧНОЕ | смешанное: память мировых NPC о конкретном игроке |
| `disguise_state` | gameplay_disguise | флаг «актёр замаскирован» | ЛИЧНОЕ | |
| `drink` | actor_status_thirst | жажда: время последнего питья и проверки | ЛИЧНОЕ | |
| `game_statistics` | game_statistics (через actor_binder), ui_pda_encyclopedia_tab | статистика и достижения, найденные артефакты и карты аномалий, посещённые уровни и смарты, статьи и заметки энциклопедии | ЛИЧНОЕ | |
| `jobs_guide` | tasks_guide | подработка «проводник»: guid, curr_guid (id отряда, целевой смарт и уровень, оплата), таймеры предложений, флаг newgame | ЛИЧНОЕ | смешанное: текущая работа ссылается на мировой отряд |
| `lttz_hb_last_stash_time` | dialogs_lostzone | сюжет ISG: время последнего «аварийного тайника» | ЛИЧНОЕ | сюжетный таймер; выдаёт игроку мировой тайник |
| `lttz_hb_next_stash_time` | dialogs_lostzone | сюжет ISG: через сколько часов следующий тайник | ЛИЧНОЕ | то же |
| `mlr` | mlr_utils (вызовы из dialogs_mlr, txr_routes) | `debt_<id NPC>` — долг актёра NPC; `routes_<имя>` — открытые маршруты и переходы; `routes_faction` | ЛИЧНОЕ | долги ссылаются на id NPC; маршруты нужны для «быстрого перехода только в известные места» |
| `multifetch_data` | tasks_multifetch | task_id → требуемые и дополнительные предметы | ЛИЧНОЕ | чистые данные задания |
| `psy_table` | arszi_psy | пси-здоровье актёра и стадия эффектов | ЛИЧНОЕ | |
| `PsyAntenna` | sr_psy_antenna (через actor_binder) | текущая интенсивность пси-излучения на актёре (хит, звук, постпроцесс) | ЛИЧНОЕ | пишется только в пси-зоне и при загрузке не удаляется, поэтому может оставаться устаревшим |
| `recover_mutant_data_mdata` | tasks_recover_mutant_data | task_id → id мутанта и id предмета, заспавненного на трупе | ЛИЧНОЕ | смешанное: задание создаёт мировой предмет |
| `RF_freq` | item_radio | частота, на которую настроен приёмник актёра | ЛИЧНОЕ | |
| `RF_targets` | item_radio (add_target из tasks_fate, xr_effects) | id объекта → {freq, dist}: квестовые радиомаяки (например, stitch_decoder) | ЛИЧНОЕ | смешанное: цели — мировые предметы, созданные заданием |
| `sleep` | actor_status_sleep | недосып: время последнего сна | ЛИЧНОЕ | |
| `start_wpn_ammo` | ui_mm_faction_select; читает itms_manager | id стартового оружия → секция патронов (новая игра) | ЛИЧНОЕ | одноразовый; ссылки на id предметов |
| `stealth_kills` | gameplay_silent_kills | {victims: id трупа → срок, пока увидевший труп NPC «свяжет» его с актёром} | ЛИЧНОЕ | кратковременное; виновником считается db.actor, то есть тот, кто загрузил сейв; проще очищать |
| `task_chimera_scan` | tasks_chimera_scan | task_id → смарт и уровень, id химеры, сканера, отряда | ЛИЧНОЕ | смешанное: задание спавнит мировой отряд и предмет |
| `task_info` | task_manager | множество активных task_id актёра | ЛИЧНОЕ | ядро заданий |
| `task_objects` | task_objects (CGeneralTask) | task_id → статус, стадия, таймауты (и откат повтора), заголовок, описание, current_target (id), task_giver_id (id NPC) | ЛИЧНОЕ | смешанное: цели и заказчики — мировые id |
| `tasks_fetch_ids` | tasks_fetch | id NPC → task_id → какой предмет и сколько он просит | ЛИЧНОЕ | смешанное: ключ — мировой NPC; таблица чистится при смене уровня |
| `tasks_rioc` | tasks_recover_item_on_corpse | task_id → настройки и стадия «забрать предмет с трупа» | ЛИЧНОЕ | смешанное: предмет и труп мировые |
| `tasks_veh_destroy` | tasks_veh_destroy | task_id → заспавненные машины (id, позиция, dead), текущая цель | ЛИЧНОЕ | смешанное: задание создаёт мировые машины и даёт им логику через logic_assign |
| `darkscape_phys_fix` | game_setup | одноразовый фикс: удалены физобъекты в поезде Тёмной долины | МИР | |
| `delayed_upgrades_fix` | inventory_upgrades | одноразовая миграция (сброс старого RepairItemList) | МИР | |
| `dialog_override` | xr_meet | id NPC → подменённый диалог | МИР | в vanilla override_dialog никто не вызывает, поэтому таблица всегда пуста |
| `duty_medic_fix` | game_setup | одноразовый фикс Бара (удалены 2 объекта) | МИР | |
| `enable_azazel_mode` | ui_mm_faction_select | режим Azazel (перерождение за другого сталкера) | МИР | настройка создания мира |
| `enable_campfire_mode` | ui_mm_faction_select | сохранение только у костра | МИР | настройка мира; в co-op сохраняет мастер |
| `enable_conditions_mode` | ui_mm_faction_select | режим «условий» (gamemode_agony) | МИР | настройка мира |
| `enable_survival_mode` | ui_mm_faction_select | режим выживания | МИР | настройка мира |
| `enable_timer_mode` | ui_mm_faction_select | минуты между разрешёнными сохранениями (gamemode_timer) | МИР | настройка мира |
| `enable_warfare_mode` | ui_mm_faction_select | режим Warfare | МИР | настройка мира |
| `freedom_medic_fix` | game_setup | одноразовый фикс базы Свободы | МИР | |
| `GAME_VERSION` | alife_storage_manager | версия игры, записавшей сейв (для миграций) | МИР | |
| `item_removal_done` | game_setup | флаг «мировые предметы (world_itm) уже расставлены» | МИР | одноразовая генерация при новой игре |
| `mine_kill` | txr_mines | одноразово удалены старые мины (mine, ied, ied_rpg) | МИР | |
| `new_game_relations` | game_relations | флаг «отношения фракций инициализированы» | МИР | сами отношения хранятся в pstor актёра (drx_df_*), не в m_data |
| `opened_routes` | ui_mm_faction_select | настройка мира: все маршруты открыты | МИР | |
| `stop_respawns` | ui_debug_launcher | отладка: смарты не респавнят отряды | МИР | только debug |
| `warfare_filled_start_position` | warfare | одноразовый флаг стартовой расстановки Warfare | МИР | |
| `artefact_respawn_levels` | bind_anomaly_zone | уровни, где при заходе актёра заспавнятся артефакты | МИР+СИНХР | ставится в конце выброса или пси-шторма; при заходе актёра на уровень снимается и спавнит артефакты |
| `campfire_states` | bind_campfire | id горящих костров (только онлайн-уровень сохраняющего) | МИР+СИНХР | игрок зажёг или потушил костёр |
| `device_condition` | item_device (legacy-чтение в bind_item) | id устройства → заряд (детекторы, фонарь, PDA) | МИР+СИНХР | меняется при использовании; свойство объекта, должно ехать вместе с предметом (Spawn_Write его не несёт) |
| `diff_eco` | ui_mm_faction_select, game_difficulties | экономика: тип, рестоки, деградация оружия, артефактов и рюкзаков, запчасти, лимит болтов, дроп брони | МИР+СИНХР | меняется в меню опций на любом клиенте |
| `dyn_anomalies` | bind_anomaly_field | уровень → id аномалии → включена или нет | МИР+СИНХР | перетасовывается после выброса (в co-op сейчас выключено) |
| `item_condition` | bind_item | id предмета → состояние (деградирующие предметы) | МИР+СИНХР | меняется при использовании; должно ехать с предметом |
| `item_remaining_uses` | bind_item | id предмета → остаток использований (многоразовая еда и медицина) | МИР+СИНХР | меняется при использовании или объединении; должно ехать с предметом |
| `items_by_npc` | death_manager | id NPC → id предметов, заспавненных для торговли (false — торговли нет) | МИР+СИНХР | меняется при торговле с NPC; при смене уровня **любым** игроком все эти предметы удаляются |
| `items_marked_for_removal` | release_item_manager | id выброшенного предмета → {имя, время}; через срок предмет удаляется | МИР+СИНХР | выброс или подбор предмета любым игроком; удаление делает authority |
| `logic_assign` | logic_enforcer (assign из tasks_pump_station_defense, tasks_veh_destroy) | id объекта → логика, которую выдать при выходе в онлайн | МИР+СИНХР | заполняется скриптами заданий любого игрока |
| `offline_task_squads` | sim_offline_combat (пишут tasks_bounty, assault, delivery, agent_rescue, chimera_scan, axr_companions) | id отрядов, исключённых из офлайн-боя | МИР+СИНХР | задания любого игрока, а офлайн-бой идёт у мастера |
| `player_created_stashes` | item_backpack | id тайника, созданного из рюкзака → секция рюкзака | МИР+СИНХР | создание или опустошение тайника; рюкзак возвращается тому, кто опустошил |
| `PsiStormManager` | psi_storm_manager | пси-шторм: started, finished, last_psi_storm_time, inited_time, task_given, game_time_factor, _delta | МИР+СИНХР | таймер идёт на каждом клиенте, нужен один источник; task_given касается UI актёра |
| `RF_stashes` | item_radio | уровень → id тайника → частота радиомаяка | МИР+СИНХР | генерится один раз; чистится, когда тайник найден (treasure_manager) |
| `spawned_sleepbags` | item_tent | id расстеленных спальников | МИР+СИНХР | игрок постелил или свернул |
| `spawned_tents` | item_tent | id поставленных палаток | МИР+СИНХР | игрок поставил или свернул |
| `SurgeManager` | surge_manager (через actor_binder) | выброс: started, finished, время последнего и начала, game_time_factor + UI-флаги (task_given, effector_set, second_message_given, ui_disabled, blowout_sound) | МИР+СИНХР | таймер на каждом клиенте; UI-флаги относятся к актёру |
| `trade_manager` | trade_manager | id торговца → конфиг, текущие условия buy/sell (выбраны по condlist от db.actor), время последнего рестока | МИР+СИНХР | рестоки при открытии торговли; условия пересчитываются на каждой торговле |
| `trader_buy_condition_override` | ui_options; читает trade_manager | опция «минимальное состояние при скупке» | МИР+СИНХР | меню опций на любом клиенте |
| `treasure_manager` | treasure_manager | {caches_count, caches: id ящика → false / строка содержимого (тайник выдан) / true (заспавнен, ещё не взят)} | МИР+СИНХР | выдача тайника (маркер ставится у получателя), открытие, взятие |
| `weather_manager` | level_weathers (через actor_binder) | погода: цикл, пресет, хранилище по уровням, время смены, текущий WFX | МИР+СИНХР | меняется с ходом времени на каждом клиенте |
| `workshop` | bind_awr | верстаки механиков: тиски → {механик, …, 'dead'}; если механик мёртв, доступ свободный | МИР+СИНХР | смерть механика |
| `world_itm_num` | game_setup | место → случайный размер пачки, число использований или состояние мирового предмета | МИР+СИНХР | подбор предмета |
| `world_itm_on` | game_setup | id мирового предмета → имя места | МИР+СИНХР | подбор предмета любым игроком (+ маркеры на PDA) |
| `dyn_anomalies_dbg` | bind_anomaly_field | отладочная копия, пишется только при enable_debug | ВРЕМЕННОЕ | |
| `m_mine_table` | item_mine | {priming, turn_hostile, recently_placed} старых мин | ВРЕМЕННОЕ | скрипт помечен UNUSED, а его предметы удаляет txr_mines; будь он жив, это было бы ЛИЧНОЕ |
| `r2_drops_control` | level_environment | параметры капель дождя {сила, скорость} | ВРЕМЕННОЕ | производное от погоды |
| `xr_sound` | xr_motivator → xr_sound.npc_save_state(id, m_data) | состояние тем звуков, перезаписывается каждым онлайн-NPC | ВРЕМЕННОЕ | мусор из-за бага vanilla: никто не читает (читается game_object[id].xr_sound) |
| `bounty_squad` | sim_squad_bounty | {last_spawn_time, active_squads: id отрядов-охотников} | СПОРНОЕ | охотников вызывают ранг и репутация конкретного игрока, но это мировые отряды с целью «актёр», то есть id 0 на каждом клиенте |
| `companion_assigned_items` | axr_companions | id NPC-компаньона → id выданных ему предметов | СПОРНОЕ | компаньоны принадлежат игроку, но это мировые NPC и предметы (этап 3) |
| `companion_squads` | axr_companions | id отрядов-компаньонов (объекты подхватываются при регистрации) | СПОРНОЕ | свои у каждого игрока, но мировые отряды с флагами companion в se_object; на чужом клиенте пойдут за его актёром |
| `defense_task_data` | tasks_defense | оборона Барьера: {barrier_defense_monolith, barrier_defense_zombie, allow_surge} | СПОРНОЕ | задание одного игрока, но allow_surge=false запрещает выброс во всём мире |
| `diff_game` | ui_mm_faction_select, game_difficulties | сложность: иммунитеты, урон, разброс, выносливость, вес, жажда и сон, радиация днём | СПОРНОЕ | выбирается для мира, но все факторы действуют только на актёра и меняются в опциях любым игроком |
| `game_object` | alife_storage_manager | контейнер по id **онлайн**-объектов: name, xr_logic, pstor_all, pstor_ctime, xr_sound; запись стирается при уходе в офлайн | СПОРНОЕ | записи NPC — мир; запись 0 (actor_binder, pstor и звук актёра) — личное, её разбирает другой агент |
| `guaranteed_drops_data` | guaranteed_loot | {counters: секция → счётчик гарантированного дропа, used_npc: id обысканных трупов} | СПОРНОЕ | счётчики — личная «удача», used_npc — мировое состояние трупов; дроп спавнится в мировой труп |
| `hostages_by_id` | axr_task_manager (пишут axr_companions, dialogs) | id NPC-заложника → id смарта | СПОРНОЕ | мировые NPC, созданные заданием одного игрока и записанные ему в компаньоны; освободить может любой |
| `ironman` | ui_mm_faction_select, gamemode_ironman | {uuid, death_limit, death_count, life_feature, life_cycle, granted_lives, sleep_hrs} | СПОРНОЕ | режим — настройка мира, счётчики жизней — личные; при смерти правит и удаляет локальные .scoc с тем же uuid |
| `lttz_hb_leave_time` | dialogs_lostzone | сюжет ISG: когда отряды ISG уходят с Юпитера | СПОРНОЕ | сюжетный таймер одного игрока, но по нему удаляются мировые отряды ISG |
| `new_mines` | txr_mines | id установленной мины → {exp_time, mode, witnesses, active} | СПОРНОЕ | мины — мировые объекты, но урон и свидетели засчитываются db.actor, то есть тому, у кого мина сработала |
| `non_task_companions` | axr_companions | id NPC-компаньонов, нанятых не по заданию | СПОРНОЕ | то же, что companion_squads |
| `paid_companions` | txr_paid_companions | id отряда → {members_id, join_time, guard_period}: эскорт, нанятый за деньги | СПОРНОЕ | наём одного игрока, но отряд мировой |
| `pump_station_def_csky` | tasks_pump_station_defense | оборона насосной станции ЧН: атакующие и охрана (id), замена командира, точки спавна, награда, триггер | СПОРНОЕ | задание одного игрока меняет логику существующих мировых NPC и спавнит до 50 атакующих |
| `RepairItemList` | inventory_upgrades | механик → id предмета → {время сдачи, срок}: предметы, сданные на ремонт и лежащие у механика | СПОРНОЕ | предметы сдавшего игрока лежат у мирового механика, забрать их может любой; флаг <механик>_is_repairing стоит на актёре |
| `se_object` | alife_storage_manager (+ se_save_var в _g и многие модули) | контейнер переменных по id серверных объектов, живёт и в офлайне | СПОРНОЕ | в основном мир (parts, unpatched, info PDA…), но запись 0 и часть полей NPC про актёра личные (last_seen_level/time, companion*, icon_name/visual мимика Azazel); актёра разбирает другой агент |
| `warfare` | warfare | Warfare: владельцы смартов, отряды, вторжения, патрули, faction_information, influence_levels + actor_influence_points, manual_control, manual_point, player_heli | СПОРНОЕ | только в режиме Warfare; мировое состояние смешано с личными очками влияния, вертолётом и ручным управлением |

## Ключи, которые в vanilla 1.5.3 на верхний уровень `m_data` не пишутся

| Ключ | Почему его нет |
|---|---|
| `comp_mule` | legacy (до 1.5): при смене версии переносится в companion_assigned_items и удаляется (alife_storage_manager.on_before_load_state) |
| `disguise_default_comm` | запись и чтение закомментированы (gameplay_disguise:962, 970) |
| `disguise_unpatched_outfit` | legacy: переносится в se_object[id].unpatched и удаляется |
| `event_queue` | вызовы ProcessEventQueueState закомментированы (alife_storage_manager:188, 268) |
| `icon_name`, `visual` | пишутся в se_object[id мимика] (gamemode_azazel:271, warfare_faction_control:783), не в верхний уровень |
| `item_parts_state` | legacy: переносится в se_object[id].parts и удаляется |
| `last_seen_time` (и `last_seen_level`) | поля se_object[id NPC] через se_save_var (pda:438-439): где и когда актёр последний раз видел NPC; по смыслу личное, но лежит внутри se_object |
| `ltx` | не ключ m_data: `smart.ltx` — поле смарта (gulag_general:1332) |
| `npc_pda` | legacy: переносится в se_object[id].info и удаляется |
| `objects_to_release` | только читается (safe_release_manager:53), никто не пишет |
| `offline_power` | запись закомментирована (sim_offline_combat:751) |
| `pstor_ctime` | на верхнем уровне встречается только в баг-строке bind_trader:194 (`m_data.pstor_ctime = nil`, где m_data не определён); настоящее место — game_object[id].pstor_ctime |
| `sim_squad_scripted` | sim_squad_scripted:save_state лежит внутри `--[[ ]]` и не регистрируется; состояние отрядов в бинарном .scop (STATE_Write) |
| `smart_terrains` | se_smart_terrain:save_state тоже внутри `--[[ ]]`; состояние смартов в бинарном .scop (STATE_Write) |
