-- Shelter test copies only (deployed as gamedata\scripts\zz_base_test.script with zz_test_modes.script, not part of the
-- game): keys for going through проверки.md without waiting game weeks. A test mode: switched on in the F7 menu (tab
-- "toggle", "Тест: База"); the keys and what they do show at the left edge while it is on (the author's keyboard has
-- no numpad):
-- PgUp the window of "Cooling" now     PgDn the next rescue target for the next raid, in turn
-- Del  scientists and medic saved, Shurup hired, parts for all the base's work (the staff come at the next load of the
--      shelter)
-- Ins  the next crisis, in turn         End  the Scorcher on or off
-- ScrLk a decoder; the hack at 40 s     F6   2 game hours off the window (past the entry, then past its close)
-- F8   to the Radar, by X-10's door     F10  health and psi back
-- J    the base's clock 12 hours on (the clinic, the incubator, the autoclave, the technician)

local TARGETS = { "scientists", "medic", "frame", "sect" }
local CRISES = { "audit", "double", "snipers", "dry", "psi", "dump", "rats" }
local KIT = { "device_weather_radar", "detector_radio", "batteries_dead", "batteries_dead", "batteries_dead", "batteries_dead",
	"mutant_part_cat_thyroid", "af_drops", "drug_psy_blockade", "drug_psy_blockade", "drug_psy_blockade", "drug_psy_blockade",
	"drug_psy_blockade", "af_gravi", "af_gravi", "af_electra_flash", "af_electra_flash", "device_pda_3", "medium_repair_kit", "medium_repair_kit",
	"raid_incubator_frame", "exo_outfit" }

local function msg(s)
	actor_menu.set_msg(1, s, 6)
	printf("[base test] %s", s)
end

local turn_target, turn_crisis = 0, 0

local function press(dik)
	local k = DIK_keys
	if dik == k.DIK_NUMPAD1 then
		raid_window.force_open()
		msg("Окно открыто")
	elseif dik == k.DIK_NUMPAD2 then
		turn_target = turn_target % #TARGETS + 1
		local t = TARGETS[turn_target]
		shelter.set_state("rescue_done_" .. t, nil)
		shelter.set_state("rescue_lost_" .. t, nil)
		shelter.set_state("rescue_skip_next", nil)
		shelter.set_state("rescue_active", t)
		msg("Цель следующего рейда: " .. t)
	elseif dik == k.DIK_NUMPAD3 then
		shelter.set_state("rescue_done_scientists", true)
		shelter.set_state("rescue_done_medic", true)
		shelter.set_state("tech_hired", true)
		shelter.set_state("tech_new", true)
		for _, s in ipairs(KIT) do
			alife_create_item(s, db.actor)
		end
		shelter_trade.ledger_add("medkit", 20)
		shelter_trade.ledger_add("medium_repair_kit", 10)
		db.actor:give_money(500000)
		msg("Все спасены, Шуруп нанят, детали выданы. Сохранись и загрузись: персонал появится в убежище")
	elseif dik == k.DIK_NUMPAD4 then
		turn_crisis = turn_crisis % #CRISES + 1
		local id = CRISES[turn_crisis]
		if shelter_trade.crisis() then
			shelter_base.crisis_ended(shelter_trade.crisis())
		end
		shelter.set_state("crisis", id)
		shelter.set_state("crisis_until", shelter_trade.hours() + 48)
		shelter_base.crisis_started(id)
		msg("Кризис: " .. id)
	elseif dik == k.DIK_NUMPAD5 then
		if raid_window.off() then
			disable_info("bar_deactivate_radar_done")
			msg("Выжигатель работает")
		else
			give_info("bar_deactivate_radar_done")
			msg("Выжигатель отключён")
		end
	elseif dik == k.DIK_NUMPAD6 then
		if not shelter_scorcher.has_decoder() then
			alife_create_item(ini_sys:r_string_ex("shelter_scorcher", "decoder"), db.actor)
		end
		shelter.set_state("x10_left", 40)
		msg("Дешифратор выдан, подбор кода на 40 секунд")
	elseif dik == k.DIK_NUMPAD7 then
		local opened = tonumber(shelter.state("cool_open", nil)) or shelter_trade.hours()
		shelter.set_state("cool_open", opened - 2)
		msg("Окно: прошло ещё 2 игровых часа, всего " .. (shelter_trade.hours() - opened + 2))
	elseif dik == k.DIK_NUMPAD8 then
		local se = SIMBOARD.smarts_by_names["rad_antenna_camper"]
		if se then
			ChangeLevel(se.position, se.m_level_vertex_id, se.m_game_vertex_id, vector():set(0, 0, 0))
		end
	elseif dik == k.DIK_NUMPAD9 then
		db.actor:set_health_ex(1)
		db.actor.radiation = 0
		db.actor.bleeding = 1000
		arszi_psy.actor_on_item_use({ section = function() return "drug_anabiotic" end })
		msg("Здоровье и пси восстановлены")
	elseif dik == k.DIK_NUMPAD0 then
		shelter.set_state("base_last_hour", shelter_trade.hours() - 12)
		msg("Часы базы: +12")
	end
end

local function act(n)
	return function()
		press(DIK_keys["DIK_NUMPAD" .. n])
	end
end

function on_game_start()
	zz_test_modes.add("base", {
		name = "База",
		keys = {
			{ "DIK_PRIOR", "PgUp", "окно «Охлаждения» сейчас", act(1) },
			{ "DIK_NEXT", "PgDn", "следующая цель рейда (по кругу)", act(2) },
			{ "DIK_DELETE", "Del", "все спасены, Шуруп нанят, детали", act(3) },
			{ "DIK_INSERT", "Ins", "следующий кризис (по кругу)", act(4) },
			{ "DIK_END", "End", "Выжигатель вкл / выкл", act(5) },
			{ "DIK_SCROLL", "ScrLk", "дешифратор, взлом на 40 с", act(6) },
			{ "DIK_F6", "F6", "окно: прошло ещё 2 часа", act(7) },
			{ "DIK_F8", "F8", "на Радар, к двери X-10", act(8) },
			{ "DIK_F10", "F10", "здоровье и пси", act(9) },
			{ "DIK_J", "J", "часы базы +12 ч", act(0) },
		},
	})
end
