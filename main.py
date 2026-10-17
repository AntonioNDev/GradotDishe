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
      map_widget = tkintermapview.TkinterMapView(root, width=900, height=700, corner_radius=0)
      map_widget.pack(fill="both", expand=True)

      # Center the map for Skopje (temporary situation)
      map_widget.set_position(41.9981, 21.4254) # Skopje lt, alt
      map_widget.set_zoom(14)

      # Temporary setting points A to B
      marker_a = map_widget.set_marker(41.9981, 21.4254, text="Точка А (Центар)")
      marker_b = map_widget.set_marker(42.0020, 21.4090, text="Точка Б (Карпош)")

      # list of test cordinates 
      route_coordinates = [
         (41.9981, 21.4254),
         (41.9995, 21.4180),
         (42.0020, 21.4090)
      ]

      # Drawing of the shortest and cleanest path
      path = map_widget.set_path(route_coordinates, color="#2ea44f", width=5)

      # START APP
      root.mainloop()


if __name__ == "__main__":
   app = mainApp()