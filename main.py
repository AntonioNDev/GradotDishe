# GLOBAL APP FILE
import tkinter as tk
import tkintermapview

class mainApp:
   def __init__(self):
      # Initialization for the windows app
      root = tk.Tk()
      size = (900, 700)
      root.title("Gradot Dishe")

      # Creation of the Widgit map
      map_widget = tkintermapview.TkinterMapView(root, size, corner_radius=0)
      map_widget.pack(fill="both", expand=True)
      
      # Center the map for Skopje (temporary situation)
      map_widget.set_position(41.9981, 21.4254) # Skopje lt, alt
      map_widget.set_zoom(14)

      # Temporary setting points A to B
      marker_a = None
      marker_b = None

      # list of route cordinates 
      route_coordinates = list()

      # START APP
      root.mainloop()

   def drawPath(route_cords, map_widget):
      """ Drawing of the shortest and cleanest path 
      
          route_cords: list of cordinates from A to B location
          map_widget: tkintermapview for the interactive map
      """

      path = map_widget.set_path(route_cords, color="#2ea44f", width=5)


if __name__ == "__main__":
   app = mainApp()