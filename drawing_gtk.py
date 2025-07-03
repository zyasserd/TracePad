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
    def __init__(self, on_event, on_error):
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

        # Create a 1x1 transparent pixbuf
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 1, 1)
        pixbuf.fill(0x00000000)  # Fully transparent

        # Convert Pixbuf to Texture
        texture = Gdk.Texture.new_for_pixbuf(pixbuf)

        # Create blank cursor from texture with hotspot (0,0)
        blank_cursor = Gdk.Cursor.new_from_texture(texture, 0, 0)
        self.set_cursor(blank_cursor)

        self.label = Gtk.Label(label="Starting touchpad reader...\nCursor is hidden. Press Esc to exit.")
        self.set_child(self.label)

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key)
        self.add_controller(key_controller)

        self.touchpad_reader = TouchpadReaderThread(self.handle_touchpad_event, self.handle_touchpad_error)
        self.touchpad_reader.start()

    def handle_touchpad_event(self, event):
        data = event.get('data', {})
        # Show number of fingers and their positions
        if data:
            fingers = [f"Slot {slot}: x={info.get('x')}, y={info.get('y')}" for slot, info in data.items()]
            msg = f"Fingers: {len(data)}\n" + "\n".join(fingers)
        else:
            msg = "No fingers detected."
        self.append_label_message(msg)
        

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

    def append_label_message(self, text):
        # Show only the last 10 lines
        current = self.label.get_text().split('\n')
        current.append(text)
        self.label.set_text('\n'.join(current[-10:]))

    def on_key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
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
