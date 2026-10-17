import tkinter as tk
import tkintermapview
from pathlib import Path
import algorithm.Graph as graph
import math
import pandas as pd
import threading

class mainApp:
    def __init__(self):
        # 1. Initialization for the windows app
        self.root = tk.Tk()
        self.root.geometry("900x700")
        self.root.title("Gradot Dishe")
<<<<<<< HEAD
        self.paths = []
=======
>>>>>>> cc44704c53af2d7887d70590ee171a64e526e096

        # 2. State Management
        self.marker_a = None
        self.marker_b = None
        self.start_coords = None
        self.end_coords = None
        self.current_path = None
<<<<<<< HEAD

        # 3. Build UI Design (ПОВИКУВАЊЕ НА ДИЗАЈНОТ)
        self.graph = graph.load_graph(Path(__file__).parent / "algorithm" / "streets_with_values.csv")
        self.appDesign()

    def drawPaths(self, result):
        self.clearPaths()
        self.paths.append(self.map_widget.set_path(result["shortest"]["path"], color="#eb411f", width=5))
        if result["clean"]:
            self.paths.append(self.map_widget.set_path(result["clean"]["path"], color="#2ea44f", width=5))

    def appDesign(self):
        # Top Control Panel (UI Status & Controls)
        self.top_panel = tk.Frame(self.root, bg="#f8f9fa", pady=10, padx=15)
        self.top_panel.pack(fill="x", side="top")

        self.status_label = tk.Label(
            self.top_panel,
            text="Click on the map to set Point A (Start)",
            font=("Arial", 11, "bold"),
            bg="#f6fafe",
            fg="#3B6186"
        )
        self.status_label.pack(side="left")

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
            highlightbackground="#f8f9fa",  # Matches top_panel background
            cursor="hand2",  # Hand pointer on hover
            padx=12,
            pady=6
        )
        self.reset_button.pack(side="right")

        # Interactive Map Widget
        self.map_widget = tkintermapview.TkinterMapView(self.root, width=900, height=650, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)

        # Center map on Skopje
        self.map_widget.set_position(41.9981, 21.4254)
        self.map_widget.set_zoom(14)

        # Bind Map Click Event
        self.map_widget.add_left_click_map_command(self.onMapClick)

    def onMapClick(self, coords):
        """ndles user click events to select points (A, B) """
        lat, lon = coords

        # Select Point A
        if self.start_coords is None:
            self.start_coords = (lat, lon)
            self.marker_a = self.map_widget.set_marker(lat, lon, text="Point A")
            self.status_label.config(text="Click on the map to set Point B (Destination)")

        # Select Point B
        elif self.end_coords is None:
            self.end_coords = (lat, lon)
            self.marker_b = self.map_widget.set_marker(lat, lon, text="Point B")
            self.status_label.config(text="Calculating routes...")
            self.root.update_idletasks()

            result = graph.find_routes(self.graph, self.start_coords, self.end_coords)

            if result:
                self.drawPaths(result)
                s, c = result["shortest"], result["clean"]
                if c is None:
                    text = f"No cleaner route found, showing shortest ({s['length']:.0f} m)"
                else:
                    text = (f"Blue shortest: {s['length']:.0f} m | "
                            f"Green best air: {c['length']:.0f} m")
                self.status_label.config(text=text)
            else:
                self.status_label.config(text="No path found between these points")

    def clearPaths(self):
        for p in self.paths:
            self.map_widget.delete(p)
        self.paths = []

    def resetMap(self):
        """ Clears all active markers, polylines, and resets click states """
        if self.marker_a:
            self.marker_a.delete()
            self.marker_a = None
        if self.marker_b:
            self.marker_b.delete()
            self.marker_b = None
        if self.current_path:
            self.map_widget.delete(self.current_path)
            self.current_path = None
            # self.clearPaths()

        self.start_coords = None
        self.end_coords = None
        self.status_label.config(text="Click on the map to set Point A (Start)")

=======
        self.graph = None

        # Pollution State
        self.pollution_layers = []
        self.pollution_visible = True

        # 3. Build UI Design
        self.appDesign()

        # 4. Start Background Thread for Data Loading
        # This prevents the UI from freezing while loading graph/CSV
        self.status_label.config(text="Loading map data and sensors... Please wait.")
        threading.Thread(target=self.load_data_background, daemon=True).start()

    def appDesign(self):
        # Top Control Panel
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

        # Debug ON/OFF Button
        self.debug_button = tk.Button(
            self.top_panel,
            text="Hide debug",
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

        # Reset Button
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

        # Interactive Map Widget
        self.map_widget = tkintermapview.TkinterMapView(self.root, width=900, height=650, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)

        self.map_widget.set_position(41.9981, 21.4254)
        self.map_widget.set_zoom(14)
        self.map_widget.add_left_click_map_command(self.onMapClick)

    def load_data_background(self):
        """ Runs on a background thread to load heavy files without freezing UI """
        try:
            # 1. Load Graph
            self.graph = graph.load_graph(Path(__file__).parent / "algorithm" / "streets_with_values.csv")
            
            # 2. Process Pandas CSV for pollution
            csv_path = Path(__file__).parent / "data" / "streets_with_values.csv"
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            df = df.dropna(subset=["sensor_lat", "sensor_lon", "pm25"])
            sensors = df.drop_duplicates(subset=["sensor_id"]).sort_values(by="pm25", ascending=True)

            # Extract data into a plain list to safely pass back to UI thread
            sensor_data = []
            for _, s in sensors.iterrows():
                sensor_data.append((s["sensor_lat"], s["sensor_lon"], s["pm25"], s["sensor_name"]))

            # Schedule the UI drawing on the main thread safely
            self.root.after(0, lambda: self.drawPollutionBySensor(sensor_data))

        except Exception as e:
            self.root.after(0, lambda: self.status_label.config(text=f"Грешка при вчитување: {e}"))

    def drawPollutionBySensor(self, sensor_data):
        """ Draws colored radiuses safely on the main UI thread """
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

            # Draw polygon (Hollow Circle)
            poly = self.map_widget.set_polygon(
                circle_coords,
                fill_color="",         # Empty string makes the inside completely transparent
                outline_color=color,   # Keeps the colored ring
                border_width=4,        # Made slightly thicker so it stands out visually
            )
            self.pollution_layers.append(poly)

            # Draw Marker
            marker = self.map_widget.set_marker(
                lat, lon,
                text=f'{name}\nPM2.5: {pm25}',
                marker_color_circle=color,
                marker_color_outside=color,
            )
            self.pollution_layers.append(marker)

        self.status_label.config(text=f"Available sensors {len(sensor_data)}. Click to start.")

    def togglePollution(self):
        """Вклучува или исклучува приказ на загадувањето (Debug режим)."""
        if self.pollution_visible:
            for layer in self.pollution_layers:
                self.map_widget.delete(layer)
            self.pollution_visible = False
            self.debug_button.config(text="Show pollution (Debug)")
        else:
            self.pollution_layers.clear()
            self.status_label.config(text="Re-rendering sensors...")
            # Re-trigger background load to keep things simple and safe
            threading.Thread(target=self.load_data_background, daemon=True).start()
            self.pollution_visible = True
            self.debug_button.config(text="Hide pollution (Debug)")

    def onMapClick(self, coords):
        """ Handles user click events to select points (A, B) """
        lat, lon = coords

        if self.start_coords is None:
            self.start_coords = (lat, lon)
            self.marker_a = self.map_widget.set_marker(lat, lon, text="Point A")
            self.status_label.config(text="Click on the map to set Point B (Destination)")

        elif self.end_coords is None:
            self.end_coords = (lat, lon)
            self.marker_b = self.map_widget.set_marker(lat, lon, text="Point B")
            self.status_label.config(text="Calculating cleanest path...")

            # Fire the algorithm calculation to the background thread
            threading.Thread(target=self.calculate_route_background, args=(self.start_coords, self.end_coords), daemon=True).start()

    def calculate_route_background(self, start, end):
        """ Runs the algorithm without freezing the UI, then tells the UI to draw """
        if not self.graph:
            self.root.after(0, lambda: self.status_label.config(text="Graph not ready yet!"))
            return

        route_coordinates = graph.find_route(self.graph, start, end, alpha=3)

        if route_coordinates:
            # Use root.after to safely pass the result back to the main UI thread
            self.root.after(0, lambda: self.drawPath(route_coordinates))
            self.root.after(0, lambda: self.status_label.config(text="Path displayed successfully"))
        else:
            self.root.after(0, lambda: self.status_label.config(text="No path found between these points"))

    def drawPath(self, route_cords):
        if self.current_path:
            self.map_widget.delete(self.current_path)

        self.current_path = self.map_widget.set_path(route_cords, color="#2ea44f", width=5)

    def resetMap(self):
        if self.marker_a:
            self.marker_a.delete()
            self.marker_a = None
        if self.marker_b:
            self.marker_b.delete()
            self.marker_b = None
        if self.current_path:
            self.map_widget.delete(self.current_path)
            self.current_path = None

        self.start_coords = None
        self.end_coords = None
        self.status_label.config(text="Click on the map to set Point A (Start)")

>>>>>>> cc44704c53af2d7887d70590ee171a64e526e096
    def main(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = mainApp()
    app.main()