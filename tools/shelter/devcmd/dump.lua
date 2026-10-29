-- copy files out of the game archives into appdata\dump
local fs = getFS()
local files = {
	{ "$game_textures$", [[prop\prop_kucha.dds]] },
	{ "$game_textures$", [[crete\crete_debris_01.dds]] },
	{ "$game_textures$", [[crete\crete_beton_lom.dds]] },
	{ "$game_textures$", [[garbage\garbage_small_l_heap.dds]] },
	{ "$game_textures$", [[floor\floor_pol_musor_kroska.dds]] },
	{ "$game_textures$", [[amik\nature\stonedebris1.dds]] },
	{ "$game_textures$", [[crete\crete_beton_slag.dds]] },
	{ "$game_textures$", [[ston\ston_beton_lom_iov.dds]] },
	{ "$game_meshes$", [[dynamics\large_trash\aes_zabor.ogf]] },
}
local dir = fs:update_path("$app_data_root$", "dump\\")
local out = {}
for _, f in ipairs(files) do
	local r = fs:r_open(f[1], f[2])
	if r then
		local bytes, n = {}, 0
		while not r:r_eof() do
			n = n + 1
			bytes[n] = string.char(r:r_u8())
		end
		local name = f[2]:gsub("\\", "__")
		local h = io.open(dir .. name, "wb")
		h:write(table.concat(bytes))
		h:close()
		out[#out + 1] = name .. " " .. n
	else
		out[#out + 1] = f[2] .. " missing"
	end
end
return table.concat(out, "; ")
