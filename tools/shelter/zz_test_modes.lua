-- Test modes (test copies only: deployed as gamedata\scripts\zz_test_modes.script, not part of the game). Each test
-- script registers a mode here (zz_test_modes.add); every mode is a switch in the F7 debug menu, tab "toggle". One mode
-- is on at a time, so modes may use the same keys (the author's keyboard is a TKL: no numpad). While a mode is on, its
-- keys work and a panel at the left edge lists them, with the mode's own readout under them. The mode on is kept in the
-- save (actor var).
--   zz_test_modes.add(id, { name = "...", keys = { { "DIK_PRIOR", "PgUp", "what it does", function() end }, ... },
--                           status = function() return { "line", ... } end, on = function() end, off = function() end })

local modes, order = {}, {}
local current = nil
local injected = false

-------------------------------------------------------------------------------
-- the panel at the left edge

class "test_modes_hud" (CUIScriptWnd)

function test_modes_hud:__init() super()
	self:SetWndRect(Frect():set(0, 0, 1024, 768))
	self.text = CUIStatic()
	self.text:SetAutoDelete(true)
	self:AttachChild(self.text)
	self.text:SetWndPos(vector2():set(8, 170))
	self.text:SetWndSize(vector2():set(360, 520))
	local t = self.text:TextControl()
	t:SetFont(GetFontLetterica16Russian())
	t:SetTextComplexMode(true)
	t:SetTextColor(GetARGB(255, 235, 235, 200))
end

function test_modes_hud:set(text)
	self.text:TextControl():SetText(text)
end

local hud, shown = nil, false

local function show(on)
	if on and not hud then
		hud = test_modes_hud()
	end
	if hud and on ~= shown then
		if on then
			get_hud():AddDialogToRender(hud)
		else
			get_hud():RemoveDialogToRender(hud)
		end
		shown = on
	end
end

local function refresh()
	local m = current and modes[current]
	if not m then
		show(false)
		return
	end
	local lines = { "%c[255,255,210,120]Тест: " .. m.name .. "%c[default]  (F7 - выключить)" }
	for _, k in ipairs(m.keys or {}) do
		lines[#lines + 1] = string.format("%%c[255,150,220,255]%s%%c[default]  %s", k[2], k[3])
	end
	if m.status then
		local ok, extra = pcall(m.status)
		if ok and extra and #extra > 0 then
			lines[#lines + 1] = " "
			for _, l in ipairs(extra) do
				lines[#lines + 1] = l
			end
		elseif not ok then
			lines[#lines + 1] = "status: " .. tostring(extra)
		end
	end
	show(true)
	hud:set(table.concat(lines, "\\n"))
end

-------------------------------------------------------------------------------

local function title(id)
	return "Тест: " .. modes[id].name .. (current == id and "  [вкл]" or "")
end

local function retitle()
	for _, id in ipairs(order) do
		if modes[id].entry then
			modes[id].entry.name = title(id)
		end
	end
end

local function set(id)
	if current and modes[current] and modes[current].off then
		pcall(modes[current].off)
	end
	current = id
	if id and modes[id].on then
		pcall(modes[id].on)
	end
	if db.actor then
		save_var(db.actor, "zz_test_mode", id)
	end
	retitle()
	refresh()
	actor_menu.set_msg(1, id and ("Тест: " .. modes[id].name .. " - включён") or "Тестовый режим выключен", 3)
end

function toggle(id)
	set(current ~= id and id or nil)
end

function active(id)
	return current == id
end

function add(id, def)
	if not modes[id] then
		order[#order + 1] = id
	end
	modes[id] = def
end

local function inject()
	if injected or not ui_debug_launcher or not ui_debug_launcher.inject then
		return
	end
	injected = true
	for _, id in ipairs(order) do
		local entry = { name = title(id), functor = { toggle, id }, hide_ui = 2 }
		modes[id].entry = entry
		ui_debug_launcher.inject("toggle", entry)
	end
end

local function on_key_press(dik)
	local m = current and modes[current]
	if not (m and db.actor) then
		return
	end
	for _, k in ipairs(m.keys or {}) do
		if dik == DIK_keys[k[1]] then
			local ok, err = pcall(k[4])
			if not ok then
				printf("! test mode %s, %s: %s", current, k[2], tostring(err))
			end
			refresh()
			return
		end
	end
end

local next_at = 0
local function actor_on_update()
	local now = time_global()
	if current and now >= next_at then
		next_at = now + 250
		refresh()
	end
end

local function actor_on_first_update()
	-- a new level has a new HUD: the panel is made again
	hud, shown = nil, false
	inject()
	local id = load_var(db.actor, "zz_test_mode", nil)
	if id and modes[id] then
		current = id
		if modes[id].on then
			pcall(modes[id].on)
		end
		retitle()
		refresh()
	end
end

function on_game_start()
	RegisterScriptCallback("on_key_press", on_key_press)
	RegisterScriptCallback("actor_on_update", actor_on_update)
	RegisterScriptCallback("actor_on_first_update", actor_on_first_update)
end
