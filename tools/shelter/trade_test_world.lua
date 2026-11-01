-- trade_test.py's second part: a small mock world for the store's scan, the hourly loop, withdrawing, the courier's
-- case, handing in; then the Trade app with the real texts (each %s, %d against its arguments), every button pressed.
local bar, orders = shelter_trade, shelter_orders
local missing = {}
game.translate_string = function(id)
	if not py_has_text(id) then
		missing[id] = true
	end
	return py_text(id)
end

local OBJ = {}
local next_id = 10
local function new_se(section, parent, x, z, extra)
	next_id = next_id + 1
	local se = extra or {}
	se.id, se.parent_id, se.position = next_id, parent or 65535, { x = x or 0, y = 3, z = z or 0 }
	se.m_game_vertex_id, se.m_level_vertex_id = 1, 1
	se.section_name = function() return section end
	se.clsid = function() return se.is_box and 1 or 2 end
	OBJ[next_id] = se
	return se
end
function alife()
	return { object = function(_, id) return OBJ[id] end, level_name = function() return "bunker_a1" end }
end
function alife_object(id) return OBJ[id] end
function alife_release(se) OBJ[se.id] = nil end
function game_graph()
	return { vertex = function() return { level_id = function() return 1 end } end }
end
function IsInvbox(_, c) return c == 1 end
function ini_file()
	return { r_string_ex = function(_, room) return room == "room_y" and "20,30,20,30" or "0,10,0,10" end }
end
utils_stpk = {
	get_ammo_data = function(se) return { ammo_left = se.ammo } end,
	get_item_data = function(se) return { condition = se.cond or 1 } end,
}
local CREATED = {}
function alife_create(sec) return new_se(sec) end
function alife_create_item(sec, owner)
	CREATED[#CREATED + 1] = sec
	return new_se(sec, 0)
end
function create_ammo(sec, pos, lv, gv, pid, n)
	CREATED[#CREATED + 1] = sec .. "*" .. n
	new_se(sec, pid, 0, 0, { ammo = n })
end
function CreateTimeEvent(a, b, c, f) f() end
local MARKED
level = {
	name = function() return "bunker_a1" end,
	get_start_time = function() return 0 end,
	get_time_hours = function() return 12 end,
	get_time_minutes = function() return 0 end,
	map_has_object_spot = function() return 0 end,
	map_add_object_spot_ser = function(id) MARKED = id end,
}
local CLOCK = 0
game.get_game_time = function() return { diffSec = function() return CLOCK end } end
local MONEY = 500000
db = { actor = {
	money = function() return MONEY end,
	give_money = function(_, n) MONEY = MONEY + n end,
	id = function() return 0 end,
	position = function() return { x = 0, y = 0, z = 0 } end,
	level_vertex_id = function() return 1 end,
	game_vertex_id = function() return 1 end,
	give_game_news = function() end,
} }
local VARS = {}
function load_var(_, k, d)
	local v = VARS[k]
	if v == nil then
		return d
	end
	return v
end
function save_var(_, k, v) VARS[k] = v end

for k in pairs(WORLD) do
	WORLD[k] = nil
end
GOODWILL = 0
WORLD.room_store = "room_x"
WORLD.barman = "hired"

-- the store
local store = new_se("shelter_stash", nil, 5, 5, { is_box = true })
new_se("vodka", store.id)
new_se("vodka", store.id)
new_se("wpn_svd", store.id, 0, 0, { cond = 0.6 })
new_se("ammo_9x19_fmj", store.id, 0, 0, { ammo = 15 })
new_se("af_electra_flash", store.id, 0, 0, { cond = 0.9 })
new_se("shelter_note", store.id)
local goods = bar.stock()
assert(#goods == 5, "goods in the store, the note isn't: " .. #goods)
local p_by = {}
for _, p in ipairs(bar.positions(goods)) do
	p_by[p.section] = p
end
assert(p_by.ammo_9x19_fmj.crates == 15, "rounds counted")
assert(math.abs(p_by.wpn_svd.cond - 0.6) < 1e-6, "cond")
assert(p_by.af_electra_flash.on == false, "artefact off")

-- withdrawing
bar.ledger_add("ammo_9x19_fmj", 100)
bar.ledger_add("vodka", 3)
assert(bar.withdraw("ammo_9x19_fmj", 15) == 15, "withdrawn")
assert(CREATED[#CREATED] == "ammo_9x19_fmj*15", "made as rounds")
assert(bar.withdraw("vodka", 99) == 3, "only as many as there are")
assert((bar.ledger().vodka or 0) == 0, "ledger empty of vodka")

-- the loop: an artefact off sale stays
local update
function RegisterScriptCallback(name, f)
	if name == "actor_on_update" and not update then
		update = f
	end
end
bar.on_game_start()
local tick_ms = 0
function time_global()
	tick_ms = tick_ms + 10000
	return tick_ms
end
update()
CLOCK = 3600 * 24 * 3
for _ = 1, 40 do
	update()
	CLOCK = CLOCK + 3600
end
assert(OBJ[store.id], "the box stays")
local flash = 0
for _, se in pairs(OBJ) do
	if se.section_name() == "af_electra_flash" then
		flash = flash + 1
	end
end
assert(flash == 1, "the off-sale artefact wasn't sold")
assert((WORLD.eco_hours or 0) >= 72, "hours counted")
assert((WORLD.bar_total or 0) > 0, "something sold")

-- the courier's case
local sup = orders.supplier("barman")
sup.intercept = 1
local SQUAD
local smart = { position = {}, m_level_vertex_id = 1, m_game_vertex_id = 1 }
SIMBOARD = { smarts_by_names = { rad_entrance = smart, mil_smart_terrain_8_3 = smart }, create_squad = function() SQUAD = true end }
WORLD.till = 5000000
local lot = orders.lots(sup, "vodka")[1]
local money0 = MONEY
assert(orders.order(sup, "vodka", lot, "pocket"), "paid by pocket")
assert(MONEY == money0 - lot.total, "pocket down")
WORLD.eco_hours = WORLD.eco_hours + 100
orders.on_hours()
local d = orders.deliveries()[1]
assert(d and d.state == "sos", "intercepted")
assert(SQUAD, "a squad on it")
local upd, take
function RegisterScriptCallback(name, f)
	if name == "actor_on_item_take" then
		take = f
	elseif name == "actor_on_update" then
		upd = f
	end
end
orders.on_game_start()
upd()
assert(MARKED == d.cargo, "marked on the map")
local before = bar.ledger().vodka or 0
take({ section = function() return "shelter_cargo" end, id = function() return d.cargo end })
assert(bar.ledger().vodka == before + 20, "the lot from the case")
assert(#orders.deliveries() == 0, "done")
assert(OBJ[d.cargo] == nil, "the case gone")

-- a case not reached in time is looted
assert(orders.order(sup, "vodka", lot, "till"), "till")
WORLD.eco_hours = WORLD.eco_hours + 100
orders.on_hours()
d = orders.deliveries()[1]
assert(d.state == "sos", "intercepted again")
WORLD.eco_hours = WORLD.eco_hours + 7
orders.on_hours()
assert(#orders.deliveries() == 0 and OBJ[d.cargo] == nil, "looted")
sup.intercept = 0.15

-- handing in: through the box picked, wherever it stands
local obox = new_se("shelter_stash", nil, 25, 25, { is_box = true })
assert(bar.orders_box() == nil and #bar.orders_items() == 0, "no box yet")
bar.set_orders_box(obox.id)
assert(bar.orders_box() == obox, "the box picked")
WORLD.offer_next = 1e9
WORLD.contracts = "7|duty_post|ammo_9x19_fmj*20,wpn_svd*1|12345|99999|1|99999|"
local c = orders.contracts()[1]
assert(select(2, orders.progress(c)) == false, "not ready")
new_se("ammo_9x19_fmj", obox.id, 0, 0, { ammo = 30 })
assert(select(2, orders.progress(c)) == false, "still not")
new_se("wpn_svd", obox.id, 0, 0, { cond = 0.95 })
assert(select(2, orders.progress(c)) == true, "ready")
assert(next(orders.wanted()) ~= nil, "wanted")
local till0 = WORLD.till
assert(orders.hand_in(7), "handed in")
assert(WORLD.till == till0 + 12345, "paid into the till")
assert(GOODWILL > 0, "goodwill")
local rest = 0
for _, se in pairs(OBJ) do
	if se.parent_id == obox.id then
		rest = rest + (se.ammo or 100)
	end
end
assert(rest == 10, "the rest of the box stays: " .. rest)
assert(orders.discount("petrenko") > 0, "discount")

-- the orders' box in the store's room isn't the store
local inroom = new_se("placeable_blue_box", nil, 5, 5, { is_box = true })
new_se("beer", inroom.id)
local beers = 0
for _, g in ipairs(bar.stock()) do
	beers = beers + (g.section == "beer" and 1 or 0)
end
assert(beers == 1, "in the store while it's an ordinary box")
bar.set_orders_box(inroom.id)
beers = 0
for _, g in ipairs(bar.stock()) do
	beers = beers + (g.section == "beer" and 1 or 0)
end
assert(beers == 0, "not in the store as the orders' box")
assert(#bar.orders_items() == 1, "in the orders' box")
local listed = 0
for _, b in ipairs(bar.boxes()) do
	if b.id == inroom.id then
		listed = b.count
	end
end
assert(listed == 1, "the box listed with what it holds")
for _, b in ipairs(bar.boxes()) do
	assert(b.section ~= "shelter_stash", "the stash isn't offered")
end

-- furniture isn't goods
local get_param = SYS_GetParam
SYS_GetParam = function(kind, s, k, d)
	if k == "use1_functor" and s == "vodka" then
		return "placeable_furniture.place_item"
	end
	return get_param(kind, s, k, d)
end
assert(bar.category("vodka") == nil, "furniture isn't goods")
SYS_GetParam = get_param
assert(bar.category("vodka") ~= nil, "vodka is")
bar.set_orders_box(obox.id)

-- a missed contract costs goodwill as the news is heard
GOODWILL = 100
VARS.shelter_eco_heard = WORLD.eco_news_seq
WORLD.contracts = "8|duty_post|vodka*1|100|99999|1|0|"
orders.on_hours()
update()
assert(GOODWILL == 50, "penalty applied: " .. GOODWILL)

-- the visitors of whole days, as things stand: how many came each day; the store left as it is
local function days_of_visitors(days)
	local counts = {}
	WORLD.bar_last, WORLD.visitors_day = CLOCK, nil
	WORLD.crisis, WORLD.crisis_next = nil, 1e9
	WORLD.offer_next = 1e9
	-- from the start of a world day
	WORLD.eco_hours = math.floor((WORLD.eco_hours + 24) / 24) * 24 - 1
	for d = 1, days do
		local before = (WORLD.bar_served or 0) + (WORLD.bar_left or 0)
		for _ = 1, 24 do
			CLOCK = CLOCK + 3600
			update()
		end
		counts[d] = (WORLD.bar_served or 0) + (WORLD.bar_left or 0) - before
	end
	return counts
end
local function in_range(counts, a, b, what)
	local sum = 0
	for _, n in ipairs(counts) do
		assert(n >= a and n <= b, what .. ": " .. n .. " visitors a day, not " .. a .. "-" .. b)
		sum = sum + n
	end
	return sum / #counts
end
local keep_ledger, keep_rep, keep_store = WORLD.bar_ledger, WORLD.bar_rep, WORLD.room_store

-- the worst: nothing on sale, no name
WORLD.bar_ledger, WORLD.room_store, WORLD.bar_rep = "vodka=0", "room_empty", 0
for id, se in pairs(OBJ) do
	if se.is_box and se.position.x == 5 then
		se.position = { x = 500, y = 3, z = 500 }
	end
end
local worst = in_range(days_of_visitors(30), 3, 5, "the worst")

-- the best: all categories full, a fair price, a name
local secs = { "conserva", "tushonka", "bread", "kolbasa", "mre", "vodka", "beer", "cigarettes", "mineral_water", "energy_drink",
	"medkit", "bandage", "antirad", "medkit_army", "glucose", "ammo_9x19_fmj", "ammo_9x18_fmj", "ammo_5.45x39_fmj", "ammo_12x70_buck", "ammo_11.43x23_fmj",
	"wpn_svd", "wpn_ak74", "wpn_pm", "wpn_beretta", "wpn_colt1911", "exo_outfit", "stalker_outfit", "novice_outfit", "scientific_outfit", "svoboda_light_outfit",
	"grenade_f1", "grenade_rgd5", "gun_oil", "light_repair_kit", "medium_repair_kit" }
for _, sec in ipairs(secs) do
	if bar.category(sec) then
		bar.ledger_add(sec, 100000)
	end
end
WORLD.bar_rep = 100
bar.set_markup(1)
local best = in_range(days_of_visitors(30), 12, 14, "the best")
bar.set_markup(1.1)

-- no barman: no visitors, no new offers, the world's hours go on
WORLD.barman = nil
local total0, hours0 = WORLD.bar_total, WORLD.eco_hours
WORLD.contracts, WORLD.offer_next = nil, 0
in_range(days_of_visitors(3), 0, 0, "no barman")
WORLD.offer_next = 0
orders.on_hours()
assert(#orders.contracts() == 0, "no offers without a barman")
assert(WORLD.bar_total == total0, "nothing sold without a barman")
assert(WORLD.eco_hours > hours0, "the hours go on")
-- hired: out of the pocket
MONEY = 100
assert(bar.hire_barman() == false and WORLD.barman == nil, "no money, no barman")
MONEY = 100000
assert(bar.hire_barman() and WORLD.barman == "hired", "hired")
assert(MONEY == 100000 - bar.barman_cost(), "paid for")
WORLD.bar_ledger, WORLD.bar_rep, WORLD.room_store = keep_ledger, keep_rep, keep_store
VISITORS = string.format("visitors a day: %.1f at the worst, %.1f at the best", worst, best)

-- the Trade app
CGameFont = { alLeft = 0, alCenter = 1, alRight = 2 }
local function widget()
	return setmetatable({}, { __index = function(_, k)
		return function()
			if k == "GetText" then
				return ""
			end
		end
	end })
end
ui_shelter_style = { C = setmetatable({}, { __index = function() return { 1, 2, 3 } end }) }
local drawn = 0
local function make_os()
	local os = { wx = 0, wy = 0, app_clicks = {}, xml = { InitEditBox = function() return widget() end } }
	function os:place() end
	function os:text(x, y, w, h, str)
		assert(type(str) == "string", "a text not a string: " .. tostring(str))
		assert(not string.find(str, "!!NO TEXT", 1, true), str)
		drawn = drawn + 1
		return widget()
	end
	function os:box() return widget() end
	function os:rect() return widget() end
	function os:framed() end
	function os:round() end
	function os:image() end
	function os:icon(sec) assert(type(sec) == "string", "icon") end
	function os:button(x, y, w, h, str, f, list, parent, ax, ay, kind)
		assert(type(str) == "string", "button label")
		assert(not string.find(str, "!!NO TEXT", 1, true), str)
		local b = { x, y, w, h, f }
		if kind ~= "off" then
			list[#list + 1] = b
		end
		return b
	end
	function os:click_at(list, x, y, w, h, f, hover, tag)
		local b = { x, y, w, h, f }
		if tag then
			b[tag] = true
		end
		list[#list + 1] = b
		return b
	end
	function os:window()
		self.win = widget()
		return self.win
	end
	function os:room_name(id) return "room " .. tostring(id) end
	function os:room_name_at(pos) return pos.x < 100 and "room" or nil end
	return os
end
local env = setmetatable({}, { __index = _G })
ui_shelter_trade = env
local f = assert(loadstring(py_read_trade(), "ui_shelter_trade"))
setfenv(f, env)
f()

local function fresh_world()
	WORLD.contracts = nil
	for _ = 1, 6 do
		WORLD.offer_next = 0
		orders.on_hours()
	end
	assert(#orders.contracts() >= 3, "offers on the board")
	orders.take(orders.contracts()[1].id)
	bar.ledger_add("medkit", 50)
	bar.ledger_add("ammo_9x19_fmj", 3000)
	bar.ledger_add("wpn_svd", 2)
	WORLD.till = 5000000
	MONEY = 5000000
	assert(orders.order(sup, "vodka", orders.lots(sup, "vodka")[1], "till"), "one on its way")
	WORLD.crisis, WORLD.crisis_until = "dry", WORLD.eco_hours + 5
	bar.set_own_markup("medkit", 1.5)
end

local TAB_I = { overview = 0, stock = 1, supply = 2, ways = 3, contracts = 4, journal = 5, settings = 6 }
local pressed = 0
for _, w in ipairs({ 1024, 1365 }) do
	for tab, i in pairs(TAB_I) do
		fresh_world()
		WORLD.barman = tab ~= "overview" and "hired" or nil -- the overview's hire button gets pressed
		local os = make_os()
		env.open(os, w, 720)
		local function go()
			for _, b in ipairs(os.app_clicks) do
				if b[2] == 50 and b[1] == 18 + i * 150 then
					b[5]()
					return true
				end
			end
		end
		assert(go(), "the tab's button " .. tab)
		assert(os.trade.tab == tab, "on tab " .. tab)
		env.update(os)
		-- every click once, by its place: the list is drawn anew after each press
		local seen, guard = {}, 0
		while guard < 400 do
			guard = guard + 1
			local pick
			for n = #os.app_clicks, 2, -1 do
				local b = os.app_clicks[n]
				local key = b[1] .. ":" .. b[2]
				if not seen[key] and not (b[2] == 50 and b[1] ~= 18 + i * 150) and b[2] ~= 6 then
					seen[key], pick = true, b
					break
				end
			end
			if not pick then
				break
			end
			pick[5]({ x = pick[1], y = pick[2] })
			pressed = pressed + 1
			if os.trade.tab ~= tab then
				go()
			end
		end
		os.trade.at = 0
		env.update(os)
	end
end
local miss = {}
for k in pairs(missing) do
	miss[#miss + 1] = k
end
table.sort(miss)
return pressed, drawn, table.concat(miss, " "), VISITORS
