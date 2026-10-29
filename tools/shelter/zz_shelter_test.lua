-- Shelter test copy only (H:\anomaly-shelter): F8 takes you to the bunker (bunker_a1, the entrance, point 1) and back
-- (back where you were, or to the Cordon village if you came in another way). Digging the rubble goes faster here
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

local function on_key_press(dik)
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
			msg("Бункер. F8 — обратно")
		else
			msg("Тест убежища: F8 — в бункер и обратно")
		end
	end)
end
