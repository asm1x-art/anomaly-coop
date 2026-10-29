-- every hanging lamp of the bunker's middle floor, its state read past the saved bone positions (utils_stpk doesn't skip
-- them): name, where, angle, visual, colour animator, range, brightness, colour, flags
local function lamp_data(se)
	local p = net_packet()
	p:w_begin(0)
	se:STATE_Write(p)
	p:r_seek(2)
	local t = {}
	utils_stpk.parse_cse_alife_object_properties_packet(t, p)
	utils_stpk.parse_cse_visual_properties_packet(t, p)
	utils_stpk.parse_cse_ph_skeleton_properties_packet(t, p)
	if bit_and(t.skeleton_flags, 4) ~= 0 then -- flSavedData: mask u64, root u16, min, max, count u16, 8 bytes a bone
		for _ = 1, 8 + 2 + 24 do p:r_u8() end
		local count = p:r_u16()
		for _ = 1, count * 8 do p:r_u8() end
	end
	utils_stpk.parse_cse_alife_object_hanging_lamp_properties_packet(t, p)
	return t
end

local lines = {}
level.iterate_nearest(vector():set(3, 4, 0), 45, function(obj)
	local lamp = obj:clsid() == clsid.hlamp_s and obj:get_hanging_lamp()
	if lamp then
		local se = alife_object(obj:id())
		local d = lamp_data(se)
		local p, a = se.position, se.angle
		lines[#lines + 1] = string.format("%s|%d|%.2f,%.2f,%.2f|ang %.2f,%.2f,%.2f|%s|anim=%s|range=%.1f|bright=%.2f|color=%08x|flags=%d|tex=%s|bone=%s|fixed=%s|sk=%d", obj:name(), obj:id(),
			p.x, p.y, p.z, a.x, a.y, a.z, d.visual_name, d.main_color_animator, d.main_range, d.main_brightness, d.main_color, d.light_flags,
			d.main_texture, d.main_bone, d.lamp_fixed_bones, d.skeleton_flags)
	end
end)
local f = io.open(getFS():update_path("$app_data_root$", "lamps_info.txt"), "w")
f:write(table.concat(lines, "\n"))
f:close()
return #lines .. " lamps"
