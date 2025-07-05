import cairo
import tempfile
from math import sqrt
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

        # [[ OVERLAY ]]
        self.overlay = Gtk.Overlay()
        self.set_child(self.overlay)

        # [[ HEADER BAR (Always Visible) ]]
        self.header_bar = Gtk.HeaderBar()
        self.header_bar.set_title_widget(Gtk.Label(label="Absolute Touchpad"))
        self.header_bar.set_show_title_buttons(False)
        # Open/Save buttons
        open_btn = Gtk.Button(icon_name="document-open")
        open_btn.connect("clicked", self.on_open_clicked)
        save_btn = Gtk.Button(icon_name="document-save")
        save_btn.connect("clicked", self.on_save_clicked)
        self.header_bar.pack_start(open_btn)
        self.header_bar.pack_start(save_btn)
        # Custom close button (top right)
        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.set_tooltip_text("Close")
        close_btn.connect("clicked", lambda btn: self.get_application().quit())
        self.header_bar.pack_end(close_btn)
        # Hamburger menu
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu.append("Settings", "app.settings")
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)
        self.header_bar.pack_end(menu_btn)

        # self.overlay.add_overlay(self.header_bar)
        self.header_bar.set_halign(Gtk.Align.FILL)
        self.header_bar.set_valign(Gtk.Align.START)

        # [[ TOP OVERLAY: Banner below header bar ]]
        self.top_overlay_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.top_overlay_box.set_halign(Gtk.Align.FILL)
        self.top_overlay_box.set_valign(Gtk.Align.START)
        self.top_overlay_box.set_margin_top(0)
        self.top_overlay_box.set_margin_bottom(0)
        self.top_overlay_box.set_margin_start(0)
        self.top_overlay_box.set_margin_end(0)
        # Add header bar and banner to the top overlay box
        # (header bar is already overlaid, so only add banner here)

        # [[ BOTTOM BANNER (Adw.Banner) -- now at top after header bar ]]
        self.bottom_banner = Adw.Banner()
        self.bottom_banner.set_halign(Gtk.Align.FILL)
        self.bottom_banner.set_valign(Gtk.Align.END)
        self.bottom_banner.set_revealed(True)
        self.bottom_banner.set_margin_bottom(0)
        self.bottom_banner.set_margin_top(0)
        self.bottom_banner.set_css_classes(["big-banner-radius"])

        self.top_overlay_box.append(self.header_bar)
        self.top_overlay_box.append(self.bottom_banner)
        self.overlay.add_overlay(self.top_overlay_box)

        # [[ PENS ]]
        self.pens = [
            Pen("red ballpoint", color=(1, 0, 0, 1), width=2),
            Pen("white ballpoint", color=(1, 1, 1, 1), width=2),
            Pen("yellow highlighter", color=(1, 1, 0, 0.3), width=18, supports_incremental_drawing=False),
            CalligraphyPen(color=(0.1, 0.15, 0.4, 1), width=10, angle=45),
            PointerPen(color=(0, 1, 0, 1), width=16),
            Eraser(),
        ]
        self.pen_index = 0

        # [[ PEN SELECTOR (Bottom Left) ]]
        self.pen_selector_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.pen_selector_box.set_halign(Gtk.Align.START)
        self.pen_selector_box.set_valign(Gtk.Align.END)
        self.pen_selector_box.set_margin_start(24)
        self.pen_selector_box.set_margin_bottom(24)
        self.overlay.add_overlay(self.pen_selector_box)
        for i, pen in enumerate(self.pens):
            btn = Gtk.Button()
            btn.set_size_request(48, 48)
            btn.set_css_classes(["pen"])
            btn.set_tooltip_text(f"({i+1}) {pen.name}")
            btn.connect("clicked", self.on_pen_selected, i)

            # Draw selector icon
            drawing = Gtk.DrawingArea()
            drawing.set_draw_func(pen.draw_selector_icon)

            btn.set_child(drawing)
            self.pen_selector_box.append(btn)
        self.update_pen_selector()

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
        # Remove make_drawing_area_controller, use click gesture inline
        click_controller = Gtk.GestureClick.new()
        click_controller.connect("pressed", self.on_drawing_area_click)
        self.drawing_area.add_controller(click_controller)
        self.drawing_area.set_can_focus(True)
        self.drawing_area.set_focus_on_click(True)

        # [[ FRAME AROUND DRAWING AREA ]]
        self.frame = Gtk.Frame()
        self.frame.set_child(self.drawing_area)
        self.frame.set_halign(Gtk.Align.CENTER)
        self.frame.set_valign(Gtk.Align.CENTER)
        self.frame.set_css_classes(["drawing-frame"])  # Default class
        self.overlay.set_child(self.frame)

        # [[ STROKE MANAGER ]]
        self.stroke_manager = StrokeManager()
        self.strokes_surface = None
        self.surface_size = None

        self.set_drawing_mode(True)


        # Connect hamburger menu actions
        app = self.get_application()
        app.add_action(self.create_shortcuts_action())


    def create_shortcuts_action(self):
        action = Gio.SimpleAction.new("shortcuts", None)
        action.connect("activate", self.show_shortcuts_dialog)
        return action

    def show_shortcuts_dialog(self, action, param):
        help_text = (
            "<b>Keybindings &amp; Controls</b>\n\n"
            "• <b>P</b>: Cycle pen\n"
            "• <b>Click pen icon</b>: Select pen\n"
            "• <b>Ctrl+Z/Y</b>: Undo/Redo\n"
            "• <b>S</b>: Save\n"
            "• <b>Esc</b>: Normal mode\n"
            "• <b>Click drawing area</b>: Drawing mode\n"
            "• <b>Q</b>: Quit\n"
        )
        dialog = Gtk.Dialog(transient_for=self, modal=True)
        dialog.set_title("Keyboard Shortcuts")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        label = Gtk.Label(label=help_text)
        label.set_justify(Gtk.Justification.LEFT)
        box.append(label)
        # Add custom close button at the bottom
        close_btn = Gtk.Button(label="Close")
        close_btn.set_halign(Gtk.Align.END)
        close_btn.connect("clicked", lambda btn: dialog.close())
        box.append(close_btn)
        dialog.set_child(box)
        dialog.present()

    def on_drawing_area_click(self, controller, n_press, x, y):
        if not self.drawing_mode:
            self.set_drawing_mode(True)

    def set_drawing_mode(self, drawing: bool):
        self.drawing_mode = drawing
        if drawing:
            self.set_cursor(Gdk.Cursor.new_from_name("none"))
            self.frame.remove_css_class("drawing-frame-inactive")
            self.frame.add_css_class("drawing-frame-active")
            self.bottom_banner.set_title("🖱️ Mouse captured! Press Esc to exit.")
        else:
            self.set_cursor(Gdk.Cursor.new_from_name("default"))
            self.frame.remove_css_class("drawing-frame-active")
            self.frame.add_css_class("drawing-frame-inactive")
            self.bottom_banner.set_title("Click anywhere on the pad to start drawing ✏️")

        self.drawing_area.queue_draw()

    def update_pen_selector(self):
        # pass
        child = self.pen_selector_box.get_first_child()
        i = 0
        while child:
            if i == self.pen_index:
                child.set_css_classes(["pen-selected"])
            else:
                child.set_css_classes(["pen"])
            child = child.get_next_sibling()
            i += 1

    def on_pen_selected(self, btn, idx):
        self.pen_index = idx
        self.update_pen_selector()

    def on_open_clicked(self, btn):
        # TODO: implement open
        pass

    def on_save_clicked(self, btn=None):
        self.set_drawing_mode(False)  # Switch to normal mode when saving
        self.save_as_dialog()

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
        # self.set_child(self.frame)  # REMOVE this line, overlay is always the window child

        # Create the cache surface
        self.strokes_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        self.surface_size = Vec2(width, height)

    def handle_touchpad_event(self, data) -> None:
        if not self.drawing_mode:
            return
        
        # data: {slot: {x, y}}
        current_slots = set(self.stroke_manager.current_strokes.keys())
        new_slots = set(data.keys())

        # End strokes for slots that disappeared
        ended = current_slots - new_slots
        if ended:
            for slot in ended:
                self.stroke_manager.end_stroke(slot)

        if ended or self.stroke_manager.require_redraw:
            # Redraw cache surface only once after all ended strokes or stroke_manager.require_redraw
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
        
        # Glassy blur/dim effect when not in drawing mode
        if not self.drawing_mode:
            cr.set_source_rgba(0, 0, 0, 0.55)
            cr.rectangle(0, 0, width, height)
            cr.fill()

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
        self.update_pen_selector()

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
        dialog = Gtk.FileChooserDialog(
            title="Save Drawing",
            transient_for=self,
            modal=True,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Save", Gtk.ResponseType.ACCEPT
        )

        # Create filters
        svg_filter = Gtk.FileFilter()
        svg_filter.set_name("svg")
        svg_filter.add_mime_type("image/svg+xml")
        svg_filter.add_pattern("*.svg")
        dialog.add_filter(svg_filter)

        png_filter = Gtk.FileFilter()
        png_filter.set_name("png")
        png_filter.add_mime_type("image/png")
        png_filter.add_pattern("*.png")
        dialog.add_filter(png_filter)

        jpg_filter = Gtk.FileFilter()
        jpg_filter.set_name("jpg")
        jpg_filter.add_mime_type("image/jpeg")
        jpg_filter.add_pattern("*.jpg")
        jpg_filter.add_pattern("*.jpeg")
        dialog.add_filter(jpg_filter)

        # Suggest a default file name
        dialog.set_current_name("drawing.svg")

        dialog.connect("response", self.on_file_save_response)
        dialog.present()

    def on_file_save_response(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file:
                filename = file.get_path()

                # Determine filetype from selected filter
                selected_filter = dialog.get_filter()
                filetype = selected_filter.get_name() if selected_filter else "svg"

                self.export(filename, filetype)
        dialog.destroy()

    def on_key(self, controller, keyval: int, keycode: int, state: int) -> None:
        keyval_lower = chr(keyval).lower()
        is_control = bool(state & Gdk.ModifierType.CONTROL_MASK)

        match (is_control, keyval_lower, keyval):
            # Ctrl+Z/Y/S/Q
            case (True, 'z', _) :
                self.undo_last_stroke()
            case (True, 'y', _) :
                self.redo_last_stroke()
            case (True, 's', _) :
                self.on_save_clicked()
            case (True, 'q', _) :
                self.touchpad_reader.stop()
                self.get_application().quit()
            # Escape
            case (_, _, Gdk.KEY_Escape):
                self.set_drawing_mode(False)
            # Switch pens: 'p' or number keys
            case (_, 'p', _):
                self.cycle_pen_type()
            case (_, _, k) if Gdk.KEY_1 <= k < Gdk.KEY_1 + len(self.pens):
                self.pen_index = k - Gdk.KEY_1
                self.update_pen_selector()
            # Clear
            case (_, 'c', _):
                self.clear_drawing()
            # Help
            case (_, _, Gdk.KEY_F1) | (_, _, Gdk.KEY_question):
                self.show_shortcuts_dialog(None, None)
            case _:
                pass


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
            border-radius: 24px;
            border: 4px solid #888;
            background: #222;
            transition: border-color 0.2s, box-shadow 0.2s;
        }
        .drawing-frame-active {
            border-color: #00aaff;
            box-shadow: 0 0 16px 2px #00aaff44;
        }
        .drawing-frame-inactive {
            border-color: #888;
            box-shadow: none;
            opacity: 0.85;
        }
        .pen {
            border: 1px solid #888;
            margin: 2px;
            padding: 0px;
        }
        .pen-selected {
            border: 3px solid #00aaff;
            padding: 0px;
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
