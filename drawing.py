import cairo
import tempfile
from PIL import Image  # Add to imports

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib, Gio

from drawing_helpers import *


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fullscreen()

        # [[ CURSOR ]]
        self.set_cursor(Gdk.Cursor.new_from_name("none"))


        # [[ TOUCHPAD THREAD ]]
        self.touchpad_reader = TouchpadReaderThread(
            self.handle_device_init,
            self.handle_touchpad_event,
            self.handle_touchpad_error
        )
        self.touchpad_reader.start()


        # [[ KEYBINDINGS ]]
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_key)
        self.add_controller(key_controller)
        

        # [[ DRAWING AREA ]]
        self.coverage = 0.65
        self.drawing_area = Gtk.DrawingArea()

        # [[ FRAME AROUND DRAWING AREA ]]
        self.frame = Gtk.Frame()
        self.frame.set_child(self.drawing_area)
        self.frame.set_halign(Gtk.Align.CENTER)
        self.frame.set_valign(Gtk.Align.CENTER)
        self.frame.set_css_classes(["drawing-frame"])

        # [[ STOKE MANAGER ]]
        self.stroke_manager = StrokeManager()

        # [[ CACHE SURFACE ]]
        self.strokes_surface = None  # The cache surface
        self.surface_size = None  # Vec2(width, height)

        # [[ PENS ]]
        self.pens = [
            # Red pinpoint as normal pen
            Pen(color=(1, 0, 0, 1), width=2),
            # White pinpoint as normal pen
            Pen(color=(1, 1, 1, 1), width=2),
            # Highlighter as normal pen
            Pen(color=(1, 1, 0, 0.3), width=18, supports_incremental_drawing=False),
            # Calligraphy
            CalligraphyPen(color=(0.1, 0.15, 0.4, 1), width=10, angle=45),
            # Pointer pen
            PointerPen(color=(0, 1, 0, 1), width=16),
        ]
        self.pen_index = 0


    def handle_device_init(self) -> None:
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

        # show only after the resize
        self.drawing_area.set_draw_func(self.on_draw)
        self.set_child(self.frame)

        # Create the cache surface
        self.strokes_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        self.surface_size = Vec2(width, height)

    def handle_touchpad_event(self, data) -> None:
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

            # Draw incrementally for Strokes that support that
            stroke : Stroke = self.stroke_manager.current_strokes[slot]
            if stroke.pen.supports_incremental_drawing:
                cr = cairo.Context(self.strokes_surface)
                stroke.draw(cr, True)
        
        self.drawing_area.queue_draw()

    def on_draw(self, area, cr: cairo.Context, width: int, height: int) -> None:
        # Paint the cached surface (completed strokes)
        if self.strokes_surface:
            cr.set_source_surface(self.strokes_surface, 0, 0)
            cr.paint()
        
        # Draw current (in-progress) strokes on top
        for stroke in self.stroke_manager.current_strokes.values():
            if not stroke.pen.supports_incremental_drawing:
                stroke.draw(cr)
        
        # Draw pointers
        for stroke in self.stroke_manager.current_strokes.values():
            stroke.pen.draw_cursor(cr, stroke.points[-1])

    def handle_touchpad_error(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            buttons=Gtk.ButtonsType.CLOSE,
            message_type=Gtk.MessageType.ERROR,
            text="Touchpad Reader Error",
            secondary_text=message
        )
        dialog.connect("response", self._on_error_dialog_response)
        dialog.present()

    def _on_error_dialog_response(self, dialog: Gtk.MessageDialog, response: int) -> None:
        dialog.destroy()
        self.touchpad_reader.stop()
        self.get_application().quit()
    
    def cycle_pen_type(self) -> None:
        self.pen_index = (self.pen_index + 1) % len(self.pens)

    def rebuild_surface_from_strokes(self) -> None:
        if not self.surface_size:
            return
        self.strokes_surface = cairo.ImageSurface(
            cairo.FORMAT_ARGB32, int(self.surface_size.x), int(self.surface_size.y)
        )
        self.stroke_manager.draw(self.strokes_surface)
        self.drawing_area.queue_draw()

    def undo_last_stroke(self) -> None:
        if self.stroke_manager.undo():
            self.rebuild_surface_from_strokes()

    def redo_last_stroke(self) -> None:
        if self.stroke_manager.redo():
            self.rebuild_surface_from_strokes()

    def clear_drawing(self) -> None:
        if self.surface_size:
            self.stroke_manager.clear()
            self.rebuild_surface_from_strokes()

    def export(self, filename: str, filetype: str) -> None:
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

    def save_as_dialog(self) -> None:
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

    def _on_save_dialog_response(self, dialog: Gtk.FileDialog, result: int) -> None:
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

    def on_key(self, controller, keyval: int, keycode: int, state: int) -> None:
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
    def __init__(self) -> None:
        super().__init__(application_id="org.example.FullscreenHiddenCursor")
        self.connect('activate', self.on_activate)

    def on_activate(self, app: Adw.Application) -> None:
        self.win = MainWindow(application=app)
        self.win.present()

        # CSS for frame border
        css = b'''
        .drawing-frame {
            /* border: 4px solid #00aaff; */
            border-radius: 0px;
        }
        '''
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

app = MyApp()
app.run()
