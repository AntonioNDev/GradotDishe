import csv
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from requests.auth import HTTPBasicAuth

USERNAME = "alek123"
PASSWORD = "novaNOVA"
BASE_URL = "https://skopje.pulse.eco/rest"
OUTPUT_CSV = "pm25_sensors.csv"
STREETS_WITH_SENSORS_CSV = "../data/streets_with_sensors.csv"
STREETS_WITH_VALUES_CSV = "../data/streets_with_values.csv"
CACHE_TTL_SECONDS = 30 * 60   # 30 мин

auth = HTTPBasicAuth(USERNAME, PASSWORD)


# ---------- 1. Помошни функции ----------
def is_cache_fresh(path, ttl_seconds):
    """Враќа True ако фајлот постои и е помлад од ttl_seconds."""
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    return age < ttl_seconds


def load_streets_with_sensors(path):
    """Ги чита сите редови од streets_with_sensors.csv."""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


# ---------- 2. Преземање на свежи PM2.5 вредности по сензор ----------
def fetch_pm25_by_sensor():
    """
    Враќа dict: sensor_id -> просечна pm25 вредност во последните 15 мин.
    """
    resp = requests.get(f"{BASE_URL}/sensor", auth=auth, timeout=30)
    resp.raise_for_status()
    sensors = resp.json()
    active = [s for s in sensors if s.get("status", "").upper().startswith("ACTIVE")]

    tz_skopje = timezone(timedelta(hours=2))
    now = datetime.now(tz_skopje)
    from_dt_str = (now - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S") + "%2b02:00"
    to_dt_str = now.strftime("%Y-%m-%dT%H:%M:%S") + "%2b02:00"

    url = f"{BASE_URL}/dataRaw?type=pm25&from={from_dt_str}&to={to_dt_str}"
    data = requests.get(url, auth=auth, timeout=30)
    data.raise_for_status()
    measurements = data.json()

    sums = {}
    counts = {}
    for m in measurements:
        sid = m.get("sensorId")
        val = m.get("value")
        if sid is None or val is None:
            continue
        try:
            val = float(val)
        except (ValueError, TypeError):
            continue
        sums[sid] = sums.get(sid, 0.0) + val
        counts[sid] = counts.get(sid, 0) + 1

    return {
        sid: sums[sid] / counts[sid]
        for sid in sums
        if counts[sid] > 0
    }


# ---------- 3. Fillna со глобален просек ----------
def fill_with_global_mean(rows):
    """
    Ги пополнува празните 'pm25' вредности со просекот на сите
    валидни pm25 вредности во rows (in-place).
    """
    vals = []
    for r in rows:
        v = r.get("pm25", "")
        if v in ("", None):
            continue
        try:
            vals.append(float(v))
        except (ValueError, TypeError):
            continue

    if not vals:
        print("Nema validni PM2.5 vrednosti za presmetka na prosek.")
        return rows

    mean = sum(vals) / len(vals)
    print(f"Globalen prosek PM2.5: {mean:.1f} µg/m³ (od {len(vals)} ulici)")

    filled = 0
    for r in rows:
        if r.get("pm25", "") in ("", None):
            r["pm25"] = f"{mean:.1f}"
            filled += 1

    print(f"Popolnati {filled} ulici so globalen prosek.")
    return rows


# ---------- 4. Генерирање на streets_with_values.csv ----------
def build_streets_with_values():
    """Пресметува нов streets_with_values.csv од streets_with_sensors.csv + свежи PM2.5."""
    streets = load_streets_with_sensors(STREETS_WITH_SENSORS_CSV)
    print(f"Ulici vo {STREETS_WITH_SENSORS_CSV}: {len(streets)}")

    pm25_by_sensor = fetch_pm25_by_sensor()
    print(f"Senzori so PM2.5: {len(pm25_by_sensor)}")

    now_iso = datetime.now(timezone(timedelta(hours=2))).isoformat(timespec="seconds")

    # 1. припиши вредности по sensor_id
    matched = 0
    for st in streets:
        sid = st.get("sensor_id", "")
        val = pm25_by_sensor.get(sid)
        if val is not None:
            st["pm25"] = f"{val:.1f}"
            matched += 1
        else:
            st["pm25"] = ""          # ќе се пополни подолу
        st["pm25_timestamp"] = now_iso
    print(f"Ulici so direktna PM2.5 vrednost: {matched}/{len(streets)}")

    # 2. fillna so globalen prosek
    streets = fill_with_global_mean(streets)

    # 3. запиши (атомарно преку .tmp)
    fieldnames = list(dict.fromkeys(list(streets[0].keys()) + ["pm25", "pm25_timestamp"]))
    tmp_path = STREETS_WITH_VALUES_CSV + ".tmp"

    with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(streets)

    os.replace(tmp_path, STREETS_WITH_VALUES_CSV)
    print(f"Zachuvano: {STREETS_WITH_VALUES_CSV}")


# ---------- 5. Главна логика ----------
def main():
    if is_cache_fresh(STREETS_WITH_VALUES_CSV, CACHE_TTL_SECONDS):
        age_min = (time.time() - os.path.getmtime(STREETS_WITH_VALUES_CSV)) / 60
        print(f"Kesh e svezh ({age_min:.1f} min) -> ne se prebrisuva.")
        print(f"Koristi: {STREETS_WITH_VALUES_CSV}")
        return

    print("Kesh e postar od 30 min ili ne postoi -> se presmetuva novo.")
    build_streets_with_values()


if __name__ == "__main__":
    main()