import subprocess
import threading
import sys
import os
import json
import math  # Global import for math
import cairo
import itertools
from dataclasses import dataclass
from typing import Callable, Optional, List, Any, Tuple, Union

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib, Gio

@dataclass
class Vec2:
    x: float
    y: float

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

    def __mul__(self, other) -> 'Vec2':
        if isinstance(other, (int, float)):  # Scalar multiplication
            return Vec2(self.x * other, self.y * other)
        elif isinstance(other, Vec2):        # element-wise multiplication
            return Vec2(self.x * other.x, self.y * other.y)
        else:
            return NotImplemented

    def __rmul__(self, other) -> 'Vec2':
        return self.__mul__(other)
    
    def dot(self, other: 'Vec2') -> float:
        return self.x * other.x + self.y * other.y

    def length(self) -> float:
        return math.hypot(self.x, self.y)
    
    def distance_to(self, other: 'Vec2') -> float:
        return (self - other).length()
    
    def transform_to_space(self, from_space: 'Vec2', to_space: 'Vec2') -> 'Vec2':
        """
        Transform this Vec2 from one coordinate space to another.
        from_space: Vec2 (source max_x, max_y)
        to_space: Vec2 (target width, height)
        """
        return Vec2(self.x * to_space.x / from_space.x, self.y * to_space.y / from_space.y)
    
    def distance_to_segment(self, a: 'Vec2', b: 'Vec2') -> float:
        """
        Returns the shortest distance from this point to the segment ab.
        """
        if a == b:
            return self.distance_to(a)
        
        ab = b - a
        ap = self - a
        ab_len2 = ab.dot(ab)
        t = ap.dot(ab) / ab_len2
        t = max(0, min(1, t))
        closest = a + ab * t
        return self.distance_to(closest)
    
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

@dataclass
class Pen:
    name : str
    color: Tuple[float, float, float, float] = (0, 0, 0, 1)
    width: int = 2
    supports_incremental_drawing: bool = True
    is_temporary: bool = False
    stroke_add_point_handler: Optional[Callable[['Stroke'], None]] = None

    def set_style(self, cr: cairo.Context) -> None:
        cr.set_source_rgba(*self.color)
        cr.set_line_width(self.width)
        # cr.set_line_cap(cairo.LINE_CAP_ROUND)

    def draw(self, cr: cairo.Context, points: List[Vec2]) -> None:
        if len(points) < 2:
            return
        
        self.set_style(cr)

        cr.move_to(*points[0])
        for pt in points[1:]:
            cr.line_to(*pt)
        cr.stroke()

    def draw_cursor(self, cr: cairo.Context, point: Vec2) -> None:
        cr.set_source_rgba(*self.color)
        cursor_radius = max(5, (self.width/2) * 1.25)  # Make the cursor clearly larger than the pen
        cr.arc(*point, cursor_radius, 0, 2 * math.pi)
        cr.fill()

    def draw_selector_icon(self, area, cr: cairo.Context, width, height) -> None:
        context_size = Vec2(width, height)

        # Control points in normalized coordinates
        a, b = 1.5, 0.75
        pts = [
            Vec2(0, 0.25),
            Vec2(0.5 + a, 0.5 - b),
            Vec2(0.5 - a, 0.5 + b),
            Vec2(1, 0.75),
        ]
        pts = [pt * context_size for pt in pts]


        self.set_style(cr)

        # Draw the cubic Bézier curve directly with Cairo
        cr.move_to(*pts[0])
        cr.curve_to(*itertools.chain.from_iterable(pts[1:]))
        cr.stroke()
        
    
class CalligraphyPen(Pen):
    def __init__(self, color: Tuple[float, float, float, float] = (0, 0, 0, 1), width: int = 10, angle: float = 45) -> None:
        super().__init__("calligraphy pen", color, width, supports_incremental_drawing=True)
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
    def __init__(self, color: Tuple[float, float, float, float] = (0, 1, 0, 1), width: int = 16, max_length: int = 250) -> None:
        def stroke_add_point_handler(str: Stroke):
            if len(str.points) > max_length:
                del str.points[0]

        super().__init__(
            "pointer",
            color,
            width,
            supports_incremental_drawing=False,
            is_temporary=True,
            stroke_add_point_handler=stroke_add_point_handler
        )

    def draw_cursor(self, cr: cairo.Context, point: Vec2, scaling_ratio=1) -> None:
        cr.set_source_rgba(*self.color)
        cr.arc(*point, self.width / 2 * scaling_ratio, 0, 2 * math.pi)
        cr.fill()

    def draw_selector_icon(self, area, cr, width, height):
        return self.draw_cursor(cr, Vec2(width, height) * 0.5, 0.8)
    
class Eraser(Pen):
    def __init__(self, width: int = 16, is_object_eraser=True) -> None:
        # TODO: (LATER) implement area eraser
        assert(is_object_eraser)
        super().__init__(
            ("object" if is_object_eraser else "area") + " eraser",
            (0.53, 0.53, 0.53, 1),
            width,
            supports_incremental_drawing=False,
            is_temporary=True,
        )

    def draw(self, cr: cairo.Context, points: List[Vec2]) -> None:
        """
        No draw functionality, so that it doesn't leave trace
        """
        pass

    def draw_cursor(self, cr: cairo.Context, point: Vec2, scaling_ratio=1) -> None:
        cr.set_source_rgba(*self.color)
        cr.arc(*point, self.width / 2 * scaling_ratio, 0, 2 * math.pi)
        cr.stroke()

    def draw_selector_icon(self, area, cr, width, height):
        return self.draw_cursor(cr, Vec2(width, height) * 0.5, 0.8)

    def intersects_stroke(self, stroke: 'Stroke', point: Vec2) -> bool:
        """
        Returns True if the eraser at 'point' (center) with its radius intersects any segment of the stroke.
        Call StrokeManager.erase_stroke_at_point(point, eraser) from your event handler when the eraser is used.
        """
        radius = self.width / 2
        for p1, p2 in zip(stroke.points, stroke.points[1:]):
            if point.distance_to_segment(p1, p2) <= radius:
                return True
        return False

    def erase_stroke_at_point(self, point: Vec2, stroke_manager: 'StrokeManager') -> Optional['Stroke']:
        """
        Remove the first completed stroke in the stroke_manager that is intersected by the eraser at the point.
        Returns the stroke if erased, else None.
        """
        for i, stroke in enumerate(stroke_manager.completed_strokes):
            if self.intersects_stroke(stroke, point):
                stroke_manager.require_redraw = True
                return stroke_manager.completed_strokes.pop(i)
        return None

class Stroke:
    def __init__(self, pen: Pen) -> None:
        self.points = []
        self.last_drawn_index = 0
        self.pen = pen

    def add_point(self, point: Vec2) -> None:
        self.points.append(point)
        if self.pen.stroke_add_point_handler:
            self.pen.stroke_add_point_handler(self)

        # TODO: (LATER) add smoothening, if needed
            

    def draw(self, cr: cairo.Context, new_only: bool = False) -> None:
        start = self.last_drawn_index if new_only else 0
        points = self.points[start:]

        self.pen.draw(cr, points)

        if new_only:
            self.last_drawn_index = len(self.points) - 1

@dataclass
class StrokeAction:
    stroke: 'Stroke'
    is_add : bool # false for deleted stroke, true for added stroke

class StrokeManager:
    def __init__(self) -> None:
        self.current_strokes = {}      # slot -> Stroke
        self.completed_strokes = []    # List[Stroke]
        self.undo_stack: list[StrokeAction] = []
        self.redo_stack: list[StrokeAction] = []
        self.require_redraw = False

    def start_stroke(self, slot: int, point: Vec2, pen: Pen) -> None:
        stroke = Stroke(pen)
        stroke.add_point(point)
        self.current_strokes[slot] = stroke

    def update_stroke(self, slot: int, point: Vec2) -> None:
        if slot in self.current_strokes:
            stroke = self.current_strokes[slot]
            stroke.add_point(point)
            # Eraser: erase intersecting strokes
            if isinstance(stroke.pen, Eraser):
                deletedStroke = stroke.pen.erase_stroke_at_point(point, self)
                if deletedStroke:
                    self.undo_stack.append(StrokeAction(deletedStroke, False))
                    self.redo_stack.clear()

    def end_stroke(self, slot: int) -> None:
        if slot in self.current_strokes:
            # temporary pen: just gets erased
            if not self.current_strokes[slot].pen.is_temporary:
                stroke = self.current_strokes[slot]
                self.completed_strokes.append(stroke)
                self.undo_stack.append(StrokeAction(stroke, True))
                self.redo_stack.clear()
            del self.current_strokes[slot]

    def get_all_strokes(self) -> list['Stroke']:
        return self.completed_strokes + list(self.current_strokes.values())
    
    def draw(self, surface, scale=1) -> None:
        cr = cairo.Context(surface)
        cr.scale(scale, scale)
        for stroke in self.get_all_strokes():
            stroke.draw(cr)
        self.require_redraw = False

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        action = self.undo_stack.pop()
        if action.is_add:
            stroke = action.stroke
            if stroke in self.completed_strokes:
                idx = self.completed_strokes.index(stroke)
                self.completed_strokes.pop(idx)
                self.redo_stack.append(StrokeAction(stroke, True))
                return True
        else:
            stroke = action.stroke
            self.completed_strokes.append(stroke)  # Always add to top
            self.redo_stack.append(StrokeAction(stroke, False))
            return True
        return False

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        action = self.redo_stack.pop()
        if action.is_add:
            stroke = action.stroke
            self.completed_strokes.append(stroke)
            self.undo_stack.append(StrokeAction(stroke, True))
            return True
        else:
            stroke = action.stroke
            if stroke in self.completed_strokes:
                self.completed_strokes.remove(stroke)
            self.undo_stack.append(StrokeAction(stroke, False))
            return True
        return False

    def clear(self) -> None:
        self.completed_strokes.clear()
        self.current_strokes.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
