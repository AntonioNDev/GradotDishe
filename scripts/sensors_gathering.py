import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta, timezone
import csv


USERNAME = "PLACEHOLDER"
PASSWORD = "PLACEHOLDER*"
BASE_URL = "https://skopje.pulse.eco/rest"
OUTPUT_CSV = "pm25_sensors.csv"

auth = HTTPBasicAuth(USERNAME, PASSWORD)


def main():
    resp = requests.get(f"{BASE_URL}/sensor", auth=auth, timeout=30)
    resp.raise_for_status()
    sensors = resp.json()
    print(f"Vkupno senzori: {len(sensors)}")

    active = [s for s in sensors if s.get("status", "").upper().startswith("ACTIVE")]
    print(f"Aktivni senzori: {len(active)}")
    tz_skopje = timezone(timedelta(hours=2))

    now = datetime.now(tz_skopje)
    from_dt_str = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S") + "%2b02:00"
    to_dt_str = now.strftime("%Y-%m-%dT%H:%M:%S") + "%2b02:00"

    url = f"{BASE_URL}/dataRaw?type=pm25&from={from_dt_str}&to={to_dt_str}"

    data = requests.get(url, auth=auth, timeout=30)
    data.raise_for_status()
    measurements = data.json()

    pm25_sensor_ids = {m["sensorId"] for m in measurements}
    print(f"Senzori so PM2.5 merenja vo poslednite 15 min: {len(pm25_sensor_ids)}")

    pm25_sensors = []
    for s in active:
        if s["sensorId"] not in pm25_sensor_ids:
            continue
        pos = s.get("position", "").strip()
        if not pos:
            continue
        try:
            lat_str, lon_str = pos.split(",")
            lat, lon = float(lat_str), float(lon_str)
        except ValueError:
            print(f"Nepravilen position: {s['sensorId']} -> {pos}")
            continue

        pm25_sensors.append({
            "sensor_id": s["sensorId"],
            "lat": lat,
            "lon": lon,
            "description": s.get("description", ""),
        })

    print(f"Aktivni PM2.5 senzori: {len(pm25_sensors)}")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sensor_id", "lat", "lon", "description"])
        writer.writeheader()
        writer.writerows(pm25_sensors)

    print(f"Zachuvano vo {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
