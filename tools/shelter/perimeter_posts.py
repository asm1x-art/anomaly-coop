r"""The perimeter's posts on l10_radar (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5, "Perimeter"): writes
gamedata\configs\scripts\shelter_perimeter.ltx (the jobs scripts\shelter_base.script adds to the smarts) and
gamedata\configs\mod_patrol_paths_shelter.ltx (their stand points, watch points with the pose, the rounds loop).
  perimeter_posts.py            run from the repo root
Positions are AI-map nodes read in the game (devcmd). A job is taken only by an NPC of a squad in its "squad"; "when":
calm (posts) or surge (an emission or a psi storm: inside the surge covers rad_prip_road_surge_hide_a2, the trailer by
the fork, and rad_entrance_surge_hide_a1 by the checkpoint), or always: the shelter's entrance, held by the Hospital's
assault group (scripts\shelter_assault.script), lies inside the cover rad2_prip_teleport_surge_hide_a1 (a box x 640..667,
z 165..194 round the half-open gate at 654.7, 182.3).
"""
import os

POST, POST2, SNIPER, GATE, PATROL = ("shelter_perim_post", "shelter_perim_post2", "shelter_perim_sniper",
                                     "shelter_perim_gate", "shelter_perim_patrol")
DOOR = "shelter_assault_guard"
FORK_MEN = [POST, POST2, SNIPER, PATROL]

# (job, squads, stand point(s), watch point, pose, note); a list of several stand points is a loop walked round
FORK = [
    ("shelter_post_1", [POST], [(567.7, -50.1, 16.1)], (530, -50, 15), "hide", "west road: crouched"),
    ("shelter_post_2", [POST], [(566.3, -50.0, 11.9)], (530, -50, 8), "hide", "west road: crouched"),
    ("shelter_post_3", [POST], [(571.9, -50.0, 14.0)], (540, -50, 13), "guard", "west road: standing behind them"),
    ("shelter_post_4", [POST], [(588.0, -50.4, -2.8)], (590.8, -50.3, -7.0), "sit_ass", "rest in the middle"),
    ("shelter_post_5", [POST], [(590.8, -50.3, -7.0)], (588.0, -50.4, -2.8), "sit_knee", "rest in the middle"),
    ("shelter_post_6", [POST2], [(602.7, -50.2, -23.8)], (603, -50, -60), "hide", "south road from the valley: by the concrete"),
    ("shelter_post_7", [POST2], [(608.3, -50.1, -27.3)], (612, -50, -60), "guard", "south road from the valley"),
    ("shelter_post_8", [POST2], [(599.9, -50.1, 20.3)], (600, -50, 50), "guard", "north: the road to the shelter"),
    ("shelter_post_9", [POST2], [(595.0, -50.6, 0.0), (599.9, -50.3, -28.0), (585.2, -50.7, -14.7), (574.7, -50.1, 9.8),
                                 (597.8, -50.3, 11.9)], None, None, "rounds of the post"),
    # the sniper stands on the wooden tower: put there and kept from walking (shelter_base.script, hold_sniper)
    ("shelter_post_sniper", [SNIPER], None, (530, -50, 14), "guard", "sniper on the wooden tower, down the west road"),
]
GATE_POSTS = [
    ("shelter_gate_1", [GATE], [(606.9, -52.2, -312.2)], (590, -52, -345), "guard", ""),
    ("shelter_gate_2", [GATE], [(611.1, -51.5, -312.2)], (615, -52, -345), "hide", ""),
    ("shelter_gate_3", [GATE], [(603.4, -52.3, -312.2)], (575, -52, -312), "guard", ""),
    ("shelter_gate_4", [GATE], [(606.9, -52.0, -316.4)], (606, -52, -285), "guard", ""),
]
# the shelter's entrance: the yard's east end before the half-open gate (654.7, 182.3), facing the yard and the Monolith's
# camp rad2_prip_teleport (626, 182) west of it; clear of the gate and of where one comes out (652.4, 182.7). AI nodes
# (l10_radar level.ai): 226828, 226818, 226654; the rounds 226982, 226479, 226347, 226741
DOOR_POSTS = [
    ("shelter_door_1", [DOOR], [(650.3, -43.9, 186.2)], (628, -43.9, 186), "guard", "the entrance: north of the gate"),
    ("shelter_door_2", [DOOR], [(650.3, -43.9, 179.2)], (628, -43.9, 179), "hide", "the entrance: south of the gate"),
    ("shelter_door_3", [DOOR], [(647.5, -43.9, 186.2)], (625, -43.9, 192), "guard", "the entrance: toward the campfire"),
    ("shelter_door_4", [DOOR], [(653.8, -43.9, 178.5), (644.7, -43.9, 177.8), (641.9, -43.9, 185.5), (648.9, -43.9, 185.5)],
     None, None, "the entrance: rounds"),
]

# AI nodes inside the covers, two rows along the trailer; poses taken in turn
TRAILER = [(569.8, -49.5, 19.6), (571.2, -49.3, 20.3), (571.9, -49.3, 19.6), (573.3, -49.1, 20.3), (574.0, -49.1, 19.6),
           (575.4, -48.8, 20.3), (576.1, -48.8, 19.6), (576.8, -48.7, 20.3), (569.8, -49.4, 20.3), (571.2, -49.3, 19.6),
           (573.3, -49.1, 19.6), (575.4, -48.9, 19.6), (576.8, -48.8, 19.6)]
GATE_COVER = [(613.2, -51.5, -312.9), (613.2, -51.5, -312.2), (613.9, -51.5, -312.9), (613.9, -51.5, -312.2)]
COVER_POSES = ["sit_ass", "sit_knee", "wait", "hide"]


def cover_jobs(prefix, nodes, squads, toward):
    return [("%s_%d" % (prefix, i + 1), squads, [p], (toward[0], p[1], toward[1]), COVER_POSES[i % len(COVER_POSES)],
             "surge cover" if i == 0 else "", "surge") for i, p in enumerate(nodes)]


def main():
    smarts = {
        "rad_after_valley": [j + ("calm",) for j in FORK] + cover_jobs("shelter_cover", TRAILER, FORK_MEN, (573, 0))
        + [j + ("always",) for j in DOOR_POSTS],
        "rad_entrance": [j + ("calm",) for j in GATE_POSTS] + cover_jobs("shelter_gate_cover", GATE_COVER, [GATE], (600, -312)),
    }
    jobs = ["; The perimeter's posts, generated by tools\\shelter\\perimeter_posts.py (edit there). scripts\\shelter_base.script",
            "; adds them to the smarts' jobs (https://app.notion.com/p/40ed89dbf39d818cb08efde54df35db5). [shelter_perimeter]: per smart its jobs; a job is taken only",
            "; by an NPC of a squad in its \"squad\"; when = calm (the posts) or surge (an emission or a psi storm: the covers),",
            "; always: the entrance's posts, in a cover already.",
            "; Positions and poses (the watch point's a=): mod_patrol_paths_shelter.ltx. prior over every vanilla job; the covers",
            "; over the posts.", "", "[shelter_perimeter]"]
    paths = ["; The perimeter's posts on l10_radar, generated by tools\\shelter\\perimeter_posts.py: a stand point and a point to",
             "; watch with the pose (a=guard, hide, sit_ass...) per guard; a loop for the one making rounds. Point 1, the fork:",
             "; 590,-5; point 2, the checkpoint at the entry: 607,-312; the shelter's entrance: 654.7,182.3.", ""]
    body = []
    for smart, entries in smarts.items():
        jobs.append("%s = %s" % (smart, ", ".join(e[0] for e in entries)))
        for name, squads, walk, look, pose, note, when in entries:
            body.append("")
            if note:
                body.append("; " + note)
            scheme = "remark" if walk is None else "walker"
            body += ["[logic@%s]" % name, "active          = %s@%s" % (scheme, name),
                     "squad           = %s" % ", ".join(squads), "when            = %s" % when,
                     "prior           = %d" % (300 if when == "surge" else 200), "", "[%s@%s]" % (scheme, name)]
            if scheme == "remark":
                body += ["anim            = %s" % pose, "target          = path | %s_look, 0" % name]
            else:
                body.append("path_walk       = %s_walk" % name)
                if look:
                    body.append("path_look       = %s_look" % name)
                paths += ["[%s_walk]" % name, "level           = l10_radar",
                          "points          = " + ",".join("p%d" % i for i in range(len(walk)))]
                for i, pos in enumerate(walk):
                    paths += ["p%d:name         = wp%02d" % (i, i), "p%d:position     = %.1f,%.1f,%.1f" % ((i,) + pos)]
                    if len(walk) > 1:
                        paths.append("p%d:links        = p%d(1)" % (i, (i + 1) % len(walk)))
                paths.append("")
            if look:
                paths += ["[%s_look]" % name, "level           = l10_radar", "points          = p0",
                          "p0:name         = wp00|a=%s" % pose, "p0:position     = %.1f,%.1f,%.1f" % look, ""]
    root = os.path.join("gamedata", "configs")
    open(os.path.join(root, "scripts", "shelter_perimeter.ltx"), "wb").write(("\r\n".join(jobs + body) + "\r\n").encode("cp1251"))
    open(os.path.join(root, "mod_patrol_paths_shelter.ltx"), "wb").write("\r\n".join(paths).encode("cp1251"))
    print("jobs: %d" % sum(len(e) for e in smarts.values()))


if __name__ == "__main__":
    main()
