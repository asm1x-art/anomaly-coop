local gg, sim = game_graph(), alife()
local n, gvid = 0, 0
while gg:valid_vertex_id(gvid) do
	if sim:level_name(gg:vertex(gvid):level_id()) == "bunker_a1" then n = n + 1 end
	gvid = gvid + 1
end
local p = db.actor:position()
return string.format("level=%s pos=%.1f,%.1f,%.1f bunker_vertices=%d", level.name(), p.x, p.y, p.z, n)
