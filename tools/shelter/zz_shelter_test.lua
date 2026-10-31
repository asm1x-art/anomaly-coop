-- Shelter test copy only (H:\anomaly-shelter): F8 takes you to the bunker (bunker_a1, the entrance, point 1) and back
-- (back where you were, or to the Cordon village if you came in another way). F10 gives a demo's kit, F6 pushes the
-- synthesis questline on to the chambers (below). Digging the rubble goes faster here
-- (shelter.script, DIG); the rubble a save of 2026-10-28 holds stays frozen.
local BUNKER = "bunker_a1"
local ENTRANCE = { pos = vector():set(-6.99, 3.28, -27.09), lvid = 1600, look = vector():set(0.978, 0, -0.124) } -- point 1
local back = nil -- where we came from: { pos, lvid, gvid }

local function msg(text)
	actor_menu.set_msg(1, text, 6)
end

-- the level's game vertex nearest a point of it
local function level_vertex(level_name, pos)
	local gg, sim = game_graph(), alife()
	local best, best_d
	local gvid = 0
	while gg:valid_vertex_id(gvid) do
		local v = gg:vertex(gvid)
		if sim:level_name(v:level_id()) == level_name then
			local d = v:level_point():distance_to(pos)
			if not best_d or d < best_d then
				best, best_d = gvid, d
			end
		end
		gvid = gvid + 1
	end
	return best
end

-- F10: a demo's kit, to show the shelter quickly: shovels for the rubble, Kardan's tools and an electric artefact for
-- the generator (another for the Brigadier's helmet module), the laptop, an empty capsule of each nature for the
-- synthesis chambers, the junk of the Chemist's recipes, a sleeping bag to wait out a synthesis
local KIT = {
	"shovel_mili", "shovel_mili", "shovel_mili",
	"shelter_generator_tools", "af_electra_flash", "af_electra_flash",
	"shelter_laptop_item",
	"shelter_capsule_gravi", "shelter_capsule_thermo", "shelter_capsule_chem", "shelter_capsule_electro",
	"ball_hammer", "steel_wool", "grease", "tarpaulin", "e_syringe", "jar", "radio2", "duct_tape",
	"itm_sleepbag",
	"prt_i_textolite", "prt_i_textolite", "prt_i_copper", "prt_i_copper", "prt_i_resistors", "prt_i_resistors", -- the lift
	"prt_i_capacitors", "prt_i_capacitors", "prt_i_transistors", "prt_i_transistors", "prt_i_copper", -- its control box
}
-- and in the bunker an anomaly of each nature in a row across the hall where the water was (point 5), for the capsules
-- (once a game), made as the synthesis chambers' are: the shape set before it's online, as a zone with none crashes
-- the game
local DEMO_ANOMALIES = {
	{ "zone_mine_gravitational_weak", vector():set(12.6, 1.45, -14.7) },
	{ "zone_mine_thermal_weak", vector():set(15.4, 1.45, -14.7) },
	{ "zone_mine_acidic_weak", vector():set(18.2, 1.45, -14.7) },
	{ "zone_mine_electric_weak", vector():set(21.7, 1.45, -14.7) },
}
local DEMO_ANOMALY_RADIUS = 1

local function spawn_demo_anomalies()
	if level.name() ~= BUNKER or load_var(db.actor, "shelter_demo_anomalies") then
		return false
	end
	for _, a in ipairs(DEMO_ANOMALIES) do
		local lv = level.vertex_id(a[2])
		if lv < 4294967295 then
			local se = alife_create(a[1], level.vertex_position(lv), lv, db.actor:game_vertex_id())
			local data = se and utils_stpk.get_anom_zone_data(se)
			if data then
				data.shapes[1] = { shtype = 0, offset = vector():set(0, 0, 0), center = vector():set(0, 0, 0),
					radius = DEMO_ANOMALY_RADIUS }
				utils_stpk.set_anom_zone_data(data, se)
			elseif se then
				alife_release(se)
			end
		else
			printf("! [shelter test] no AI vertex for %s at %s", a[1], vec_to_str(a[2]))
		end
	end
	save_var(db.actor, "shelter_demo_anomalies", true)
	return true
end

local function give_kit()
	for _, sec in ipairs(KIT) do
		if ini_sys:section_exist(sec) then
			alife_create_item(sec, db.actor)
		else
			printf("! [shelter test] no section %s", sec)
		end
	end
	local anomalies = spawn_demo_anomalies() and " В зале, где была вода, — по аномалии каждой природы." or ""
	local group = coop and coop.connected and coop.connected() and #coop.group() < 2
		and " Вы не в группе: в коопе задания убежища даются только группе." or ""
	msg("Демо-набор выдан, что в нём — в сообщениях ПДА.")
	db.actor:give_game_news("Тест убежища", "Демо-набор: лопаты, инструменты Кардана, две «Вспышки», ноутбук, хлам для"
		.. " рецептов, спальник, 4 пустые капсулы: наполнить в аномалиях в СЕВА Химика или костюме эколога, или F6 — сразу"
		.. " наполненные и задания синтеза." .. anomalies .. group, "ui_inGame2_Poslednie_razrabotki", 0, 20000)
end

-- F6: the synthesis questline pushed on to the chambers, as if the idea were read, Herman's eight capsules filled and
-- his half paid: the empty capsules carried become a full one of each nature
local NATURES = { "gravi", "thermo", "chem", "electro" }

local function push_synthesis()
	local tm = task_manager.get_task_manager()
	if not db.actor:get_task("shelter_synthesis", true) then
		give_info("shelter_idea_synthesis_read")
		tm:give_task("shelter_synthesis")
	end
	give_info("shelter_capsules_got")
	local empty = {}
	db.actor:iterate_inventory(function(_, item)
		local sec = item:section()
		for _, n in ipairs(NATURES) do
			if sec == "shelter_capsule_" .. n then
				empty[#empty + 1] = item
			end
		end
	end, db.actor)
	for _, item in ipairs(empty) do
		alife_release(item)
	end
	shelter_synthesis.take_quietly(3000) -- the full ones aren't picked up in a suit
	for _, n in ipairs(NATURES) do
		shelter.set_state("capsules_filled_" .. n, 2)
		if not db.actor:get_task("shelter_synthesis_" .. n, true) then
			tm:give_task("shelter_synthesis_" .. n)
		end
		if not db.actor:object("shelter_capsule_" .. n .. "_full") then
			alife_create_item("shelter_capsule_" .. n .. "_full", db.actor)
		end
	end
	give_info("shelter_capsules_paid")
	msg("Синтез: капсулы наполнены, Герману отдано. Осталось поставить 4 наполненные капсулы в камеры у входа.")
end

-- INSERT: every rubble of the bunker gone in this save, the ones not meant for digging too (the stairs' mounds 2 and 4):
-- counted as dug out, so they don't come back and their rooms open for the cleaning. Kept only in the save made after.
local RUBBLE = { 2, 3, 4, 8, 9, 10, 11, 12, 13 }

function clear_rubble()
	local sim = alife()
	local removed = 0
	for _, n in ipairs(RUBBLE) do
		local section = "shelter_mound_" .. n
		shelter.set_state("dug_" .. section, true)
		local zone = ini_sys:r_string_ex(section, "shelter_zone")
		if zone then
			shelter.set_state("open_" .. zone, true)
		end
		local var = "shelter_keep_out_" .. section
		local keep_out = load_var(db.actor, var, nil)
		local se = keep_out and sim:object(keep_out)
		if se and se:section_name() == "space_restrictor" then
			alife_release(se)
		end
		save_var(db.actor, var, nil)
	end
	for id = 1, 65534 do
		local se = sim:object(id)
		local section = se and se:section_name()
		if section and (string.find(section, "^shelter_mound_") or string.find(section, "^shelter_rubble_")) then
			alife_release(se)
			removed = removed + 1
		end
	end
	msg("Завалы убраны: " .. removed .. ". Останется в сохранении, сделанном после этого.")
	return removed
end

-- End: one of each pack's things into the shelter's stash, to try them (tools\\shelter\\packs.json)
function fill_stash()
	local id = shelter.state("stash_id", nil)
	local box = id and alife_object(id)
	if not box then
		return msg("no stash yet")
	end
	local ini = ini_sys
	local n = 0
	for i = 0, ini:line_count("shelter_pack_items") - 1 do
		local _, sec = ini:r_line_ex("shelter_pack_items", i, "", "")
		if sec and ini:section_exist(sec) then
			alife_create_item(sec, box)
			n = n + 1
		end
	end
	msg("packs: " .. n .. " things in the stash; H, the arrows go through the categories")
	return n
end

local function on_key_press(dik)
	if dik == DIK_keys.DIK_END and db.actor then
		return fill_stash()
	end
	if dik == DIK_keys.DIK_INSERT and db.actor then
		return clear_rubble()
	end
	if dik == DIK_keys.DIK_F10 and db.actor then
		return give_kit()
	elseif dik == DIK_keys.DIK_F6 and db.actor then
		return push_synthesis()
	end
	if dik ~= DIK_keys.DIK_F8 or not db.actor then
		return
	end
	if level.name() == BUNKER then
		if back then
			ChangeLevel(back.pos, back.lvid, back.gvid, VEC_ZERO)
			return
		end
		-- came in some other way: the Cordon village
		local smart = SIMBOARD and SIMBOARD.smarts_by_names["esc_smart_terrain_2_12"]
		if smart then
			ChangeLevel(smart.position, smart.m_level_vertex_id, smart.m_game_vertex_id, VEC_ZERO)
		else
			msg("Обратно некуда: деревня новичков не найдена")
		end
		return
	end
	local gvid = level_vertex(BUNKER, ENTRANCE.pos)
	if not gvid then
		return msg("Бункер не найден в графе: пакет локации не подключился (см. лог, [spawn_overlays])")
	end
	back = { pos = db.actor:position(), lvid = db.actor:level_vertex_id(), gvid = db.actor:game_vertex_id() }
	save_var(db.actor, "shelter_test_arriving", true)
	ChangeLevel(ENTRANCE.pos, ENTRANCE.lvid, gvid, VEC_ZERO)
end

-- the rubble of the save of 2026-10-28 (shelter_rubble_* sections): stays where it was put
class "shelter_block_binder" (object_binder)
function shelter_block_binder:__init(obj) super(obj)
	self.frozen = false
end
function shelter_block_binder:update(delta)
	object_binder.update(self, delta)
	if not self.frozen then
		local shell = self.object:get_physics_shell()
		if shell then
			shell:freeze()
			self.frozen = true
		end
	end
end
function init_block(obj)
	obj:bind_object(shelter_block_binder(obj))
end

function on_game_start()
	RegisterScriptCallback("on_key_press", on_key_press)
	-- digging: 8 strokes a shovel, not 40
	shelter.DIG.wear = 0.125
	shelter.DIG.stroke = 1250
	RegisterScriptCallback("actor_on_first_update", function()
		-- a game started from the command line has no faction: a loner, so fast travel has its points (the option shows
		-- them all, visited or not) and traders talk
		if character_community(db.actor) == "actor" then
			db.actor:set_character_community("actor_stalker", 0, 0)
			game_fast_travel.update_settings()
		end
		if level.name() == BUNKER then
			if load_var(db.actor, "shelter_test_arriving") then
				save_var(db.actor, "shelter_test_arriving", nil)
				db.actor:set_actor_direction(-ENTRANCE.look:getH())
			end
			msg("Бункер. F8 — обратно, INSERT — убрать все завалы")
		else
			msg("Тест убежища: F8 — в бункер и обратно, F10 — демо-набор, INSERT — убрать все завалы, F6 — капсулы наполнены и отданы Герману")
		end
	end)
end
