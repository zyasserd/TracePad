import os
import sys
import json
import threading
import subprocess
from typing import Optional, Callable, Any

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import GLib

from vec2 import Vec2

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
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'reader.py'))
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
        # TODO: (LATER) understand how the multithreading work here; then review this function
        self._should_stop.set()
        if self.reader_process and self.reader_process.poll() is None:
            try:
                self.reader_process.terminate()
            except Exception:
                pass

    @property
    def dimensions(self) -> Optional[Vec2]:
        return self.max

