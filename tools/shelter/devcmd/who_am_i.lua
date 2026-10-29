-- read-only: the player's faction, money, level and what they carry
local items = {}
db.actor:iterate_inventory(function(_, item) items[#items + 1] = item:section() end, db.actor)
local p = db.actor:position()
return string.format("%s community %s money %s at %.1f,%.1f,%.1f: %s", level.name(), character_community(db.actor), tostring(db.actor:money()),
	p.x, p.y, p.z, table.concat(items, ","))
