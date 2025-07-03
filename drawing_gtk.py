# drawing_gtk.py
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib, Gio
import os
import subprocess
import json
import threading
import time

# --- Evdev Reader Thread ---
class EvdevReaderThread(threading.Thread):
    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback
        self.process = None
        self._running = True

    def run(self):
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_evdev_reader.py")

        try:
            self.process = subprocess.Popen(
                ["pkexec", "python3", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            print(f"Started pkexec process: PID {self.process.pid}")

            for line in self.process.stdout:
                if not self._running:
                    break
                try:
                    data = json.loads(line)
                    GLib.idle_add(self.callback, data)
                    
                    if data.get("info") and "exiting" in data["info"].lower():
                        print("Evdev reader signaled its own exit.")
                        self._running = False
                        break
                except json.JSONDecodeError as e:
                    print(f"JSON Decode Error: {e} - Line: {line.strip()}")
                    GLib.idle_add(self.callback, {"error": f"JSON decode error from evdev reader: {e}, line: {line.strip()}"})
                except Exception as e:
                    print(f"Error processing evdev data line: {e} - Line: {line.strip()}")
                    GLib.idle_add(self.callback, {"error": f"Error processing evdev data: {e}"})

            stderr_output = self.process.stderr.read()
            if stderr_output:
                print(f"pkexec stderr: {stderr_output.strip()}")
                GLib.idle_add(self.callback, {"error": f"Reader process ended with error: {stderr_output.strip()}"})

        except FileNotFoundError:
            GLib.idle_add(self.callback, {"error": "pkexec command not found. Is PolicyKit installed?"})
        except subprocess.CalledProcessError as e:
            GLib.idle_add(self.callback, {"error": f"pkexec failed: {e.stderr}"})
        except Exception as e:
            GLib.idle_add(self.callback, {"error": f"Failed to start evdev reader: {e}"})
        finally:
            if self.process:
                self.process.wait(timeout=1)
                if self.process.poll() is None:
                    print(f"Warning: pkexec process {self.process.pid} did not exit gracefully. It might be orphaned.")
            print("EvdevReaderThread finished its run method.")

    def stop(self):
        self._running = False
        print("EvdevReaderThread stop method called.")


class MultitouchDataViewerApp(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(application_id="org.example.MultitouchDataViewer", **kwargs)
        self.evdev_reader_thread = None
        self.x_label = None # New: Label for X coordinate
        self.y_label = None # New: Label for Y coordinate
        self.open_dialog = None

    def do_activate(self):
        self.win = Adw.ApplicationWindow(application=self)
        self.win.set_default_size(600, 400)
        self.win.set_title("Multitouch Data Viewer")

        # Create an AdwHeaderBar
        header_bar = Adw.HeaderBar()
        self.status_label = Gtk.Label(label="Waiting for touchpad data...")
        header_bar.set_title_widget(self.status_label)

        # --- Add Open Button with Icon ---
        self.open_button = Gtk.Button(label="Open")
        self.open_button.set_icon_name("document-open-symbolic")
        self.open_button.set_tooltip_text("Open (Functionality not fully implemented)")
        self.open_button.connect("clicked", self.show_open_dialog)
        header_bar.pack_start(self.open_button)

        # --- Setup Gtk.FileDialog ---
        self.open_dialog = Gtk.FileDialog.new()
        self.open_dialog.set_title("Select a File")
        f = Gtk.FileFilter()
        f.set_name("Image files")
        f.add_mime_type("image/jpeg")
        f.add_mime_type("image/png")
        f.add_pattern("*.jpg")
        f.add_pattern("*.jpeg")
        f.add_pattern("*.png")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        self.open_dialog.set_filters(filters)
        self.open_dialog.set_default_filter(f)

        # --- Add Menu Button with PopoverMenu and Action ---
        action = Gio.SimpleAction.new("something", None)
        action.connect("activate", self.print_something)
        self.win.add_action(action)
        menu = Gio.Menu.new()
        menu.append("Do Something", "win.something")
        self.popover = Gtk.PopoverMenu()
        self.popover.set_menu_model(menu)
        self.hamburger = Gtk.MenuButton()
        self.hamburger.set_popover(self.popover)
        self.hamburger.set_icon_name("open-menu-symbolic")
        self.hamburger.set_tooltip_text("Menu Button")
        header_bar.pack_end(self.hamburger)


        # Create an AdwToolbarView to hold header bar and content
        toolbar_view = Adw.ToolbarView.new()
        toolbar_view.add_top_bar(header_bar)

        # --- New: Labels for X and Y coordinates ---
        self.x_label = Gtk.Label(label="X: N/A")
        self.x_label.set_halign(Gtk.Align.CENTER) # Center horizontally
        self.x_label.set_vexpand(True) # Take vertical space

        self.y_label = Gtk.Label(label="Y: N/A")
        self.y_label.set_halign(Gtk.Align.CENTER)
        self.y_label.set_vexpand(True)

        # Use a Gtk.Box to arrange the labels vertically
        main_content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_content_box.set_halign(Gtk.Align.CENTER)
        main_content_box.set_valign(Gtk.Align.CENTER)
        main_content_box.append(self.x_label)
        main_content_box.append(self.y_label)
        main_content_box.set_margin_top(20)
        main_content_box.set_margin_bottom(20)
        main_content_box.set_margin_start(20)
        main_content_box.set_margin_end(20)

        # Set the main_content_box as the content of the AdwToolbarView
        toolbar_view.set_content(main_content_box)

        # Set the AdwToolbarView as the main content of the AdwApplicationWindow
        self.win.set_content(toolbar_view)
        
        # Start the evdev reader thread
        self.evdev_reader_thread = EvdevReaderThread(self.on_evdev_data_received)
        self.evdev_reader_thread.start()
        
        self.win.present()

    def do_shutdown(self):
        if self.evdev_reader_thread:
            self.evdev_reader_thread.stop()
            self.evdev_reader_thread.join(timeout=2) 
        super().do_shutdown()

    def on_evdev_data_received(self, data):
        """Callback from evdev reader thread, runs on main GTK thread."""
        
        if data.get("error"):
            print(f"ERROR: {data['error']}") # Print to console
            self.status_label.set_label("Error: See Console") # Update header status label
            self.show_error_dialog("Evdev Reader Error", data['error'])
            # Reset X/Y labels on error
            self.x_label.set_label("X: N/A")
            self.y_label.set_label("Y: N/A")
        elif data.get("info"):
            print(f"INFO: {data['info']}") # Print to console
            # No change to X/Y labels for info messages
        elif data.get("type") == "dimensions":
            # This is received once at the start
            max_x = data["max_x"]
            max_y = data["max_y"]
            self.status_label.set_label(f"Touchpad: {max_x}x{max_y} (Ready)")
            print(f"Received touchpad dimensions: Max X={max_x}, Max Y={max_y}")
        elif data.get("type") == "fingers":
            fingers = data["data"]
            if fingers:
                # For simplicity, display the first detected finger's coordinates
                # The keys in `fingers` are slots, values are dicts {x, y, id}
                first_slot = list(fingers.keys())[0]
                first_finger = fingers[first_slot]
                
                x = first_finger.get('x', 'N/A')
                y = first_finger.get('y', 'N/A')
                
                self.x_label.set_label(f"X: {x}")
                self.y_label.set_label(f"Y: {y}")
                self.status_label.set_label("Tracking...")
            else:
                # No fingers detected
                self.x_label.set_label("X: N/A")
                self.y_label.set_label("Y: N/A")
                self.status_label.set_label("No touch detected")
        else:
            # Handle unknown data types if necessary
            print(f"Unknown data type received: {data}")


    def show_error_dialog(self, title, message):
        dialog = Adw.MessageDialog.new(self.win, title, message)
        dialog.add_response("ok", "OK")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.show()

    def show_open_dialog(self, button):
        self.open_dialog.open(self.win, None, self.open_dialog_open_callback)
        
    def open_dialog_open_callback(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file is not None:
                print(f"File path is {file.get_path()}")
                # You'd typically load the file content here
                self.status_label.set_label(f"Opened: {os.path.basename(file.get_path())}")
            else:
                self.status_label.set_label("File dialog cancelled.")
        except GLib.Error as error:
            print(f"Error opening file: {error.message}")
            self.status_label.set_label(f"Open Error: {error.message[:30]}...")

    def print_something(self, action, param):
        print("Something!")
        self.status_label.set_label("Menu 'Something' triggered!")


# Main execution
if __name__ == "__main__":
    import sys
    app = MultitouchDataViewerApp()
    app.run(sys.argv)