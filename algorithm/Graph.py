from dataclasses import dataclass
import heapq
import csv
from pathlib import Path

ALPHAS = {"shortest": 0, "balanced": 3, "cleanest": 25}

@dataclass
class Edge:
    to: int
    length: float
    risk: float

class Graph:
    def __init__(self):
        self.coords = {}
        self.adj={}

    def add_node(self, node_id, lat, lon):
        self.coords[node_id] = (lat, lon)
        self.adj.setdefault(node_id, [])

    def add_edge(self, u, v, length, risk, two_way=True):
        risk = min(max(risk, 0.0), 1.0)
        self.adj[u].append(Edge(v, length, risk))
        if two_way:
            self.adj[v].append(Edge(u, length, risk))

def load_graph(path):
    g = Graph()

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        rows = list(reader)

    max_value = max(float(r[16]) for r in rows)

    for r in rows:
        lat1, lon1 = float(r[4]), float(r[5])
        lat2, lon2 = float(r[6]), float(r[7])
        length = float(r[8])
        risk = float(r[16]) / max_value

        a = (round(lat1, 6), round(lon1, 6))
        b = (round(lat2, 6), round(lon2, 6))

        g.add_node(a, lat1, lon1)
        g.add_node(b, lat2, lon2)
        g.add_edge(a, b, length, risk)

    return g

def nearest_node(graph, lat, lon):
    return min(
        graph.coords,
        key=lambda n: (graph.coords[n][0] - lat) ** 2 + (graph.coords[n][1] - lon) ** 2
    )

def edge_cost(edge, alpha):
    return edge.length * (1+alpha * edge.risk)

def dijkstra(graph, start, goal, alpha=0.0):
    dist = {start: 0.0}
    prev = {}
    heap = [(0.0, start)]
    visited = set()

    while heap:
        d,  u = heapq.heappop(heap)

        if u in visited:
            continue
        visited.add(u)
        if u == goal:
            break

        for edge in graph.adj[u]:
            new_d = d + edge_cost(edge, alpha)
            if new_d < dist.get(edge.to, float("inf")):
                dist[edge.to] = new_d
                prev[edge.to] = u
                heapq.heappush(heap, (new_d, edge.to))

    if goal not in dist:
        return None

    path = [goal]
    while path[-1] != start:
        path.append(prev[path[-1]])
    path.reverse()
    return path, dist[goal]

def show(result):
    if result is None:
        print("No path")
        return
    path, cost = result
    print(f"Cost: {cost:.1f}, nodes: {len(path)}")
    for i, (lat, lon) in enumerate(path):
        print(f"  {i}: {lat}, {lon}")

def find_routes(g, start_latlon, end_latlon):
    start = nearest_node(g, start_latlon[0], start_latlon[1])
    goal = nearest_node(g, end_latlon[0], end_latlon[1])
    print("start node:", start, "goal node:", goal)


    shortest = dijkstra(g, start, goal, alpha=0)
    if shortest is None:
        return None
    short_path = shortest[0]
    short_len, short_risk = path_stats(g, short_path)

    result = {
        "shortest": {"path": short_path, "length": short_len, "risk": short_risk},
        "clean": None,
    }

    clean_path = dijkstra(g, start, goal, alpha=ALPHAS["cleanest"])[0]
    clean_len, clean_risk = path_stats(g, clean_path)

    if clean_path != short_path and clean_risk < short_risk:
        result["clean"] = {"path": clean_path, "length": clean_len, "risk": clean_risk}

    return result

def path_stats(g, path):
    length = 0.0
    exposure = 0.0
    for u, v in zip(path, path[1:]):
        edge = min((e for e in g.adj[u] if e.to == v), key=lambda e: e.length)
        length += edge.length
        exposure += edge.length * edge.risk
    avg_risk = exposure / length if length > 0 else 0.0
    return length, avg_risk

if __name__ == "__main__":
    BASE = Path(__file__).parent
    g = load_graph(BASE / "streets_with_values.csv")
    start = nearest_node(g, 41.9945, 21.3270)
    goal = nearest_node(g, 41.9932, 21.3216)
    print(dijkstra(g, start, goal, alpha=0))
    print(dijkstra(g, start, goal, alpha=3))
