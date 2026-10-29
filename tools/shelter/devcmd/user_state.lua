-- read-only: where the player is in the shelter questline; bodies near them and the note
local out = { "level " .. level.name() }
local p = db.actor:position()
out[#out + 1] = string.format("at %.1f,%.1f,%.1f", p.x, p.y, p.z)
for _, i in ipairs({ "shelter_note_read", "shelter_laptop_asked", "shelter_container_given", "shelter_laptop_got", "shelter_laptop_installed", "shelter_tools_asked", "shelter_pda_returned" }) do
	if has_alife_info(i) then out[#out + 1] = "+" .. i end
end
local carry = {}
for _, s in ipairs({ "shelter_note", "shelter_generator_tools", "shelter_af_container", "shelter_laptop_item", "shelter_stalker_pda", "zat_a23_access_card" }) do
	if db.actor:object(s) then carry[#carry + 1] = s end
end
out[#out + 1] = "carrying: " .. table.concat(carry, ",")
level.iterate_nearest(p, 40, function(obj)
	if (IsStalker(obj) or IsMonster(obj)) and obj:id() ~= AC_ID then
		local items = {}
		if IsStalker(obj) then
			obj:iterate_inventory(function(_, item) items[#items + 1] = item:section() end, obj)
		end
		out[#out + 1] = string.format("%s alive=%s [%s]", obj:section(), tostring(obj:alive()), table.concat(items, ","))
	end
end)
return table.concat(out, " | ")
