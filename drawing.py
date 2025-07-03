import gi
import subprocess
import threading
import sys
import os
import json
import cairo

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib


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
        self.set_cursor(Gdk.Cursor.new_from_name("none"))


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
        self.coverage = 0.6
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_draw_func(self.on_draw)
        self.finger_positions = {}
        # Store paths as: slot -> list of segments, each segment is dict with 'points' and 'pen_type'
        self.paths = {}  # slot: [ {'points': [(x, y), ...], 'pen_type': ...}, ... ]
        self.active_segments = {}  # slot: current segment being drawn
        self.current_pen_type_idx = 0
        self.default_pen_types = [
            {'name': 'red', 'color': (1, 0, 0, 0.8), 'thickness': 4},
            {'name': 'green', 'color': (0, 1, 0, 0.8), 'thickness': 4},
            {'name': 'blue', 'color': (0, 0, 1, 0.8), 'thickness': 4},
            {'name': 'black', 'color': (0, 0, 0, 0.8), 'thickness': 8},
            {'name': 'highlighter', 'color': (1, 1, 0, 0.3), 'thickness': 18},
        ]
        self.current_pen_type = self.default_pen_types[self.current_pen_type_idx]
        # For performance: cache the drawing as a cairo.ImageSurface
        self._drawing_cache = None
        self._drawing_cache_valid = False

        self.undo_stack = []  # Stack for undo
        self.redo_stack = []  # Stack for redo

    def handle_device_info(self):
        # Get window size (fullscreen, so only set once)
        win_width = self.get_size(orientation=Gtk.Orientation.HORIZONTAL)
        win_height = self.get_size(orientation=Gtk.Orientation.VERTICAL)

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
        prev_slots = set(self.finger_positions.keys())
        self.finger_positions = event.get('data', {})
        new_slots = set(self.finger_positions.keys())
        # For each slot, if new, start a new segment with current pen type
        for slot in new_slots:
            info = self.finger_positions[slot]
            x = info.get('x', 0)
            y = info.get('y', 0)
            if slot not in self.active_segments:
                # New touch: start new segment
                seg = {'points': [(x, y)], 'pen_type': self.current_pen_type.copy()}
                self.active_segments[slot] = seg
            else:
                self.active_segments[slot]['points'].append((x, y))
        # For slots that disappeared, commit their segment to paths
        for slot in prev_slots - new_slots:
            if slot in self.active_segments:
                if slot not in self.paths:
                    self.paths[slot] = []
                # Save state for undo before committing
                self.undo_stack.append((self._copy_paths(), self._copy_active_segments()))
                self.redo_stack.clear()
                self.paths[slot].append(self.active_segments[slot])
                del self.active_segments[slot]
                self._drawing_cache_valid = False  # New stroke, need redraw
        # If any new points were added to active segments, mark cache invalid
        if new_slots:
            self._drawing_cache_valid = False
        self.drawing_area.queue_draw()

    def cycle_pen_type(self):
        self.current_pen_type_idx = (self.current_pen_type_idx + 1) % len(self.default_pen_types)
        self.current_pen_type = self.default_pen_types[self.current_pen_type_idx].copy()

    def draw_all(self, cr, width, height, draw_background=False, draw_fingers=True):
        # Optionally fill background (for SVG)
        if draw_background:
            cr.save()
            cr.set_source_rgb(1, 1, 1)
            cr.rectangle(0, 0, width, height)
            cr.fill()
            cr.restore()
        # Draw border
        cr.set_source_rgba(1, 0, 0, 1)
        cr.set_line_width(2)
        cr.rectangle(1, 1, width-2, height-2)
        cr.stroke()
        max_x = self.touchpad_reader.max_x
        max_y = self.touchpad_reader.max_y
        # Draw cached finished paths
        for slot, segments in self.paths.items():
            for seg in segments:
                pts = seg['points']
                pen = seg['pen_type']
                if len(pts) < 2:
                    continue
                cr.set_source_rgba(*pen['color'])
                cr.set_line_width(pen['thickness'])
                for i, (x, y) in enumerate(pts):
                    sx = x / max_x * width
                    sy = y / max_y * height
                    if i == 0:
                        cr.move_to(sx, sy)
                    else:
                        cr.line_to(sx, sy)
                cr.stroke()
        # Draw active segments (not yet committed)
        for slot, seg in self.active_segments.items():
            pts = seg['points']
            pen = seg['pen_type']
            if len(pts) < 2:
                continue
            cr.set_source_rgba(*pen['color'])
            cr.set_line_width(pen['thickness'])
            for i, (x, y) in enumerate(pts):
                sx = x / max_x * width
                sy = y / max_y * height
                if i == 0:
                    cr.move_to(sx, sy)
                else:
                    cr.line_to(sx, sy)
            cr.stroke()
        # Draw current finger positions as circles
        if draw_fingers:
            for i, (slot, info) in enumerate(self.finger_positions.items()):
                x = info.get('x', 0)
                y = info.get('y', 0)
                draw_x = x / max_x * width
                draw_y = y / max_y * height
                pen = self.current_pen_type
                cr.set_source_rgba(*pen['color'])
                cr.arc(draw_x, draw_y, 15, 0, 2*3.1416)
                cr.fill()

    def _update_drawing_cache(self):
        width = self.drawing_area.get_size(orientation=Gtk.Orientation.HORIZONTAL)
        height = self.drawing_area.get_size(orientation=Gtk.Orientation.VERTICAL)
        if width <= 0 or height <= 0:
            return
        self._drawing_cache = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(self._drawing_cache)
        self.draw_all(cr, width, height, draw_background=False, draw_fingers=False)
        self._drawing_cache_valid = True

    def on_draw(self, area, cr, width, height):
        # Only redraw finished paths if cache is invalid
        if not self._drawing_cache_valid or self._drawing_cache is None:
            self._update_drawing_cache()
        if self._drawing_cache:
            cr.set_source_surface(self._drawing_cache, 0, 0)
            cr.paint()
        # Draw active segments and fingers live (not cached)
        self.draw_all(cr, width, height, draw_background=False, draw_fingers=True)

    def save_as_svg(self):
        # Save the current drawing as SVG
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Save as SVG")
        def on_response(dialog, result):
            file = dialog.save_finish(result)
            if file:
                path = file.get_path()
                self._export_svg(path)
        dialog.save(self, None, on_response)

    def _export_svg(self, path):
        width = self.drawing_area.get_allocated_width()
        height = self.drawing_area.get_allocated_height()
        with cairo.SVGSurface(path, width, height) as surface:
            cr = cairo.Context(surface)
            self.draw_all(cr, width, height, draw_background=True, draw_fingers=False)

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

    def clear_drawing(self):
        # Push current state to undo stack before clearing
        self.undo_stack.append((self._copy_paths(), self._copy_active_segments()))
        self.redo_stack.clear()
        self.paths.clear()
        self.active_segments.clear()
        self._drawing_cache = None
        self._drawing_cache_valid = False
        self.drawing_area.queue_draw()

    def undo_last_stroke(self):
        # Save current state to redo stack
        if self.paths or self.active_segments:
            self.redo_stack.append((self._copy_paths(), self._copy_active_segments()))
        if self.undo_stack:
            prev_paths, prev_active = self.undo_stack.pop()
            self.paths = prev_paths
            self.active_segments = {}  # Always clear active segments after undo
            self._drawing_cache_valid = False
            self.drawing_area.queue_draw()

    def redo_last_stroke(self):
        if self.redo_stack:
            # Save current state to undo stack
            self.undo_stack.append((self._copy_paths(), self._copy_active_segments()))
            next_paths, next_active = self.redo_stack.pop()
            self.paths = next_paths
            self.active_segments = {}  # Always clear active segments after redo
            self._drawing_cache_valid = False
            self.drawing_area.queue_draw()

    def _copy_paths(self):
        # Deep copy paths for undo/redo
        import copy
        return copy.deepcopy(self.paths)

    def _copy_active_segments(self):
        import copy
        return copy.deepcopy(self.active_segments)

    def on_key(self, controller, keyval, keycode, state):
        if (keyval == Gdk.KEY_z or keyval == Gdk.KEY_Z) and (state & Gdk.ModifierType.CONTROL_MASK):
            self.undo_last_stroke()
        elif (keyval == Gdk.KEY_y or keyval == Gdk.KEY_Y) and (state & Gdk.ModifierType.CONTROL_MASK):
            self.redo_last_stroke()
        elif keyval == Gdk.KEY_Escape or keyval == Gdk.KEY_q or keyval == Gdk.KEY_Q:
            self.touchpad_reader.stop()
            self.get_application().quit()
        elif keyval == Gdk.KEY_s or keyval == Gdk.KEY_S:
            self.save_as_svg()
        elif keyval == Gdk.KEY_p or keyval == Gdk.KEY_P:
            self.cycle_pen_type()
        elif keyval == Gdk.KEY_c or keyval == Gdk.KEY_C:
            self.clear_drawing()

class MyApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.example.FullscreenHiddenCursor")
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()

app = MyApp()
app.run()
