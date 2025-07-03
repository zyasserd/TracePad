import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GdkPixbuf

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.set_decorated(False)
        self.fullscreen()

        # Create a 1x1 transparent pixbuf
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)
        pixbuf.fill(0x00000000)  # Fully transparent

        # Convert Pixbuf to Texture
        texture = Gdk.Texture.new_for_pixbuf(pixbuf)

        # Create blank cursor from texture with hotspot (0,0)
        blank_cursor = Gdk.Cursor.new_from_texture(texture, 0, 0)

        self.set_cursor(blank_cursor)

        label = Gtk.Label(label="Cursor is hidden. Press Esc to exit.")
        self.set_child(label)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key)
        self.add_controller(key_controller)

    def on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.get_application().quit()

class MyApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.example.FullscreenHiddenCursor")
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()

app = MyApp()
app.run()
