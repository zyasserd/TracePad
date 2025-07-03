from evdev import InputDevice, list_devices, ecodes
from typing import Optional, Tuple
from collections import defaultdict


def find_touchpad() -> Optional[str]:
    for path in list_devices():
        try:
            dev = InputDevice(path)
            caps = dev.capabilities()

            # Check for multitouch position axes
            abs_caps = caps.get(ecodes.EV_ABS, [])
            abs_codes = set(code for code, _ in abs_caps)

            has_mt = ecodes.ABS_MT_POSITION_X in abs_codes and ecodes.ABS_MT_POSITION_Y in abs_codes
            has_xy = ecodes.ABS_X in abs_codes and ecodes.ABS_Y in abs_codes

            # Heuristic: likely touchpad
            if has_xy and has_mt:
                if "touchpad" in dev.name.lower() or "trackpad" in dev.name.lower():
                    # print(f"Found touchpad: {dev.name} at {path}")
                    return path
                # Some devices may not follow naming conventions
                # Still return if multitouch is supported
                # print(f"Found likely touchpad: {dev.name} at {path}")
                return path

        except Exception as e:
            continue

    # print("Touchpad not found.")
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
    dev_path = find_touchpad()
    print(get_max_xy(dev_path))
    for v in touchpad_positions_generator(dev_path):
        print(v)
