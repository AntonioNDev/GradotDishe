import argparse
import csv
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import osmium
import requests
from requests.auth import HTTPBasicAuth

USERNAME = os.getenv("PULSE_USERNAME", "PLACEHOLDER")  # INSERT YOUR API USERNAME
PASSWORD = os.getenv("PULSE_PASSWORD", "PLACEHOLDER")  # INSERT YOUR API PASSWORD
BASE_URL = "https://skopje.pulse.eco/rest"

PBF_URL = "https://download.geofabrik.de/europe/macedonia-latest.osm.pbf"
SKOPJE_BBOX = (21.30, 41.93, 21.58, 42.07)  # min_lon, min_lat, max_lon, max_lat

STREET_HIGHWAYS = {
    "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "pedestrian", "service", "trunk",
    "primary_link", "secondary_link", "tertiary_link", "trunk_link",
}

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
PBF_PATH = DATA_DIR / "macedonia-latest.osm.pbf"
SENSORS_CSV = DATA_DIR / "pm25_sensors.csv"
STREETS_PIECES_CSV = DATA_DIR / "skopje_street_pieces.csv"
STREETS_PIECES_JSON = DATA_DIR / "skopje_street_pieces.json"
STREETS_WITH_SENSORS_CSV = DATA_DIR / "streets_with_sensors.csv"
STREETS_WITH_VALUES_CSV = DATA_DIR / "streets_with_values.csv"

CACHE_TTL_SECONDS = 30 * 60  # 30 min
WINDOW_MINUTES = 15          # averaging window for sensor readings
TZ_SKOPJE = ZoneInfo("Europe/Skopje")

log = logging.getLogger("skopje_air")


class DataStore:
    """Reads and writes the files in the data folder."""

    @staticmethod
    def read_csv(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def write_csv(path, fieldnames, rows):
        # Write to a temp file first so a crash never leaves a half-written CSV
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            os.replace(tmp, path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    @staticmethod
    def write_json(path, rows):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

class Geo:
    R = 6371000.0

    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * Geo.R * math.asin(math.sqrt(a))

    @staticmethod
    def dist_m(p, q):
        # points are (lon, lat) tuples
        return Geo.haversine(p[1], p[0], q[1], q[0])

    @staticmethod
    def bearing(p, q):
        lon1, lat1, lon2, lat2 = map(math.radians, (p[0], p[1], q[0], q[1]))
        y = math.sin(lon2 - lon1) * math.cos(lat2)
        x = (math.cos(lat1) * math.sin(lat2)
             - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    @staticmethod
    def angle_diff(a, b):
        d = abs(a - b) % 360
        return d if d <= 180 else 360 - d

    @staticmethod
    def in_bbox(lon, lat):
        min_lon, min_lat, max_lon, max_lat = SKOPJE_BBOX
        return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


class PulseEcoClient:
    """This is our client for the Pulse.eco Skopje API."""

    def __init__(self, base_url=BASE_URL, username=USERNAME, password=PASSWORD):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(username, password)

    def _get(self, endpoint, params=None):
        resp = self.session.get(f"{self.base_url}/{endpoint}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def fetch_sensors(self):
        return self._get("sensor")

    def fetch_pm25_measurements(self):
        now = datetime.now(TZ_SKOPJE)
        params = {
            "type": "pm25",
            "from": (now - timedelta(minutes=WINDOW_MINUTES)).isoformat(timespec="seconds"),
            "to": now.isoformat(timespec="seconds"),
        }
        return self._get("dataRaw", params)

    def fetch_pm25_by_sensor(self):
        """Returns dict: sensor_id -> average pm25 over the last WINDOW_MINUTES."""
        sums, counts = {}, {}
        for m in self.fetch_pm25_measurements():
            sid = m.get("sensorId")
            val = m.get("value")
            if sid is None or val is None:
                continue
            try:
                val = float(val)
            except (ValueError, TypeError):
                continue
            sid = str(sid)  # CSV ids are strings
            sums[sid] = sums.get(sid, 0.0) + val
            counts[sid] = counts.get(sid, 0) + 1
        return {sid: sums[sid] / counts[sid] for sid in sums}


class SensorCollector:
    """Saves the active sensors that reported pm25 recently to pm25_sensors.csv."""

    FIELDNAMES = ["sensor_id", "lat", "lon", "description"]

    def __init__(self, client, output_csv=SENSORS_CSV):
        self.client = client
        self.output_csv = output_csv

    @staticmethod
    def parse_position(pos):
        try:
            lat_str, lon_str = pos.split(",")
            return float(lat_str), float(lon_str)
        except ValueError:
            return None

    def run(self):
        try:
            sensors = self.client.fetch_sensors()
            measurements = self.client.fetch_pm25_measurements()
        except (requests.RequestException, ValueError) as e:
            log.error("Could not fetch sensors: %s", e)
            return False

        active = [s for s in sensors if (s.get("status") or "").upper().startswith("ACTIVE")]
        log.info("Sensors: %d total, %d active", len(sensors), len(active))

        reporting = {str(m["sensorId"]) for m in measurements if "sensorId" in m}
        log.info("Sensors with pm25 readings in the last %d min: %d", WINDOW_MINUTES, len(reporting))

        pm25_sensors = []
        for s in active:
            sid = str(s.get("sensorId", ""))
            if sid not in reporting:
                continue
            pos = (s.get("position") or "").strip()
            if not pos:
                continue
            coords = self.parse_position(pos)
            if coords is None:
                log.warning("Bad position for sensor %s: %s", sid, pos)
                continue
            pm25_sensors.append({
                "sensor_id": sid,
                "lat": coords[0],
                "lon": coords[1],
                "description": s.get("description", ""),
            })

        if not pm25_sensors:
            log.warning("No usable pm25 sensors, keeping the old %s", self.output_csv.name)
            return False

        try:
            DataStore.write_csv(self.output_csv, self.FIELDNAMES, pm25_sensors)
        except OSError as e:
            log.error("Could not write %s: %s", self.output_csv, e)
            return False

        log.info("Saved %d pm25 sensors -> %s", len(pm25_sensors), self.output_csv)
        return True


class StreetHandler(osmium.SimpleHandler):
    """Collects named streets from the PBF and cuts them into pieces."""

    def __init__(self, max_angle, max_len, per_segment):
        super().__init__()
        self.max_angle = max_angle
        self.max_len = max_len
        self.per_segment = per_segment
        self.rows = []

    def split_straight(self, coords):
        pieces = []
        start = last = coords[0]
        piece_bearing = None

        for pt in coords[1:]:
            seg_len = Geo.dist_m(last, pt)
            if seg_len < 0.5:
                continue

            if piece_bearing is None:
                piece_bearing = Geo.bearing(last, pt)
                last = pt
                continue

            turn = Geo.angle_diff(piece_bearing, Geo.bearing(last, pt))
            too_long = Geo.dist_m(start, last) >= self.max_len

            if (turn > self.max_angle and seg_len >= 3) or too_long:
                pieces.append((start, last))
                start = last
                piece_bearing = Geo.bearing(last, pt)
            last = pt

        if Geo.dist_m(start, last) >= 0.5:
            pieces.append((start, last))
        return pieces

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
            pieces = self.split_straight(coords)

        for idx, (s, e) in enumerate(pieces, start=1):
            if not (Geo.in_bbox(*s) and Geo.in_bbox(*e)):
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
                "length_m": round(Geo.dist_m(s, e), 1),
            })


class StreetCollector:
    """Downloads the OSM extract and writes skopje_street_pieces.csv/json."""

    FIELDNAMES = ["name", "highway", "way_id", "piece", "start_lat", "start_lon",
                  "end_lat", "end_lon", "length_m"]

    def __init__(self, pbf_path=PBF_PATH, max_angle=20.0, max_len=300.0, per_segment=False,
                 out_csv=STREETS_PIECES_CSV, out_json=STREETS_PIECES_JSON):
        self.pbf_path = Path(pbf_path)
        self.max_angle = max_angle
        self.max_len = max_len
        self.per_segment = per_segment
        self.out_csv = out_csv
        self.out_json = out_json

    def download_pbf(self):
        if self.pbf_path.exists():
            return True

        log.info("Downloading %s", PBF_URL)
        self.pbf_path.parent.mkdir(parents=True, exist_ok=True)
        part = self.pbf_path.with_suffix(".part")
        try:
            with requests.get(PBF_URL, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
            os.replace(part, self.pbf_path)
            return True
        except (requests.RequestException, OSError) as e:
            log.error("PBF download failed: %s", e)
            part.unlink(missing_ok=True)
            return False

    def run(self):
        if not self.download_pbf():
            return False

        log.info("Reading and cutting streets...")
        handler = StreetHandler(self.max_angle, self.max_len, self.per_segment)
        try:
            handler.apply_file(str(self.pbf_path), locations=True, idx="flex_mem")
        except (RuntimeError, OSError) as e:
            log.error("Could not read %s: %s", self.pbf_path, e)
            return False

        if not handler.rows:
            log.warning("No streets found, keeping the old files")
            return False

        handler.rows.sort(key=lambda r: (r["name"], r["way_id"], r["piece"]))
        try:
            DataStore.write_csv(self.out_csv, self.FIELDNAMES, handler.rows)
            DataStore.write_json(self.out_json, handler.rows)
        except OSError as e:
            log.error("Could not write street files: %s", e)
            return False

        names = len({r["name"] for r in handler.rows})
        log.info("%d straight pieces from %d street names -> %s", len(handler.rows), names, self.out_csv)
        return True


class StreetSensorMapper:
    """Assigns the nearest pm25 sensor to every street."""

    FIELDNAMES = [
        "street_name", "highway", "way_id", "piece",
        "start_lat", "start_lon", "end_lat", "end_lon", "length_m",
        "street_center_lat", "street_center_lon",
        "sensor_id", "sensor_name", "sensor_lat", "sensor_lon", "distance_m",
    ]

    def __init__(self, sensors_csv=SENSORS_CSV, pieces_csv=STREETS_PIECES_CSV,
                 output_csv=STREETS_WITH_SENSORS_CSV):
        self.sensors_csv = sensors_csv
        self.pieces_csv = pieces_csv
        self.output_csv = output_csv

    def load_sensors(self):
        sensors = []
        for row in DataStore.read_csv(self.sensors_csv):
            try:
                sensors.append({
                    "id": row["sensor_id"],
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "name": row.get("description", ""),
                })
            except (ValueError, KeyError):
                continue
        return sensors

    def load_segments(self):
        segments = []
        for row in DataStore.read_csv(self.pieces_csv):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            try:
                lat1, lon1 = float(row["start_lat"]), float(row["start_lon"])
                lat2, lon2 = float(row["end_lat"]), float(row["end_lon"])
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

    @staticmethod
    def nearest_sensor(lat, lon, sensors):
        return min(
            ((Geo.haversine(lat, lon, s["lat"], s["lon"]), s) for s in sensors),
            key=lambda pair: pair[0],
        )

    def run(self):
        try:
            sensors = self.load_sensors()
            segments = self.load_segments()
        except OSError as e:
            log.error("Could not read the input CSVs: %s", e)
            return False

        log.info("Loaded %d sensors and %d segments", len(sensors), len(segments))
        if not sensors or not segments:
            log.error("Missing data, check the input CSVs")
            return False

        # One lookup per street instead of one per segment
        street_points = defaultdict(list)
        for seg in segments:
            street_points[seg["street_name"]].append((seg["start_lat"], seg["start_lon"]))
            street_points[seg["street_name"]].append((seg["end_lat"], seg["end_lon"]))

        street_sensor = {}
        for name, pts in street_points.items():
            clat = sum(p[0] for p in pts) / len(pts)
            clon = sum(p[1] for p in pts) / len(pts)
            dist, sensor = self.nearest_sensor(clat, clon, sensors)
            street_sensor[name] = (sensor, dist, clat, clon)

        rows = []
        for seg in segments:
            sensor, dist, clat, clon = street_sensor[seg["street_name"]]
            rows.append({
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

        try:
            DataStore.write_csv(self.output_csv, self.FIELDNAMES, rows)
        except OSError as e:
            log.error("Could not write %s: %s", self.output_csv, e)
            return False

        log.info("Saved %s", self.output_csv)
        return True


class StreetPM25Builder:
    """Builds streets_with_values.csv from streets_with_sensors.csv + live pm25."""

    def __init__(self, client, streets_with_sensors_csv=STREETS_WITH_SENSORS_CSV,
                 streets_with_values_csv=STREETS_WITH_VALUES_CSV,
                 cache_ttl_seconds=CACHE_TTL_SECONDS):
        self.client = client
        self.streets_with_sensors_csv = Path(streets_with_sensors_csv)
        self.streets_with_values_csv = Path(streets_with_values_csv)
        self.cache_ttl_seconds = cache_ttl_seconds

    def cache_age_seconds(self):
        try:
            return time.time() - self.streets_with_values_csv.stat().st_mtime
        except FileNotFoundError:
            return None

    def is_cache_fresh(self):
        age = self.cache_age_seconds()
        if age is None or age >= self.cache_ttl_seconds:
            return False
        # The street-sensor mapping may have been rebuilt after the values were made
        try:
            return (self.streets_with_values_csv.stat().st_mtime
                    >= self.streets_with_sensors_csv.stat().st_mtime)
        except FileNotFoundError:
            return True

    @staticmethod
    def fill_with_global_mean(rows):
        """Fills empty pm25 cells with the mean of the known values."""
        vals = []
        for r in rows:
            try:
                vals.append(float(r["pm25"]))
            except (KeyError, ValueError, TypeError):
                continue

        if not vals:
            return rows

        mean_str = f"{sum(vals) / len(vals):.1f}"
        for r in rows:
            if r.get("pm25", "") in ("", None):
                r["pm25"] = mean_str
        return rows

    def build_streets_with_values(self):
        try:
            streets = DataStore.read_csv(self.streets_with_sensors_csv)
        except OSError as e:
            log.error("Could not read %s: %s", self.streets_with_sensors_csv, e)
            return False

        if not streets:
            log.warning("No streets found, nothing to do")
            return False

        try:
            pm25_by_sensor = self.client.fetch_pm25_by_sensor()
        except (requests.RequestException, ValueError) as e:
            log.error("Could not fetch pm25 data: %s", e)
            return False

        if not pm25_by_sensor:
            log.warning("API returned no pm25 readings, keeping the old file")
            return False

        now_iso = datetime.now(TZ_SKOPJE).isoformat(timespec="seconds")

        for st in streets:
            val = pm25_by_sensor.get(st.get("sensor_id", ""))
            st["pm25"] = f"{val:.1f}" if val is not None else ""  # gaps filled below
            st["pm25_timestamp"] = now_iso

        streets = self.fill_with_global_mean(streets)

        fieldnames = list(dict.fromkeys([*streets[0].keys(), "pm25", "pm25_timestamp"]))
        try:
            DataStore.write_csv(self.streets_with_values_csv, fieldnames, streets)
        except OSError as e:
            log.error("Could not write %s: %s", self.streets_with_values_csv, e)
            return False

        log.info("Saved %s", self.streets_with_values_csv)
        return True

    def run(self):
        if self.is_cache_fresh():
            log.info("Cache is fresh (%.1f min), not overwriting %s",
                     self.cache_age_seconds() / 60, self.streets_with_values_csv.name)
            return True

        log.info("Cache is older than %d min or missing, recalculating", self.cache_ttl_seconds // 60)
        return self.build_streets_with_values()


class Pipeline:
    """Runs all stages in order. A failed stage is logged and the rest still run."""

    def __init__(self, args):
        client = PulseEcoClient()
        self.rebuild_streets = args.rebuild_streets
        self.streets = StreetCollector(
            pbf_path=args.pbf,
            max_angle=args.angle,
            max_len=args.max_len,
            per_segment=args.per_segment,
        )
        self.sensors = SensorCollector(client)
        self.mapper = StreetSensorMapper()
        self.values = StreetPM25Builder(client)

    def run_streets(self):
        # Street extraction is slow and the output rarely changes
        if STREETS_PIECES_CSV.exists() and not self.rebuild_streets:
            log.info("%s already exists, skipping (use --rebuild-streets)", STREETS_PIECES_CSV.name)
            return True
        return self.streets.run()

    def run(self):
        stages = [
            ("sensors", self.sensors.run),
            ("streets", self.run_streets),
            ("street-sensor mapping", self.mapper.run),
            ("pm25 values", self.values.run),
        ]

        failed = []
        for name, stage in stages:
            log.info("--- %s ---", name)
            try:
                ok = stage()
            except Exception:
                log.exception("Stage '%s' crashed", name)
                ok = False
            if not ok:
                failed.append(name)

        if failed:
            log.warning("Finished with problems in: %s", ", ".join(failed))
            return 1
        log.info("All stages finished")
        return 0


def parse_args():
    ap = argparse.ArgumentParser(description="Collect Skopje street and pm25 data into the data folder")
    ap.add_argument("--pbf", default=str(PBF_PATH))
    ap.add_argument("--angle", type=float, default=20.0,
                    help="max turn (degrees) inside one piece, default 20")
    ap.add_argument("--max-len", type=float, default=300.0,
                    help="max piece length in meters, default 300")
    ap.add_argument("--per-segment", action="store_true",
                    help="every pair of neighbouring nodes = one row (finest)")
    ap.add_argument("--rebuild-streets", action="store_true",
                    help="re-cut the streets even if the CSV already exists")
    return ap.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    return Pipeline(parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())