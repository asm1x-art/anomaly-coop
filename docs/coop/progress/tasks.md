# Опись: задания и сюжетные флаги Anomaly 1.5.3 (для личного прогресса в коопе)

Только чтение, ничего не менялось. Пути ниже:
- `scripts/…`, `configs/…` — от `G:\stalker-test\anomaly-unpacked\` (файлы в cp1251);
- `xrGame/…` — от `G:\stalker-test\xray-monolith\src\`.

Числа посчитаны по конфигам (разбор всех `tm_*.ltx` и `task_manager.ltx`) и grep по скриптам; там, где сказано «≈», это порядок величины.

## Главное коротко

1. **Задание живёт в трёх местах сразу**: движковый `CGameTask` в реестре актёра (id 0) в `.sav`, Lua-объект `CGeneralTask` в `m_data.task_info/task_objects` в `.scoc`, и «данные задания» в личных переменных актёра (`load_var(db.actor, task_id)` и т.п.) плюс таблицы модулей `tasks_*.script`, которые ключуются **по task_id, а не по игроку** и лежат в общем `.scoc` мира.
2. **task_id — это имя секции LTX** (`esc_m_trader_task_1`, `simulation_task_47`), один на актёра. Два игрока с одним id — норма (у каждого свой task_manager), но всё, что ключуется по task_id в мире (цели, тайники, заспавненные отряды со `story_id`, флаги «уже заспавнено»), столкнётся.
3. **Цель выбирается случайно на клиенте** в момент, когда NPC рассказывает о работе (`on_job_descr`, `fetch_func`), и кэш этого выбора у каждого клиента свой. Два игрока, взявшие «одно и то же» задание у одного NPC, сейчас почти всегда получат **разные** цели. Для правила «одно задание на нескольких» выбор цели надо сделать общим для мира (по паре заказчик + task_id).
4. **Ни одно задание не проверяет, кто убил цель.** Устранение засчитывается при любой смерти цели (`axr_task_manager.script:104-109`: «complete task anyway instead of failing»), зачистка — когда на точке нет врагов (умерли *или ушли*). Убийцу знает только тот клиент, где произошла смерть (`who`/`killer` в колбэках). Для правил нужен свой учёт убийцы.
5. **Мягкая отмена в игре есть**: `set_task_cancelled` (`task_manager.script:97-102`) запускает только `on_cancel`, а не `on_fail`, так что штрафа из `on_fail` не будет. Но: в движке задание станет «провалено» (удалить задание из движка нельзя), приходит новость «Задание провалено», `on_cancel` есть у 19 заданий: у 1 в нём прямо штраф, у 4 — уборка мира (`remove_special_task_squad`), у остальных — личная уборка (`pstor_reset`, снятие заказчика, изъятие посылки). А вместе с `on_fail` пропадает и уборка личных данных; у сюжетных DRX-заданий без `on_fail` цепочка просто встанет.
6. **Инфопоршень в движке monolith — это голая строка.** Загрузчик XML закомментирован целиком (`xrGame/InfoPortion.cpp:5-120`), теги `<dialog>`/`<disable>`/`<article>` не работают. Выдача флага вызывает только Lua-колбэк `actor_on_info_callback` (3 слушателя; один из них сам выдаёт сюжетные задания Warlab) и обновление окна диалога. Всё «мировое» происходит **позже**: логика NPC и рестрикторов, задания, функторы статуса и спаун смартов **опрашивают** флаги и реагируют. Поэтому «выставить флаг без побочных эффектов» = записать его так, чтобы опрашивающая логика не сработала второй раз, а не просто «не вызвать колбэк».
7. **Логика мира читает флаги того актёра, на чьём клиенте она идёт** (`xr_logic.script:391-401`, `_g.script:2533-2535`). В коопе логику уровня гоняет хозяин уровня, и она будет видеть **его** личные флаги. Нужен отдельный «мировой» набор флагов (факты о мире: отряд мёртв, сцена отыграна, NPC ушёл) или правило объединения.
8. Флаги-«факты о мире» уже раздаются как флаги актёра: 148 `on_death` у отрядов (`squad_descr*.ltx`) и ≈160 файлов логики со схемой `[death] on_info = %+…_dead%`. Это ≈300 флагов вида `*_squad_dead`/`*_dead`/`*_death`, на них завязаны и задания (11 несюжетных заданий со ступенями lostzone и сюжет). Их надо делать общими, иначе задание у игрока не увидит смерть цели.

---

## 1. Где живёт состояние заданий

### 1.1. Движок: `CGameTaskManager` и реестры актёра

Все личные реестры движка лежат в `CALifeRegistryContainer` (`xrGame/alife_registry_container.h:31-40`) и пишутся в `.sav` мира вместе с A-Life:

| Реестр | Ключ | Что внутри | Для коопа |
|---|---|---|---|
| `m_game_tasks` (`CGameTaskRegistry`, `GameTaskDefs.h:47-58`) | `0` (актёр, `GametaskManager.cpp:50`) | вектор `SGameTaskKey{task_id, CGameTask*}` — **все** задания, включая выполненные/проваленные (история ПДА), плюс `g_active_task_id` (`GameTaskDefs.h:52,58`) | личное |
| `m_info_portions` (`KNOWN_INFO_VECTOR`) | id владельца (актёр = 0) | список строк-флагов | личное + «мировые факты» (см. §4) |
| `m_map_locations` (`CMapLocationRegistry`) | один общий список, `init(1)` (`map_manager.cpp:86-115`) | метки на карте, в т.ч. метки заданий (`SetSerializable(true)`, `m_owner_task_id`, `GameTask.cpp:94-106`), метки игрока, `red_location` на отрядах | смешанное: метки заданий и игрока — личные |
| `m_game_news` | 0 | лента новостей ПДА | личное |
| `m_actor_statistics` | 0 | статистика | личное |

Что хранит `CGameTask` (`GameTask.cpp:212-229`): состояние (`eTaskStateInProgress/Completed/Fail`), тип (storyline/additional), время получения/окончания/таймер, заголовок, описание, имена Lua-функторов завершения и провала (`task_manager.task_complete`/`task_fail`, добавляются в `task_objects.script:142-143`), иконку, метку на карте (`m_map_location`, `m_map_object_id`), приоритет.

Как движок ведёт задание:
- Выдача: `db.actor:give_task(t, …)` → `CGameTaskManager::GiveGameTaskToActor` (`GametaskManager.cpp:94-132`). **Дубликат id в процессе отклоняется** (`:97-101`, `Msg("! task [%s] already inprocess")`). Затем `OnArrived` создаёт метку, а `ChangeStateCallback` вызывает колбэк актёра `task_state`.
- Каждый кадр `UpdateTasks` (`:161-206`) → `CGameTask::UpdateState` (`GameTask.cpp:142-170`): сначала проверки провала (инфо, функторы), потом завершения. В Anomaly функторы — это `task_manager.task_fail/task_complete` (`task_manager.script:122-168`), а они смотрят только на `last_check_task`/`forced_status` Lua-объекта.
- При смене состояния `SetTaskState` (`GameTask.cpp:40-60`) удаляет метку, выдаёт `m_infos_on_*` (в Anomaly не используются) и зовёт колбэк → `bind_stalker_ext.actor_on_task_callback` (`scripts/bind_stalker_ext.script:321-330`) → новость «Новое/Выполнено» и `task_manager.task_callback`.
- **API удаления задания нет**: вектор только растёт, есть лишь смена состояния (`SetGameTaskState`, `script_game_object_inventory_owner.cpp:1107-1111`). Повторная выдача того же id после завершения добавляет новую запись в историю.

### 1.2. Lua: `task_manager` / `CGeneralTask`

Жизненный цикл (общий для всех типов):
1. Диалог «Есть работа?» строит список (`axr_task_manager.generate_available_tasks`, `scripts/axr_task_manager.script:838-939`). Уже на этом шаге, **ещё до согласия игрока**, исполняются `on_job_descr` и `fetch_func` (`scripts/dialogs.script:653-664`), и именно там выбирается цель (`setup_bounty_task`, `setup_assault_task`, `on_init_delivery_task`, …).
2. Согласие → `CRandomTask:give_task(task_id, giver_id)` (`task_manager.script:50-83`): создаётся `CGeneralTask` (`task_objects.script:34-119`; у сюжетных — затухающий текст на экране), `give_task()` (`:130-171`) исполняет `on_init`, выдаёт движковый `CGameTask` и метку. `giver_id` — id NPC или id его отряда (`axr_task_manager.script:792-794`, `dialogs.script:573`).
3. `CRandomTask:update` (`task_manager.script:104-119`) → `check_task` (`task_objects.script:173-248`) раз в 0,5-1 с: пересчитывает заголовок, описание и цель через функторы, проходит `condlist_N` (`complete/fail/reversed`), потом `status_functor`. Функтор статуса двигает `tsk.stage` или возвращает `"complete"/"fail"`.
4. `stage == stage_complete` значит «готово к сдаче». Сдача у заказчика: диалог `actor_has_finished_task` → `set_finished_task_complete` (`axr_task_manager.script:769-778`, `dialogs.script:694-725`) ставит `forced_status="complete"`.
5. Движок видит `task_complete`=true → колбэк → `task_callback` (`task_manager.script:183-248`): `on_complete` (здесь почти всегда **награда**: `reward_money`, `reward_random_money`, `reward_stash`, `complete_task_inc_goodwill`, `fetch_reward_and_remove`…), затем `give_reward()` (`task_objects.script:251-279`; работает только в диалоге, у 2 заданий), `save_var(db.actor, id, nil)`, статистика, счётчик `toolkit_reward_count`. Если у задания есть `repeat_timeout`, запись остаётся в `task_info` с `timeout` (NPC не предложит его снова до истечения, `:238-246`, `:109-116`), иначе удаляется.

Сохранение (Anomaly работает через marshal, `USE_MARSHAL`, `_g.script:46`): `bind_stalker.script:437/474` → `task_manager.save_state/load_state` (`task_manager.script:255-290`) → `m_data.task_info[id]=true`, `m_data.task_objects[id] = {status, timeout, inited_time, current_title, current_descr, current_target, stage, task_giver_id}` (`task_objects.script:418-460`). Пакетный путь `CRandomTask:save/load` (`task_manager.script:10-46`) при marshal не работает.

### 1.3. Lua: состояние модулей `tasks_*` и связанных скриптов

| Где | Ключ | Что хранит | Сохраняется | Что это |
|---|---|---|---|---|
| `axr_task_manager.bounties_by_id` (`axr_task_manager.script:14,144-159`) | task_id | id цели устранения | `m_data.bounties_by_id` | личное (цель игрока), но цель — объект мира |
| `axr_task_manager.hostages_by_id` | id NPC-заложника | id смарта | `m_data.hostages_by_id` | мир |
| `available_tasks/ongoing_tasks/finished_tasks` (`:15-17`), `skipped_tasks` (`:201`) | id NPC / task_id | списки для диалога | нет | личное, временное |
| `CFG_CACHE` (`:182-198`) | task_id | кэш полей LTX | нет | статика |
| `tasks_fetch.DIALOG_ID` (`tasks_fetch.script:662-668`) | id NPC → var | какой предмет NPC просит | `m_data.tasks_fetch_ids`, чистится при смене уровня | личное |
| `tasks_multifetch._M` (`tasks_multifetch.script:52-57`) | task_id | список предметов | `m_data.multifetch_data` | личное |
| `tasks_recover_item_on_corpse.M` (`tasks_recover_item_on_corpse.script:8-14`) | task_id | id трупа, предмета, мутантов, настройки | `m_data.tasks_rioc` | мир (объекты) + личное (стадия) |
| `tasks_recover_mutant_data.M` (`:4-9`) | task_id | id мутанта, id прибора | `m.recover_mutant_data_mdata` | мир + личное |
| `tasks_veh_destroy.DATA` (`:35-40`) | task_id | id заспавненных БТР, «мёртв» | `md.tasks_veh_destroy` | мир |
| `tasks_chimera_scan._m` (`:22-28`) | task_id | смарт, id химеры, id сканера, время скана | `m.task_chimera_scan` | мир + личное |
| `tasks_defense.MDATA` (`:54-61`) | id задания обороны | отряды нападающих, сколько осталось, заказчик, запрет выброса | `mdata.defense_task_data` | мир (событие) |
| `tasks_pump_station_defense.M` (`:22-26`) | — | командир, охрана, тайник, нападающие | `m_data.pump_station_def_csky` | мир |
| `tasks_guide` (`:194-205`, `:631-638`) | — | проводник (отдельная система, не task_manager) | `m_data.jobs_guide` | личное |
| кэши без сохранения: `bounty_cache` (`tasks_bounty.script:108-164`), `cache_assault`, `cache_assault_func` (`tasks_assault.script`), `delivery_cache[var][giver]` (`tasks_delivery.script:45,67-119`), `fate_cache` (`tasks_fate.script:112-146`), `cache` в measure/spy/smart_control/dominance, `cache_stash` (`tasks_stash.script:32-50`), `is_dead_spawned` (fate) | task_id (+giver) | выбранная цель | нет (на клиенте) | источник «разных целей у разных игроков» |
| `sim_offline_combat.task_squads[squad_id]` | id отряда | отряд не участвует в офлайн-бою | нет | мир |
| `db.storage[npc].dyn_quest_rand` (`axr_task_manager.script:853-937`) | NPC | какую работу NPC предлагает сейчас | нет | личное (клиент) |

### 1.4. Личные переменные актёра (`db.storage[0].pstor` → `m_data.game_object[0].pstor_all`, `alife_storage_manager.script:174-183`)

Всё ниже пишется через `save_var/load_var(db.actor, …)`:
- данные задания под именем `task_id`: таблица цели у bounty, assault, delivery, fate, measure, stash, spy, top_10 (`{target_id, smart_id, squad_id, lvl_target, item_1_id, …}`), имя аномалии у сканера;
- fetch: `<task_id>_fetch` (секция предмета), `<task_id>_fetch_count` (`tasks_fetch.script:314-330, 489-530, 598-640`);
- DRX: `drx_sl_current_honcho`, `drx_sl_current_task`, `drx_sl_current_task_number`, `drx_sl_total_task_number` (8-12, случайно при старте, `xr_effects.script:835`, `ui_mm_faction_select.script:256`), `drx_sl_start_task`, `drx_sl_endgame_task`;
- предложения NPC: `drx_sl_npc_stored_task_<npc_id>`, `drx_sl_npc_stored_task_time_<npc_id>` (`axr_task_manager.script:365-388, 464-465`);
- счётчики заказчиков: `drx_sl_task_giver_<giver_id>` (`dialogs.script:574-575`, `xr_effects.script:1175-1205`), `drx_sl_hostage_giver_<id>`;
- прочее: `impending_doom_timer` (ctime, lostzone), `<id>_tissue_count/need`, `toolkit_reward_count` (`task_manager.script:233-235`), `task_target_anomaly*`, `warfare_escort_task_smart`;
- сюда же пишут фракционные войны `drx_df_*` — по плану это мир.

Уборка: при смене уровня `axr_task_manager.on_before_level_changing` (`:161-179`) стирает переменные заданий, которых нет в `task_info`.

### 1.5. Что сохранять/восстанавливать на игрока

Чтобы список заданий стал личным, в «карточку» игрока нужно класть и при входе подменять:

**Движок (блоб на C++, сериализаторы уже есть: `SGameTaskKey::save/load`, `GameTask.cpp:330-342`):**
1. `m_game_tasks[0]` целиком с историей и `g_active_task_id`;
2. `m_info_portions[0]` (личная часть, §4);
3. `m_game_news[0]`;
4. метки карты с `m_owner_task_id` и личные метки игрока; метки на объектах мира, которые ставит Lua (`level.map_add_object_spot(target, "ui_*_task_blink")`, `task_objects.script:154-156, 221-223`; `red_location` в assault/smart_control), — либо в личный набор, либо пересоздавать после загрузки.

Пересоздавать задания через Lua (`CGameTask()` + `give_task`) хуже: колбэк `task_state` выдаст новость «Новое задание», а историю выполненных так не вернуть. Лучше импортировать реестр в C++ без колбэков. Lua-функторы задания пересоздаются сами (`CommitScriptHelperContents` в `load_task`, `GameTask.cpp:248-258`).

**Lua (`.scoc`):**
5. `m_data.task_info` + `m_data.task_objects`;
6. `pstor_all`/`pstor_ctime` актёра (без мировых `drx_df_*`);
7. `bounties_by_id`, `tasks_fetch_ids`, `multifetch_data`, `jobs_guide`, личные стадии из `tasks_rioc`/`recover_mutant_data`/`chimera_scan` (их нужно разделить: id объектов — мир, стадия — игрок);
8. статистика (`game_statistics`: tasks_completed/failed/cancelled).

Порядок при входе: движковый реестр и флаги должны встать **до** первого `CRandomTask:update` (иначе `check_task` у загруженного Lua-задания не найдёт `self.t`, `task_objects.script:184-188`, и задание повиснет, пока не истечёт таймаут).

### 1.6. Что из заданий — объекты мира (должно оставаться общим)

- Цели, которые **уже существуют** в мире и только помечаются: NPC для bounty, top_10, delivery (получатель); отряды на смарте для assault/dominance/spy; аномалии для measure/scanner; мутант для recover_mutant_data. Пометки — тоже мир: `squad.stay_time`, `force_online`, `sim_offline_combat.task_squads`, `smart.locked`, `smart.faction`. После зачистки assault/smart_control **присваивают смарт фракции игрока** (`tasks_assault.script:338-342`).
- То, что задание **создаёт**:
  - отряды через `create_squad` (`on_init`/`on_complete`/функторы; у сюжетных 103 вызова только в `on_*`);
  - спец-отряды со `story_id` (`squad_descr_lostzone.ltx:8-13, 50-56`);
  - компаньоны (`axr_companions.script:741-823`: hostage, ecolog/bandit companion);
  - мёртвый отряд с предметом (fate, `tasks_fate.script:66-104`);
  - труп + предмет + мутанты (RIOC, `tasks_recover_item_on_corpse.script:162-207`);
  - прибор на трупе мутанта (`tasks_recover_mutant_data.script:12-19`);
  - БТР (`tasks_veh_destroy.script:58-105`);
  - химера + сканер (`tasks_chimera_scan.script:191-206`);
  - волны нападающих (`tasks_defense.script:484-541`, pump station);
  - тайник с сюжетным предметом `drx_sl_quest_item_N` (`tasks_stash.script:33-80, 135-146`);
  - предметы прямо в инвентарь актёра: посылка delivery `tasks_delivery.script:198-209`, прибор measure `tasks_measure.script:362-374`, сканер химеры `spawn_on_id(ITEM, 0)`;
  - награда `reward_stash` → новый тайник `treasure_manager.create_random_stash`.
- Уборка мира в `on_complete/on_fail/on_cancel`: `remove_special_task_squad`, `veh_destroy_unset` (выпускает БТР), `recover_mutant_data_unset`, `cleanup_recover_item_on_corpse`, `forget_dead_npcs`, `unlock_smart`, `pump_station_defense_task_cleanup`, `barrier_defense_clean_flags`.

---

## 2. Типы заданий

Всего ≈642 задания: 601 в `tm_*.ltx` (611 секций минус 10 шаблонов RIOC) + 41 в `task_manager.ltx`. Распределение по `status_functor`: fetch 206, без функтора (диалоги/флаги) 167, assault 80, bounty 42, lostzone-ступени 34, тайник 21, DRX-предмет 10, DRX-деньги 10, заложник 9, агент 5, замер 4, доставка 3, судьба 3, по 1-2 у остальных.

Общее для всех: «засчитано» = `stage` дошёл до `stage_complete`. Награда почти всегда выдаётся **при сдаче** заказчику (`on_complete` после `set_finished_task_complete`). Исключения: вертолёт (сразу при смерти), доставка (сдаётся получателю, не заказчику), оборона барьера и топ-10 (свой диалог), сюжетные (по флагу).

### 2.1. Таблица

| # | Тип | Код (функторы / скрипт) | Заданий | Как определяется «выполнено» | Награда | Что создаёт в мире | Предлагаемый зачёт в коопе |
|---|---|---|---|---|---|---|---|
| 1 | Устранение NPC (bounty) | `bounty_task` / `general_bounty_task`, `tasks_bounty.script:55-245`; `axr_task_manager.script:92-114` | 42 (8 сюжетных DRX) | цель мертва → stage 1 (`:239-241`), **любой убийца**: и в колбэке смерти (`:104-109`), и в функторе | при сдаче (`on_complete`) | ничего; цель — существующий sim-сталкер, выбран на клиенте в `on_job_descr` (`:55-204`), его отряд исключён из офлайн-боя (`:181`) | **по правилу**: в момент убийства stage 1 ставится только убийце (`who:id()==0` у него на клиенте; убийство компаньоном = владельцу, как в ваниле `:97`), награда при его сдаче. У остальных держателей той же цели — «опоздал» + мягкая отмена. Убил не игрок (NPC, мутант, аномалия, офлайн-бой) → мягкая отмена у всех |
| 2 | Топ-10 (Снитч) | `top_10_task_*`, `tasks_top_10.script:9-115` | 1 | цели по очереди; любая смерть сдвигает stage (`:37-50`); stage 10 → сдача диалогом (`:113-115`) | при сдаче | ничего (существующие NPC из рейтинга) | правило не покрывает. Предложение: каждая цель — отдельное «устранение»: засчитывается убийце; цель, убитую не им, вычёркивать без зачёта; сдача по исчерпании списка, награда пропорционально своим целям (или «нужна хотя бы одна своя») |
| 3 | Зачистка точки (assault) | `assault_task_*`, `tasks_assault.script:79-346` | 80 (23 сюжетных) | на смарте нет отрядов врага, которые «стоят» на нём (`:327-345`): **умерли или ушли**; цель выбрана в `validate_assault_task` (кэш клиента) | при сдаче | ничего не спавнит; держит отряды (`stay_time`, `force_online`, `:143-145`); по завершении `smart.faction = фракция игрока` (`:338-342`) | правило «отряд — кто добил последнего»: вести по смарту журнал смертей врагов с убийцей; когда функтор увидел «пусто», засчитать игроку, убившему последнего врага на этом смарте (окно, напр., 60 с). Последний убит не игроком или враги ушли → мягкая отмена у всех. Смену фракции смарта делать один раз, у засчитанного |
| 4 | Господство на уровне | `dominance_task_*`, `tasks_dominance.script:155-246` | 2 (сюжетные DRX) | все отряды фракций на уровне ушли/умерли | при сдаче | ничего | как assault (последний убитый на уровне) |
| 5 | Контроль смартов | `smart_control_*`, `tasks_smart_control.script` | 0 (не используется в ванили) | — | — | — | как assault |
| 6 | Очистить уровень от мутантов | `mutants_in_map*`, `tasks_clear_map.script:30-93` | 1 (`cit_killers_merc_barman_mlr_task_5`) | condlist: на уровне нет мутантов → stage 1 | при сдаче | ничего | как assault (кто убил последнего мутанта) |
| 7 | Спец-отряд (lostzone-ступени, не сюжет) | `special_steps_for_lostzone_tasks`, `task_status_functor.script:12-51, 330-340` | 11 не сюжетных (из 34) | флаг `*_squad_dead`, который выдаёт `on_death` отряда (`sim_squad_scripted.script:464-470`) актёру **того клиента**, где умер последний | при сдаче | `on_init`: `create_squad(...)` со `story_id` (напр. `boss_sultan_task_5_stalkers`, `squad_descr_lostzone.ltx:50-56`) | «кто добил последнего члена». Флаг смерти — общий факт мира. Отряд спавнить один раз на мир (второй держатель берёт тот же) |
| 8 | Уничтожить технику | `veh_destroy_*`, `tasks_veh_destroy.script` | 1 | все БТР с `must_kill` мертвы (`vehicle_on_death_callback`, **без убийцы**, `:24-33`) → stage 2 → сдача | при сдаче | 4 БТР (`:58-105`); `veh_destroy_unset` их выпускает (`:43-55`) | «кто уничтожил последнюю»: нужен учёт последнего попавшего (у машины нет убийцы в колбэке). Спавн один раз на мир, уборка — когда держателей не осталось |
| 9 | Сбить вертолёт | `mar_base_owl_stalker_trader_task_2`, `sim_default_csky_trader_task_2`; `bind_heli.script:295-300` | 2 | `heli_die` сразу ставит complete (без сдачи) | **сразу** при смерти | ничего (вертолёт уровня) | «кто сбил»: последний попавший из `heli_binder:on_hit(…, enemy_id)` (`bind_heli.script:211`) |
| 10 | Принести предмет (fetch) | `actor_has_fetch_item`, `tasks_fetch.script:109-258, 314-640` | 206 всего, из них обычных ≈100 (оружие 19, артефакты 18, припасы 14, части мутантов 23, …), 6 lostzone, 2 warfare-оружие (`actor_has_fetch_weapon_warfare`) | предмет(ы) в инвентаре → stage 1 (`:598-640`); сдача диалогом, `fetch_reward_and_remove` забирает предметы и платит | при сдаче | ничего (предмет игрок несёт свой) | **по правилу**: засчитывается первому сдавшему, в момент сдачи; у остальных — «опоздал» + мягкая отмена |
| 11 | Инструменты технику / аптечки медику | те же fetch-задания с `setup_generic_fetch_task(…itm_basickit/advancedkit/expertkit/drugkit)`; в `on_complete` флаг `+<техник>_upgrade_tier_N` / `<медик>_drugkit_done` | 98 инструменты (≈33 техника × 3 уровня), 8 аптечки | как fetch; уровень техника — флаг (проверка: `xr_conditions.script:18-25`, `stalkers_upgrade_info.ltx`) | при сдаче | ничего | **по правилу и по плану**: первому сдавшему; флаг уровня — общий мировой; держатели того же уровня закрываются без штрафа: «Инструменты уже принёс …». Старые затонские/юпитерские инструменты идут через диалоги и флаги (`zat_b3_tech_instrument_N_brought`, `jup_b217_…`, `dialogs_zaton.script:1205-1257`, `dialogs_jupiter.script:918-930`), а не через задания |
| 12 | Мультифетч | `multifetch_*`, `tasks_multifetch.script:156-344` | 2 | все обязательные предметы есть → stage 1 | при сдаче | ничего | как fetch |
| 13 | Предмет из тайника (DRX quest item) | `drx_sl_quest_item_task_*`, `tasks_stash.script:33-155` | 21 (9 сюжетных) | у игрока предмет `drx_sl_quest_item_<N>` → stage 1 | при сдаче | тайник с **уникальным** сюжетным предметом (`set_random_stash`, `:138`), флаг `drx_sl_quest_item_task_N_started` | как fetch (первый сдавший). Предмет физически один, тайник — один на мир для пары заказчик + task_id |
| 14 | DRX: забрать предмет | `drx_sl_retrieve_item_task_status`, `task_status_functor.script:420-468` | 10 (сюжетные) | предмет(ы) у игрока | при сдаче | предмет на точке (`spawn_item_at_pos` в `on_init`) | как fetch; спавн один раз на мир |
| 15 | Предмет на трупе (RIOC) | `recover_item_on_corpse_*`, `tasks_recover_item_on_corpse.script:162-257` | 17 | предмет у игрока → stage 1 | при сдаче | труп + предмет + 0-3 мутанта (`:174-193`) | как fetch; спавн один раз на мир |
| 16 | Данные с мутанта | `recover_mutant_data_*`, `tasks_recover_mutant_data.script` | 1 | мутант умер (кем угодно) → на теле прибор (`:12-19`); прибор у актёра (`parent_id == 0`, `:108-118`) → сдача | при сдаче | прибор | как fetch (первый сдавший прибор). Внимание: `parent_id == 0` в коопе — «у локального актёра» на каждом клиенте |
| 17 | Судьба отряда (найти КПК пропавших) | `fate_task`, `tasks_fate.script:113-400` | 3 (2 сюжетных) | найти мёртвый отряд по радиочастоте, забрать предмет → stage 4 → сдача | при сдаче | создаёт отряд и тут же убивает (`:66-104`), предмет на трупе; флаги `<id>_dead_spawned/_item_spawned/_target_found` | как fetch (первый сдавший). Спавн — один на мир; флаги «заспавнено» сделать мировыми |
| 18 | Доставка посылки | `delivery_task`, `tasks_delivery.script:46-309` | 3 | посылка у игрока → stage 1; сдача **получателю** (`dialogs.complete_simulation_task`, `:301-309`) | при сдаче получателю | посылка в инвентарь (`:198-209`), флаг `<id>_quest_item_received`; получатель — случайный NPC (кэш по заказчику) | правило не покрывает. Предложение: как fetch — первому доставившему; у остальных посылка изымается, мягкая отмена. Получатель умер от игрока → у убийцы провал (с ванильным штрафом), у остальных мягкая отмена |
| 19 | Замер аномалии | `measure_task`, `tasks_measure.script:281-487` | 4 (1 сюжетное) | взять прибор, подойти, сделать замер (флаг `<id>_measurment_finished`) → stage 3 → сдача | при сдаче | прибор в инвентарь; по желанию отряд мутантов на игрока | предложение: личное — каждый делает свой замер, аномалия не расходуется (нет «опоздал»). Вариант строже: первый сдавший |
| 20 | Поставить сканер в аномалию | `anomaly_scanner_*`, `tasks_anomaly_scanner.script:84-158` | 2 | сканер выложен у аномалии → stage 3 | при сдаче | сканер (мировой предмет после выкладки) | предложение: засчитать первому, кто поставил (в момент установки), остальным «опоздал» |
| 21 | Скан химеры | `chimera_scan_*`, `tasks_chimera_scan.script:30-253` | 1 | 20 с в радиусе от живой химеры со сканером → stage 2 → сдача; химера мертва → провал | при сдаче | химера (отряд) + сканер в инвентарь | предложение: первый, кто досканировал (в момент окончания); химеру спавнить одну на мир; убита игроком-держателем → провал у него, у остальных мягкая отмена; убита не игроком → мягкая отмена у всех |
| 22 | Образцы тканей (Семенов) | `task_type_ecolog_gathered_tissue_samples`, `task_status_functor.script:557-569` | 1 | счётчик образцов в pstor ≥ нужного | при сдаче | компаньон-отряд учёных | предложение: первый сдавший; отряд-компаньон один на мир → лучше не давать второму, пока задание у кого-то |
| 23 | Спасти заложника | `hostage_task` / `simulation_task_target`, `tasks_faction_control.script:3-55`; спавн `axr_companions.script:741-823` | 9 (4 сюжетных) | после зачистки охраны поговорить с заложником (флаг `hostage_companion_task_1_hostage_rescued`) → stage 1; заказчик мёртв → complete | при сдаче | отряд-заложник со `story_id hostage_companion_task_1`, `smart.locked` | предложение: тот, кто освободил (диалог с заложником), в момент освобождения; заложник идёт за ним. Предусловие `!squad_exist(hostage_companion_task_1)` и так не даёт второго заложника на мир, поэтому второй держатель — только «тот же заложник» |
| 24 | Вызволить агента | `spy_task_*`, `tasks_agent_rescue.script:200-418` | 5 (3 сюжетных) | перебить отряд кроме агента → агент становится компаньоном (stage 2) → довести до заказчика (stage 3) → сдача; агент мёртв → провал | при сдаче | меняет оружие в отряде (`:234-266`), агент → компаньон, отряд удаляется (`:394`) | «отряд — кто добил последнего»: агент становится компаньоном этого игрока; агент убит игроком → провал у него, у остальных мягкая отмена |
| 25 | Сопроводить учёного/бандита (escort-компаньон) | `setup_companion_task` + target-функторы (`task_functor.script:411-513`), `mar_base_owl_stalker_trader_task_3`, `jup_b6_scientist_tech_task_1`, `val_…_task_3`, `sim_default_*` | 6 | дойти до аномалии, «анализ», вернуть; сдача диалогом | при сдаче | компаньон-отряд со `story_id` (`ecolog_companion_task_1/2`, `bandit_companion_task_1`) | предложение: только один держатель на мир (компаньон один); засчитывается владельцу компаньона |
| 26 | Проводник (отвести NPC на другой уровень) | `tasks_guide.script` (отдельная система, вне task_manager) | — | дошли → оплата | сразу | NPC-попутчик | личное (владелец попутчика) |
| 27 | Оборона (барьер, насосная станция, база фракции) | `tasks_defense.script` (`barrier_defense_monolith/zombie` в `task_manager.ltx`), `tasks_pump_station_defense.script` (`gd_task_*`, `mar_…_task_4`), `faction_base_defense` (`tm_dynamic.ltx`, `surge_manager.script:73`) | 4 | все нападающие мертвы (`tasks_defense.script:443-464`) / стадии; у насосной провал, если держатель ушёл с уровня или командир агрится на актёра id 0 (`tasks_pump_station_defense.script:193-210, 453-470`) | барьер — в диалоге сдачи (`:343-415`), насосная — `on_complete` | волны отрядов (`:484-541`), командир, охрана, тайник | правило не покрывает. Предложение: событие мира одно; засчитывается всем держателям, которые были в зоне обороны во время волны, каждому своя награда при сдаче; провал — у всех |
| 28 | Деньги (DRX смена фракции) | `drx_sl_money_task_status`, `task_status_functor.script:405-417` | 10 (сюжетные) | у игрока есть сумма → сдача, деньги списываются | при сдаче | ничего | личное, конфликтов нет |
| 29 | DRX «встреться с …» / старт / «найди Исполнитель» | `task_manager.ltx` (26 meet + 10 start_game + 1 wish granter) | 37 (сюжетные) | флаг снимается разговором (`{-drx_sl_start_game_…} complete`) | `on_complete` → следующий заказчик | ничего | личное (сюжет) |
| 30 | Сюжетные и скриптовые по флагам (condlist) | без `status_functor`, `condlist_N = {+info} complete` | 167 (111 сюжетных; + Cordon «девушка»/«фанат», Ной, история ЧН и т.п.) | флаг, выданный диалогом или логикой | `on_complete` (часто + спавн, §4) | часто в `on_init/on_complete` | личное (сюжет), делится через «Поделиться сюжетом» / «Общий сюжет» |
| 31 | Сюжетные lostzone со ступенями | `special_steps_for_lostzone_tasks` (23 сюжетных) | 23 | флаги + таймеры; функтор **сам спавнит** (`task_status_functor.script:123-137, 258-329`) | по флагу / сдача | `create_squad`, выброс, смена фракции, убийство актёра | личное (сюжет), но спаун из функтора — мировой (см. §4.4 П3) |
| 32 | Спрятаться от выброса / пси-шторма | `hide_from_surge`, `hide_from_psi_storm` (`task_manager.ltx`) | 2 | менеджер выброса | — | — | личное |

### 2.2. Как узнать, какой игрок убил цель

Что есть в игре:
- **Сталкер онлайн**: `motivator_binder:death_callback(victim, who)` (`scripts/xr_motivator.script:319-400`). Колбэк `npc_on_death_callback(victim, who)` шлётся, только если `who` — сталкер/монстр (актёр сюда входит: `IsStalker` включает `clsid.actor`, `_g.script:2838-2843`). Пишет `db.storage[id].death_by_id = who:id()`.
- **Монстр онлайн**: `bind_monster.script:244` → `monster_on_death_callback(victim, who)`, `st.death_by_id`.
- **Серверная сторона (онлайн и офлайн)**: `se_stalker:on_death(killer)` / `se_monster` (`se_stalker.script:127-136`, `se_monster.script:103`) → `squad:on_npc_death(se_npc, se_killer)` → колбэк `squad_on_npc_death(squad, se_npc, se_killer)` (`sim_squad_scripted.script:480-496`). Когда умер последний, исполняется `death_condlist` отряда **без убийцы** и с `db.actor` (`:464-470`) — отсюда флаги `*_squad_dead`.
- **Офлайн-бой**: `sim_offline_combat.script:432,446,523,546` → `victim:on_death(se_attacker)`. Убийца всегда NPC (актёр всегда онлайн), значит по правилу это «убил не игрок».
- **Как движок назначает убийцу**: смерть от потери здоровья, в т.ч. от кровотечения, идёт с «кто бил последним» `KillEntity(conditions().GetWhoHitLastTimeID())` (`xrGame/entity_alive.cpp:225-237`). Граната/взрыв — инициатор взрыва. Так что «смерть, которую вызвал игрок» движок уже относит к нему.
- **Метка «задет актёром»**: `axr_task_manager.npc_on_hit_callback` ставит `db.storage[npc].tagged_by_actor` (`:116-127`). Ваниль её читает, но всё равно засчитывает задание.
- **Компаньоны**: bounty считает убийство компаньоном (`who:has_info("npcx_is_companion")`) за актёра (`axr_task_manager.script:97`) — предлагаю засчитывать владельцу компаньона.
- **Техника**: `vehicle_on_death_callback(obj)` — без убийцы (`tasks_veh_destroy.script:24-33`); у вертолёта убийца есть только в `heli_binder:on_hit(power, impulse, hit_type, enemy_id)` (`bind_heli.script:211`), `heli_die` его не получает.

Для коопа: убийца — это «локальный актёр» (`who:id() == 0`) **только на клиенте, где произошла смерть** (у хозяина уровня или у стрелявшего). На других клиентах смерть приходит репликацией (шаг 3 «death replication»). Предложение: в сообщение о смерти класть «кто убил» как имя игрока (или id его двойника/стенд-ина) и вести общий журнал `victim_id → {killer_player | npc | none, time}`. Из журнала:
- устранение: при смерти цели засчитать убийце, остальным — отмена;
- отряд/точка: последний убитый с `killer_player`;
- «убил не игрок» = в журнале NPC/никто/офлайн.

### 2.3. Замечания, которые влияют на правила

- **Assault/dominance завершаются и когда враги ушли**, а не только умерли (`tasks_assault.script:327-345`). Движение отрядов в коопе пока считается на каждом клиенте отдельно (чек-лист расхождений), поэтому у двух игроков точка может «очиститься» в разное время. Решение принимать на одном клиенте (хозяин уровня), а остальным рассылать.
- Цели выбираются случайно и **на клиенте**: `bounty_cache`, `cache_assault`, `delivery_cache[var][giver]`, `fate_cache`, кэши measure/spy. У двух игроков «одно задание» = разные цели. «То же задание» надо сравнивать по цели (`target_id`/`smart_id`/`item_id`), а лучше хранить выбор цели в мире по паре заказчик + task_id, чтобы второй взявший получил ту же цель.
- `on_job_descr` срабатывает при **рассказе** о работе (`dialogs.script:653-659`), даже если игрок откажется: цель уже помечена, отряд задержан.
- `generate_finished_tasks` сравнивает `stage == stage_complete` (`axr_task_manager.script:1051`). Мягкую отмену у остальных делать раньше, чем они успеют сдать.

---

## 3. Мягкая отмена и сообщение от заказчика

### 3.1. Что есть в игре

`CRandomTask:set_task_cancelled(task_id)` (`task_manager.script:97-102`): `forced_status="fail"`, `cancelled_by_actor=true`. Это ванильная «отмена» через диалог (`dialogs.npc_cancel_task`, `dialogs.script:772-779`), через `drx_sl_cancel_questlines` (`xr_effects.script:897-903`) и в `surge_manager.script:73`. Дальше:
1. движок видит `task_fail`=true и ставит **eTaskStateFail** (`GameTask.cpp:40-60`);
2. `task_callback` (`task_manager.script:195-223`): `news_manager.send_task(db.actor,"fail",tsk)` — новость «Задание провалено»; статистика `tasks_cancelled` (не `tasks_failed`); **исполняется только `on_cancel`**, если он есть, и `save_var(db.actor,id,nil)`; `on_fail` **не исполняется**, значит штрафа `fail_task_dec_goodwill` из `on_fail` не будет;
3. при `repeat_timeout` запись остаётся до истечения таймаута (`:215-220`), и NPC не предложит это задание снова.

Подводные камни:
- **`on_cancel` есть у 19 заданий** (dynamic 14, warfare 3, darkvalley 1, jupiter 1):
  - у `zat_b7_bandit_boss_sultan_task_5` в `on_cancel` **штраф** `fail_task_dec_goodwill(25:bandit)`;
  - у 4 (включая султана) — уборка мира `remove_special_task_squad`: убирает отряд, который может быть нужен другому игроку;
  - у остальных — личное: `pstor_reset` (10, у 5 из них ещё `drx_sl_unregister_task_giver`/`drx_sl_reset_stored_task`), `remove_delivery_item` (3), `reset_task_target_anomaly`/`reset_warfare_escort_task`, `-faction_base_defense_active`, `+yar_ashot_cancelled`.
- **Без `on_fail` пропадает личная уборка**:
  - `pstor_reset(<id>_fetch)`;
  - `drx_sl_unregister_task_giver` — счётчик «долгов» у заказчика `drx_sl_task_giver_<id>` останется увеличенным (`xr_effects.script:1175-1205`);
  - `drx_sl_reset_stored_task`, `-hostage_companion_task_1_*`, `unlock_smart`, `forget_dead_npcs`, `script(tasks_recover_item_on_corpse:cleanup…)` (18 заданий), `veh_destroy_unset`, `recover_mutant_data_unset`.
  Часть этого личное, часть мир.
- **Сюжетные DRX**: продвижение цепочки (`drx_sl_meet_random_honcho()`, 125 вызовов) стоит в `on_complete/on_fail`, а не в `on_cancel`. Мягкая отмена сюжетного DRX-задания **остановит цепочку**: следующего заказчика не будет.
- В движке задание останется «проваленным» в истории ПДА. Своего состояния «отменено» нет, удалить задание нельзя (`GametaskManager.cpp`, вектор только растёт).
- Другие пути: `set_task_failed` (`task_manager.script:91-95`) = провал с `on_fail` (штраф); `db.actor:set_task_state(task.fail, id)` (`script_game_object_inventory_owner.cpp:1107-1111`) = тот же колбэк, но без флагов Lua; `xr_effects.set_task_completed/failed` (`xr_effects.script:3616-3626`).

### 3.2. Предложение: «кооп-отмена»

Своя функция рядом с `set_task_cancelled`:
- ставит `forced_status="fail"`, `cancelled_by_actor=true` и свой флаг `coop_soft_cancel=true`;
- в `task_callback` при `coop_soft_cancel`: не исполнять ни `on_cancel`, ни `on_fail`. Вместо них — **белый список личной уборки**, разобранный из `on_fail/on_cancel` (`pstor_reset`, `drx_sl_unregister_task_giver`, `drx_sl_reset_stored_task`, снятие личных флагов `-…`, `remove_delivery_item`/`remove_quest_item` для своего предмета). Штрафы (`fail_task_dec_goodwill`, `dec_goodwill_by_tasker_id`, `decrease_rep`) и уборку мира (`remove_special_task_squad`, `*_unset`, `cleanup…`, `unlock_smart`) пропускать: мир убирает тот, кому засчитали, или последний держатель;
- статистику не трогать (или отдельный счётчик), новость «провалено» заменить своей;
- для сюжетных DRX после отмены вызывать продвижение цепочки (`drx_sl_meet_random_honcho`) без штрафа;
- порядок: сначала мягко отменить у всех остальных, потом исполнять `on_complete` у засчитанного (его уборка мира, например `veh_destroy_unset`, иначе уронит задания остальных в «fail» с ванильным штрафом через их функторы статуса).

### 3.3. Как прислать сообщение от заказчика

- `dynamic_news_helper.send_tip(msg, header, timeout, showtime, sender, sound, icon_by)` (`scripts/dynamic_news_helper.script:693-749`): `header` = имя заказчика, `sender` = иконка, `icon_by="npc"`. Пример — `tasks_agent_rescue.join_message` (`tasks_agent_rescue.script:102-111`): `dynamic_news_helper.send_tip(text, se_obj:character_name(), nil, nil, se_obj:character_icon(), nil, 'npc')`. Работает на `db.actor:give_game_news`, тратит заряд ПДА.
- `news_manager.send_tip(actor, news_id, timeout, sender, showtime, sender_id)` (`news_manager.script:39-92`): не отправит, если сюжетный отправитель мёртв или тяжело ранен.
- Напрямую `db.actor:give_game_news(caption, text, icon, delay_ms, show_ms[, type])`; в диалоге — `db.actor:give_talk_message2(caption, text, icon, "iconed_answer_item")` (как в `news_manager.send_task`, `:173-192`).
- Канал «сети сталкеров» (`DynamicNewsManager:PushToChannel`, `dynamic_news_manager.script:686`) — общий эфир, для личного «опоздал» не подходит.
- Кто заказчик: `task_info[id].task_giver_id`. Это id NPC **или его отряда** (`axr_task_manager.script:792-794`); у отряда брать командира. Если заказчик умер, у sim-заданий id переходит командиру (`:129-142`).

---

## 4. Сюжет

### 4.1. Сюжетные задания (`storyline = true`)

Всего **255**: 218 в `tm_*.ltx` + 37 в `task_manager.ltx`.

| Линия | Заданий | Файлы | Фракционность |
|---|---|---|---|
| DRX Questlines (цепочка заказчиков) | 147 = 74 `drx_sl_<заказчик>_task_N` + 26 `_default_task` + 10 `_cf_task_1` (смена фракции) + 26 `_meet_task_N` + 10 `_start_game_1` + 1 `drx_sl_find_wish_granter_task` | `tm_agroprom/bar/darkvalley/deadcity/escape/jupiter/marsh/military/pripyat2/red_forest/yantar/zaton.ltx`, `task_manager.ltx` | 26 заказчиков, 12 фракций (`axr_task_manager.script:23-85`: stalker, dolg, freedom, csky, ecolog, killer, army, bandit, monolith, renegade, greh, isg); **порядок заказчиков случайный и личный** (`xr_effects.script:704-783`), длина цепочки 8-12 (`drx_sl_total_task_number`); конец — «Исполнитель желаний» при `bar_deactivate_radar_done` (`dialogs.script:156-162, 285-295`) |
| «Тайны Зоны» (Доктор → лаборатории → Выжигатель → Варлаб/Монолит) | 14: `mar_find_doctor_task`, `cit_doctor_task`, `main_1…7_search_*` (`tm_marsh.ltx`), `turn_off_brain_scorcher` (`tm_radar.ltx`), `sar_monolith`, `sar_monolith_destroy` (`tm_sarcofag.ltx`), `sar_warlab`, `warlab_kill_crazy_entity` (`tm_warlab.ltx`) | старт `dialogs.give_task_mysteries_of_the_zone` (`dialogs.script:30-32`) для csky/dolg/ecolog/freedom/killer/stalker (`:15-28`); лаборатории выдаёт рестриктор `configs/scripts/marsh/mar_add_quest_on_object.ltx:5`; Warlab — `info_portions.proceed()` (`info_portions.script:36-56`) | — |
| LTTZ: Living Legend | 26 `lttz_ll_*` | `tm_lostzone_ll.ltx`, `dialogs_lostzone_ll.xml` | финалы ×6 фракций (`lttz_ll_finish_dolg/killer/stalker/csky/freedom/ecolog`) |
| LTTZ: Mortal Sin | 47 `lttz_ms_*` | `tm_lostzone_ms.ltx`, `dialogs_lostzone_ms.xml` | start/report/ambush/urban_warfare/zone_hero ×6 фракций; переключение флагов при смене фракции `dialogs_lostzone.update_lttz_faction_info` (`dialogs_lostzone.script:13-…`) |
| LTTZ: Operation Afterglow | 10 `lttz_oa_*` | `tm_lostzone_oa.ltx`, `dialogs_lostzone_oa.xml` | — |
| LTTZ: Hollow Boundaries | 11 `lttz_hb_task_*` | `tm_lostzone_hb.ltx`, `dialogs_lostzone_hb.xml` | — |

Ещё 11 заданий заказчиков используют сюжетные ступени lostzone, но помечены не сюжетными (`bar_dolg_leader_task_2/3`, `zat_b7_…_task_5/6` и т.п.).

### 4.2. Семейства флагов

Всего в скриптах, LTX и диалогах упоминается ≈3000 разных флагов (вместе с шумом разбора). Объявлено в XML ≈1160, но XML движок не читает (§4.3), и многие флаги вообще не объявлены (`info_awr.xml`, `info_mlr.xml` даже не перечислены в `system.ltx:88-89`). Грубое разбиение:

| Семейство | ≈ флагов | Примеры | Чьё |
|---|---|---|---|
| LTTZ Living Legend | 75 | `living_legend_*`, `stalker_rogue_*`, `lttz_ll_*` | сюжет (личное) |
| LTTZ Mortal Sin | 60 | `mortal_sin_*`, `stalker_stitch_*`, `kat_greh_*`, `greh_prisoner_*`, `lazarus_*`, `too_late`, `premature_emission*` | сюжет |
| LTTZ Operation Afterglow | 50 | `operation_afterglow_*`, `degtyarev_further/finale_*`, `undercover_agent_*`, `strelok_choice_*` | сюжет |
| LTTZ Hollow Boundaries | 35 | `hb_*`, `lttz_hb_*`, `isg_entered_the_zone` | сюжет |
| «Тайны Зоны»: Доктор, лаборатории, Варлаб, Саркофаг | ≈350 | `mar_doctor_found`, `cit_jail_doctor_pryp_task`, `pri_monolith_decoder_got`, `main_N_*_task_done`, `warlab_*`, `sar2_death_N`/`sar2_spawn_N` (≈120), `lx8_*`, `dar_*` (X-18), `bun_*`, `yan_labx16_*`, `bar_deactivate_radar_done` | сюжет; часть — сцены уровня (мир) |
| DRX | 45 + динамические | `drx_sl_start_game_<заказчик>`, `drx_sl_meet_honcho_<заказчик>`, `drx_sl_on_cf_task`, `drx_sl_quest_item_task_N_started` | сюжет (личное) |
| Факты о мире: смерти | ≈300 | `*_squad_dead`, `*_dead`, `*_death` (148 `on_death` у отрядов, ≈160 `[death] on_info`) | **мир** |
| Уровни техников и аптечки | ≈124 | `<техник>_upgrade_tier_1..3`, `<медик>_drugkit_done`, `zat_b3_tech_instrument_N_brought` | **мир** (по плану) |
| Старые квесты ЗП на уровнях | Затон ≈490, Юпитер ≈550, Припять ≈290 | `zat_b*`, `jup_a*/b*`, `pri_a*/b*` | личный прогресс побочных квестов (почти все через диалоги и логику рестрикторов, без заданий ПДА); часть — сцены мира |
| Кордон, Бар, Болота и т.п. | ≈200 | `esc_2_12_*`, `devushka_*`, `fanat_training_*`, `bar_*`, `look_for_cs_history_*` | личное (побочные) |
| Арена, тотализатор | ≈110 | `bar_arena_*`, `total_*` | личное, но арена — сцена мира |
| Флаги «данных задания» | ≈90 | `<task_id>_quest_item_received`, `_dead_spawned`, `_item_spawned`, `_target_found`, `hostage_companion_task_1_started`, `spy_task_active`, `pump_station_defense_task_smart_reserved`, `barrier_defense_*_first_spawn` | смешанное: многие — **страж «уже заспавнено»** (мир) |
| Мастерские AWR, проводники, апгрейды | ≈55 | `awr_*_access`, `meet_guid_*`, `info_up_*` | личное |
| UI и служебные | ≈20 | `ui_pda`, `ui_talk`, `actor_is_sleeping`, `npcx_beh_*` | личное, временное |

Сюжетные задания сами ставят или проверяют ≈230 флагов. Ставят 56 (в `on_*`), проверяют 195 (`{+…}` в condlist, title, descr, target). Основная масса сюжетных флагов выдаётся в диалогах:

| Диалоги | Уникальных `<give_info>` |
|---|---|
| `dialogs_lostzone_ll.xml` | 56 |
| `dialogs_lostzone_ms.xml` | 46 |
| `dialogs_lostzone_oa.xml` | 70 |
| `dialogs_lostzone_hb.xml` | 25 |
| `dialogs_warlab.xml` | 9 |
| `dialogs_pripyat.xml` | 122 |
| `dialogs_jupiter.xml` | 304 |
| `dialogs_zaton.xml` | 204 |

Рабочее определение «сюжетного флага» для синхронизации: флаги, которые ставят или проверяют сюжетные задания, плюс флаги из сюжетных диалогов (`dialogs_lostzone_*.xml`, `dialogs_warlab.xml`, Доктор/лаборатории), плюс `drx_sl_*`; **минус** мировые факты и стражи спауна.

### 4.3. Есть ли у инфопоршня собственные действия

Нет.
- Схема XML: `<info_portion id="…">` с необязательными `<dialog>` (1 раз, `global_dialogs`) и `<disable>` (10 раз, пары `ui_*`, `configs/gameplay/info_portions.xml:191-233`). В `info_alife_switch.xml` разметка вообще битая (`id=""`).
- Движок monolith: загрузчик `CInfoPortion::load_shared` (диалоги, `disable`, статьи, скриптовые действия) **закомментирован** (`xrGame/InfoPortion.cpp:5-120`), рабочий класс хранит только id (`InfoPortion.h:211-217`).
- Выдача: `give_info_portion` → `CInventoryOwner::TransferInfo` (`inventory_owner_info.cpp:96-118`; сетевое событие `GE_INFO_TRANSFER` сервер просто рассылает, `xrServer_process_event.cpp:47-59`) → `OnReceiveInfo` дописывает строку в реестр (`:45-62`) → `CActor::OnReceiveInfo` зовёт колбэк `eInventoryInfo` и обновляет вопросы в окне диалога (`actor_communication.cpp:47-70`).
- Lua-слушатели колбэка (`bind_stalker_ext.script:372-374` → `actor_on_info_callback`) — их три:
  - `info_portions.script:58-68`: пары-переключатели (`ui_*`, арена, `:16-34`) и **`proceed()`**, который при наборе из 9 флагов выдаёт `warlab_password_info` и задания `sar_warlab`, `sar_monolith_destroy` (`:36-56`);
  - `item_device.script:160-175, 399` (ПДА открыт/закрыт);
  - `ui_map_debug_ex.script:72` (отладка).
- Флаги также выдают предметы с `info_portion` (`InfoDocument.cpp:69`) и обыск трупа (`UIActorMenuDeadBodySearch.cpp:158`).

### 4.4. Где флаг приводит к изменениям мира (шаблоны)

Флаг сам ничего не делает, на него **реагируют**. Шаблоны:

| # | Где | Как | Масштаб | Пример |
|---|---|---|---|---|
| П1 | Логика NPC, рестрикторов и смартов (`configs/scripts/**.ltx`, схемы `sr_idle`, `on_info`, `on_infoN`) | опрос condlist при апдейте объекта, `{+флаг} секция %эффекты%` | 605 файлов с проверками флагов, ≈3000 строк; эффекты: `spawn_object` 115, `create_squad` 80, `give_task` 35, `teleport_squad` 29, `clear_smart_terrain` 19, `remove_squad` 12, `destroy_object` 12, `teleport_actor` 7, `play_sound` 702 | `bar/bar_arena_sr.ltx:18` (`{+bar_arena_spawn_monstr +…} … %=spawn_object(…)%`); `agroprom_underground/agru_poltergeist_end_spawns.ltx:7` (`+agr_u_soldiers_dead` → `create_squad`); `agroprom_underground/kat_gunslinger_cache_room.ltx:5` (`+living_legend_st` → `give_task`); `marsh/mar_add_quest_on_object.ltx:5` (флаги + 8 `give_task`) |
| П2 | Респаун смартов | `spawn_num = {+флаг} 1, 0` | 72 строки | заставы Бара `{+bar_zastava_*_dead …}` |
| П3 | Функторы статуса заданий | каждый `check_task` активного задания | 34 задания lostzone | `task_status_functor.script:123-137` (`lttz_ms_contact_lost`: `create_squad` при `+lim_stalker_scout_dead`), `:258-329` (`lazarus_*_squad` при `+lazarus_join`), `:186-205` (выброс, `kill_actor`) |
| П4 | `on_init` / `on_complete` / `on_fail` заданий | при выдаче и завершении | у сюжетных: `create_squad` 103, `give_task` 54, `clear_smart_terrain` 21, `open_route` 21, `spawn_item_at_pos` 12, `remove_squad` 9, `spawn_*` 8, `drx_sl_change_factions` 11 | `tm_lostzone_hb.ltx:17-28` (`on_complete`: `clear_smart_terrain` + 5×`create_squad` + `give_task`) |
| П5 | `condlist_N` заданий | `{+флаг} complete` → исполнится `on_complete` (П4) | 167 заданий без функтора | `mar_find_doctor_task`: `{+mar_doctor_found} complete` |
| П6 | Диалоги | `<has_info>/<dont_has_info>` в предусловиях; `<action>` (спаун, компаньоны) исполняется при выборе фразы, не от флага | — | `dialogs_lostzone.script` (`aditional_spawn`, компаньоны) |
| П7 | Lua-колбэк выдачи | `actor_on_info_callback` | 3 слушателя | `info_portions.proceed()` → `give_task(sar_warlab)` |
| П8 | Обратное направление: мир → флаг | `on_death` отрядов и `[death] on_info` NPC выдают флаг `db.actor` того клиента, где идёт логика | 148 + ≈160 | `squad_descr_lostzone.ltx:13` `%+special_chimera_task_squad_dead%` |

Где читаются флаги: `xr_logic.pick_section_from_condlist` (`xr_logic.script:365-480`; `+/-` проверяет `db.actor:has_info`, а без актёра — `alife():has_info(0,…)`), `_g.has_alife_info` (`_g.script:2533-2535` → `alife():has_info(0, id)`), `give_info/disable_info` (`:2537-2553`), плюс прямые `db.actor:has_info(...)` по скриптам. Все они смотрят на **локального** актёра.

### 4.5. Что это значит для синхронизации флагов «без побочных эффектов»

1. **Сама запись флага безопасна**, если не дать сработать П7. Варианты: писать в реестр напрямую из C++ (`OnReceiveInfo` без колбэка; новый скрипт-экспорт «тихой» выдачи) или выставлять глобальный флаг «идёт синхронизация», при котором `info_portions.proceed()` и переключатели молчат. Задания Warlab из `proceed()` тогда выдавать отдельно, как подтягивание сюжетного задания.
2. **Опасна реакция потом** (П1-П5). Безопасно, если мировая логика, которая реагирует на флаг, уже отыграла в общем мире: её состояние (активная секция рестриктора, `sr_idle@nil`) хранится в объекте мира, и второй раз она не сработает. Опасно, когда:
   - а) логика ещё «ждёт» флага, потому что её хозяин (тот, кто гоняет уровень) этот флаг не имеет. Тогда синхронизация флага хозяину уровня запустит спаун, который уже сделан у другого игрока. Нужен **общий мировой набор флагов** для логики мира (П1, П2, П8), отдельно от личных;
   - б) у получателя подтягивается сюжетное задание, и его `condlist {+флаг} complete` или функтор сработает на его клиенте → `on_complete`/функтор заспавнит второй раз (П3-П5).
3. **Подтягивание сюжетных заданий** нельзя делать через `task_manager:give_task` (исполнит `on_init`, у сюжетных там спавн, компаньоны, `open_route`) и через естественное завершение (исполнит `on_complete`). Нужно:
   - пройденные шаги записывать прямо в историю движка как Completed, а в `task_info` — без `on_*`, наград и новостей;
   - активный шаг создавать с готовой стадией и `stage` отдающего, без `on_init`;
   - помечать его «синхронизирован», чтобы при завершении у получателя из `on_complete` исполнялась только личная часть (флаги, награда), а мировые эффекты (`create_squad`, `clear_smart_terrain`, `remove_squad`, `spawn_*`, `give_task` следующего шага, если его уже подтянули) — нет. Удобно разобрать эффекты на «личные» (`+/-флаг`, `reward_*`, `*_goodwill`, `pstor_*`, `drx_sl_*`, `open_route`, `remove_item`, `give_task`) и «мировые», как в §3.2.
4. **Стражи «уже заспавнено»** (`lazarus_spawn`, `lim_bloodsucker_ambush_squad_spawn`, `<task>_dead_spawned`, `hostage_companion_task_1_started`, `barrier_defense_*_first_spawn` …) сейчас — флаги актёра. Их надо сделать мировыми, иначе второй игрок с тем же шагом заспавнит второй раз. Со спец-отрядами при этом сломается и реестр `story_id`: второй объект с тем же `story_id` не регистрируется (`story_objects.script:6-13`), и `get_story_squad` вернёт первый.
5. **DRX нельзя «поделить» шагами 1:1**: цепочка у каждого случайная (свои заказчики и длина 8-12). «Поделиться сюжетом» для DRX = копировать `drx_sl_current_honcho/current_task/current_task_number/total_task_number` + `drx_sl_meet_honcho_*`/`drx_sl_start_game_*` + активное DRX-задание. Либо решить, что DRX-цепочка всегда личная, а делятся только «Тайны Зоны» и LTTZ.
6. Фракционные варианты LTTZ (`lttz_ms_*_<фракция>`, `living_legend_<фракция>*`) зависят от фракции персонажа: при передаче получателю другой фракции нужно перекладывать флаги (`dialogs_lostzone.update_lttz_faction_info`).
7. Функторы lostzone (П3) работают на клиенте держателя и сами вызывают `create_squad`, `premature_emission`, `kill_actor`, `drx_sl_change_factions`. Их мировые части надо пропускать через «авторитет» (`coop_sync` / `begin_shared`), иначе спаун будет у каждого держателя.

---

## 5. Что сломается при одном задании у двоих / коллизии id

**Как устроены id**: task_id = имя секции LTX. Пространство имён — по персонажу-заказчику (`<секция NPC>_task_N`, у Сидоровича по имени, `axr_task_manager.script:399-401`; или параметр `task_section` в логике) **или общий пул** `simulation_task_N` для всех рядовых NPC, `sim_default_<фракция>_trader_task_N` для торговцев warfare. Ключ один на актёра: в Lua `task_info[task_id]`, в движке `HasGameTask(id, in-process)`. Кто заказчик, хранится отдельно (`task_giver_id`). Значит, один игрок не может одновременно держать `simulation_task_47` от двух разных NPC. У двух игроков одинаковый id сам по себе не конфликтует: у каждого свой task_manager.

Ломается то, что ключуется по task_id **в мире** или живёт в общем сохранении:

1. **Общий `.scoc` мира держит личные данные заданий** (сейчас всё от мастера): `m_data.task_info/task_objects`, `bounties_by_id`, `tasks_fetch_ids`, `multifetch_data`, `tasks_rioc`, `recover_mutant_data_mdata`, `tasks_veh_destroy`, `task_chimera_scan`, `defense_task_data`, `pump_station_def_csky`, pstor актёра. Плюс движковые реестры актёра в `.sav`. При загрузке мира у не-мастера чужие задания, цели и стадии (наблюдение из плана: «выполнено задание от Хипа» после перезагрузки).
2. **Таблицы модулей по task_id**: `DATA[task_id]` у БТР, `M[task_id]` у RIOC и данных мутанта, `_m[task_id]` у химеры, `bounties_by_id[task_id]`. Второй держатель перезапишет данные первого (новые БТР, новый труп) или увидит чужие id.
3. **Повторный спаун**: задания спавнят при выдаче или в функторе на клиенте держателя. Двое → два набора (два трупа RIOC, две химеры, два комплекта БТР, два мёртвых отряда fate, два тайника). Отряды со `story_id` (`hostage_companion_task_1`, `ecolog_companion_task_1/2`, `bandit_companion_task_1`, `boss_sultan_task_5_*`, `lazarus_*_squad`, `degtyarev_taskforce_squad`…) — второй не регистрируется (`story_objects.script:6-13`).
4. **Стражи спауна как личные флаги** (`<task>_quest_item_received`, `_dead_spawned`, `_item_spawned`, `hostage_companion_task_1_started`, `spy_task_active`, `drx_sl_quest_item_task_N_started`, `pump_station_defense_task_smart_reserved`, `faction_base_defense_active`): с личными флагами они не защищают мир от второго спауна.
5. **Уборка одного ломает задание другого**: `on_complete/on_fail` первого (`veh_destroy_unset`, `recover_mutant_data_unset`, `remove_special_task_squad`, `cleanup_recover_item_on_corpse`, `forget_dead_npcs`, `pump_station_defense_task_cleanup`, `unlock_smart`, `sim_offline_combat.task_squads[...] = nil` в `tasks_chimera_scan.task_cleanup`) удаляет объекты. Функтор статуса второго тогда вернёт `"fail"` (предмет или цель пропали), исполнится **его `on_fail` со штрафом**. Отсюда правило порядка из §3.2: сначала мягкая отмена остальных, потом `on_complete` засчитанного. Уборку мира делать, когда держателей не осталось.
6. **Разные цели у «одного» задания**: выбор цели случаен и кэшируется на клиенте (`bounty_cache`, `cache_assault`, `delivery_cache`, `fate_cache`, кэш measure/spy/stash). Чтобы «одно задание у нескольких» было одним, выбор цели (`setup_*`) нужно делать общим для мира по паре заказчик + task_id (первый взявший фиксирует, остальные получают то же). Иначе правило «опоздал» должно сравнивать цели, а не id.
7. **Метки и пометки мира**: `stay_time`, `force_online`, `sim_offline_combat.task_squads`, `smart.locked`, `red_location` ставит и снимает клиент держателя. Снятие одним (`se_stalker.script:138-139` снимает `red_location` при смерти; `task_cleanup`) затрагивает другого. Метки карты лежат в одном общем реестре (`map_manager.cpp:115`), чужие метки заданий приедут с миром.
8. **Предусловия, завязанные на мир**, сами ограничивают задания «одним на мир»: заложник `!squad_exist(hostage_companion_task_1)`, оборона насосной `pump_station_defense_task_precondition`, барьер. Это совпадает с «один держатель», но правило «могут взять несколько» для этих типов не выполнится, пока цель не сделана общей.
9. **Проверки на `id == 0`**: `parent_id == 0` (данные мутанта, `tasks_recover_mutant_data.script:110,116`), `best_enemy():id() == 0` (насосная, `tasks_pump_station_defense.script:193-206`), `spawn_on_id(ITEM, 0)` (химера), `alife_create_item(…, db.actor)`. На каждом клиенте это «свой» актёр, что для личных заданий правильно. Но на клиенте хозяина уровня предмет у другого игрока будет у его «двойника», а не у 0, и проверки чужих заданий там не сработают. Проверки статуса надо исполнять на клиенте держателя.
10. **Флаги-факты о смерти** (`*_squad_dead` от `on_death`, П8) получит актёр того клиента, где отряд умер или где идёт логика уровня, а не держатель задания. 11 несюжетных заданий со ступенями lostzone, сюжет и «спец-отряды» не завершатся у держателя. Нужно сделать эти флаги общими.
11. **Движок**: повторная выдача того же id, пока у игрока такое задание в процессе, отклоняется (`GametaskManager.cpp:97-101`), а Lua к этому моменту уже перезаписал `task_info` (`task_manager.script:61-83` лишь пишет предупреждение) — рассинхрон. При синхронизации сюжета сначала проверять `db.actor:get_task(id, true)`.
12. **Счётчики заказчика** `drx_sl_task_giver_<giver_id>` (личные) — без проблем, если pstor личный. Но если мягкая отмена пропустит `drx_sl_unregister_task_giver`, счётчик у этого NPC останется завышенным.
13. **Задания-события мира** (барьер, насосная, оборона базы, выброс): одно на мир (`MDATA`, флаги `barrier_defense_*`); у второго держателя повторный старт волн. Насосная проваливается у держателя, ушедшего с уровня (`level.name() ~= 'k00_marsh'`, `tasks_pump_station_defense.script:459`).
14. **Запись при отказе от работы**: `on_job_descr` уже на этапе рассказа о работе пишет в pstor и задерживает отряд, даже если задание не взято.
