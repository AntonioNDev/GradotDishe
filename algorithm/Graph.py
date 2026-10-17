from dataclasses import dataclass
from itertools import chain
from pathlib import Path
import csv
import heapq
import math

import numpy as np

# cleanest = how strongly pollution is penalised. Risk is now scaled 0..1 between
# the cleanest and dirtiest street, so a street at risk 1 costs (1 + alpha) times
# its length. Raise it to avoid dirty streets harder, lower it for smaller detours.
ALPHAS = {"shortest": 0, "balanced": 3, "cleanest": 10}

# CSV column indexes
LAT1_COL, LON1_COL, LAT2_COL, LON2_COL = 4, 5, 6, 7
LENGTH_COL = 8
RISK_COL = 16   # pollution value per street (printed on load so you can verify it)


@dataclass
class Edge:
    to: tuple
    length: float
    risk: float


class Graph:
    def __init__(self):
        self.coords = {}
        self.adj = {}
        # filled by _build_index(): only the largest connected piece of the street
        # network is used for snapping, so start and goal can always be connected.
        self.main_nodes = set()
        self._segs = []   # (u, v, edge) for every street segment in the main component
        self._A = None    # numpy arrays of segment endpoints (lat, lon)
        self._B = None

    def add_node(self, node_id, lat, lon):
        self.coords[node_id] = (lat, lon)
        self.adj.setdefault(node_id, [])

    def add_edge(self, u, v, length, risk, two_way=True):
        risk = min(max(risk, 0.0), 1.0)
        self.adj[u].append(Edge(v, length, risk))
        if two_way:
            self.adj[v].append(Edge(u, length, risk))


# --------------------------------------------------------------------- loading
def _num(s):
    """float(s), or None for blank / non-numeric / NaN / inf."""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def load_graph(path):
    g = Graph()

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    if RISK_COL < len(header):
        print(f"[Graph] using column {RISK_COL} ('{header[RISK_COL]}') as pollution value")

    raw = [_num(r[RISK_COL]) if len(r) > RISK_COL else None for r in rows]
    known = [v for v in raw if v is not None]
    if not known:
        raise ValueError(f"No numeric pollution values in column {RISK_COL}")

    # Scale min..max -> 0..1 (the old code divided by max only, which squeezes
    # all streets into a narrow band near 1 so the router barely notices them).
    lo, hi = min(known), max(known)
    span = (hi - lo) or 1.0
    # Streets with a missing value get the average instead of NaN (which made
    # them impassable) or 0 (which made them look perfectly clean).
    fill = sum(known) / len(known)

    for r, v in zip(rows, raw):
        vals = [_num(r[i]) if i < len(r) else None
                for i in (LAT1_COL, LON1_COL, LAT2_COL, LON2_COL, LENGTH_COL)]
        if any(x is None for x in vals):
            continue
        lat1, lon1, lat2, lon2, length = vals

        a = (round(lat1, 6), round(lon1, 6))
        b = (round(lat2, 6), round(lon2, 6))
        if a == b:
            continue

        risk = ((v if v is not None else fill) - lo) / span

        g.add_node(a, lat1, lon1)
        g.add_node(b, lat2, lon2)
        g.add_edge(a, b, length, risk)

    _build_index(g)
    return g


def _build_index(g):
    """Find the largest connected component and index its segments for snapping."""
    seen = set()
    best = []
    for s in g.adj:
        if s in seen:
            continue
        comp, stack = [], [s]
        seen.add(s)
        while stack:
            u = stack.pop()
            comp.append(u)
            for e in g.adj[u]:
                if e.to not in seen:
                    seen.add(e.to)
                    stack.append(e.to)
        if len(comp) > len(best):
            best = comp

    g.main_nodes = set(best)
    if len(seen) != len(best):
        print(f"[Graph] network has several disconnected pieces; "
              f"using the largest ({len(best)} of {len(seen)} nodes)")

    g._segs = [(u, e.to, e)
               for u in g.main_nodes
               for e in g.adj[u]
               if u < e.to]                       # each two-way street once
    g._A = np.array([u for u, _, _ in g._segs], dtype=float)
    g._B = np.array([v for _, v, _ in g._segs], dtype=float)


# -------------------------------------------------------------------- snapping
def _nearest_segment(g, lat, lon):
    """Index of the nearest street segment to (lat, lon) and the position t (0..1)
    along it of the closest point. Always returns something."""
    kx = 111320.0 * math.cos(math.radians(lat))   # metres per degree of longitude
    ky = 110540.0                                 # metres per degree of latitude

    ax = (g._A[:, 1] - lon) * kx
    ay = (g._A[:, 0] - lat) * ky
    dx = (g._B[:, 1] - g._A[:, 1]) * kx
    dy = (g._B[:, 0] - g._A[:, 0]) * ky

    seg2 = dx * dx + dy * dy
    safe = np.where(seg2 > 0, seg2, 1.0)
    t = np.clip(-(ax * dx + ay * dy) / safe, 0.0, 1.0)

    px = ax + t * dx
    py = ay + t * dy
    i = int(np.argmin(px * px + py * py))
    return i, float(t[i])


def _snap_point(g, lat, lon):
    """Snap a clicked point onto the nearest street.

    Returns (node, extra_adj, seg_index, t). If the closest point is in the middle
    of a segment, a virtual node is created there and wired to both ends through
    `extra_adj`, so the graph itself is never modified (thread-safe).
    """
    i, t = _nearest_segment(g, lat, lon)
    u, v, e = g._segs[i]

    if t <= 1e-9:
        return u, {}, i, 0.0
    if t >= 1 - 1e-9:
        return v, {}, i, 1.0

    (ulat, ulon), (vlat, vlon) = u, v
    node = (round(ulat + t * (vlat - ulat), 6), round(ulon + t * (vlon - ulon), 6))
    l1, l2 = e.length * t, e.length * (1 - t)
    extra = {
        u: [Edge(node, l1, e.risk)],
        v: [Edge(node, l2, e.risk)],
        node: [Edge(u, l1, e.risk), Edge(v, l2, e.risk)],
    }
    return node, extra, i, t


def _merge(*dicts):
    out = {}
    for d in dicts:
        for k, lst in d.items():
            out.setdefault(k, []).extend(lst)
    return out


# ---------------------------------------------------------------------- search
def edge_cost(edge, alpha):
    return edge.length * (1 + alpha * edge.risk)


def dijkstra(graph, start, goal, alpha=0.0, extra=None):
    """Returns (path, cost, edges) or None. `edges` are the edges actually used."""
    extra = extra or {}
    dist = {start: 0.0}
    prev = {}
    heap = [(0.0, start)]
    visited = set()

    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)
        if u == goal:
            break

        for edge in chain(graph.adj.get(u, ()), extra.get(u, ())):
            new_d = d + edge_cost(edge, alpha)
            if new_d < dist.get(edge.to, float("inf")):
                dist[edge.to] = new_d
                prev[edge.to] = (u, edge)
                heapq.heappush(heap, (new_d, edge.to))

    if goal not in dist:
        return None

    path, edges = [goal], []
    while path[-1] != start:
        u, e = prev[path[-1]]
        edges.append(e)
        path.append(u)
    path.reverse()
    edges.reverse()
    return path, dist[goal], edges


def path_stats(edges):
    """Length and length-weighted average risk of the edges the route really uses.
    (The old version re-picked the shortest parallel edge, which could differ from
    the one Dijkstra chose, so clean-vs-short comparisons were wrong.)"""
    length = sum(e.length for e in edges)
    exposure = sum(e.length * e.risk for e in edges)
    return length, (exposure / length if length > 0 else 0.0)


def find_routes(g, start_latlon, end_latlon):
    s_node, s_extra, s_i, s_t = _snap_point(g, *start_latlon)
    g_node, g_extra, g_i, g_t = _snap_point(g, *end_latlon)
    extra = _merge(s_extra, g_extra)

    # Both points on the same street segment: connect them directly.
    if s_i == g_i and s_node != g_node and s_node not in g.adj and g_node not in g.adj:
        e = g._segs[s_i][2]
        d = abs(s_t - g_t) * e.length
        extra = _merge(extra, {s_node: [Edge(g_node, d, e.risk)],
                               g_node: [Edge(s_node, d, e.risk)]})

    if s_node == g_node:
        return None

    shortest = dijkstra(g, s_node, g_node, alpha=ALPHAS["shortest"], extra=extra)
    if shortest is None:
        return None
    short_path, _, short_edges = shortest
    short_len, short_risk = path_stats(short_edges)

    result = {
        "shortest": {"path": short_path, "length": short_len, "risk": short_risk},
        "clean": None,
    }

    clean = dijkstra(g, s_node, g_node, alpha=ALPHAS["cleanest"], extra=extra)
    if clean is not None:
        clean_path, _, clean_edges = clean
        clean_len, clean_risk = path_stats(clean_edges)
        if clean_path != short_path and clean_risk < short_risk:
            result["clean"] = {"path": clean_path, "length": clean_len, "risk": clean_risk}

    return result


def show(result):
    if result is None:
        print("No path")
        return
    path, cost, edges = result
    length, risk = path_stats(edges)
    print(f"Cost: {cost:.1f}, length: {length:.0f}, avg risk: {risk:.2f}, nodes: {len(path)}")
    for i, (lat, lon) in enumerate(path):
        print(f"  {i}: {lat}, {lon}")


if __name__ == "__main__":
    BASE = Path(__file__).parent
    g = load_graph(BASE / "streets_with_values.csv")
    res = find_routes(g, (41.9945, 21.3270), (41.9932, 21.3216))
    if res:
        for name in ("shortest", "clean"):
            r = res[name]
            print(name, None if r is None else (round(r["length"]), round(r["risk"], 2)))