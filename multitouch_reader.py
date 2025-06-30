from evdev import InputDevice, list_devices, categorize, ecodes
from typing import Optional, Tuple
from collections import defaultdict


def find_touchpad() -> Optional[str]:
    # TODO: fix
    """Find a device that supports ABS_X and ABS_Y (likely a touchpad)."""
    for path in list_devices():
        dev = InputDevice(path)
        caps = dev.capabilities()
        if ecodes.EV_ABS in caps:
            abs_codes = [ecodes.ABS[code] for code, _ in caps[ecodes.EV_ABS]]
            if 'ABS_X' in abs_codes and 'ABS_Y' in abs_codes:
                print(f"Found touchpad: {dev.name} at {path}")
                return path
    print("Touchpad not found.")
    return None


def get_max_xy(device_path: str) -> Tuple[int, int]:
    """Get the max values for ABS_X and ABS_Y from a device."""
    dev = InputDevice(device_path)
    caps = dev.capabilities().get(ecodes.EV_ABS, [])
    caps_dict = dict(caps)

    # for code, absinfo in caps:
    #     name = ecodes.ABS.get(code, f'UNKNOWN({code})')
    #     print(f"{name:<20} {absinfo}")

    return (
        caps_dict.get(ecodes.ABS_X).max,
        caps_dict.get(ecodes.ABS_Y).max
    )


def touchpad_positions_generator(device_path: str):
    """Reads multitouch data (ABS_MT_*) grouped by SYN_REPORT frames."""
    dev = InputDevice(device_path)

    frame_data = defaultdict(dict)
    current_slot = 0

    for event in dev.read_loop():
        if event.type == ecodes.EV_ABS:
            if event.code == ecodes.ABS_MT_SLOT:
                current_slot = event.value
            elif event.code == ecodes.ABS_MT_TRACKING_ID:
                if event.value == -1:
                    frame_data.pop(current_slot, None)
                else:
                    frame_data[current_slot]['id'] = event.value
            elif event.code == ecodes.ABS_MT_POSITION_X:
                frame_data[current_slot]['x'] = event.value
            elif event.code == ecodes.ABS_MT_POSITION_Y:
                frame_data[current_slot]['y'] = event.value

        elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
            # Yield a copy of positions to avoid mutation issues
            fingers = {slot: data.copy() for slot, data in frame_data.items() if 'x' in data and 'y' in data}
            yield fingers


# 🧪 Run all steps
if __name__ == '__main__':
    path = '/dev/input/event6'  # update accordingly
    max_x, max_y = get_max_xy(path)
