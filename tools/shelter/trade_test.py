# Offline test of the shelter's trade (shelter_trade.script, shelter_orders.script), no game needed: compiles the scripts,
# checks the config against the game's real sections, runs the logic in lupa on a mock of the game and a money simulation.
# python tools/shelter/trade_test.py <anomaly-unpacked>
import os, random, re, sys
from lupa import luajit21 as lua_mod

HERE = os.path.dirname(os.path.abspath(__file__))
G = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
VANILLA = sys.argv[1] if len(sys.argv) > 1 else r"H:\stalker-test\anomaly-unpacked"


def parse_ltx(paths):
    sec = {}
    for path in paths:
        cur = None
        for line in open(path, encoding="cp1251", errors="ignore"):
            line = line.split(";")[0].strip()
            m = re.match(r"\[([^\]]+)\]\s*(?::\s*(.*))?", line)
            if m:
                cur = m.group(1)
                sec[cur] = {"_p": [p.strip() for p in (m.group(2) or "").split(",") if p.strip()]}
            elif cur and "=" in line:
                k, v = line.split("=", 1)
                sec[cur][k.strip()] = v.strip()
    return sec


def walk(root):
    return [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".ltx")]


items = parse_ltx(walk(os.path.join(VANILLA, "configs", "items")) + walk(os.path.join(VANILLA, "configs", "misc", "squad_descr")))
trade = parse_ltx([os.path.join(G, "configs", "mod_system_shelter_trade.ltx")])
all_sec = {**items, **trade}


def param(section, key):
    e = all_sec.get(section)
    if not e:
        return None
    if key in e:
        return e[key]
    for parent in e["_p"]:
        v = param(parent, key)
        if v is not None:
            return v


def csv(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


fails = []


def check(ok, what):
    if not ok:
        fails.append(what)


# 1. every section the config names is in the game (the GRA pack's are only warned of)
kinds = {}
for cid in csv(trade["shelter_trade"]["categories"]):
    for k in csv(trade["shelter_trade_cat_" + cid]["kinds"]):
        kinds[k] = cid
for sup in csv(trade["shelter_orders"]["suppliers"]):
    s = trade["shelter_supplier_" + sup]
    for sec in csv(s["goods"]):
        check(sec in items, "supplier %s: no section %s" % (sup, sec))
        check(param(sec, "kind") in kinds, "supplier %s: %s has kind %s, no category" % (sup, sec, param(sec, "kind")))
for sq in csv(trade["shelter_orders"]["squads"]):
    check(sq in items, "no squad " + sq)
for cid in csv(trade["shelter_contracts"]["list"]):
    for var in trade["shelter_contract_" + cid]["variants"].split("/"):
        for sec, n in re.findall(r"([\w.\-]+)\s*=\s*(\d+)", var):
            if sec not in items:
                print("note: contract %s names %s, not in vanilla (a pack's, or the variant is skipped)" % (cid, sec))
            elif param(sec, "kind") not in kinds:
                fails.append("contract %s: %s has kind %s, no category" % (cid, sec, param(sec, "kind")))

# 2. bulk is always under retail
o = trade["shelter_orders"]
top = max(float(o["rep_k_low"]), 1) * max(float(x) for x in csv(o["bulk"]))
check(top < 1, "bulk at worst goodwill is not under retail: %s" % top)
print("worst lot against retail: %.3f" % top)

# 3. the scripts compile and run against a mock
lua = lua_mod.LuaRuntime(unpack_returned_tuples=True)
scripts = ["shelter_trade.script", "shelter_orders.script", "ui_shelter_trade.script", "ui_shelter_laptop.script"]
for name in scripts:
    src = open(os.path.join(G, "scripts", name), encoding="cp1251", newline="").read()
    chunk = lua.eval("function(s, n) local f, e = loadstring(s, n); return e end")(src, name)
    check(chunk is None, "%s: %s" % (name, chunk))

# a method defined twice: the second silently replaces the first (the plan's room_at was lost so)
src = open(os.path.join(G, "scripts", "ui_shelter_laptop.script"), encoding="cp1251").read()
names = re.findall(r"^function UIShelterOS:(\w+)", src, re.M)
for name in sorted(set(n for n in names if names.count(n) > 1)):
    fails.append("UIShelterOS:%s defined twice" % name)

ini = lua.table()


def py_float(s, k, d=None):
    v = param(s, k)
    try:
        return float(v) if v is not None else d
    except ValueError:
        return d


def py_str(s, k, d=None):
    v = param(s, k)
    return v if v is not None else d


def py_bool(s, k, d=False):
    v = param(s, k)
    return v in ("true", "1", "on", "yes") if v is not None else d


lua.globals()["py_float"] = py_float
lua.globals()["py_str"] = py_str
lua.globals()["py_bool"] = py_bool
lua.globals()["py_exists"] = lambda s: s in all_sec
lua.execute(r'''
ini_sys = {
  r_float_ex = function(_, s, k, d) return py_float(s, k, d) end,
  r_string_ex = function(_, s, k, d) return py_str(s, k, d) end,
  r_bool_ex = function(_, s, k, d) return py_bool(s, k, d) end,
  section_exist = function(_, s) return py_exists(s) end,
}
function SYS_GetParam(kind, s, k, d)
  if kind == 0 then return py_str(s, k, d) end
  if kind == 1 then return py_bool(s, k, d or false) end
  return py_float(s, k, d)
end
function str_explode(str, sep, plain)
  local t, pos = {}, 1
  while true do
    local a, b = string.find(str, sep, pos, true)
    if not a then t[#t + 1] = (string.gsub(string.sub(str, pos), "^%s*(.-)%s*$", "%1")); return t end
    t[#t + 1] = (string.gsub(string.sub(str, pos, a - 1), "^%s*(.-)%s*$", "%1"))
    pos = b + 1
  end
end
function RegisterScriptCallback() end
AC_ID = 0
WORLD = {}
shelter = {
  state = function(n, d) local v = WORLD[n]; if v == nil then return d end; return v end,
  set_state = function(n, v) WORLD[n] = v end,
  everyones = function(f, ...) return f(...) end,
  once = function(_, f) f() end,
}
game = { translate_string = function(id) return id end }
GOODWILL = 0
relation_registry = {
  community_goodwill = function() return GOODWILL end,
  change_community_goodwill = function(_, _, d) GOODWILL = GOODWILL + d end,
}
news_manager = { relocate_money = function() end, relocate_item = function() end }
ui_item = { get_sec_name = function(s) return s end }
RELEASED = {}
function alife_release(se) RELEASED[#RELEASED + 1] = se end
function get_story_se_object() return nil end
function time_global() return 0 end
''')
for name in ("shelter_trade", "shelter_orders"):
    src = open(os.path.join(G, "scripts", name + ".script"), encoding="cp1251", newline="").read()
    lua.eval('''function(src, name)
        local env = setmetatable({}, { __index = _G })
        _G[name] = env
        local f = assert(loadstring(src, name))
        setfenv(f, env)
        f()
    end''')(src, name)

# a store's scan comes from the test, the world's objects being a mock
run = lua.execute
run(r'''
math.randomseed(7)
local bar, orders = shelter_trade, shelter_orders
local function eq(a, b, what) if a ~= b then error(what .. ": " .. tostring(a) .. " ~= " .. tostring(b), 2) end end
local function near(a, b, what) if math.abs(a - b) > 1e-6 then error(what .. ": " .. tostring(a) .. " ~= " .. tostring(b), 2) end end

-- categories
eq(bar.category("vodka").id, "drink", "vodka")
eq(bar.category("ammo_9x19_fmj").id, "ammo", "ammo")
eq(bar.category("ammo_9x19_fmj").rounds, true, "ammo rounds")
eq(bar.category("wpn_svd").id, "weapon", "svd")
eq(bar.category("af_electra_flash").off, true, "artefacts off at first")
near(bar.unit_cost("ammo_9x19_fmj"), 645 / 15, "a round's cost")

-- the ledger
bar.ledger_add("vodka", 300); bar.ledger_add("ammo_9x19_fmj", 1000); bar.ledger_add("vodka", 5)
eq(bar.ledger().vodka, 305, "ledger add")

-- markups: own over category over general; on sale
bar.set_markup(1.2)
near(bar.markup_of("vodka"), 1.2, "general")
bar.set_category_markup("drink", 1.5)
near(bar.markup_of("vodka"), 1.5, "category")
bar.set_own_markup("vodka", 2)
near(bar.markup_of("vodka"), 2, "own")
bar.set_own_markup("vodka", 99)
near(bar.markup_of("vodka"), 2.5, "own clamped")
bar.set_own_markup("vodka", nil); bar.set_category_markup("drink", nil); bar.set_markup(1.1)
eq(bar.on_sale("vodka"), true, "on sale")
bar.set_own_sale("vodka", "off")
eq(bar.on_sale("vodka"), false, "off")
bar.set_own_sale("vodka", nil)
eq(bar.on_sale("af_electra_flash"), false, "artefact off by default")
bar.set_own_sale("af_electra_flash", "on")
eq(bar.on_sale("af_electra_flash"), true, "artefact put on")
bar.set_own_sale("af_electra_flash", nil)
bar.set_category_on("drink", false)
eq(bar.on_sale("vodka"), false, "category off")
bar.set_category_on("drink", true)

-- positions from goods and the ledger
local cat = bar.category
local goods = { { se = "a", section = "vodka", cat = cat("vodka"), units = 1, cond = 1 },
  { se = "b", section = "wpn_svd", cat = cat("wpn_svd"), units = 1, cond = 0.5 } }
local list = bar.positions(goods)
eq(#list, 3, "positions")
local by = {}
for _, p in ipairs(list) do by[p.section] = p end
eq(by.vodka.count, 306, "vodka both")
eq(by.vodka.crates, 1, "vodka boxes")
near(by.wpn_svd.cond, 0.5, "cond")
eq(bar.price_of("wpn_svd", 0.5), math.floor(40550 * 1.1 * 0.5 + 0.5), "worn price")

-- a visitor buys: the money and the things go down, only from what is on sale
local empty = {}
local b, how = bar.visit(empty)
eq(#b, 0, "nothing to buy"); eq(how, "empty", "empty")
local p = { section = "vodka", cat = cat("vodka"), crates = 0, ledger = 100, goods = {}, markup = 1.1 }
for i = 1, 200 do bar.visit({ drink = { p } }) end
assert(p.ledger < 100, "bought from the ledger")
assert(p.ledger >= 0, "ledger never below 0")

-- a price far over fair is refused by food, not by medicine
local dear = { section = "conserva", cat = cat("conserva"), crates = 0, ledger = 100000, goods = {}, markup = 2.5 }
local med = { section = "medkit_army", cat = cat("medkit_army"), crates = 0, ledger = 100000, goods = {}, markup = 2.5 }
for i = 1, 300 do bar.visit({ food = { dear }, medical = { med } }) end
eq(dear.ledger, 100000, "food refused at x2.5")
assert(med.ledger < 100000, "medicine still bought at x2.5")

-- news
bar.announce("st_x", { "@vodka", 5 })
eq(#bar.news(), 1, "news")

-- orders: prices under retail, paying, arriving
GOODWILL = 0
local sup = orders.supplier("barman")
local lots = orders.lots(sup, "vodka")
eq(#lots, 3, "lots")
assert(lots[1].one < orders.retail(sup, "vodka"), "under retail")
assert(lots[3].one < lots[1].one, "larger is cheaper")
for _, s in ipairs(orders.suppliers()) do
  for _, sec in ipairs(s.goods) do
    for _, l in ipairs(orders.lots(s, sec)) do assert(l.one < orders.retail(s, sec), s.id .. " " .. sec) end
  end
end
eq(orders.why_closed(sup), nil, "open")
GOODWILL = -1000
eq(orders.why_closed(sup), "hostile", "hostile")
GOODWILL = 0
WORLD.till = 1000000
assert(orders.order(sup, "vodka", lots[1], "till"), "paid")
eq(WORLD.till, 1000000 - lots[1].total, "till down")
eq(orders.order(sup, "vodka", { units = 1, total = 99999999 }, "till"), false, "no money")
eq(#orders.deliveries(), 1, "one on its way")
local before = bar.ledger().vodka
sup.intercept = 0
WORLD.eco_hours = 100
orders.on_hours()
eq(#orders.deliveries(), 0, "arrived")
eq(bar.ledger().vodka, before + 20, "into the ledger")

-- a lot that can't be intercepted for want of a point just arrives
sup.intercept = 1
SIMBOARD = { smarts_by_names = {} }
assert(orders.order(sup, "vodka", lots[1], "till"), "paid again")
WORLD.eco_hours = 200
orders.on_hours()
eq(#orders.deliveries(), 0, "arrived anyway")
eq(bar.ledger().vodka, before + 40, "into the ledger anyway")
sup.intercept = 0.15

-- contracts: offers appear, taken, missed
WORLD.barman = "hired"
WORLD.eco_hours = 1000
WORLD.offer_next = 0
orders.on_hours()
local cs = orders.contracts()
assert(#cs == 1, "an offer")
local c = cs[1]
assert(c.reward > 0, "a reward")
eq(c.taken, 0, "free")
orders.take(c.id)
eq(orders.contracts()[1].taken, 1, "taken")
local tp = orders.template(c)
WORLD.offer_next = 1e9
WORLD.eco_hours = 1000 + tp.hours + 1
orders.on_hours()
eq(#orders.contracts(), 0, "missed goes")
local n = bar.news()
assert(string.find(n[1].text, "failed", 1, true), "missed is told")

-- refused offer
WORLD.offer_next = 0
orders.on_hours()
c = orders.contracts()[1]
orders.refuse(c.id)
eq(#orders.contracts(), 0, "refused")
''')

# 4. a month of money: does trade make millions? (the mock's visitors at the most a day, a stocked store at the default markup)
res = lua.execute(r'''
local bar = shelter_trade
local cat = bar.category
local list = {}
local secs = { "conserva", "tushonka", "vodka", "beer", "cigarettes", "medkit", "medkit_army", "bandage", "ammo_9x19_fmj", "ammo_5.45x39_fmj", "wpn_ak74", "wpn_svd", "af_electra_flash" }
for _, s in ipairs(secs) do
  local c = cat(s)
  local p = { section = s, cat = c, crates = 0, ledger = 1e7, goods = {}, markup = bar.markup_of(s, c) }
  list[c.id] = list[c.id] or {}
  table.insert(list[c.id], p)
end
local money, bought = 0, 0
for day = 1, 30 do
  for v = 1, 13 do
    local b = bar.visit(list)
    for _, e in ipairs(b) do money = money + e.money; bought = bought + 1 end
  end
end
return money, bought
''')
print("stocked, 13 visitors a day, x1.1: %d RU in 30 game days (%d purchases), about %d a day" % (res[0], res[1], res[0] / 30))

# 5. the mock world and the Trade app (trade_test_world.lua)
import xml.etree.ElementTree as ET
raw = open(os.path.join(G, "configs", "text", "rus", "st_shelter.xml"), "rb").read()
texts = {e.get("id"): (e.findtext("text") or "") for e in ET.fromstring(raw).findall("string")}
lua.globals()["py_text"] = lambda i: texts.get(i, "!!NO TEXT " + i).encode("cp1251").decode("latin-1")
lua.globals()["py_has_text"] = lambda i: i in texts
lua.globals()["py_read_trade"] = lambda: open(os.path.join(G, "scripts", "ui_shelter_trade.script"), encoding="cp1251", newline="").read()
world = open(os.path.join(HERE, "trade_test_world.lua"), encoding="utf-8").read()
out = lua.execute(world)
print(out[3])
print("UI: %s buttons pressed, %s texts drawn" % (out[0], out[1]))
check(out[2] == "", "texts missing from st_shelter.xml: %s" % out[2])

for f in fails:
    print("FAIL", f)
print("OK" if not fails else "%d failed" % len(fails))
sys.exit(1 if fails else 0)
