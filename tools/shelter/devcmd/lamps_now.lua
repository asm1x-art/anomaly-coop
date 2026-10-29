-- read-only: the bunker's lamps that are on or flickering right now, and the player's torch and active item
local on = {}
level.iterate_nearest(vector():set(3, 4, 0), 45, function(obj)
	local lamp = obj:clsid() == clsid.hlamp_s and obj:get_hanging_lamp()
	if lamp and (lamp:is_on() or lamp:is_flickering()) then
		local p = obj:position()
		on[#on + 1] = string.format("%s on=%s flick=%s at %.1f,%.1f,%.1f", obj:name(), tostring(lamp:is_on()), tostring(lamp:is_flickering()), p.x, p.y, p.z)
	end
end)
local torch = db.actor:item_in_slot(10)
local active = db.actor:active_item()
return string.format("lamps on: %d %s | torch %s | active item %s | powered %s", #on, table.concat(on, "; "),
	torch and tostring(torch:torch_enabled()) or "none", active and active:section() or "none",
	tostring(load_var(db.actor, "shelter_generator_powered", false)))
