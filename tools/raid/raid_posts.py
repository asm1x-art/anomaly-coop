r"""The Monolith's own places on the raid levels (scripts\raid_monolith.script): writes
gamedata\configs\scripts\raid_posts.ltx (the jobs raid_monolith.script adds to the smarts) and
gamedata\configs\mod_patrol_paths_raid.ltx (their stand points, watch points with the pose, the patrols' loops).
  raid_posts.py [<levels dir>]     run from the repo root; levels dir: the game's gamedata\levels with the raid
                                   copies (default H:\anomaly-lift\gamedata\levels), for the AI-map nodes
A post is a place a squad of its own holds (Hospital, Control Center: the levels with too few smarts), the scientists'
lab with its guards, or a lair: a smart terrain whose vanilla jobs are mutants' only, where its garrison would stand
in a crowd. A route is a loop of points a patrol walks (a level with few smarts). Each belongs to a host smart: the
squads are made there and the jobs are that smart's. Which posts and routes a level uses, squads, counts and chances:
mod_system_raid.ltx. Positions are AI-map nodes (read from level.ai, mostly vanilla path points: surge covers the
Monolith never takes, story posts of the Control Center); the game snaps every point to the nearest node.
"""
import math
import os
import struct
import sys

GUARD, HIDE, THREAT, WAIT, SIT, KNEE = "guard", "hide", "threat", "wait", "sit_ass", "sit_knee"


def spot(x, y, z, lx, ly, lz, pose=GUARD, role=None):
    return dict(pos=(x, y, z), look=(lx, ly, lz), pose=pose, role=role)


# post: level, host smart, spots (one man each). A post's jobs are taken only by its own squads ("raid_post_<post>"
# in the world's state); "lair" jobs by any Monolith man of the smart; role scientist / guard: only such men
POSTS = {
    # Hospital, from the Limansk side (north, z 860) to the ChNPP exit (south, z 567); away from the catacombs' narrow
    # passages (a man standing in one blocks it), mostly at the vanilla surge covers the Monolith never takes
    "raid_hos_p1": ("raid_hospital", "raid_katacomb_smart_terrain", "the north cave's wide part, facing Limansk", [
        spot(-86.8, 32.2, 805.7, -86.8, 32.2, 830.0, GUARD),
        spot(-81.2, 32.3, 807.8, -78.0, 32.3, 830.0, HIDE),
        spot(-86.8, 32.7, 811.3, -84.0, 32.7, 835.0, HIDE),
        spot(-81.9, 32.3, 802.9, -81.9, 32.3, 825.0, GUARD),
    ]),
    "raid_hos_p2": ("raid_hospital", "raid_katacomb_smart_terrain", "lower floor, the big hall's east side", [
        spot(-79.8, 25.0, 672.0, -95.0, 25.0, 672.0, GUARD),
        spot(-77.7, 25.0, 665.0, -95.0, 25.0, 665.0, HIDE),
        spot(-84.7, 25.2, 676.9, -84.7, 25.2, 690.0, GUARD),
        spot(-78.4, 25.1, 660.1, -78.4, 25.1, 645.0, HIDE),
    ]),
    "raid_hos_p3": ("raid_hospital", "raid_katacomb_smart_terrain", "lower floor, the south hall by the medic's room", [
        spot(-84.7, 24.5, 637.7, -84.7, 24.5, 615.0, GUARD),
        spot(-79.8, 25.0, 639.1, -79.8, 25.0, 660.0, HIDE),
        spot(-81.9, 25.0, 644.0, -81.9, 25.0, 665.0, GUARD),
        spot(-87.5, 25.4, 636.3, -87.5, 25.4, 615.0, KNEE),
    ]),
    "raid_hos_p4": ("raid_hospital", "raid_katacomb_smart_terrain", "south, before the exit to ChNPP", [
        spot(-85.4, 23.4, 595.0, -85.4, 23.4, 575.0, GUARD),
        spot(-88.2, 23.3, 597.8, -88.2, 23.3, 575.0, HIDE),
        spot(-81.2, 23.1, 596.4, -75.0, 23.1, 575.0, HIDE),
        spot(-86.1, 23.3, 599.2, -86.1, 23.3, 620.0, GUARD),
    ]),
    # Control Center: the vanilla story posts on the walkways south of the main hall (mon_post1/2, mon_camp)
    "raid_ctl_p1": ("raid_control_monolith", "raid_sar_monolith_zombies", "west, mon_post1", [
        spot(-37.6, -34.5, -13.9, -31.7, -34.5, -13.6, HIDE),
        spot(-35.6, -34.5, -12.6, -31.7, -34.5, -12.4, HIDE),
        spot(-39.2, -34.5, -17.5, -25.0, -34.5, -17.5, GUARD),
    ]),
    "raid_ctl_p2": ("raid_control_monolith", "raid_sar_monolith_zombies", "south-west, mon_post2 and mon_camp2", [
        spot(-42.2, -34.5, -36.6, 0.0, -34.5, -36.6, HIDE),
        spot(-14.9, -34.5, -42.5, -11.3, -34.5, -37.6, HIDE),
        spot(-27.3, -34.4, -37.8, -27.3, -34.4, -20.0, GUARD),
    ]),
    "raid_ctl_p3": ("raid_control_monolith", "raid_sar_monolith_guard", "east, mon_camp1 by the way to ChNPP North", [
        spot(42.7, -34.4, -23.7, 36.4, -34.5, -24.5, HIDE),
        spot(35.0, -34.4, -23.8, 35.0, -34.4, -5.0, GUARD),
        spot(37.8, -34.4, -19.6, 37.8, -34.4, 0.0, GUARD),
    ]),
    # the Monolith's scientists with their guards: the Sarcophagus' store, the Control Center's main hall
    "raid_sar_lab": ("raid_sarcofag", "raid_sar_monolith_sklad", "the store's long room; guards at its ends", [
        spot(12.6, -0.4, 12.6, 12.6, -0.4, 8.0, WAIT, "scientist"),
        spot(18.9, -0.2, 12.6, 18.9, -0.2, 8.0, KNEE, "scientist"),
        spot(27.3, -0.3, 11.2, 27.3, -0.3, 16.0, WAIT, "scientist"),
        spot(9.1, 0.0, 17.5, 0.0, 0.0, 17.5, GUARD, "guard"),
        spot(33.6, -0.4, 13.3, 40.0, -0.4, 13.3, GUARD, "guard"),
        spot(35.7, -0.5, 11.2, 35.7, -0.5, 0.0, HIDE, "guard"),
        spot(1.4, -0.1, 6.3, 1.4, -0.1, -10.0, GUARD, "guard"),
    ]),
    "raid_ctl_lab": ("raid_control_monolith", "raid_sar_monolith_guard", "the main hall round its middle", [
        spot(-6.3, -34.2, 18.9, 0.0, -34.2, 18.9, WAIT, "scientist"),
        spot(6.3, -34.4, 18.9, 0.0, -34.4, 18.9, KNEE, "scientist"),
        spot(0.0, -34.5, 10.5, 0.0, -34.5, 18.0, WAIT, "scientist"),
        spot(-6.3, -34.5, 28.0, -6.3, -34.5, 40.0, GUARD, "guard"),
        spot(6.3, -34.5, 28.0, 20.0, -34.5, 28.0, GUARD, "guard"),
        spot(-6.3, -34.4, 9.1, -6.3, -34.4, -5.0, GUARD, "guard"),
        spot(6.3, -34.5, 9.1, 6.3, -34.5, -5.0, HIDE, "guard"),
    ]),
    # lairs: vanilla jobs for mutants only; places for the smart's own garrison
    "raid_sar_polt": ("raid_sarcofag", "raid_sar_monolith_poltergeists", "upper floor", [
        spot(8.4, 49.0, 7.7, 8.4, 49.0, -10.0, GUARD, "lair"),
        spot(25.2, 52.9, -22.4, 10.0, 52.9, -22.4, HIDE, "lair"),
        spot(27.3, 52.4, -21.0, 27.3, 52.4, -5.0, GUARD, "lair"),
        spot(-2.1, 49.3, 11.9, 10.0, 49.3, 11.9, HIDE, "lair"),
        spot(10.5, 49.0, 13.3, 10.5, 49.0, 30.0, GUARD, "lair"),
    ]),
    "raid_aes_m2": ("raid_stancia", "raid_aes_smart_terrain_monsters2", "open ground, lair 2", [
        spot(807.8, 0.0, -169.4, 780.0, 0.0, -190.0, GUARD, "lair"),
        spot(811.3, 0.0, -172.9, 830.0, 0.0, -190.0, HIDE, "lair"),
        spot(802.9, 0.0, -175.0, 780.0, 0.0, -175.0, HIDE, "lair"),
        spot(812.0, 0.0, -85.4, 812.0, 0.0, -60.0, GUARD, "lair"),
        spot(807.8, 0.0, -80.5, 790.0, 0.0, -80.0, HIDE, "lair"),
    ]),
    "raid_aes_m3": ("raid_stancia", "raid_aes_smart_terrain_monsters3", "open ground, lair 3", [
        spot(468.3, -0.1, -196.0, 468.3, -0.1, -220.0, GUARD, "lair"),
        spot(464.1, -0.1, -198.1, 440.0, -0.1, -198.0, HIDE, "lair"),
        spot(464.1, 0.0, -191.1, 440.0, 0.0, -180.0, GUARD, "lair"),
        spot(477.4, 0.4, -190.4, 500.0, 0.4, -190.0, HIDE, "lair"),
        spot(466.9, 1.0, -186.9, 466.9, 1.0, -160.0, GUARD, "lair"),
    ]),
    "raid_aes_m4": ("raid_stancia", "raid_aes_smart_terrain_monsters4", "open ground, lair 4", [
        spot(142.1, 4.8, -174.3, 160.0, 4.8, -150.0, GUARD, "lair"),
        spot(140.0, 4.8, -170.1, 120.0, 4.8, -160.0, HIDE, "lair"),
        spot(147.7, 4.9, -176.4, 170.0, 4.9, -180.0, HIDE, "lair"),
        spot(135.1, 4.8, -171.5, 115.0, 4.8, -175.0, GUARD, "lair"),
        spot(140.7, 4.3, -183.4, 140.7, 4.3, -205.0, GUARD, "lair"),
    ]),
}

# route: level, host smart, points walked there and back (a loop through them); a patrol of its own squad
ROUTES = {
    "raid_hos_route": ("raid_hospital", "raid_katacomb_smart_terrain", "lower floor, south to north", [
        (-86.4, 24.2, 604.9), (-88.9, 25.5, 633.7), (-80.3, 25.0, 641.1), (-92.1, 25.0, 660.1), (-86.6, 25.0, 674.8),
        (-79.2, 25.0, 689.5), (-82.3, 25.0, 710.4), (-80.7, 25.0, 731.6), (-89.5, 25.2, 749.5), (-92.6, 24.2, 763.8)]),
    "raid_sar_route_hall": ("raid_sarcofag", "raid_sar_monolith_general", "the general's rooms (sar_monolith_general_patrol_walk_room)", [
        (18.4, 0.1, 41.5), (28.2, -0.1, 39.9), (42.9, 0.0, 40.7), (47.6, 0.1, 37.5), (57.9, 0.1, 36.9), (63.6, -0.1, 36.0),
        (67.2, -0.1, 38.5), (73.7, 0.1, 37.3), (73.6, 0.0, 26.6), (74.9, -0.1, 21.1), (72.8, 0.0, 9.8), (69.2, 0.1, 5.3)]),
}
ROUTE_MEN = 3  # jobs on a route: a patrol's men


def nodes_of(levels, level):
    """(node, position) of a level.ai's nodes"""
    ai = open(os.path.join(levels, level, "level.ai"), "rb").read()
    _, count, size, size_y = struct.unpack_from("<IIff", ai, 0)
    minx, miny, minz = struct.unpack_from("<3f", ai, 16)
    maxz = struct.unpack_from("<f", ai, 36)[0]
    row = int(math.floor((maxz - minz) / size + 1e-6 + 1.5))
    for i in range(count):
        p = ai[56 + i * 23 + 18:56 + i * 23 + 23]
        xz = p[0] | (p[1] << 8) | (p[2] << 16)
        yield i, (minx + (xz // row) * size, miny + struct.unpack_from("<H", p, 3)[0] / 65535 * size_y, minz + (xz % row) * size)


def nearest_node(nodes, pos):
    return min(nodes, key=lambda n: (n[1][0] - pos[0]) ** 2 + 4 * (n[1][1] - pos[1]) ** 2 + (n[1][2] - pos[2]) ** 2)


def main():
    levels = sys.argv[1] if len(sys.argv) > 1 else r"H:\anomaly-lift\gamedata\levels"
    nodes = {}
    spawns = ["", "; where a post's squads are made: its first man's place (x, y, z, AI node)", "[raid_post_spawns]"]
    by_smart, hosts, body = {}, ["[raid_post_hosts]"], []
    paths = ["; The Monolith's places on the raid levels, generated by tools\\raid\\raid_posts.py (edit there): a stand point",
             "; and a point to watch with the pose (a=guard, hide...) per man of a post; a loop for a patrol's route.", ""]

    def path(name, level, points, loop=False, pose=None):
        paths.extend(["[%s]" % name, "level           = %s" % level, "points          = " + ",".join("p%d" % i for i in range(len(points)))])
        for i, pos in enumerate(points):
            paths.append("p%d:name         = wp%02d%s" % (i, i, "|a=" + pose if pose else ""))
            paths.append("p%d:position     = %.1f,%.1f,%.1f" % ((i,) + pos))
            if loop:
                paths.append("p%d:links        = p%d(1)" % (i, (i + 1) % len(points)))
        paths.append("")

    for post, (level, smart, note, spots) in POSTS.items():
        hosts.append("%s = %s" % (post, smart))
        if level not in nodes:
            nodes[level] = list(nodes_of(levels, level))
        node, at = nearest_node(nodes[level], spots[0]["pos"])
        if spots[0]["role"] != "lair":
            spawns.append("%s = %.1f, %.1f, %.1f, %d" % ((post,) + at + (node,)))
        body += ["", "; %s: %s" % (post, note)]
        for i, s in enumerate(spots):
            job = "%s_%d" % (post, i + 1)
            by_smart.setdefault(smart, []).append(job)
            body += ["[logic@%s]" % job, "active          = walker@%s" % job, "post            = %s" % post]
            if s["role"]:
                body.append("role            = %s" % s["role"])
            body += ["prior           = 200", "[walker@%s]" % job, "path_walk       = %s_walk" % job, "path_look       = %s_look" % job]
            path(job + "_walk", level, [s["pos"]])
            path(job + "_look", level, [s["look"]], pose=s["pose"])
    for route, (level, smart, note, points) in ROUTES.items():
        hosts.append("%s = %s" % (route, smart))
        body += ["", "; %s: %s" % (route, note)]
        for i in range(ROUTE_MEN):
            job = "%s_%d" % (route, i + 1)
            by_smart.setdefault(smart, []).append(job)
            body += ["[logic@%s]" % job, "active          = patrol@%s" % route, "post            = %s" % route,
                     "prior           = 200"]
        body += ["[patrol@%s]" % route, "path_walk       = %s_walk" % route, "formation       = back"]
        path(route + "_walk", level, points + points[-2:0:-1], loop=True)

    jobs = ["; The Monolith's places on the raid levels, generated by tools\\raid\\raid_posts.py (edit there).",
            "; scripts\\raid_monolith.script adds them to the smarts' jobs: [raid_posts] per smart its jobs, [raid_post_hosts]",
            "; the smart each post or route is made at. A job is taken only by a man of its post's squads (role: scientist",
            "; or guard: only such; lair: any Monolith man of the smart). Positions and poses: mod_patrol_paths_raid.ltx.",
            "", "[raid_posts]"]
    jobs += ["%s = %s" % (smart, ", ".join(names)) for smart, names in by_smart.items()]
    jobs += [""] + hosts + spawns + body
    root = os.path.join("gamedata", "configs")
    open(os.path.join(root, "scripts", "raid_posts.ltx"), "wb").write(("\r\n".join(jobs) + "\r\n").encode("cp1251"))
    open(os.path.join(root, "mod_patrol_paths_raid.ltx"), "wb").write("\r\n".join(paths).encode("cp1251"))
    print("jobs: %d" % sum(len(v) for v in by_smart.values()))


if __name__ == "__main__":
    main()
