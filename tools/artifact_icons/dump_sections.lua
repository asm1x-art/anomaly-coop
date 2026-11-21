-- Run in game (a dev command or the console's Lua): writes <appdata>\artefact_sections.json, the artefacts as the game
-- has them after every config mod, for tools/artifact_icons/make_icons.py (copy it to tools/artifact_icons/sections.json).
local rows = {}
ini_sys:section_for_each(function(sec)
	local kind = ini_sys:r_string_ex(sec, "kind")
	if (kind == "i_arty" or kind == "i_arty_junk") and ini_sys:r_string_ex(sec, "visual") and ini_sys:r_string_ex(sec, "inv_name") then
		local fam = artefact_fx and artefact_fx.family_of and artefact_fx.family_of(sec)
			or (af_quality and af_quality.nature_of and af_quality.nature_of(sec)) or "plain"
		rows[#rows + 1] = string.format(
			'{"sec": "%s", "kind": "%s", "visual": "%s", "x": %d, "y": %d, "w": %d, "h": %d, "icons_texture": "%s", "family": "%s", "tier": %d}',
			sec, kind, string.gsub(ini_sys:r_string_ex(sec, "visual"), "\\", "\\\\"),
			ini_sys:r_float_ex(sec, "inv_grid_x") or 0, ini_sys:r_float_ex(sec, "inv_grid_y") or 0,
			ini_sys:r_float_ex(sec, "inv_grid_width") or 1, ini_sys:r_float_ex(sec, "inv_grid_height") or 1,
			string.gsub(ini_sys:r_string_ex(sec, "icons_texture") or "", "\\", "\\\\"), fam,
			ini_sys:r_float_ex(sec, "tier") or 0)
	end
end)
table.sort(rows)
local path = getFS():update_path("$app_data_root$", "artefact_sections.json")
local f = io.open(path, "w")
f:write("[\n" .. table.concat(rows, ",\n") .. "\n]\n")
f:close()
return #rows .. " -> " .. path
