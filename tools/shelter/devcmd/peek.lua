-- look at the mound for a screenshot, then put the player back where they stood
local back_pos = vector():set(db.actor:position())
local back_dir = db.actor:direction()
local target = vector():set(-2.4, 4.2, -16.0)
local eye = vector():set(-0.6, 2.95, -10.6)
db.actor:set_actor_position(eye)
local look = vector():set(target):sub(eye)
look.y = 0
db.actor:set_actor_direction(-look:normalize():getH())
CreateTimeEvent("shelter_peek", "shot", 1.5, function()
	get_console():execute("screenshot 0")
	CreateTimeEvent("shelter_peek", "back", 0.5, function()
		db.actor:set_actor_position(back_pos)
		db.actor:set_actor_direction(-back_dir:getH())
		return true
	end)
	return true
end)
return "peek"
