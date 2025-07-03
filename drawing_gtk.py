import gi
import subprocess
import threading
import sys
import os
import json

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GdkPixbuf, GLib


class TouchpadReaderThread:
    def __init__(self, on_device_info, on_event, on_error):
        self.on_device_info = on_device_info  # callback for device info
        self.on_event = on_event  # callback for normal events
        self.on_error = on_error  # callback for errors
        self.reader_process = None
        self.reader_thread = None
        self.max_x = None
        self.max_y = None
        self._should_stop = threading.Event()

    def start(self):
        # TODO: pkg_resources.resource_filename('fingerpaint', 'data/fix_permissions.sh')
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'touchpad_reader.py'))
        self.reader_process = subprocess.Popen([
            'pkexec', sys.executable, script_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

    def _read_output(self):
        if not self.reader_process or not self.reader_process.stdout:
            return

        for line in self.reader_process.stdout:
            if self._should_stop.is_set():
                break
                
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except Exception:
                GLib.idle_add(self.on_error, "Invalid JSON: [no error code] - " + line)
                break

            if 'error' in event:
                error_code = event.get('error', 'Error')
                error_msg = event.get('message', '')
                GLib.idle_add(self.on_error, f"{error_code}: {error_msg}")
                break
            elif event.get('event') == 'device_info':
                data = event.get('data', {})
                self.max_x = data.get('max_x')
                self.max_y = data.get('max_y')
                if self.on_device_info:
                    GLib.idle_add(self.on_device_info)
            elif event.get('event') == 'touch_update':
                GLib.idle_add(self.on_event, event)
            
            # ignore shutdown event type

        if self.reader_process.stdout:
            self.reader_process.stdout.close()

    def stop(self):
        self._should_stop.set()
        if self.reader_process and self.reader_process.poll() is None:
            try:
                self.reader_process.terminate()
            except Exception:
                pass

    @property
    def dimensions(self):
        return self.max_x, self.max_y

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fullscreen()

        # [[ CURSOR ]]
        # Create a 1x1 transparent pixbuf
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)
        pixbuf.fill(0x00000000)  # Fully transparent

        # Convert Pixbuf to Texture
        texture = Gdk.Texture.new_for_pixbuf(pixbuf)

        # Create blank cursor from texture with hotspot (0,0)
        blank_cursor = Gdk.Cursor.new_from_texture(texture, 0, 0)
        self.set_cursor(blank_cursor)


        # [[ TOUCHPAD THREAD ]]
        self.touchpad_reader = TouchpadReaderThread(
            self.handle_device_info,
            self.handle_touchpad_event,
            self.handle_touchpad_error
        )
        self.touchpad_reader.start()


        # [[ KEYBINDINGS ]]
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key)
        self.add_controller(key_controller)
        

        # [[ DRAWING AREA ]]
        self.coverage = 0.8
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_draw_func(self.on_draw)
        self.finger_positions = {}

    def handle_device_info(self):
        # Get window size (fullscreen, so only set once)
        win_width = self.get_allocated_width()
        win_height = self.get_allocated_height()

        # Calculate aspect ratio
        aspect = self.touchpad_reader.max_x / self.touchpad_reader.max_y
        # Calculate drawing area size based on coverage
        if win_width / win_height > aspect:
            # Window is wider than touchpad
            height = int(win_height * self.coverage)
            width = int(height * aspect)
        else:
            width = int(win_width * self.coverage)
            height = int(width / aspect)
        self.drawing_area.set_size_request(width, height)
        # Center the drawing area
        self.drawing_area.set_halign(Gtk.Align.CENTER)
        self.drawing_area.set_valign(Gtk.Align.CENTER)

        # show only after the resize
        self.set_child(self.drawing_area)

    def handle_touchpad_event(self, event):
        self.finger_positions = event.get('data', {})
        self.drawing_area.queue_draw()
    
    def on_draw(self, area, cr, width, height):
        # Draw border and fingers as before...
        cr.set_source_rgba(1, 0, 0, 1)
        cr.set_line_width(2)
        cr.rectangle(1, 1, width-2, height-2)
        cr.stroke()

        for i, (slot, info) in enumerate(self.finger_positions.items()):
            x = info.get('x', 0)
            y = info.get('y', 0)
            draw_x = x / self.touchpad_reader.max_x * width
            draw_y = y / self.touchpad_reader.max_y * height
            cr.set_source_rgba(1, 0, 0, 0.8) if i == 0 else cr.set_source_rgba(0, 1, 0, 0.8)
            cr.arc(draw_x, draw_y, 30, 0, 2*3.1416)
            cr.fill()

    def handle_touchpad_error(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            buttons=Gtk.ButtonsType.CLOSE,
            message_type=Gtk.MessageType.ERROR,
            text="Touchpad Reader Error",
            secondary_text=message
        )
        dialog.connect("response", self._on_error_dialog_response)
        dialog.show()

    def _on_error_dialog_response(self, dialog, response):
        dialog.destroy()
        self.touchpad_reader.stop()
        self.get_application().quit()

    def on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape or keyval == Gdk.KEY_q or keyval == Gdk.KEY_Q:
            self.touchpad_reader.stop()
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
