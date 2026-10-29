# upgrade_tree.py <item section> <suffix> <configs dir>...: an item's upgrade tree with every upgrade in a group of its
# own (the engine installs no second upgrade of a group, so a vanilla tree can't have both of a pair), for a unique
# item that comes with all of them: its upgrades' sections (each the vanilla one, effects to the new groups), the
# groups, and to stderr the item's "upgrades" and "installed_upgrades" (in an order the engine takes: an upgrade after
# all that lead to it) and what the upgrades add up to. The configs dirs are read in order, later ones over earlier
# (DLTX ![section] merged). As made for the shelter's occupants' gear (configs\mod_system_shelter_brigadier.ltx).
import os
import re
import sys

item, suffix, roots = sys.argv[1], sys.argv[2], sys.argv[3:]
# system.ltx's files: items\ and the DLTX mod_system_*.ltx (plugins' own ltx name the same sections for scripts)
files = []
for root in roots:
    for dp, _, names in os.walk(os.path.join(root, "items")):
        files += [os.path.join(dp, n) for n in names if n.endswith(".ltx")]
    files += [os.path.join(root, n) for n in sorted(os.listdir(root)) if n.startswith("mod_system_") and n.endswith(".ltx")]
secs = {}
for path in files:
    cur = None
    for line in open(path, encoding="cp1251", errors="replace"):
        line = line.split(";")[0].strip()
        m = re.match(r"^(!?)\[([^\]]+)\]\s*(?::\s*(.*))?$", line)
        if m:
            cur = m.group(2).strip()
            if not m.group(1) or cur not in secs:
                secs[cur] = {"__parents": [p.strip() for p in (m.group(3) or "").split(",") if p.strip()]}
            continue
        if cur and "=" in line:
            k, v = line.split("=", 1)
            secs[cur][k.strip()] = v.strip()


def get(sec, key):
    s = secs.get(sec, {})
    if key in s:
        return s[key]
    for p in s.get("__parents", []):
        v = get(p, key)
        if v is not None:
            return v
    return None


def items(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


roots_groups = items(get(item, "upgrades"))
group_of, parents, effects, seen = {}, {}, {}, set()
todo = list(roots_groups)
while todo:
    g = todo.pop(0)
    if g in seen:
        continue
    seen.add(g)
    for u in items(get(g, "elements")):
        group_of[u] = g
        parents.setdefault(u, set())
        effects[u] = items(get(u, "effects"))
        todo += effects[u]
# an upgrade's parents: the upgrades whose effects reach its group
for u, eff in effects.items():
    for g in eff:
        for e in items(get(g, "elements")):
            parents.setdefault(e, set()).add(u)

new = lambda u: u + "_" + suffix  # noqa: E731
group = lambda u: "up_gr_" + re.sub(r"^up_", "", new(u))  # noqa: E731
order, done = [], set()
while len(order) < len(group_of):
    ready = [u for u in group_of if u not in done and parents[u] <= done]
    assert ready, "a loop in the tree"
    for u in sorted(ready, key=lambda u: list(group_of).index(u)):
        order.append(u)
        done.add(u)

out = ["; %s's upgrade tree with each upgrade in a group of its own (tools\\shelter\\upgrade_tree.py)" % item]
for u in order:
    out.append("[%s]:%s" % (new(u), u))
    reach = [new(e) for g in effects[u] for e in items(get(g, "elements"))]
    if reach:
        out.append("effects = " + ", ".join(group(e) for g in effects[u] for e in dict.fromkeys(items(get(g, "elements")))))
out.append("")
for u in order:
    out.append("[%s]" % group(u))
    out.append("elements = " + new(u))
print("\n".join(out))

sums = {}
for u in order:
    for key in ("inv_weight", "artefact_count", "condition_shot_dec", "condition_queue_shot_dec", "additional_inventory_weight"):
        v = get(get(u, "section"), key)
        if v:
            sums[key] = sums.get(key, 0) + float(v)
print("upgrades = " + ", ".join(group(e) for g in roots_groups for e in items(get(g, "elements"))), file=sys.stderr)
print("installed_upgrades = " + ", ".join(new(u) for u in order), file=sys.stderr)
print("%d upgrades; they add %s; base inv_weight %s, condition_shot_dec %s" % (
    len(order), {k: round(v, 6) for k, v in sums.items()}, get(item, "inv_weight"), get(item, "condition_shot_dec")),
    file=sys.stderr)
