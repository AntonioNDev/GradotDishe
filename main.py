# GLOBAL APP FILE
import tkinter as tk
import tkintermapview

class mainApp:
   def __init__(self):
      # Initialization for the windows app
      self.root = tk.Tk()
      self.root.geometry("900x700")
      self.root.title("Gradot Dishe")

       # 4. State Management
      self.marker_a = None
      self.marker_b = None
      self.start_coords = None
      self.end_coords = None
      self.current_path = list()

   def appDesign(self):
      # 2. Top Control Panel (UI Status & Controls)
      self.top_panel = tk.Frame(self.root, bg="#f8f9fa", pady=10, px=15)
      self.top_panel.pack(fill="x", side="top")

      self.status_label = tk.Label(
         self.top_panel, 
         text="Click on the map to set Point A (Start)", 
         font=("Arial", 11, "bold"), 
         bg="#f8f9fa",
         fg="#212529"
      )
      self.status_label.pack(side="left")

      self.reset_button = tk.Button(
         self.top_panel, 
         text="Reset Map", 
         command=self.resetMap, 
         bg="#dc3545", 
         fg="white", 
         font=("Arial", 9, "bold"),
         relief="flat",
         padx=10,
         pady=3
      )
      self.reset_button.pack(side="right")

      # 3. Interactive Map Widget
      self.map_widget = tkintermapview.TkinterMapView(self.root, width=900, height=650, corner_radius=0)
      self.map_widget.pack(fill="both", expand=True)

      # Center map on Skopje
      self.map_widget.set_position(41.9981, 21.4254)
      self.map_widget.set_zoom(14)

      # 5. Bind Map Click Event
      self.map_widget.add_left_click_map_command(self.onMapClick)

   def drawPath(route_cords, map_widget):
      """ Drawing of the shortest and cleanest path 
      
          route_cords: list of cordinates from A to B location
          map_widget: tkintermapview for the interactive map
      """

      path = map_widget.set_path(route_cords, color="#2ea44f", width=5)

   def onMapClick(self, coords):
      """ Handles user clicks events to select points (A, B) """
      lat, lon = coords

      # Select Point A
      if self.start_coords is None:
         self.start_coords = (lat, lon)
         self.marker_a = self.map_widget.set_marker(lat, lon, text="Point A")
         self.status_label.config(text="Click on the map to set Point B (Destination)")

      elif self.end_coords is None:
         self.end_coords = (lat, lon)
         self.marker_b = self.map_widget.set_marker(lat, lon, text="Point B")
         self.status_label.config(text="Calculating cleanest path...")

         # BELOW GOES THE DJIKSTAR FUNCTION
         route_coordinates = None # CALL LATER 

         if route_coordinates:
            self.drawPath(route_coordinates)
            self.status_label.config(text="Path displayed successfully")

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
   app.main() # STARTS THE APP