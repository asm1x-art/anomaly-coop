-- the questline's state, read-only: power, lamps, the tasks' stages
local lamps, on = 0, 0
level.iterate_nearest(vector():set(3, 4, 0), 45, function(obj)
	local lamp = obj:clsid() == clsid.hlamp_s and obj:get_hanging_lamp()
	if lamp then
		lamps = lamps + 1
		if lamp:is_on() then on = on + 1 end
	end
end)
local out = { string.format("repaired %s powered %s lamps %s on %s", tostring(load_var(db.actor, "shelter_generator_repaired", false)),
	tostring(load_var(db.actor, "shelter_generator_powered", false)), tostring(lamps), tostring(on)) }
for _, t in ipairs({ "shelter_laptop", "shelter_tools" }) do
	local task = db.actor:get_task(t, true)
	local obj = task_manager.get_task_manager().task_info[t]
	out[#out + 1] = string.format("%s: %s stage %s status %s", t, task and game.translate_string(task:get_title()) or "none",
		obj and tostring(obj.stage) or "-", obj and tostring(obj.status) or "-")
end
local item_names = {}
for _, s in ipairs({ "shelter_note", "shelter_generator_tools", "shelter_af_container", "shelter_laptop_item", "shelter_stalker_pda", "af_electra_sparkler" }) do
	if db.actor:object(s) then item_names[#item_names + 1] = s end
end
out[#out + 1] = "carrying: " .. table.concat(item_names, ",")
return table.concat(out, " | ")
