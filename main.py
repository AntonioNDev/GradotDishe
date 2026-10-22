import csv
import importlib
import logging
import math
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from argparse import Namespace
from collections import namedtuple
from pathlib import Path

import tkintermapview
from PIL import Image, ImageDraw, ImageTk

from algorithm.Graph import Graph, Router

log = logging.getLogger("app")

ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
VALUES_CSV = ROOT / "data" / "streets_with_values.csv"

START_POS = (41.9981, 21.4254)
START_ZOOM = 14
RING_RADIUS_M = 50
REFRESH_EVERY_MS = 30 * 60 * 1000
SPEEDS = {"Walk": 80, "Bike": 250}  # meters per minute

# upper limit, color, label, legend text
PM25_LEVELS = [
    (5, "#2ecc71", "Very good", "<5"),
    (10, "#a3e635", "Good", "5-10"),
    (15, "#facc15", "Moderate", "10-15"),
    (25, "#f97316", "Poor", "15-25"),
    (math.inf, "#dc2626", "Very poor", "25+"),
]
ROUTE_COLORS = {"shortest": "#eb411f", "clean": "#2ea44f"}
PIN_START = "#2563eb"
PIN_END = "#7c3aed"

UI = {
    "bg": "#ffffff",
    "panel": "#f8fafc",
    "border": "#e5e7eb",
    "text": "#111827",
    "muted": "#6b7280",
}
# normal color, hover color, text color
BUTTON_STYLES = {
    "neutral": ("#eef0f3", "#e1e4e8", "#111827"),
    "accent": ("#2563eb", "#1d4ed8", "#ffffff"),
    "danger": ("#ef4444", "#dc2626", "#ffffff"),
}

Sensor = namedtuple("Sensor", "name lat lon pm25")


# HELPER FUNCTIONS
def pm25_level(value):
    for limit, color, label, _ in PM25_LEVELS:
        if value < limit:
            return color, label

def fmt_dist(meters):
    if meters < 1000:
        return f"{meters:.0f} m"
    return f"{meters / 1000:.2f} km"


def fmt_time(minutes):
    minutes = round(minutes)
    if minutes < 1:
        return "<1 min"
    hours, rest = divmod(minutes, 60)
    if hours:
        return f"{hours} h {rest:02d} min"
    return f"{minutes} min"


def ring_points(lat, lon, steps=40):
    """Points of a circle with RING_RADIUS_M around a sensor."""
    dlat = RING_RADIUS_M / 110540.0
    dlon = RING_RADIUS_M / (111320.0 * math.cos(math.radians(lat)))
    points = []
    for i in range(steps + 1):
        angle = 2 * math.pi * i / steps
        points.append((lat + dlat * math.sin(angle), lon + dlon * math.cos(angle)))
    return points


def pick_font_family(root):
    available = set(tkfont.families(root))
    for name in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu", "DejaVu Sans", "Arial"):
        if name in available:
            return name
    return "Helvetica"


def enable_hidpi():
    """Sharper text on high-DPI Windows screens. Has to run before Tk()."""
    if sys.platform != "win32":
        return

def load_sensors(path):
    """Unique sensors from streets_with_values.csv, plus the data timestamp."""
    sensors = {}
    stamp = "unknown time"
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sensor_id = row.get("sensor_id")
            if not sensor_id or sensor_id in sensors:
                continue
            try:
                lat = float(row["sensor_lat"])
                lon = float(row["sensor_lon"])
                pm25 = float(row["pm25"])
            except (KeyError, ValueError):
                continue
            if row.get("pm25_timestamp"):
                stamp = row["pm25_timestamp"][:16].replace("T", " ")
            sensors[sensor_id] = Sensor(row.get("sensor_name") or "Sensor", lat, lon, pm25)

    # dirtiest last, so they end up on top
    return sorted(sensors.values(), key=lambda s: s.pm25), stamp


def refresh_data(force=False):
    """Runs collect_data when possible. Returns a short note for the status bar."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))

    try:
        collect = importlib.import_module("collect_data")
    except Exception as e:
        return f"Using saved data (collector unavailable: {e})"

    if "PLACEHOLDER" in (collect.USERNAME, collect.PASSWORD):
        return "Using saved data (no API credentials set)"

    try:
        age = time.time() - VALUES_CSV.stat().st_mtime
    except FileNotFoundError:
        age = math.inf
    if not force and age < collect.CACHE_TTL_SECONDS:
        return "Air data is up to date"

    try:
        args = Namespace(pbf=str(collect.PBF_PATH), angle=20.0, max_len=300.0,
                         per_segment=False, rebuild_streets=False)
        pipeline = collect.Pipeline(args)
        if force:
            pipeline.values.cache_ttl_seconds = 0
        success = pipeline.run() == 0
    except Exception:
        log.exception("Refresh crashed")
        return "Refresh failed, using saved data"

    if success:
        return "Air data refreshed"
    return "Refresh had problems, using last saved data"


# WIDGETS
_pin_cache = {}

def make_pin_icon(color, size=(22, 30)):
    """Map pin drawn with PIL, so it looks the same on every OS."""
    key = (color, size)
    if key in _pin_cache:
        return _pin_cache[key]

    scale = 4  # draw big and shrink afterwards for smooth edges
    w, h = size[0] * scale, size[1] * scale
    center = w / 2
    radius = center - 2 * scale

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # white outline first, then the colored body on top
    for rad, tip, fill in ((radius + scale, h - 1, "white"), (radius, h - 1 - 2 * scale, color)):
        draw.polygon([(center - rad * 0.87, center + rad * 0.5),
                      (center + rad * 0.87, center + rad * 0.5),
                      (center, tip)], fill=fill)
        draw.ellipse((center - rad, center - rad, center + rad, center + rad), fill=fill)

    hole = radius * 0.4
    draw.ellipse((center - hole, center - hole, center + hole, center + hole), fill="white")

    icon = ImageTk.PhotoImage(img.resize(size, Image.LANCZOS))
    _pin_cache[key] = icon
    return icon


class RoundButton(tk.Canvas):
    """Flat rounded button. Native tk buttons ignore colors on macOS, this one doesn't."""
    HEIGHT = 34

    def __init__(self, parent, text, command, font, style="neutral", width=None):
        label_font = tkfont.Font(root=parent, font=font)
        button_width = width or label_font.measure(text) + 32
        super().__init__(parent, width=button_width, height=self.HEIGHT, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0, cursor="hand2")

        self.button_width = button_width
        self.label_font = label_font
        self.text = text
        self.style = style
        self.on_click = command
        self.hovered = False

        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        self.bind("<Button-1>", self.on_press)
        self.draw()

    def restyle(self, text=None, style=None):
        if text:
            self.text = text
        if style:
            self.style = style
        self.draw()

    def on_enter(self, event):
        self.hovered = True
        self.draw()

    def on_leave(self, event):
        self.hovered = False
        self.draw()

    def on_press(self, event):
        self.on_click()

    def draw(self):
        normal, hover, text_color = BUTTON_STYLES[self.style]
        fill = hover if self.hovered else normal

        x1, y1 = 1, 1
        x2, y2 = self.button_width - 1, self.HEIGHT - 1
        r = 10

        # smooth=True turns this polygon into a rounded rectangle
        points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
                  x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
                  x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]

        self.delete("all")
        self.create_polygon(points, smooth=True, fill=fill, outline=fill)
        self.create_text(self.button_width / 2, self.HEIGHT / 2, text=self.text,
                         fill=text_color, font=self.label_font)


def color_dot(parent, color, bg):
    """Small drawn circle. Used instead of emojis, which show up as black dots on Windows."""
    dot = tk.Canvas(parent, width=12, height=12, bg=bg, highlightthickness=0)
    dot.create_oval(1, 1, 11, 11, fill=color, outline=color)
    return dot


# Main App functions and design
class MainApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Gradot Dishe")
        self.root.geometry("1000x720")
        self.root.minsize(820, 560)
        self.root.configure(bg=UI["bg"])

        # Negative sizes are pixels, so text is the same size on every OS
        family = pick_font_family(self.root)
        self.fonts = {
            "title": (family, -20, "bold"),
            "body": (family, -13),
            "bold": (family, -13, "bold"),
            "small": (family, -12),
            "pin": (family, -12, "bold"),
        }

        self.router = None
        self.sensors = []
        self.sensor_layers = []
        self.sensors_visible = False

        self.start_coords = None
        self.end_coords = None
        self.marker_a = None
        self.marker_b = None
        self.paths = []
        self.last_result = None

        self.mode = "Walk"
        self.loading = False
        self.request_id = 0  # used to ignore results of outdated route requests
        self.resize_job = None
        self.ui_queue = queue.Queue()

        self.build_toolbar()
        self.build_statusbar()
        self.build_map()
        self.build_card()

        self.root.bind("<Configure>", self.on_resize)
        self.root.bind("<Escape>", lambda event: self.reset_map())
        self.root.bind("s", lambda event: self.toggle_sensors())

        self.root.after(50, self.pump)
        # Tiles sometimes stay blank until the map is moved, so nudge it after startup
        self.root.after(300, self.redraw_map)
        self.root.after(1200, self.redraw_map)
        self.start_loading()

    # LAYOUT
    def build_toolbar(self):
        top = tk.Frame(self.root, bg=UI["bg"])
        top.pack(fill="x", side="top")
        tk.Frame(self.root, bg=UI["border"], height=1).pack(fill="x", side="top")

        title = tk.Frame(top, bg=UI["bg"])
        title.pack(side="left", padx=16, pady=10)
        tk.Label(title, text="Gradot Dishe", font=self.fonts["title"],
                 bg=UI["bg"], fg=UI["text"]).pack(anchor="w")
        tk.Label(title, text="Find the cleanest way across Skopje", font=self.fonts["small"],
                 bg=UI["bg"], fg=UI["muted"]).pack(anchor="w")

        buttons = tk.Frame(top, bg=UI["bg"])
        buttons.pack(side="right", padx=12)
        bold = self.fonts["bold"]

        self.sensor_btn = RoundButton(buttons, "Show sensors", self.toggle_sensors, bold, width=130)
        self.mode_btn = RoundButton(buttons, "Mode: Walk", self.toggle_mode, bold, width=110)
        self.swap_btn = RoundButton(buttons, "Swap A/B", self.swap_points, bold)
        self.refresh_btn = RoundButton(buttons, "Refresh data",
                                       lambda: self.start_loading(force=True), bold)
        self.reset_btn = RoundButton(buttons, "Reset", self.reset_map, bold, style="danger")

        for button in (self.sensor_btn, self.mode_btn, self.swap_btn, self.refresh_btn, self.reset_btn):
            button.pack(side="left", padx=4)

    def build_statusbar(self):
        bottom = tk.Frame(self.root, bg=UI["panel"])
        bottom.pack(fill="x", side="bottom")
        tk.Frame(self.root, bg=UI["border"], height=1).pack(fill="x", side="bottom")

        self.status_label = tk.Label(bottom, text="Starting...", font=self.fonts["body"],
                                     bg=UI["panel"], fg=UI["text"], anchor="w")
        self.status_label.pack(side="left", padx=14, pady=8)

        legend = tk.Frame(bottom, bg=UI["panel"])
        legend.pack(side="right", padx=14)
        tk.Label(legend, text="PM2.5 µg/m³", font=self.fonts["small"],
                 bg=UI["panel"], fg=UI["muted"]).pack(side="left", padx=(0, 8))

        for _, color, _, text in PM25_LEVELS:
            color_dot(legend, color, UI["panel"]).pack(side="left")
            tk.Label(legend, text=text, font=self.fonts["small"],
                     bg=UI["panel"], fg=UI["text"]).pack(side="left", padx=(3, 10))

    def build_map(self):
        self.map_holder = tk.Frame(self.root, bg=UI["bg"])
        self.map_holder.pack(fill="both", expand=True)
        self.root.update_idletasks()  # the map needs the real widget size before it draws

        self.map_widget = tkintermapview.TkinterMapView(
            self.map_holder, width=1000, height=600, corner_radius=0
        )

        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22) # <- promena

        self.map_widget.pack(fill="both", expand=True)
        self.map_widget.set_position(*START_POS)
        self.map_widget.set_zoom(START_ZOOM)
        self.map_widget.add_left_click_map_command(self.on_map_click)

    def schedule_refresh(self):
        self.start_loading()
        self.root.after(REFRESH_EVERY_MS, self.schedule_refresh)

    def build_card(self):
        """Small route comparison card that floats over the map."""
        fonts = self.fonts
        self.card = tk.Frame(self.map_holder, bg=UI["bg"], padx=14, pady=10,
                             highlightbackground=UI["border"], highlightthickness=1)
        tk.Label(self.card, text="Route comparison", font=fonts["bold"], bg=UI["bg"],
                 fg=UI["text"]).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

        self.card_values = {}
        rows = (("shortest", "Shortest"), ("clean", "Cleanest"))
        for row, (key, name) in enumerate(rows, start=1):
            color_dot(self.card, ROUTE_COLORS[key], UI["bg"]).grid(row=row, column=0, padx=(0, 8), pady=3)
            tk.Label(self.card, text=name, font=fonts["body"], bg=UI["bg"],
                     fg=UI["text"]).grid(row=row, column=1, sticky="w")
            value = tk.Label(self.card, font=fonts["body"], bg=UI["bg"], fg=UI["text"])
            value.grid(row=row, column=2, sticky="e", padx=(18, 0))
            self.card_values[key] = value

        self.card_note = tk.Label(self.card, font=fonts["small"], bg=UI["bg"], fg=UI["muted"])
        self.card_note.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def set_status(self, text):
        self.status_label.config(text=text)

    # Background work
    def post(self, func, *args):
        """Worker threads never touch Tk directly, they queue work for the main thread."""
        self.ui_queue.put((func, args))

    def pump(self):
        while True:
            try:
                func, args = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                func(*args)
            except Exception:
                log.exception("UI callback failed")
        self.root.after(50, self.pump)

    def start_loading(self, force=False):
        if self.loading:
            self.set_status("Already loading, please wait...")
            return
        self.loading = True
        self.set_status("Refreshing air quality data...")
        threading.Thread(target=self.load_worker, args=(force,), daemon=True).start()

    def load_worker(self, force):
        note = refresh_data(force)
        self.post(self.set_status, "Building the street network...")
        try:
            graph = Graph.from_csv(VALUES_CSV)
            sensors, stamp = load_sensors(VALUES_CSV)
        except FileNotFoundError:
            self.post(self.on_data_error, f"Missing {VALUES_CSV.name} in the data folder")
            return
        except Exception as e:
            log.exception("Loading data failed")
            self.post(self.on_data_error, f"Could not load data: {e}")
            return
        self.post(self.on_data_ready, graph, sensors, stamp, note)

    def on_data_ready(self, graph, sensors, stamp, note):
        self.router = Router(graph)
        self.sensors = sensors
        self.loading = False

        if self.sensors_visible:
            self.clear_sensor_layers()
            self.draw_sensors()

        self.set_status(f"{note}. {len(sensors)} sensors, data from {stamp}. "
                        "Click the map to set the start point.")

        # A route is already on screen, so recalculate it with the new data
        if self.start_coords and self.end_coords:
            self.start_routing()

    def on_data_error(self, message):
        self.loading = False
        self.set_status(message)

    # map
    def redraw_map(self):
        lat, lon = self.map_widget.get_position()
        self.map_widget.set_position(lat, lon)

    def on_resize(self, event):
        if event.widget is not self.root:
            return
        if self.resize_job:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(150, self.redraw_map)

    # sensors
    def toggle_sensors(self):
        if self.sensors_visible:
            self.clear_sensor_layers()
            self.sensors_visible = False
            self.sensor_btn.restyle(text="Show sensors", style="neutral")
            return

        if not self.sensors:
            self.set_status("Sensors are still loading, please wait...")
            return

        self.draw_sensors()
        self.sensors_visible = True
        self.sensor_btn.restyle(text="Hide sensors", style="accent")
        self.set_status(f"Showing {len(self.sensors)} sensors. Click a pin for details.")

    def draw_sensors(self):
        for sensor in self.sensors:
            color, _ = pm25_level(sensor.pm25)
            ring = self.map_widget.set_path(ring_points(sensor.lat, sensor.lon), color=color, width=2)
            pin = self.map_widget.set_marker(
                sensor.lat, sensor.lon,
                text=f"{sensor.pm25:.0f}",
                text_color=UI["text"],
                font=self.fonts["pin"],
                icon=make_pin_icon(color),
                icon_anchor="s",
                command=self.on_sensor_click,
                data=sensor,
            )
            self.sensor_layers.extend([ring, pin])

    def clear_sensor_layers(self):
        for layer in self.sensor_layers:
            layer.delete()
        self.sensor_layers = []

    def on_sensor_click(self, marker):
        sensor = marker.data
        _, label = pm25_level(sensor.pm25)
        self.set_status(f"{sensor.name}: PM2.5 {sensor.pm25:.1f} µg/m³ ({label})")

    # points
    def on_map_click(self, coords):
        if self.router is None:
            self.set_status("Data is still loading, please wait...")
            return

        # A click after a finished route starts a new one
        if self.start_coords and self.end_coords:
            self.reset_map(announce=False)

        if self.start_coords is None:
            self.start_coords = tuple(coords)
            self.place_markers()
            self.set_status("Click the map to set the destination")
        else:
            self.end_coords = tuple(coords)
            self.place_markers()
            self.start_routing()

    def place_markers(self):
        for marker in (self.marker_a, self.marker_b):
            if marker:
                marker.delete()
        self.marker_a = self.make_marker(self.start_coords, "Start", PIN_START)
        self.marker_b = self.make_marker(self.end_coords, "End", PIN_END)

    def make_marker(self, coords, text, color):
        if coords is None:
            return None
        return self.map_widget.set_marker(*coords, text=text, text_color=UI["text"],
                                          font=self.fonts["pin"],
                                          icon=make_pin_icon(color, (28, 38)), icon_anchor="s")

    def swap_points(self):
        if not (self.start_coords and self.end_coords):
            self.set_status("Set both points first")
            return
        self.start_coords, self.end_coords = self.end_coords, self.start_coords
        self.place_markers()
        self.start_routing()

    # reouting
    def start_routing(self):
        self.request_id += 1
        self.set_status("Calculating routes...")
        threading.Thread(
            target=self.route_worker,
            args=(self.request_id, self.router, self.start_coords, self.end_coords),
            daemon=True,
        ).start()

    def route_worker(self, request_id, router, start, end):
        result = None
        error = None
        try:
            result = router.find_routes(start, end)
        except Exception as e:
            log.exception("Routing failed")
            error = str(e)
        self.post(self.on_route_done, request_id, result, error)

    def on_route_done(self, request_id, result, error):
        if request_id != self.request_id:
            return  # the user reset or moved a point in the meantime

        if error:
            self.set_status(f"Routing error: {error}")
            return
        if not result:
            self.set_status("No path found between these points")
            return

        self.last_result = result
        self.draw_paths(result)
        self.update_card()
        self.fit_route(result)

        if result["clean"]:
            self.set_status("Showing the shortest and the cleanest route")
        else:
            length = fmt_dist(result["shortest"]["length"])
            self.set_status(f"No cleaner route found, showing the shortest ({length})")

    def draw_paths(self, result):
        self.clear_paths()
        # Shortest is wider and drawn first, so both stay visible where they overlap
        self.paths.append(self.map_widget.set_path(
            result["shortest"]["path"], color=ROUTE_COLORS["shortest"], width=7))
        if result["clean"]:
            self.paths.append(self.map_widget.set_path(
                result["clean"]["path"], color=ROUTE_COLORS["clean"], width=4))

    def clear_paths(self):
        for path in self.paths:
            path.delete()
        self.paths = []

    def fit_route(self, result):
        points = []
        for route in result.values():
            if route:
                points.extend(route["path"])

        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        pad = 0.003
        try:
            self.map_widget.fit_bounding_box((max(lats) + pad, min(lons) - pad),
                                             (min(lats) - pad, max(lons) + pad))
        except Exception:
            log.exception("Could not fit the map to the route")

    # route card
    def describe(self, route):
        minutes = route["length"] / SPEEDS[self.mode]
        return f"{fmt_dist(route['length'])}  ·  {fmt_time(minutes)}"

    def update_card(self):
        if not self.last_result:
            self.card.place_forget()
            return

        shortest = self.last_result["shortest"]
        clean = self.last_result["clean"]
        self.card_values["shortest"].config(text=self.describe(shortest))

        if clean:
            self.card_values["clean"].config(text=self.describe(clean))
            less = 0
            if shortest["risk"] > 0:
                less = (shortest["risk"] - clean["risk"]) / shortest["risk"] * 100
            extra = fmt_dist(clean["length"] - shortest["length"])
            self.card_note.config(text=f"{less:.0f}% less pollution exposure for +{extra}")
        else:
            self.card_values["clean"].config(text="same as shortest")
            self.card_note.config(text="The shortest route is already the cleanest.")

        self.card.place(relx=0, rely=1, x=14, y=-14, anchor="sw")

    def toggle_mode(self):
        self.mode = "Bike" if self.mode == "Walk" else "Walk"
        self.mode_btn.restyle(text=f"Mode: {self.mode}")
        self.update_card()

    # reset
    def reset_map(self, announce=True):
        self.request_id += 1
        for marker in (self.marker_a, self.marker_b):
            if marker:
                marker.delete()
        self.marker_a = None
        self.marker_b = None

        self.clear_paths()
        self.start_coords = None
        self.end_coords = None
        self.last_result = None
        self.card.place_forget()

        if announce:
            self.set_status("Click the map to set the start point")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    enable_hidpi()
    MainApp().run()