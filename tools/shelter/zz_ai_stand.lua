-- AI sight test stand (docs/coop/ai.md, "Тестовый стенд"). Not part of the mod: copy into a test copy as
-- gamedata\scripts\zz_ai_stand.script, with zz_test_modes.script. A test mode: switched on in the F7 menu (tab
-- "toggle", "Тест: Зрение ИИ"); its keys and readout show at the left edge while it is on.
--   Page Up  an observer 20 m ahead      Page Down  an observer 40 m ahead      Delete  remove the observers
--   Scroll Lock  grass hiding off / on (console ai_grass)
-- An observer is a friendly stalker who stands still and keeps looking at you (he never shoots). The readout per
-- observer: distance, whether he sees you now (npc:see), and what lies between his eyes and your head and your
-- waist: the share of sight the grass leaves (level.grass_transparency) and the bushes and other see-through
-- materials leave (the product of their vis_transparency_factor along the ray). An NPC sees through it while that
-- product stays above 0.73 calm / 0.6 in a fight.

local observers = {}
local next_at = 0
local OBSERVER = "sim_default_stalker_2"

local function say(text)
	actor_menu.set_msg(1, text, 4)
end

local function spawn(dist)
	local dir = device().cam_dir
	dir = vector():set(dir.x, 0, dir.z):normalize()
	local p = db.actor:position():add(dir:mul(dist))
	local lv = level.vertex_id(p)
	if lv >= 4294967295 then
		say("Нет AI-сетки в " .. dist .. " м впереди: повернись или отойди")
		return
	end
	local se = alife_create(OBSERVER, level.vertex_position(lv), lv, db.actor:game_vertex_id())
	if se then
		observers[se.id] = { dist = dist }
		say("Наблюдатель в " .. dist .. " м")
	end
end

local function clear()
	for id in pairs(observers) do
		local se = alife_object(id)
		if se then
			alife_release(se)
		end
	end
	observers = {}
	say("Наблюдатели убраны")
end

-- the share of sight the see-through static materials (bushes, nets, water) leave along the ray
local function materials(from, to)
	local vis, guard = 1, 0
	local dir = vector():set(to.x - from.x, to.y - from.y, to.z - from.z)
	local left = dir:magnitude()
	dir:normalize()
	local at = vector():set(from)
	while left > 0.05 and guard < 32 do
		guard = guard + 1
		local rp = ray_pick(at, dir, left, rq_target.rqtStatic, nil)
		if not rp:query() then
			break
		end
		local r = rp:get_result()
		local f = r and r.material_vis_transparency_factor or 0
		vis = vis * f
		if vis <= 0 then
			return 0
		end
		local step = rp:get_distance() + 0.05
		at = at:add(vector():set(dir):mul(step))
		left = left - step
	end
	return vis
end

local function point(obj, bone, dy)
	local ok, p = pcall(obj.bone_position, obj, bone)
	if ok and p then
		return p
	end
	return obj:position():add(vector():set(0, dy, 0))
end

local function status()
	local lines = { "Трава прячет: " .. (get_console():get_integer("ai_grass") == 0 and "%c[255,255,120,120]НЕТ%c[default]" or "да"),
		"видно, пока остаётся > 0.73 (спокойно) / > 0.6 (в бою)" }
	local head, waist = point(db.actor, "bip01_head", 1.6), point(db.actor, "bip01_pelvis", 0.9)
	for id in pairs(observers) do
		local npc = level.object_by_id(id)
		if npc and npc:alive() then
			local eye = point(npc, "bip01_head", 1.7)
			lines[#lines + 1] = string.format("%.0f м: %s", npc:position():distance_to(db.actor:position()),
				npc:see(db.actor) and "%c[255,255,90,90]ВИДИТ%c[default]" or "%c[255,120,255,120]не видит%c[default]")
			lines[#lines + 1] = string.format("   трава: голова %.2f, пояс %.2f", level.grass_transparency(eye, head), level.grass_transparency(eye, waist))
			lines[#lines + 1] = string.format("   кусты и пр.: голова %.2f, пояс %.2f", materials(eye, head), materials(eye, waist))
			if ai_tuning.detection_factor then
				local f, name, c = ai_tuning.detection_factor(npc, db.actor)
				lines[#lines + 1] = string.format("   замечает: x%.2f от обычного (%s, видно %.0f%%)", f, name, c * 100)
			end
		end
	end
	return lines
end

-- every frame while the mode is on: the observers stand and look at you
local function update()
	if not zz_test_modes.active("ai_stand") then
		return
	end
	local head = point(db.actor, "bip01_head", 1.6)
	for id, o in pairs(observers) do
		local npc = level.object_by_id(id)
		if npc and npc:alive() then
			if not o.set then
				o.set = true
				npc:set_relation(game_object.friend, db.actor)
				npc:movement_enabled(false)
			end
			npc:set_sight(look.point, head, 0)
		end
	end
end

local function grass()
	local on = get_console():get_integer("ai_grass") ~= 0
	exec_console_cmd("ai_grass " .. (on and 0 or 1))
	say(on and "Трава больше не прячет" or "Трава снова прячет")
end

function on_game_start()
	zz_test_modes.add("ai_stand", {
		name = "Зрение ИИ",
		keys = {
			{ "DIK_PRIOR", "PgUp", "наблюдатель в 20 м впереди", function() spawn(20) end },
			{ "DIK_NEXT", "PgDn", "наблюдатель в 40 м впереди", function() spawn(40) end },
			{ "DIK_DELETE", "Del", "убрать наблюдателей", clear },
			{ "DIK_SCROLL", "ScrLk", "трава прячет / не прячет", grass },
		},
		status = status,
		off = clear,
	})
	RegisterScriptCallback("actor_on_update", update)
end
