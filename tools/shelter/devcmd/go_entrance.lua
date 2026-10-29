-- to the bunker's entrance (point 1), as F8 does (zz_shelter_test)
local gg, sim = game_graph(), alife()
local pos = vector():set(-6.99, 3.28, -27.09)
local best, best_d
local gvid = 0
while gg:valid_vertex_id(gvid) do
	local v = gg:vertex(gvid)
	if sim:level_name(v:level_id()) == "bunker_a1" then
		local d = v:level_point():distance_to(pos)
		if not best_d or d < best_d then best, best_d = gvid, d end
	end
	gvid = gvid + 1
end
save_var(db.actor, "shelter_test_arriving", true)
CreateTimeEvent("shelter_test", "go", 0.5, function()
	ChangeLevel(pos, 1600, best, VEC_ZERO)
	return true
end)
return "going to the entrance, gvid " .. tostring(best)
