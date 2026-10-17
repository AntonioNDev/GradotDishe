from dataclasses import dataclass
import heapq

@dataclass
class Edge:
    to: int
    length: float
    risk: float

class Graph:
    def __int__(self):
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