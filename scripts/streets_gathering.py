import argparse
import csv
import json
import math
import os
import sys

import osmium
import requests

PBF_URL = "https://download.geofabrik.de/europe/macedonia-latest.osm.pbf"
SKOPJE_BBOX = (21.30, 41.93, 21.58, 42.07)

STREET_HIGHWAYS = {
    "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "pedestrian", "service", "trunk",
    "primary_link", "secondary_link", "tertiary_link", "trunk_link",
}


def download_pbf(path):
    if os.path.exists(path):
        return
    print(f"[i] Симнувам {PBF_URL} ...")
    with requests.get(PBF_URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)


def in_bbox(lon, lat):
    a, b, c, d = SKOPJE_BBOX
    return a <= lon <= c and b <= lat <= d


def dist_m(p, q):
    r = 6371000.0
    lon1, lat1, lon2, lat2 = map(math.radians, (p[0], p[1], q[0], q[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + \
        math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def bearing(p, q):
    lon1, lat1, lon2, lat2 = map(math.radians, (p[0], p[1], q[0], q[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - \
        math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angle_diff(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def split_straight(coords, max_angle, max_len):
    pieces = []
    start = coords[0]
    last = coords[0]
    piece_bearing = None

    for pt in coords[1:]:
        seg_len = dist_m(last, pt)
        if seg_len < 0.5:
            continue

        if piece_bearing is None:
            piece_bearing = bearing(last, pt)
            last = pt
            continue

        seg_bearing = bearing(last, pt)
        turn = angle_diff(piece_bearing, seg_bearing)
        too_long = dist_m(start, last) >= max_len

        if (turn > max_angle and seg_len >= 3) or too_long:
            pieces.append((start, last))
            start = last
            piece_bearing = bearing(last, pt)
        last = pt

    if dist_m(start, last) >= 0.5:
        pieces.append((start, last))
    return pieces


class Handler(osmium.SimpleHandler):
    def __init__(self, max_angle, max_len, per_segment):
        super().__init__()
        self.max_angle = max_angle
        self.max_len = max_len
        self.per_segment = per_segment
        self.rows = []

    def way(self, w):
        highway = w.tags.get("highway")
        name = w.tags.get("name") or w.tags.get("name:mk")
        if highway not in STREET_HIGHWAYS or not name:
            return
        try:
            coords = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2:
            return

        if self.per_segment:
            pieces = list(zip(coords[:-1], coords[1:]))
        else:
            pieces = split_straight(coords, self.max_angle, self.max_len)

        for idx, (s, e) in enumerate(pieces, start=1):
            if not (in_bbox(*s) and in_bbox(*e)):
                continue
            self.rows.append({
                "name": name,
                "highway": highway,
                "way_id": w.id,
                "piece": idx,
                "start_lat": round(s[1], 7),
                "start_lon": round(s[0], 7),
                "end_lat": round(e[1], 7),
                "end_lon": round(e[0], 7),
                "length_m": round(dist_m(s, e), 1),
            })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", default="macedonia-latest.osm.pbf")
    ap.add_argument("--out", default="skopje_street_pieces.csv")
    ap.add_argument("--json", default="skopje_street_pieces.json")
    ap.add_argument("--angle", type=float, default=20.0,
                    help="максимално свртување (степени) во еден дел, default 20")
    ap.add_argument("--max-len", type=float, default=300.0,
                    help="максимална должина на дел во метри, default 300")
    ap.add_argument("--per-segment", action="store_true",
                    help="секој пар соседни јазли = еден ред (најситно)")
    args = ap.parse_args()

    download_pbf(args.pbf)
    print("[i] Читам и сечам улици ...")
    h = Handler(args.angle, args.max_len, args.per_segment)
    h.apply_file(args.pbf, locations=True, idx="flex_mem")
    h.rows.sort(key=lambda r: (r["name"], r["way_id"], r["piece"]))

    fields = ["name", "highway", "way_id", "piece", "start_lat", "start_lon",
              "end_lat", "end_lon", "length_m"]
    with open(args.out, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        wr.writerows(h.rows)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(h.rows, f, ensure_ascii=False, indent=2)

    names = len({r["name"] for r in h.rows})
    print(f"[i] {len(h.rows)} прави делови од {names} имиња -> {args.out}, {args.json}")


if __name__ == "__main__":
    sys.exit(main())