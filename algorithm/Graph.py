import csv
import heapq
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

import numpy as np

# How strongly pollution is penalised. A street at risk 1 costs (1 + alpha) x its length.
ALPHAS = {"shortest": 0, "balanced": 3, "cleanest": 10}

# CSV column indexes
LAT1_COL, LON1_COL, LAT2_COL, LON2_COL = 4, 5, 6, 7
LENGTH_COL = 8
RISK_COL = 16  # pm25


@dataclass(frozen=True, slots=True)
class Edge:
    to: tuple
    length: float
    risk: float


@dataclass(frozen=True, slots=True)
class Snap:
    """A point snapped onto the street network."""
    node: tuple
    extra: dict   # virtual edges for a mid-segment point (the graph stays untouched)
    seg: int
    t: float


def _num(s):
    """float(s), or None for blank / non-numeric / NaN / inf."""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class Graph:
    M_PER_DEG_LAT = 110540.0
    M_PER_DEG_LON = 111320.0

    def __init__(self):
        self.coords = {}
        self.adj = {}
        self.main_nodes = set()  # largest connected piece, used for snapping
        self._segs = []          # (u, v, edge) per street segment in main_nodes
        self._A = self._B = None  # numpy arrays of segment endpoints (lat, lon)

    # building nodes
    def add_node(self, node_id, lat, lon):
        self.coords[node_id] = (lat, lon)
        self.adj.setdefault(node_id, [])

    def add_edge(self, u, v, length, risk):
        risk = min(max(risk, 0.0), 1.0)
        self.adj[u].append(Edge(v, length, risk))
        self.adj[v].append(Edge(u, length, risk))

    @classmethod
    def from_csv(cls, path):
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

        # Scale min..max -> 0..1; streets with no value get the average
        lo, hi = min(known), max(known)
        span = (hi - lo) or 1.0
        fill = sum(known) / len(known)

        g = cls()
        for r, v in zip(rows, raw):
            vals = [_num(r[i]) if i < len(r) else None
                    for i in (LAT1_COL, LON1_COL, LAT2_COL, LON2_COL, LENGTH_COL)]
            if None in vals:
                continue
            lat1, lon1, lat2, lon2, length = vals

            a = (round(lat1, 6), round(lon1, 6))
            b = (round(lat2, 6), round(lon2, 6))
            if a == b:
                continue

            g.add_node(a, lat1, lon1)
            g.add_node(b, lat2, lon2)
            g.add_edge(a, b, length, ((v if v is not None else fill) - lo) / span)

        g._index()
        return g

    def _index(self):
        """Keep the largest connected component and index its segments for snapping."""
        seen, best = set(), []
        for start in self.adj:
            if start in seen:
                continue
            comp, stack = [], [start]
            seen.add(start)
            while stack:
                u = stack.pop()
                comp.append(u)
                for e in self.adj[u]:
                    if e.to not in seen:
                        seen.add(e.to)
                        stack.append(e.to)
            if len(comp) > len(best):
                best = comp

        self.main_nodes = set(best)
        if len(seen) != len(best):
            print(f"[Graph] several disconnected pieces; using the largest "
                  f"({len(best)} of {len(seen)} nodes)")

        # u < e.to so each two-way street is stored once
        self._segs = [(u, e.to, e) for u in best for e in self.adj[u] if u < e.to]
        self._A = np.array([s[0] for s in self._segs], dtype=float)
        self._B = np.array([s[1] for s in self._segs], dtype=float)

    # ---------- snapping ----------
    def _nearest_segment(self, lat, lon):
        """Index of the nearest segment and the position t (0..1) of the closest point."""
        kx = self.M_PER_DEG_LON * math.cos(math.radians(lat))
        ky = self.M_PER_DEG_LAT

        ax = (self._A[:, 1] - lon) * kx
        ay = (self._A[:, 0] - lat) * ky
        dx = (self._B[:, 1] - self._A[:, 1]) * kx
        dy = (self._B[:, 0] - self._A[:, 0]) * ky

        seg2 = dx * dx + dy * dy
        t = np.clip(-(ax * dx + ay * dy) / np.where(seg2 > 0, seg2, 1.0), 0.0, 1.0)
        px, py = ax + t * dx, ay + t * dy
        i = int(np.argmin(px * px + py * py))
        return i, float(t[i])

    def snap(self, lat, lon):
        """Snap a point to the nearest street. A mid-segment hit becomes a virtual node."""
        i, t = self._nearest_segment(lat, lon)
        u, v, e = self._segs[i]

        if t <= 1e-9:
            return Snap(u, {}, i, 0.0)
        if t >= 1 - 1e-9:
            return Snap(v, {}, i, 1.0)

        node = (round(u[0] + t * (v[0] - u[0]), 6), round(u[1] + t * (v[1] - u[1]), 6))
        l1, l2 = e.length * t, e.length * (1 - t)
        extra = {
            u: [Edge(node, l1, e.risk)],
            v: [Edge(node, l2, e.risk)],
            node: [Edge(u, l1, e.risk), Edge(v, l2, e.risk)],
        }
        return Snap(node, extra, i, t)


class Router:
    def __init__(self, graph):
        self.graph = graph

    @staticmethod
    def edge_cost(edge, alpha):
        return edge.length * (1 + alpha * edge.risk)

    @staticmethod
    def _merge(*dicts):
        out = defaultdict(list)
        for d in dicts:
            for k, edges in d.items():
                out[k].extend(edges)
        return out

    @staticmethod
    def path_stats(edges):
        """Length and length-weighted average risk of the edges actually used."""
        length = sum(e.length for e in edges)
        exposure = sum(e.length * e.risk for e in edges)
        return length, (exposure / length if length else 0.0)

    def _dijkstra(self, start, goal, alpha, extra):
        """Returns (path, edges) or None."""
        adj = self.graph.adj
        dist = {start: 0.0}
        prev = {}
        heap = [(0.0, start)]

        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:  # stale heap entry
                continue
            if u == goal:
                break
            for edge in chain(adj.get(u, ()), extra.get(u, ())):
                nd = d + self.edge_cost(edge, alpha)
                if nd < dist.get(edge.to, math.inf):
                    dist[edge.to] = nd
                    prev[edge.to] = (u, edge)
                    heapq.heappush(heap, (nd, edge.to))

        if goal not in dist:
            return None

        path, edges = [goal], []
        while path[-1] != start:
            u, e = prev[path[-1]]
            path.append(u)
            edges.append(e)
        return path[::-1], edges[::-1]

    def _route(self, start, goal, alpha, extra):
        found = self._dijkstra(start, goal, alpha, extra)
        if found is None:
            return None
        path, edges = found
        length, risk = self.path_stats(edges)
        return {"path": path, "length": length, "risk": risk}

    def find_routes(self, start_latlon, end_latlon):
        s = self.graph.snap(*start_latlon)
        g = self.graph.snap(*end_latlon)
        extra = self._merge(s.extra, g.extra)

        # Both points inside the same segment: connect them directly
        adj = self.graph.adj
        if s.seg == g.seg and s.node != g.node and s.node not in adj and g.node not in adj:
            e = self.graph._segs[s.seg][2]
            d = abs(s.t - g.t) * e.length
            extra = self._merge(extra, {s.node: [Edge(g.node, d, e.risk)],
                                        g.node: [Edge(s.node, d, e.risk)]})

        if s.node == g.node:
            return None

        shortest = self._route(s.node, g.node, ALPHAS["shortest"], extra)
        if shortest is None:
            return None

        # Only offer the clean route if it is really different and cleaner
        clean = self._route(s.node, g.node, ALPHAS["cleanest"], extra)
        if clean and clean["path"] != shortest["path"] and clean["risk"] < shortest["risk"]:
            return {"shortest": shortest, "clean": clean}
        return {"shortest": shortest, "clean": None}


# Thin wrappers so existing call sites keep working
def load_graph(path):
    return Graph.from_csv(path)


def find_routes(g, start_latlon, end_latlon):
    return Router(g).find_routes(start_latlon, end_latlon)


if __name__ == "__main__":
    BASE = Path(__file__).parent.parent
    router = Router(Graph.from_csv(BASE / "data" / "streets_with_values.csv"))
    res = router.find_routes((41.9945, 21.3270), (41.9932, 21.3216))
    if res:
        for name, r in res.items():
            print(name, None if r is None else (round(r["length"]), round(r["risk"], 2)))