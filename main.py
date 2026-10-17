import tkinter as tk
import tkintermapview
from pathlib import Path
import algorithm.Graph as graph
import math
import pandas as pd
import threading


class mainApp:
    def __init__(self):
        # 1. Window
        self.root = tk.Tk()
        self.root.geometry("900x700")
        self.root.title("Gradot Dishe")

        # 2. State
        self.marker_a = None
        self.marker_b = None
        self.start_coords = None
        self.end_coords = None
        self.paths = []                 # route lines currently on the map
        self.graph = None               # filled by the background loader

        # Pollution (debug) state
        self.pollution_layers = []
        self.pollution_visible = True

        # 3. UI
        self.appDesign()

        # 4. Load heavy data in the background so the window doesn't freeze
        self.status_label.config(text="Loading map data and sensors... Please wait.")
        threading.Thread(target=self.load_data_background, daemon=True).start()

    # ---------------------------------------------------------------- UI
    def appDesign(self):
        self.top_panel = tk.Frame(self.root, bg="#f8f9fa", pady=10, padx=15)
        self.top_panel.pack(fill="x", side="top")

        self.status_label = tk.Label(
            self.top_panel,
            text="Initializing...",
            font=("Arial", 11, "bold"),
            bg="#f8f9fa",
            fg="#3B6186"
        )
        self.status_label.pack(side="left")

        self.debug_button = tk.Button(
            self.top_panel,
            text="Hide pollution (Debug)",
            command=self.togglePollution,
            bg="#6c757d",
            fg="black",
            activebackground="#5a6268",
            activeforeground="white",
            font=("Arial", 10, "bold"),
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=6
        )
        self.debug_button.pack(side="right", padx=10)

        self.reset_button = tk.Button(
            self.top_panel,
            text="Reset Map",
            command=self.resetMap,
            bg="#dc3545",
            fg="Black",
            activebackground="#bb2d3b",
            activeforeground="white",
            font=("Arial", 12, "bold"),
            relief="flat",
            bd=0,
            highlightthickness=0,
            highlightbackground="#f8f9fa",
            cursor="hand2",
            padx=12,
            pady=6
        )
        self.reset_button.pack(side="right")

        self.map_widget = tkintermapview.TkinterMapView(self.root, width=900, height=650, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)
        self.map_widget.set_position(41.9981, 21.4254)
        self.map_widget.set_zoom(14)
        self.map_widget.add_left_click_map_command(self.onMapClick)

    # ------------------------------------------------------ data loading
    def load_data_background(self):
        """Runs on a background thread so the UI doesn't freeze."""
        try:
            # Load the routing graph only once
            if self.graph is None:
                self.graph = graph.load_graph(Path(__file__).parent / "algorithm" / "streets_with_values.csv")

            # Read sensors for the pollution circles
            csv_path = Path(__file__).parent / "data" / "streets_with_values.csv"
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df = df.dropna(subset=["sensor_lat", "sensor_lon", "pm25"])
            sensors = df.drop_duplicates(subset=["sensor_id"]).sort_values(by="pm25", ascending=True)

            sensor_data = []
            for _, s in sensors.iterrows():
                sensor_data.append((s["sensor_lat"], s["sensor_lon"], s["pm25"], s["sensor_name"]))

            # Drawing must happen on the main thread
            self.root.after(0, lambda: self.drawPollutionBySensor(sensor_data))

        except Exception as e:
            self.root.after(0, lambda: self.status_label.config(text=f"Loading error: {e}"))

    def drawPollutionBySensor(self, sensor_data):
        def pm25_to_color(v):
            if v < 5:    return "#2ecc71"
            if v < 10:   return "#a3e635"
            if v < 15:   return "#facc15"
            if v < 25:   return "#f97316"
            return "#dc2626"

        RADIUS_METERS = 100

        for lat, lon, pm25, name in sensor_data:
            color = pm25_to_color(pm25)
            delta_lat = RADIUS_METERS / 111320.0
            delta_lon = RADIUS_METERS / (111320.0 * math.cos(math.radians(lat)))

            circle_coords = []
            for i in range(36):
                angle = math.radians(i * 10)
                circle_coords.append((
                    lat + (delta_lat * math.cos(angle)),
                    lon + (delta_lon * math.sin(angle)),
                ))

            poly = self.map_widget.set_polygon(
                circle_coords,
                fill_color="",
                outline_color=color,
                border_width=4,
            )
            self.pollution_layers.append(poly)

            marker = self.map_widget.set_marker(
                lat, lon,
                text=f'{name}\nPM2.5: {pm25}',
                marker_color_circle=color,
                marker_color_outside=color,
            )
            self.pollution_layers.append(marker)

        self.status_label.config(text=f"Available sensors {len(sensor_data)}. Click to start.")

    def togglePollution(self):
        if self.pollution_visible:
            for layer in self.pollution_layers:
                self.map_widget.delete(layer)
            self.pollution_layers.clear()
            self.pollution_visible = False
            self.debug_button.config(text="Show pollution (Debug)")
        else:
            self.status_label.config(text="Re-rendering sensors...")
            self.pollution_visible = True
            self.debug_button.config(text="Hide pollution (Debug)")
            threading.Thread(target=self.load_data_background, daemon=True).start()

    # ------------------------------------------------------------ routing
    def onMapClick(self, coords):
        lat, lon = coords

        if self.graph is None:
            self.status_label.config(text="Data is still loading, please wait...")
            return

        if self.start_coords is None:
            self.start_coords = (lat, lon)
            self.marker_a = self.map_widget.set_marker(lat, lon, text="Point A")
            self.status_label.config(text="Click on the map to set Point B (Destination)")

        elif self.end_coords is None:
            self.end_coords = (lat, lon)
            self.marker_b = self.map_widget.set_marker(lat, lon, text="Point B")
            self.status_label.config(text="Calculating routes...")

            threading.Thread(
                target=self.calculate_route_background,
                args=(self.start_coords, self.end_coords),
                daemon=True
            ).start()

    def calculate_route_background(self, start, end):
        """Runs the algorithm off the UI thread, then hands the result back."""
        try:
            result = graph.find_routes(self.graph, start, end)
        except Exception as e:
            self.root.after(0, lambda: self.status_label.config(text=f"Routing error: {e}"))
            return

        self.root.after(0, lambda: self.showResult(result))

    def showResult(self, result):
        """Runs on the main thread: draws the routes and updates the label."""
        if not result:
            self.status_label.config(text="No path found between these points")
            return

        self.drawPaths(result)
        s, c = result["shortest"], result["clean"]
        if c is None:
            text = f"No cleaner route found, showing shortest ({s['length']:.0f} m)"
        else:
            text = (f"Red shortest: {s['length']:.0f} m | "
                    f"Green best air: {c['length']:.0f} m")
        self.status_label.config(text=text)

    def drawPaths(self, result):
        self.clearPaths()
        self.paths.append(self.map_widget.set_path(result["shortest"]["path"], color="#eb411f", width=5))
        if result["clean"]:
            self.paths.append(self.map_widget.set_path(result["clean"]["path"], color="#2ea44f", width=5))

    def clearPaths(self):
        for p in self.paths:
            self.map_widget.delete(p)
        self.paths = []

    def resetMap(self):
        if self.marker_a:
            self.marker_a.delete()
            self.marker_a = None
        if self.marker_b:
            self.marker_b.delete()
            self.marker_b = None
        self.clearPaths()

        self.start_coords = None
        self.end_coords = None
        self.status_label.config(text="Click on the map to set Point A (Start)")

    def main(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = mainApp()
    app.main()