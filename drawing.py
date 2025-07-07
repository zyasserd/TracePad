import cairo
import copy

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
        self.header_bar.pack_end(menu_btn)
        
        # Connect hamburger menu actions
        def _add_menu_action(name, detailed_action, callback, accels):
            menu.append(name, detailed_action)
            action = Gio.SimpleAction.new(detailed_action.split('.')[1].lower(), None)
            action.connect("activate", callback)
            self.get_application().add_action(action)
            self.get_application().set_accels_for_action(detailed_action, accels)
        
        menu = Gio.Menu()
        _add_menu_action("Preferences", "app.preferences", self.show_preferences_dialog, ["<Ctrl>comma"])
        _add_menu_action("Keyboard Shortcuts", "app.shortcuts", self.show_shortcuts_window, ["F1", "question"])
        _add_menu_action("About", "app.about", self.show_about_dialog, [])
        menu_btn.set_menu_model(menu)



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
        self.recreate_pen_selector()


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
        keyval_lower = chr(keyval).lower() if 0 <= keyval <= 0x10FFFF else None
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
            case _:
                pass

    def show_about_dialog(self, action=None, param=None):
        about = Adw.AboutDialog(
            application_name="TracePad",
            version="1.0.0-beta",
            developer_name="Zyad Yasser",
            copyright="© 2025 Your Name",
            website="https://github.com/your-repo",
            issue_url="https://github.com/your-repo/issues",
            comments="A simple way to draw, doodle, and sign with your touchpad!\n\nThis app turns your laptop's touchpad into an easy-to-use digital canvas. Quickly sketch, jot notes, or capture your signature with just a few clicks. The clean fullscreen interface and straightforward pen tools make it perfect for anyone who wants a fast, no-fuss way to get creative or sign documents using their touchpad."
        )
        about.present()

    def show_shortcuts_window(self, action=None, param=None):
        shortcuts = Gtk.ShortcutsWindow()

        section = Gtk.ShortcutsSection(section_name="shortcuts")

        # General group
        group_general = Gtk.ShortcutsGroup(title="General")
        group_general.add_shortcut(Gtk.ShortcutsShortcut(title="Normal mode", accelerator="Escape"))
        group_general.add_shortcut(Gtk.ShortcutsShortcut(title="Shortcuts", accelerator="F1 question"))
        group_general.add_shortcut(Gtk.ShortcutsShortcut(title="Preferences", accelerator="<Ctrl>comma"))
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
    
    def show_preferences_dialog(self, action=None, param=None):
        dialog = Gtk.Dialog(
            title="Edit Pens",
            transient_for=self,
            modal=True,
            use_header_bar=True,
            resizable=False
        )

        # Use set_child instead of deprecated get_content_area
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
        dialog.set_child(box)

        # Pens List with Scrollbar
        pens_list_scroller = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            width_request=160
        )
        pens_list_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        box.append(pens_list_scroller)

        # Pens List
        pens_list = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.SINGLE
        )
        pens_list_scroller.set_child(pens_list)

        # Pen Properties
        prop_grid = Gtk.Grid(row_spacing=8, column_spacing=8, margin_start=16)
        box.append(prop_grid)

        # Pen type mapping, TODO:
        pen_type_names = ["Pen", "CalligraphyPen", "PointerPen", "Eraser"]
        pen_type_labels = ["Ballpoint", "Calligraphy", "Pointer", "Eraser"]

        # Property widgets
        name_entry = Gtk.Entry()
        width_adjustment = Gtk.Adjustment(value=1, lower=1, upper=64, step_increment=1, page_increment=4, page_size=0)
        width_spin = Gtk.SpinButton(adjustment=width_adjustment)
        type_combo = Gtk.ComboBoxText()
        for t_name, label in zip(pen_type_names, pen_type_labels):
            type_combo.append(t_name, label)

        # Add Delete and Add Pen buttons side by side
        add_btn = Gtk.Button(label="+ Add Pen")
        delete_btn = Gtk.Button(label="Delete Pen")
        delete_btn.set_css_classes(["destructive-action"])
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.append(delete_btn)
        btn_box.append(add_btn)

        # Color display and color dialog in a horizontal box
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        color_canvas = Gtk.DrawingArea(
            width_request=32,
            height_request=32
        )
        color_box.append(color_canvas)
        color_dialog_btn = Gtk.Button(label="Select Color")
        color_box.append(color_dialog_btn)

        # Add to grid
        prop_grid.attach(Gtk.Label(label="Name:"), 0, 0, 1, 1)
        prop_grid.attach(name_entry, 1, 0, 1, 1)
        prop_grid.attach(Gtk.Label(label="Color:"), 0, 1, 1, 1)
        prop_grid.attach(color_box, 1, 1, 1, 1)
        prop_grid.attach(Gtk.Label(label="Width:"), 0, 2, 1, 1)
        prop_grid.attach(width_spin, 1, 2, 1, 1)
        prop_grid.attach(Gtk.Label(label="Type:"), 0, 3, 1, 1)
        prop_grid.attach(type_combo, 1, 3, 1, 1)
        prop_grid.attach(btn_box, 1, 4, 1, 1)



        # copy of pens
        edited_pens = copy.deepcopy(self.pens)
        selected_pen_idx = [self.pen_index]


        # Color dialog logic
        def on_color_dialog_clicked(btn):
            pen = edited_pens[selected_pen_idx[0]]
            dialog = Gtk.ColorDialog()
            def on_color_chosen(dialog, result):
                try:
                    color = dialog.choose_rgba_finish(result)
                except GLib.GError:
                    return  # User dismissed dialog, ignore
                if color:
                    pen.color = (color.red, color.green, color.blue, color.alpha)
                    color_canvas.queue_draw()
            dialog.choose_rgba(self, Gdk.RGBA(*pen.color), None, on_color_chosen)
        color_dialog_btn.connect("clicked", on_color_dialog_clicked)


        # The color to display is tracked in a closure
        def draw_color_canvas(area, cr, width, height):
            cr.set_source_rgba(*edited_pens[selected_pen_idx[0]].color)
            cr.rectangle(0, 0, width, height)
            cr.fill()
        color_canvas.set_draw_func(draw_color_canvas)


        # Populate pens list
        for pen in edited_pens:
            pens_list.append(Gtk.ListBoxRow(
                selectable=True,
                child=Gtk.Label(label=pen.name)
            ))
        pens_list.select_row(pens_list.get_row_at_index(selected_pen_idx[0]))


        def on_pen_selected(listbox, row):
            if not row:
                return
            selected_pen_idx[0] = row.get_index()
            update_properties()
        pens_list.connect("row-selected", on_pen_selected)

        # Helper to update property widgets
        def update_properties():
            pen = edited_pens[selected_pen_idx[0]]

            # Block signals to avoid triggering on_prop_changed
            name_entry.handler_block_by_func(on_prop_changed)
            width_spin.handler_block_by_func(on_prop_changed)
            type_combo.handler_block_by_func(on_prop_changed)

            name_entry.set_text(pen.name)
            color_canvas.queue_draw()
            width_spin.set_value(pen.width)
            type_combo.set_active_id(type(pen).__name__)

            # Unblock signals after setting values
            name_entry.handler_unblock_by_func(on_prop_changed)
            width_spin.handler_unblock_by_func(on_prop_changed)
            type_combo.handler_unblock_by_func(on_prop_changed)

        # Update pen on property change
        def on_prop_changed(*args):
            idx = selected_pen_idx[0]
            pen = edited_pens[idx]


            t_id = type_combo.get_active_id()
            if not t_id:
                return
            
            pen.name = name_entry.get_text()
            pen.width = width_spin.get_value()
            # Color is already handled separately

            if type(pen).__name__ != t_id:
                if t_id == "Pen":
                    new_pen = Pen(pen.name, color=pen.color, width=pen.width)
                elif t_id == "CalligraphyPen":
                    # TODO: (LATER) make angle editable
                    new_pen = CalligraphyPen(color=pen.color, width=pen.width, angle=45)
                    new_pen.pen = pen.name
                elif t_id == "PointerPen":
                    new_pen = PointerPen(color=pen.color, width=pen.width)
                    new_pen.pen = pen.name
                elif t_id == "Eraser":
                    new_pen = Eraser()
                    new_pen.name = pen.name
                else:
                    raise RuntimeError("Unknown pen type selected in preferences dialog")
                edited_pens[idx] = new_pen
            # Update list label
            pens_list.get_row_at_index(idx).get_child().set_label(edited_pens[idx].name)
        name_entry.connect("changed", on_prop_changed)
        width_spin.connect("value-changed", on_prop_changed)
        type_combo.connect("changed", on_prop_changed)

        # Delete pen
        def on_delete_clicked(btn):
            idx = selected_pen_idx[0]
            if len(edited_pens) > 1:
                edited_pens.pop(idx)
                pens_list.remove(pens_list.get_row_at_index(idx))
                if idx > 0:
                    pens_list.select_row(pens_list.get_row_at_index(idx-1))
                else:
                    pens_list.select_row(pens_list.get_row_at_index(0))
        delete_btn.connect("clicked", on_delete_clicked)

        # Add pen
        def on_add_clicked(btn):
            new_pen = Pen("New Pen", color=(1,1,1,1), width=2)
            edited_pens.append(new_pen)
            row = Gtk.ListBoxRow()
            row.pen_index = len(edited_pens)-1
            row.set_child(Gtk.Label(label=new_pen.name))
            pens_list.append(row)
            pens_list.select_row(row)
        add_btn.connect("clicked", on_add_clicked)

        # Save/Cancel
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)

        def on_response(dlg, resp):
            if resp == Gtk.ResponseType.OK:
                # Save changes: copy edited_pens to self.pens
                self.pens = copy.deepcopy(edited_pens)
                self.recreate_pen_selector()
            dlg.destroy()
        dialog.connect("response", on_response)

        # Initialize property widgets
        update_properties()
        dialog.present()

    def recreate_pen_selector(self):
        # Remove all children from pen_selector_box
        for child in list(self.pen_selector_box):
            self.pen_selector_box.remove(child)
        # Recreate pen selector buttons
        for i, pen in enumerate(self.pens):
            btn = Gtk.Button(
                width_request=48,
                height_request=48,
                css_classes=["pen"],
                tooltip_text=f"({i+1}) {pen.name}",
            )
            btn.connect("clicked", self.on_pen_selected, i)
            drawing = Gtk.DrawingArea()
            drawing.set_draw_func(pen.draw_selector_icon)
            btn.set_child(drawing)
            self.pen_selector_box.append(btn)
        self.update_pen_selector()

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
