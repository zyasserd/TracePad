import subprocess
import threading
import sys
import os
import json
import math  # Global import for math
import cairo
from typing import Callable, Optional, List, Any, Tuple

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib, Gio

class Vec2:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    def __iter__(self):
        return iter((self.x, self.y))

    def __repr__(self) -> str:
        return f"Vec2(x={self.x}, y={self.y})"
    
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Vec2) and self.x == other.x and self.y == other.y
    
    def __add__(self, other: 'Vec2') -> 'Vec2':
        return Vec2(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other: 'Vec2') -> 'Vec2':
        return Vec2(self.x - other.x, self.y - other.y)
    
    def __mul__(self, scalar: float) -> 'Vec2':
        return Vec2(self.x * scalar, self.y * scalar)
    
    def transform_to_space(self, from_space: 'Vec2', to_space: 'Vec2') -> 'Vec2':
        """
        Transform this Vec2 from one coordinate space to another.
        from_space: Vec2 (source max_x, max_y)
        to_space: Vec2 (target width, height)
        """
        return Vec2(self.x * to_space.x / from_space.x, self.y * to_space.y / from_space.y)
    
    @property
    def aspect(self) -> float:
        """Return the aspect ratio x/y (width/height)."""
        return self.x / self.y if self.y != 0 else float('inf')
    
    @staticmethod
    def from_polar_coordinates(angle_rad: float, radius: float) -> 'Vec2':
        """Create a Vec2 from an angle in radians and a radius (length)."""
        return Vec2(math.cos(angle_rad) * radius, math.sin(angle_rad) * radius)

class TouchpadReaderThread:
    def __init__(self, on_device_init: Callable[[], None], on_event: Callable[[Any], None], on_error: Callable[[str], None]) -> None:
        self.on_device_init = on_device_init
        self.on_event = on_event
        self.on_error = on_error
        self.reader_process = None
        self.reader_thread = None
        self.max = None  # Vec2(max_x, max_y)
        self._should_stop = threading.Event()

    def start(self) -> None:
        # TODO: pkg_resources.resource_filename('fingerpaint', 'data/fix_permissions.sh')
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'touchpad_reader.py'))
        self.reader_process = subprocess.Popen([
            'pkexec', sys.executable, script_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

    def _read_output(self) -> None:
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
                if self.on_device_init:
                    GLib.idle_add(self.on_device_init)
            elif event.get('event') == 'touch_update':
                GLib.idle_add(self.on_event, event['data'])
            
            # ignore shutdown event type

        if self.reader_process.stdout:
            self.reader_process.stdout.close()

    def stop(self):
        # TODO: understand how the multithreading work here; then review this function
        self._should_stop.set()
        if self.reader_process and self.reader_process.poll() is None:
            try:
                self.reader_process.terminate()
            except Exception:
                pass

    @property
    def dimensions(self) -> Optional[Vec2]:
        return self.max

class Pen:
    def __init__(self, color: Tuple[float, float, float, float] = (0, 0, 0, 1), width: float = 2, supports_incremental_drawing: bool = True) -> None:
        self.color = color
        self.width = width
        self.supports_incremental_drawing = supports_incremental_drawing

    def draw(self, cr: cairo.Context, points: List[Vec2]) -> None:
        if len(points) < 2:
            return
        
        cr.set_source_rgba(*self.color)
        
        cr.set_line_width(self.width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(*points[0])
        for pt in points[1:]:
            cr.line_to(*pt)
        cr.stroke()

    def draw_cursor(self, cr: cairo.Context, point: Vec2) -> None:
        cr.set_source_rgba(*self.color)
        cursor_radius = max(5, (self.width/2) * 1.25)  # Make the cursor clearly larger than the pen
        cr.arc(*point, cursor_radius, 0, 2 * math.pi)
        cr.fill()
    
class CalligraphyPen(Pen):
    def __init__(self, color: Tuple[float, float, float, float] = (0, 0, 0, 1), width: float = 10, angle: float = 45) -> None:
        super().__init__(color, width, supports_incremental_drawing=True)
        self.angle = angle
        self.angle_rad = math.radians(angle)

    def draw(self, cr: cairo.Context, points: List[Vec2]) -> None:
        if len(points) < 2:
            return
        
        perp = Vec2.from_polar_coordinates(self.angle_rad, self.width / 2)

        cr.set_source_rgba(*self.color)
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

    def draw_cursor(self, cr: cairo.Context, point: Vec2) -> None:
        cr.translate(*point)
        cr.rotate(self.angle_rad)
        cr.scale(1.5, 0.5)
        super().draw_cursor(cr, (0, 0))


class PointerPen(Pen):
    def __init__(self, color: Tuple[float, float, float, float] = (0, 1, 0, 1), width: float = 16) -> None:
        super().__init__(color, width, supports_incremental_drawing=True)

    def draw(self, cr: cairo.Context, points: List[Vec2]) -> None:
        # Do not draw anything on the canvas
        pass

    def draw_cursor(self, cr: cairo.Context, point: Vec2) -> None:
        cr.set_source_rgba(*self.color)
        cr.arc(*point, self.width / 2, 0, 2 * math.pi)
        cr.fill()

class Stroke:
    def __init__(self, pen: Pen) -> None:
        self.points = []
        self.last_drawn_index = 0
        self.pen = pen

    def add_point(self, point: Vec2) -> None:
        self.points.append(point)
        # TODO: add future smoothening, if needed

    def draw(self, cr: cairo.Context, new_only: bool = False) -> None:
        start = self.last_drawn_index if new_only else 0
        points = self.points[start:]

        self.pen.draw(cr, points)

        if new_only:
            self.last_drawn_index = len(self.points) - 1

class StrokeManager:
    def __init__(self) -> None:
        self.current_strokes = {}      # slot -> Stroke
        self.completed_strokes = []    # List[Stroke]
        self.redo_stack = []

    def start_stroke(self, slot: int, point: Vec2, pen: Pen) -> None:
        stroke = Stroke(pen)
        stroke.add_point(point)
        self.current_strokes[slot] = stroke

    def update_stroke(self, slot: int, point: Vec2) -> None:
        if slot in self.current_strokes:
            self.current_strokes[slot].add_point(point)

    def end_stroke(self, slot: int) -> None:
        if slot in self.current_strokes:
            self.completed_strokes.append(self.current_strokes[slot])
            del self.current_strokes[slot]
            self.redo_stack.clear()

    def get_all_strokes(self) -> List[Stroke]:
        return self.completed_strokes + list(self.current_strokes.values())
    
    def draw(self, surface) -> None:
        cr = cairo.Context(surface)
        for stroke in self.get_all_strokes():
            stroke.draw(cr)

    def undo(self) -> bool:
        if self.completed_strokes:
            stroke = self.completed_strokes.pop()
            self.redo_stack.append(stroke)
            return True
        return False

    def redo(self) -> bool:
        if self.redo_stack:
            stroke = self.redo_stack.pop()
            self.completed_strokes.append(stroke)
            return True
        return False

    def clear(self) -> None:
        self.completed_strokes.clear()
        self.current_strokes.clear()
        self.redo_stack.clear()
