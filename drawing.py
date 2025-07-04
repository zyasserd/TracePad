import gi
import subprocess
import threading
import sys
import os
import json
import cairo
import math  # Global import for math
import tempfile
from PIL import Image  # Add to imports

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib, Gio


class Vec2:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __iter__(self):
        return iter((self.x, self.y))

    def __repr__(self):
        return f"Vec2(x={self.x}, y={self.y})"
    
    def __eq__(self, other):
        return isinstance(other, Vec2) and self.x == other.x and self.y == other.y
    
    def __add__(self, other):
        return Vec2(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other):
        return Vec2(self.x - other.x, self.y - other.y)
    
    def __mul__(self, scalar):
        return Vec2(self.x * scalar, self.y * scalar)
    
    def transform_to_space(self, from_space, to_space):
        """
        Transform this Vec2 from one coordinate space to another.
        from_space: Vec2 (source max_x, max_y)
        to_space: Vec2 (target width, height)
        """
        return Vec2(self.x * to_space.x / from_space.x, self.y * to_space.y / from_space.y)
    
    @property
    def aspect(self):
        """Return the aspect ratio x/y (width/height)."""
        return self.x / self.y if self.y != 0 else float('inf')
    
    @staticmethod
    def from_polar_coordinates(angle_rad, radius):
        """Create a Vec2 from an angle in radians and a radius (length)."""
        return Vec2(math.cos(angle_rad) * radius, math.sin(angle_rad) * radius)

class TouchpadReaderThread:
    def __init__(self, on_device_info, on_event, on_error):
        self.on_device_info = on_device_info
        self.on_event = on_event
        self.on_error = on_error
        self.reader_process = None
        self.reader_thread = None
        self.max = None  # Vec2(max_x, max_y)
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
                self.max = Vec2(data.get('max_x'), data.get('max_y'))
                if self.on_device_info:
                    GLib.idle_add(self.on_device_info)
            elif event.get('event') == 'touch_update':
                GLib.idle_add(self.on_event, event['data'])
            
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
        return self.max

class Pen:
    def __init__(self, color=(0, 0, 0), width=2):
        self.color = color
        self.width = width

    def draw(self, cr, points):
        if len(points) < 2:
            return
        
        if len(self.color) == 4:
            cr.set_source_rgba(*self.color)
        else:
            cr.set_source_rgb(*self.color)
        
        cr.set_line_width(self.width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND) # TODO: highlighter
        cr.move_to(*points[0])
        for pt in points[1:]:
            cr.line_to(*pt)
        cr.stroke()

class CalligraphyPen(Pen):
    def __init__(self, color=(0, 0, 0), width=10, angle=45):
        super().__init__(color, width)
        self.angle = angle
        self.angle_rad = math.radians(angle)

    def draw(self, cr: cairo.Context, points):
        if len(points) < 2:
            return
        
        if len(self.color) == 4:
            cr.set_source_rgba(*self.color)
        else:
            cr.set_source_rgb(*self.color)
        
        perp = Vec2.from_polar_coordinates(self.angle_rad, self.width / 2)

        cr.set_line_width(1)
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]

            # Four corners of the quadrilateral
            cr.move_to(*(p1 - perp))
            cr.line_to(*(p2 - perp))
            cr.line_to(*(p2 + perp))
            cr.line_to(*(p1 + perp))
            cr.close_path()
            cr.fill_preserve()
            cr.stroke()

class Stroke:
    def __init__(self, pen):
        self.points = []
        self.last_drawn_index = 0
        self.pen = pen

    def add_point(self, point):
        self.points.append(point)
        # TODO: add future smoothening, if needed

    def draw(self, cr, new_only=False):
        start = self.last_drawn_index if new_only else 0
        points = self.points[start:]

        self.pen.draw(cr, points)

        if new_only:
            self.last_drawn_index = len(self.points) - 1

class StrokeManager:
    def __init__(self):
        self.current_strokes = {}      # slot -> Stroke
        self.completed_strokes = []    # List[Stroke]
        self.redo_stack = []

    def start_stroke(self, slot, point, pen):
        stroke = Stroke(pen)
        stroke.add_point(point)
        self.current_strokes[slot] = stroke

    def update_stroke(self, slot, point):
        if slot in self.current_strokes:
            self.current_strokes[slot].add_point(point)

    def end_stroke(self, slot):
        if slot in self.current_strokes:
            self.completed_strokes.append(self.current_strokes[slot])
            del self.current_strokes[slot]
            self.redo_stack.clear()

    def get_all_strokes(self):
        return self.completed_strokes + list(self.current_strokes.values())
    
    def draw(self, surface):
        cr = cairo.Context(surface)
        for stroke in self.get_all_strokes():
            stroke.draw(cr)

    def undo(self):
        if self.completed_strokes:
            stroke = self.completed_strokes.pop()
            self.redo_stack.append(stroke)
            return True
        return False

    def redo(self):
        if self.redo_stack:
            stroke = self.redo_stack.pop()
            self.completed_strokes.append(stroke)
            return True
        return False

    def clear(self):
        self.completed_strokes.clear()
        self.current_strokes.clear()
        self.redo_stack.clear()

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

        # [[ STOKE MANAGER ]]
        self.stroke_manager = StrokeManager()

        # [[ CACHE SURFACE ]]
        self.strokes_surface = None  # The cache surface
        self.surface_size = None  # Vec2(width, height)

        # [[ PENS ]]
        self.pens = [
            Pen(color=(1, 0, 0), width=2),      # Red pinpoint as normal pen
            Pen(color=(1, 1, 1), width=2),      # White pinpoint as normal pen
            Pen(color=(1, 1, 0, 0.3), width=18),        # Highlighter as normal pen
            # CalligraphyPen(color=(0.1, 0.15, 0.4), width=10, angle=45), # Calligraphy
            CalligraphyPen(color=(1,1,1), width=10, angle=45), # Calligraphy
        ]
        self.pen_index = 3


    def handle_device_info(self):
        # Get window size (fullscreen, so only set once)
        win_size = Vec2(
            self.get_size(orientation=Gtk.Orientation.HORIZONTAL),
            self.get_size(orientation=Gtk.Orientation.VERTICAL)
        )

        # Calculate aspect ratio
        aspect = self.touchpad_reader.max.aspect

        # Calculate drawing area size based on coverage
        if win_size.x / win_size.y > aspect:
            # Window is wider than touchpad
            height = int(win_size.y * self.coverage)
            width = int(height * aspect)
        else:
            width = int(win_size.x * self.coverage)
            height = int(width / aspect)
        self.drawing_area.set_size_request(width, height)

        # Center the drawing area
        self.drawing_area.set_halign(Gtk.Align.CENTER)
        self.drawing_area.set_valign(Gtk.Align.CENTER)

        # show only after the resize
        self.drawing_area.set_draw_func(self.on_draw)
        self.set_child(self.drawing_area)

        # Create the cache surface
        self.strokes_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        self.surface_size = Vec2(width, height)

    def handle_touchpad_event(self, data):
        # data: {slot: {x, y}}
        current_slots = set(self.stroke_manager.current_strokes.keys())
        new_slots = set(data.keys())

        # End strokes for slots that disappeared
        ended = current_slots - new_slots
        if ended:
            for slot in ended:
                self.stroke_manager.end_stroke(slot)
            # Redraw cache surface only once after all ended strokes
            self.rebuild_surface_from_strokes()
        
        # Start or update strokes for active slots
        for slot, pos in data.items():
            abs_point = Vec2(pos['x'], pos['y'])
            draw_point = abs_point.transform_to_space(self.touchpad_reader.max, self.surface_size)
            if slot not in self.stroke_manager.current_strokes:
                pen = self.pens[self.pen_index]
                self.stroke_manager.start_stroke(slot, draw_point, pen)
            else:
                self.stroke_manager.update_stroke(slot, draw_point)
        
        self.drawing_area.queue_draw()

    def on_draw(self, area, cr, width, height):
        # Paint the cached surface (completed strokes)
        if self.strokes_surface:
            cr.set_source_surface(self.strokes_surface, 0, 0)
            cr.paint()
        
        # Draw current (in-progress) strokes on top
        for stroke in self.stroke_manager.current_strokes.values():
            stroke.draw(cr)
        
        # Draw a white rectangular border around the canvas
        cr.set_source_rgb(1, 1, 1)  # White color
        cr.set_line_width(4)        # Border thickness
        cr.rectangle(2, 2, width - 2, height - 2)
        cr.stroke()

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
    
    def cycle_pen_type(self):
        self.pen_index = (self.pen_index + 1) % len(self.pens)

    def rebuild_surface_from_strokes(self):
        if not self.surface_size:
            return
        self.strokes_surface = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, int(self.surface_size.x), int(self.surface_size.y)
        )
        self.stroke_manager.draw(self.strokes_surface)
        self.drawing_area.queue_draw()

    def undo_last_stroke(self):
        if self.stroke_manager.undo():
            self.rebuild_surface_from_strokes()

    def redo_last_stroke(self):
        if self.stroke_manager.redo():
            self.rebuild_surface_from_strokes()

    def clear_drawing(self):
        if self.surface_size:
            self.stroke_manager.clear()
            self.rebuild_surface_from_strokes()

    def export(self, filename, filetype):
        width, height = int(self.surface_size.x), int(self.surface_size.y)
        if filetype == "svg":
            surface = cairo.SVGSurface(filename, width, height)
            self.stroke_manager.draw(surface)
            surface.finish()
        elif filetype == "png":
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            self.stroke_manager.draw(surface)
            surface.write_to_png(filename)
        elif filetype == "jpg":
            if Image is None:
                raise RuntimeError("Pillow (PIL) is required for JPG export.")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                self.stroke_manager.draw(surface)
                surface.write_to_png(tmp.name)
                img = Image.open(tmp.name)
                rgb_img = img.convert('RGB')
                rgb_img.save(filename, "JPEG")
        else:
            raise ValueError("Unsupported filetype")

    def save_as_dialog(self):
        self.save_dialog = Gtk.FileDialog.new()
        self.save_dialog.set_title("Save Drawing")

        # Create filters
        svg_filter = Gtk.FileFilter()
        svg_filter.set_name("SVG files")
        svg_filter.add_mime_type("image/svg+xml")
        svg_filter.add_pattern("*.svg")

        png_filter = Gtk.FileFilter()
        png_filter.set_name("PNG files")
        png_filter.add_mime_type("image/png")
        png_filter.add_pattern("*.png")

        jpg_filter = Gtk.FileFilter()
        jpg_filter.set_name("JPEG files")
        jpg_filter.add_mime_type("image/jpeg")
        jpg_filter.add_pattern("*.jpg")
        jpg_filter.add_pattern("*.jpeg")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(svg_filter)
        filters.append(png_filter)
        filters.append(jpg_filter)

        self.save_dialog.set_filters(filters)
        self.save_dialog.set_default_filter(svg_filter)

        # Suggest a default file name
        self.save_dialog.set_initial_name("drawing.svg")

        # Show the dialog
        self.save_dialog.save(self, None, self._on_save_dialog_response)

    def _on_save_dialog_response(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if file is not None:
                # TODO: do it with the filters
                filename = file.get_path()
                # Determine filetype from extension
                if filename.lower().endswith(".svg"):
                    filetype = "svg"
                elif filename.lower().endswith(".png"):
                    filetype = "png"
                elif filename.lower().endswith((".jpg", ".jpeg")):
                    filetype = "jpg"
                else:
                    filetype = "svg"  # Default
                self.export(filename, filetype)
        except GLib.Error as error:
            # TODO: show be a dialog with error
            # NOTE: dismissed by used is an error
            print(f"Error saving file: {error.message}")

    def on_key(self, controller, keyval, keycode, state):
        if (keyval == Gdk.KEY_z or keyval == Gdk.KEY_Z) and (state & Gdk.ModifierType.CONTROL_MASK):
            self.undo_last_stroke()
        elif (keyval == Gdk.KEY_y or keyval == Gdk.KEY_Y) and (state & Gdk.ModifierType.CONTROL_MASK):
            self.redo_last_stroke()
        elif keyval == Gdk.KEY_Escape or keyval == Gdk.KEY_q or keyval == Gdk.KEY_Q:
            self.touchpad_reader.stop()
            self.get_application().quit()
        elif keyval == Gdk.KEY_s or keyval == Gdk.KEY_S:
            self.save_as_dialog()
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
