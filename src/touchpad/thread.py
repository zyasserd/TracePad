import os
import sys
import json
import threading
import subprocess
import shutil
from typing import Optional, Callable, Any, Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import GLib

from vec2 import Vec2



PKEXEC_EXIT_CODE_MESSAGES = {
    126: "pkexec: Authorization could not be obtained because the user dismissed the authentication dialog.",
    127: "pkexec: Not authorized or authentication failed, or an error occurred.",
}


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
        # check pkexec available
        if not shutil.which("pkexec"):
            GLib.idle_add(self.on_error, "pkexec is not installed or not found in PATH. Please install pkexec to continue.")
            return

        # TODO: pkg_resources.resource_filename('fingerpaint', 'data/fix_permissions.sh')
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'reader.py'))
        python_exe = os.environ.get("PYTHON_NIX", sys.executable)

        self.reader_process = subprocess.Popen([
            'pkexec', python_exe, script_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

    def _handle_pkexec_exit_code(self):
        if not self.reader_process:
            return False
        
        exit_code = self.reader_process.poll()
        if exit_code not in PKEXEC_EXIT_CODE_MESSAGES:
            return False
        
        GLib.idle_add(
            self.on_error,
            PKEXEC_EXIT_CODE_MESSAGES[exit_code]
        )
        if self.reader_process.stdout:
            self.reader_process.stdout.close()
        return True
        
    def _read_output(self) -> None:
        if not self.reader_process or not self.reader_process.stdout:
            return
        
        error_to_report = None

        for line in self.reader_process.stdout:
            if self._should_stop.is_set():
                break
                
            line = line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except Exception:
                error_to_report = f"Invalid JSON: {line}" + "\n".join(self.reader_process.stdout.readlines())
                break

            if 'error' in event:
                error_code = event.get('error', 'Error')
                error_msg = event.get('message', '')
                error_to_report = f"{error_code}: {error_msg}"
                break
            elif event.get('event') == 'device_info':
                data = event.get('data', {})
                self.max = Vec2(data.get('max_x'), data.get('max_y'))
                if self.on_device_init:
                    GLib.idle_add(self.on_device_init)
            elif event.get('event') == 'touch_update':
                GLib.idle_add(self.on_event, event['data'])
            

        if self.reader_process.stdout:
            self.reader_process.stdout.close()
        
        # After reading loop, check for pkexec exit code, and those take priority
        if not self._handle_pkexec_exit_code() and error_to_report:
            self._report_error(error_to_report)

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

