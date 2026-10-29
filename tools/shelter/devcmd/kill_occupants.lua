-- the shelter's occupants die by the player's hand; what they carry stays on them
local out = {}
level.iterate_nearest(vector():set(5, 3, -10), 40, function(obj)
	if (IsStalker(obj) or IsMonster(obj)) and obj:id() ~= AC_ID and obj:alive() then
		local p = obj:position()
		out[#out + 1] = string.format("%s at %.1f,%.1f,%.1f", obj:section(), p.x, p.y, p.z)
		obj:kill(db.actor)
	end
end)
return "killed: " .. table.concat(out, "; ")
