-- what every new game gives a loner and the start I made left out (items\settings\new_game_loadouts.ltx: [shared],
-- [stalker_loadout], the items that aren't optional)
local out = {}
for _, sec in ipairs({ "device_pda_1", "device_flashlight", "itm_backpack", "box_matches", "flask", "helm_resp", "stalker_patch" }) do
	if not db.actor:object(sec) then
		local se = alife_create_item(sec, db.actor)
		out[#out + 1] = sec .. (se and "" or " (failed)")
	end
end
return "given: " .. table.concat(out, ", ")
