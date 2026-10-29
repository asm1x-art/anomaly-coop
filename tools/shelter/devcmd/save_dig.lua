-- save the game before the restart
get_console():execute("save shelter_before_line")
local p = db.actor:position()
return string.format("saved at %.1f,%.1f,%.1f", p.x, p.y, p.z)
