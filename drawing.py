import cairo

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
        self.header_bar = Gtk.HeaderBar(
            title_widget=Gtk.Label(label="Absolute Touchpad"),
            show_title_buttons=False,
            halign=Gtk.Align.FILL,
            valign=Gtk.Align.START
        )

        # Only Save button (top left, with text)
        save_btn = Gtk.Button(label="Save")  # Removed icon_name=None to avoid Gtk-CRITICAL
        save_btn.connect("clicked", self.on_save_clicked)
        self.header_bar.pack_start(save_btn)

        # Custom close button (top right)
        close_btn = Gtk.Button(
            icon_name="window-close-symbolic",
            tooltip_text="Quit"
        )
        close_btn.connect("clicked", lambda _: self.get_application().quit())
        self.header_bar.pack_end(close_btn)

        # Hamburger menu
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu.append("About", "app.about")
        menu_btn.set_menu_model(menu)
        self.header_bar.pack_end(menu_btn)

        # Connect hamburger menu actions
        def _add_menu_action(name, callback):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.get_application().add_action(action)
        _add_menu_action("about", self.show_about_dialog)
        _add_menu_action("shortcuts", self.show_shortcuts_window)
        _add_menu_action("preferences", lambda a, p: None)  # Placeholder


        # [[ TOP OVERLAY: header_bar + banner ]]
        self.top_overlay_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            valign=Gtk.Align.START
        )


        # [[ TOP BANNER ]]
        self.banner = Adw.Banner(
            halign=Gtk.Align.FILL,
            valign=Gtk.Align.END,
            revealed=True,
            css_classes=["big-banner-radius"]
        )

        self.top_overlay_box.append(self.header_bar)
        self.top_overlay_box.append(self.banner)
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
        self.pen_selector_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            halign=Gtk.Align.START,
            valign=Gtk.Align.END,
            margin_start=24,
            margin_bottom=24,
            spacing=8,
        )
        self.overlay.add_overlay(self.pen_selector_box)
        # TODO: add it to a diff function, cuz we will need to update later
        for i, pen in enumerate(self.pens):
            btn = Gtk.Button(
                width_request=48,
                height_request=48,
                css_classes=["pen"],
                tooltip_text=f"({i+1}) {pen.name}",
            )
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
        self.drawing_area = Gtk.DrawingArea(
            can_focus=True,
            focus_on_click=True
        )
        # Remove make_drawing_area_controller, use click gesture inline
        click_controller = Gtk.GestureClick.new()
        def on_drawing_area_click(controller, n_press, x, y):
            self.set_drawing_mode(True)
        click_controller.connect("pressed", on_drawing_area_click)
        self.drawing_area.add_controller(click_controller)


        # [[ FRAME AROUND DRAWING AREA ]]
        self.frame = Gtk.Frame(
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            css_classes=["drawing-frame"]
        )
        self.frame.set_child(self.drawing_area)
        self.overlay.set_child(self.frame)


        # [[ DRAWING MODE ]]
        self.drawing_mode = None
        self.set_drawing_mode(False)


        # [[ STROKE MANAGER ]]
        self.stroke_manager = StrokeManager()
        self.strokes_surface = None
        self.surface_size = None


    def set_drawing_mode(self, drawing: bool):
        if self.drawing_mode == drawing:
            return
        
        self.drawing_mode = drawing
        if drawing:
            self.set_cursor(Gdk.Cursor.new_from_name("none"))
            self.frame.set_css_classes(["drawing-frame", "drawing-frame-active"])
            self.banner.set_title("🖱️ Mouse captured! Press Esc to exit.")
        else:
            self.set_cursor(Gdk.Cursor.new_from_name("default"))
            self.frame.set_css_classes(["drawing-frame", "drawing-frame-inactive"])
            self.banner.set_title("Click anywhere on the pad to start drawing ✏️")

        self.drawing_area.queue_draw()

    def update_pen_selector(self):
        for i, child in enumerate(self.pen_selector_box):
            if i == self.pen_index:
                child.set_css_classes(["pen-selected"])
            else:
                child.set_css_classes(["pen"])

    def on_pen_selected(self, btn, idx):
        self.pen_index = idx
        self.update_pen_selector()

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
        if filetype == "svg":
            surface = cairo.SVGSurface(filename, *self.surface_size)
            self.stroke_manager.draw(surface)
            surface.finish()
        elif filetype == "png":
            scale = 4
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *(self.surface_size * scale))
            self.stroke_manager.draw(surface, scale=scale)
            surface.write_to_png(filename)
        else:
            raise ValueError("Unsupported filetype")

    def on_save_clicked(self, btn=None) -> None:
        self.set_drawing_mode(False)  # Switch to normal mode when saving

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
        svg_filter = Gtk.FileFilter(
            name="svg",
            mime_types=["image/svg+xml"],
            patterns=["*.svg"]
        )
        dialog.add_filter(svg_filter)

        png_filter = Gtk.FileFilter(
            name="png",
            mime_types=["image/png"],
            patterns=["*.png"]
        )
        dialog.add_filter(png_filter)

        # Suggest a default file name
        dialog.set_current_name("drawing")

        def on_file_save_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file:
                    filename = file.get_path()

                    # Determine filetype from selected filter
                    selected_filter = dialog.get_filter()
                    filetype = selected_filter.get_name() if selected_filter else "svg"

                    self.export(filename, filetype)
            dialog.destroy()
        
        dialog.connect("response", on_file_save_response)
        dialog.present()

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
            case (_, _, k) if Gdk.KEY_1 <= k < Gdk.KEY_1 + max(len(self.pens), 9):
                self.pen_index = k - Gdk.KEY_1
                self.update_pen_selector()
            # Clear
            case (_, 'c', _):
                self.clear_drawing()
            # Help
            case (_, _, Gdk.KEY_F1) | (_, _, Gdk.KEY_question):
                self.show_shortcuts_window(None, None)
            case _:
                pass

    def show_about_dialog(self, action=None, param=None):
        about = Adw.AboutDialog(
            application_name="Absolute Touchpad", # TODO: need to figure out name as well
            version="1.0.0", # TODO: what version shall I put
            developer_name="Zyad Yasser",
            copyright="© 2025 Your Name",
            website="https://github.com/your-repo",
            issue_url="https://github.com/your-repo/issues",
            comments="A fullscreen drawing app for touchpads."
        )
        about.present()

    def show_shortcuts_window(self, action=None, param=None):
        shortcuts = Gtk.ShortcutsWindow()

        section = Gtk.ShortcutsSection(section_name="shortcuts")

        # General group
        group_general = Gtk.ShortcutsGroup(title="General")
        group_general.add_shortcut(Gtk.ShortcutsShortcut(title="Normal mode", accelerator="Escape"))
        group_general.add_shortcut(Gtk.ShortcutsShortcut(title="Shortcuts", accelerator="F1 question"))
        group_general.add_shortcut(Gtk.ShortcutsShortcut(title="Quit", accelerator="<Ctrl>Q"))
        section.add_group(group_general)

        # File group
        group_file = Gtk.ShortcutsGroup(title="File")
        group_file.add_shortcut(Gtk.ShortcutsShortcut(title="Save", accelerator="<Ctrl>S"))
        section.add_group(group_file)

        # Pens group
        group_pens = Gtk.ShortcutsGroup(title="Pens")
        group_pens.add_shortcut(Gtk.ShortcutsShortcut(title="Cycle pen", accelerator="P"))
        group_pens.add_shortcut(Gtk.ShortcutsShortcut(title="Select pen", accelerator="1+2..."))
        section.add_group(group_pens)

        # Editing group
        group_edit = Gtk.ShortcutsGroup(title="Editing")
        group_edit.add_shortcut(Gtk.ShortcutsShortcut(title="Undo", accelerator="<Ctrl>Z"))
        group_edit.add_shortcut(Gtk.ShortcutsShortcut(title="Redo", accelerator="<Ctrl>Y"))
        group_edit.add_shortcut(Gtk.ShortcutsShortcut(title="Clear drawing", accelerator="C"))
        section.add_group(group_edit)

        shortcuts.add_section(section)
        shortcuts.present()
        

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
