import tkinter as tk
import tkintermapview
from pathlib import Path
import algorithm.Graph as graph

class mainApp:
   def __init__(self):
    # 1. Initialization for the windows app
    self.root = tk.Tk()
    self.root.geometry("900x700")
    self.root.title("Gradot Dishe")

    # 2. State Management
    self.marker_a = None
    self.marker_b = None
    self.start_coords = None
    self.end_coords = None
    self.current_path = None

    # 3. Build UI Design (ПОВИКУВАЊЕ НА ДИЗАЈНОТ)
    self.appDesign()
    self.graph = graph.load_graph(Path(__file__).parent / "algorithm" / "streets_with_values.csv")

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
      """ Handles user click events to select points (A, B) """
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
        self.status_label.config(text="Calculating cleanest path...")
        self.root.update_idletasks()

        route_coordinates = graph.find_route(
            self.graph, self.start_coords, self.end_coords, alpha=3
        )

        if route_coordinates:
            self.drawPath(route_coordinates)
            self.status_label.config(text="Path displayed successfully")
        else:
            self.status_label.config(text="No path found between these points")

   def drawPath(self, route_cords):
      """ Draws the returned path list on the map """
      if self.current_path:
         self.map_widget.delete(self.current_path)

      self.current_path = self.map_widget.set_path(route_cords, color="#2ea44f", width=5)

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

      self.start_coords = None
      self.end_coords = None
      self.status_label.config(text="Click on the map to set Point A (Start)")

   def main(self):
      self.root.mainloop()


if __name__ == "__main__":
    app = mainApp()
    app.main()