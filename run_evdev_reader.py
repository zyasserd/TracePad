# run_evdev_reader.py
import sys
import json
import time
import os
import psutil
from multitouch_reader import find_touchpad, get_max_xy, touchpad_positions_generator

# Function to check if the parent process is still alive
def is_parent_alive(parent_pid):
    try:
        p = psutil.Process(parent_pid)
        return p.is_running() and p.pid == parent_pid
    except psutil.NoSuchProcess:
        return False
    except Exception as e:
        sys.stderr.write(f"Error checking parent process: {e}\n")
        return False

if __name__ == '__main__':
    parent_pid = os.getppid()

    device_path = find_touchpad()
    if not device_path:
        print(json.dumps({"error": "Touchpad not found or accessible."}), flush=True)
        sys.exit(1)

    try:
        max_x, max_y = get_max_xy(device_path)
        print(json.dumps({"type": "dimensions", "max_x": max_x, "max_y": max_y}), flush=True)

        for fingers in touchpad_positions_generator(device_path):
            if not is_parent_alive(parent_pid):
                print(json.dumps({"info": "Parent process died, exiting gracefully."}), flush=True)
                break

            # Send each frame of finger data as a JSON string
            print(json.dumps({"type": "fingers", "data": fingers}), flush=True)
            
            # --- REMOVED: time.sleep(0.01) ---
            # This sleep was the primary cause of the lag.
            # evdev's read_loop is already blocking, so it naturally
            # waits for events. Adding an artificial sleep here
            # delays every single event transmission.

    except Exception as e:
        print(json.dumps({"error": f"Evdev reader encountered an error: {e}"}), flush=True)
        sys.exit(1)
    finally:
        print(json.dumps({"info": "Evdev reader process finished."}), flush=True)
        sys.stdout.flush()