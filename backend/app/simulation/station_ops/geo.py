"""A fictional city for the live driver map: a road graph (street grid,
two ring roads, radial highways), a river crossable only at bridges,
neighbourhoods, and shortest-path routing over it.

Drivers drive *along roads*: home -> station when they come in for their
wave, station -> delivery zone -> stop-by-stop tour -> station when out on
route. Positions are interpolated along those polylines by elapsed time.

Everything here is synthetic and seeded by the (fictional) station code —
no real geography, street names or coordinates. Units are km, station at
(0, 0), +y north.
"""

import heapq
import math
import random
from functools import lru_cache

EXTENT_KM = 26
GRID_KM = 3.0
RING_KM = (8.0, 17.0)
RADIAL_DEG = (20, 80, 140, 200, 260, 320)
SPEED = {"highway": 1.9, "ring": 1.6, "street": 1.0}
NEIGHBOURHOODS = (
    "Oakridge",
    "Millbrook",
    "Harbourside",
    "Elmstead",
    "Kestrel Park",
    "Stonebridge",
    "Fairhaven",
    "Larchmont",
    "Riverside",
    "Ashford",
    "Brackenhill",
    "Westmere",
)

Pt = tuple[float, float]


def _seg_intersect(a: Pt, b: Pt, c: Pt, d: Pt) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)


class City:
    def __init__(self, key: str):
        rng = random.Random(f"city:{key}")
        self.nodes: list[Pt] = []
        self.adj: dict[int, list[tuple[int, float]]] = {}
        self.roads: list[dict] = []
        self._idx: dict[tuple[int, int], int] = {}
        # river: a meandering line crossing the map west -> east, south of centre
        phase = rng.uniform(0, math.tau)
        self.river: list[Pt] = [
            (x, -4.5 + 2.2 * math.sin(x / 5.5 + phase) + 0.08 * x) for x in range(-27, 28, 1)
        ]
        self._build_grid(rng)
        self._build_rings()
        self._build_radials()
        self.bridges: list[Pt] = []
        self._mark_bridges()
        self.neighbourhoods = []
        for i, name in enumerate(NEIGHBOURHOODS):
            ang = math.radians(i * 30 + 15 + rng.uniform(-8, 8))
            r = rng.uniform(5.5, 19)
            self.neighbourhoods.append(
                {"name": name, "x": round(r * math.cos(ang), 2), "y": round(r * math.sin(ang), 2)}
            )
        self.parks = [
            {
                "x": round(rng.uniform(-18, 18), 2),
                "y": round(rng.uniform(-18, 18), 2),
                "r": round(rng.uniform(0.8, 1.8), 2),
            }
            for _ in range(7)
        ]

    # --- construction --------------------------------------------------------------

    def _node(self, p: Pt) -> int:
        key = (round(p[0] * 10), round(p[1] * 10))
        if key not in self._idx:
            self._idx[key] = len(self.nodes)
            self.nodes.append((round(p[0], 3), round(p[1], 3)))
            self.adj[self._idx[key]] = []
        return self._idx[key]

    def _crosses_river(self, a: Pt, b: Pt) -> bool:
        return any(
            _seg_intersect(a, b, self.river[i], self.river[i + 1])
            for i in range(len(self.river) - 1)
            if min(a[0], b[0]) - 1 <= self.river[i][0] <= max(a[0], b[0]) + 1
        )

    def _edge(self, i: int, j: int, kind: str, *, bridge_ok: bool) -> bool:
        a, b = self.nodes[i], self.nodes[j]
        if not bridge_ok and self._crosses_river(a, b):
            return False
        w = math.dist(a, b) / SPEED[kind]
        self.adj[i].append((j, w))
        self.adj[j].append((i, w))
        self.roads.append({"kind": kind, "points": [list(a), list(b)]})
        return True

    def _build_grid(self, rng: random.Random) -> None:
        n = int(24 // GRID_KM)
        coords = [k * GRID_KM for k in range(-n, n + 1)]
        jitter = {
            (x, y): (rng.uniform(-0.35, 0.35), rng.uniform(-0.35, 0.35))
            for x in coords
            for y in coords
        }

        def p(x, y):
            if x == 0 and y == 0:
                return (0.0, 0.0)
            jx, jy = jitter[(x, y)]
            return (x + jx, y + jy)

        inside = {(x, y) for x in coords for y in coords if math.hypot(x, y) <= 23.5}
        # a bridge on every third street crossing; the rest stop at the river
        for x, y in sorted(inside):
            for dx, dy in ((GRID_KM, 0), (0, GRID_KM)):
                q = (x + dx, y + dy)
                if q not in inside or rng.random() < 0.1:
                    continue
                bridge = dy != 0 and int(x / GRID_KM) % 3 == 0
                self._edge(self._node(p(x, y)), self._node(p(*q)), "street", bridge_ok=bridge)

    def _build_rings(self) -> None:
        for radius in RING_KM:
            pts = [
                self._node((radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a))))
                for a in range(0, 360, 10)
            ]
            for k in range(len(pts)):
                self._edge(pts[k], pts[(k + 1) % len(pts)], "ring", bridge_ok=True)
            for k in pts:
                self._edge(
                    k, self._nearest_grid(self.nodes[k], exclude=k), "street", bridge_ok=True
                )

    def _build_radials(self) -> None:
        for deg in RADIAL_DEG:
            th = math.radians(deg)
            prev = self._node((0.0, 0.0))
            for k in range(1, 9):
                r = k * 3.0
                cur = self._node((r * math.cos(th), r * math.sin(th)))
                self._edge(prev, cur, "highway", bridge_ok=True)
                if k % 2 == 0:
                    self._edge(
                        cur,
                        self._nearest_grid(self.nodes[cur], exclude=cur),
                        "street",
                        bridge_ok=False,
                    )
                prev = cur

    def _nearest_grid(self, p: Pt, exclude: int) -> int:
        best, bd = exclude, math.inf
        for i, q in enumerate(self.nodes):
            if i == exclude:
                continue
            d = math.dist(p, q)
            if d < bd:
                best, bd = i, d
        return best

    def _mark_bridges(self) -> None:
        for road in self.roads:
            a, b = road["points"]
            if self._crosses_river(tuple(a), tuple(b)):
                road["bridge"] = True
                self.bridges.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))

    # --- routing ------------------------------------------------------------------

    def nearest(self, p: Pt) -> int:
        best, bd = 0, math.inf
        for i, q in enumerate(self.nodes):
            d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
            if d < bd:
                best, bd = i, d
        return best

    @lru_cache(maxsize=4096)  # noqa: B019 — one City per station key, lives for the process
    def _path_nodes(self, a: int, b: int) -> tuple[int, ...]:
        dist = {a: 0.0}
        prev: dict[int, int] = {}
        pq = [(0.0, a)]
        while pq:
            d, u = heapq.heappop(pq)
            if u == b:
                break
            if d > dist.get(u, math.inf):
                continue
            for v, w in self.adj[u]:
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(pq, (nd, v))
        if b not in dist:
            return (a, b)
        out = [b]
        while out[-1] != a:
            out.append(prev[out[-1]])
        return tuple(reversed(out))

    def path(self, src: Pt, dst: Pt) -> list[Pt]:
        nodes = self._path_nodes(self.nearest(src), self.nearest(dst))
        return [src, *(self.nodes[i] for i in nodes), dst]

    def to_dict(self) -> dict:
        return {
            "extent_km": EXTENT_KM,
            "roads": self.roads,
            "river": [list(p) for p in self.river],
            "bridges": [list(b) for b in self.bridges],
            "neighbourhoods": self.neighbourhoods,
            "parks": self.parks,
        }


@lru_cache(maxsize=4)
def city_for(key: str) -> City:
    return City(key)


def length(path: list[Pt]) -> float:
    return sum(math.dist(path[i], path[i + 1]) for i in range(len(path) - 1))


def point_at(path: list[Pt], f: float) -> Pt:
    """Position a fraction `f` (0..1) of the way along a polyline."""
    if not path:
        return (0.0, 0.0)
    total = length(path)
    if total <= 0 or f <= 0:
        return path[0]
    if f >= 1:
        return path[-1]
    target, run = f * total, 0.0
    for i in range(len(path) - 1):
        seg = math.dist(path[i], path[i + 1])
        if run + seg >= target:
            t = (target - run) / seg if seg else 0
            return (
                path[i][0] + t * (path[i + 1][0] - path[i][0]),
                path[i][1] + t * (path[i + 1][1] - path[i][1]),
            )
        run += seg
    return path[-1]


def delivery_stops(seed: str, centre: Pt, n: int = 18) -> list[Pt]:
    """Display stops for a route zone (a sample of the real stop count),
    ordered as a nearest-neighbour tour from the zone edge nearest the
    station."""
    rng = random.Random(f"stops:{seed}")
    pts = [(centre[0] + rng.gauss(0, 1.3), centre[1] + rng.gauss(0, 1.3)) for _ in range(n)]
    tour, cur = [], min(pts, key=lambda p: math.hypot(*p))
    rest = [p for p in pts if p is not cur]
    tour.append(cur)
    while rest:
        nxt = min(rest, key=lambda p: math.dist(p, cur))
        rest.remove(nxt)
        tour.append(nxt)
        cur = nxt
    return [(round(x, 2), round(y, 2)) for x, y in tour]
