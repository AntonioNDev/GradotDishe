import csv
import math
import json

SENSORS_CSV = "../data/pm25_sensors.csv"
STREETS_PIECES_CSV = "../data/skopje_street_pieces.csv"
OUTPUT_CSV = "../data/streets_with_sensors.csv"


# ---------- 1. СЕНЗОРИ ----------
def load_sensors(path):
    sensors = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                lat = float(row["lat"])
                lon = float(row["lon"])
            except (ValueError, KeyError):
                continue
            sensors.append({
                "id": row["sensor_id"],
                "lat": lat,
                "lon": lon,
                "name": row.get("description", ""),
            })
    return sensors


# ---------- 2. СЕГМЕНТИ (секој ред = еден сегмент, со name) ----------
def load_segments(path):
    segments = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            try:
                lat1 = float(row["start_lat"])
                lon1 = float(row["start_lon"])
                lat2 = float(row["end_lat"])
                lon2 = float(row["end_lon"])
            except (ValueError, KeyError):
                continue
            try:
                length_m = float(row["length_m"])
            except (ValueError, KeyError):
                length_m = 0.0

            segments.append({
                "street_name": name,
                "highway": row.get("highway", ""),
                "way_id": row.get("way_id", ""),
                "piece": row.get("piece", ""),
                "start_lat": lat1,
                "start_lon": lon1,
                "end_lat": lat2,
                "end_lon": lon2,
                "length_m": length_m,
            })
    return segments


# ---------- 3. РАСТОЈАНИЕ ----------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_sensor(lat, lon, sensors):
    best, best_d = None, float("inf")
    for s in sensors:
        d = haversine(lat, lon, s["lat"], s["lon"])
        if d < best_d:
            best_d, best = d, s
    return best, best_d


# ---------- 4. ГЛАВНА ----------
def main():
    sensors = load_sensors(SENSORS_CSV)
    segments = load_segments(STREETS_PIECES_CSV)
    print(f"Vcitani {len(sensors)} senzori i {len(segments)} segmenti.")

    if not sensors or not segments:
        print("Nema podatoci — proveri gi vleznite CSV.")
        return

    # Кешираме најблизок сензор по улица (за да не го бараме за секој сегмент)
    # центарот на улицата го сметаме од сите нејзини точки
    from collections import defaultdict
    street_points = defaultdict(list)
    for seg in segments:
        street_points[seg["street_name"]].append((seg["start_lat"], seg["start_lon"]))
        street_points[seg["street_name"]].append((seg["end_lat"], seg["end_lon"]))

    street_sensor = {}
    for name, pts in street_points.items():
        clat = sum(p[0] for p in pts) / len(pts)
        clon = sum(p[1] for p in pts) / len(pts)
        sensor, dist = nearest_sensor(clat, clon, sensors)
        street_sensor[name] = (sensor, dist, clat, clon)

    fieldnames = [
        # сегмент
        "street_name", "highway", "way_id", "piece",
        "start_lat", "start_lon", "end_lat", "end_lon", "length_m",
        # центар на улицата
        "street_center_lat", "street_center_lon",
        # сензор
        "sensor_id", "sensor_name", "sensor_lat", "sensor_lon", "distance_m",
    ]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for seg in segments:
            sensor, dist, clat, clon = street_sensor[seg["street_name"]]
            writer.writerow({
                "street_name": seg["street_name"],
                "highway": seg["highway"],
                "way_id": seg["way_id"],
                "piece": seg["piece"],
                "start_lat": f"{seg['start_lat']:.6f}",
                "start_lon": f"{seg['start_lon']:.6f}",
                "end_lat": f"{seg['end_lat']:.6f}",
                "end_lon": f"{seg['end_lon']:.6f}",
                "length_m": f"{seg['length_m']:.1f}",
                "street_center_lat": f"{clat:.6f}",
                "street_center_lon": f"{clon:.6f}",
                "sensor_id": sensor["id"],
                "sensor_name": sensor["name"],
                "sensor_lat": f"{sensor['lat']:.6f}",
                "sensor_lon": f"{sensor['lon']:.6f}",
                "distance_m": f"{dist:.1f}",
            })

    print(f"Zapishano: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()