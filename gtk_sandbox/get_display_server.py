import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk

display = Gdk.Display.get_default()
print("Display type:", type(display).__name__)
