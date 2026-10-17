import csv
import math
from collections import defaultdict

# ---------- 1. ЧИТАЊЕ НА СЕНЗОРИ ----------
def load_sensors(path):
    sensors = []
    with open(path, encoding="utf-8-sig") as f:   # -sig за BOM
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (ValueError, KeyError):
                continue
            sensors.append({
                "id": row["sensor_id"],
                "lat": lat,
                "lon": lon,
                "name": row["description"],
            })
    return sensors


# ---------- 2. ЧИТАЊЕ НА УЛИЦИ (групирање по име) ----------
def load_streets(path):
    """
    CSV: name,highway,way_id,piece,start_lat,start_lon,end_lat,end_lon,length_m
    Секој ред е сегмент. Групираме по 'name'.
    """
    streets = defaultdict(lambda: {"points": [], "highway": set(), "ways": set()})
    with open(path, encoding="utf-8-sig") as f:   # -sig за BOM
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"].strip()
            if not name:
                continue
            try:
                lat1 = float(row["start_lat"])
                lon1 = float(row["start_lon"])
                lat2 = float(row["end_lat"])
                lon2 = float(row["end_lon"])
            except (ValueError, KeyError):
                continue
            s = streets[name]
            s["points"].append((lat1, lon1))
            s["points"].append((lat2, lon2))
            s["highway"].add(row["highway"])
            s["ways"].add(row["way_id"])

    result = []
    for name, s in streets.items():
        pts = s["points"]
        if not pts:
            continue
        mean_lat = sum(p[0] for p in pts) / len(pts)
        mean_lon = sum(p[1] for p in pts) / len(pts)
        result.append({
            "name": name,
            "highway": ",".join(sorted(s["highway"])),
            "n_ways": len(s["ways"]),
            "n_points": len(pts),
            "center_lat": mean_lat,
            "center_lon": mean_lon,
        })
    return result


# ---------- 3. РАСТОЈАНИЕ ----------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0  # метри
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_sensor(lat, lon, sensors):
    best = None
    best_d = float("inf")
    for s in sensors:
        d = haversine(lat, lon, s["lat"], s["lon"])
        if d < best_d:
            best_d = d
            best = s
    return best, best_d


# ---------- 4. ГЛАВНА ЛОГИКА ----------
def assign_sensors_to_streets(sensors_path, streets_path, out_path):
    sensors = load_sensors(sensors_path)
    streets = load_streets(streets_path)

    print(f"Вчитани {len(sensors)} сензори и {len(streets)} улици.\n")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "street_name", "highway", "n_ways", "n_points",
            "center_lat", "center_lon",
            "sensor_id", "sensor_name", "sensor_lat", "sensor_lon",
            "distance_m"
        ])
        for st in sorted(streets, key=lambda x: x["name"]):
            sensor, dist = nearest_sensor(st["center_lat"], st["center_lon"], sensors)
            writer.writerow([
                st["name"], st["highway"], st["n_ways"], st["n_points"],
                f"{st['center_lat']:.6f}", f"{st['center_lon']:.6f}",
                sensor["id"], sensor["name"],
                f"{sensor['lat']:.6f}", f"{sensor['lon']:.6f}",
                f"{dist:.1f}"
            ])

    print(f"Готово! Резултатот е зачуван во: {out_path}")


if __name__ == "__main__":
    assign_sensors_to_streets(
        sensors_path="../data/pm25_sensors.csv",
        streets_path="../data/skopje_street_pieces.csv",
        out_path="../data/streets_with_sensors.csv"
    )
