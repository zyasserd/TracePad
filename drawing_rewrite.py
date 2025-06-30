import pygame
import threading
import time
import sys

from multitouch_reader import touchpad_positions_generator, get_max_xy

# === CONFIGURATION ===
DEVICE_PATH = '/dev/input/event6'
PAD_COLOR = (0, 0, 0)          # Black rectangle for touchpad representation
DRAW_COLOR = (0, 0, 255)       # Blue for drawing trails
CIRCLE_COLOR = (255, 0, 0)     # Red finger circle
PEN_SIZE = 5
PAD_SCREEN_COVERAGE_RATIO = 0.5
FPS = 60

# === INIT TOUCHPAD BOUNDS ===
max_x, max_y = get_max_xy(DEVICE_PATH)
if max_x is None or max_y is None:
    print(f"Error: Could not get touchpad dimensions from {DEVICE_PATH}.")
    sys.exit(1)

# === FINGER STATE ===
finger_positions = {}
finger_trails = {}  # Maps slot to list of past positions

# === INIT PYGAME ===
pygame.init()
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
pygame.display.set_caption("Multitouch Finger Tracker with Drawing")
clock = pygame.time.Clock()
screen_width, screen_height = screen.get_size()

# === CALCULATE TOUCHPAD RECTANGLE ===
touchpad_aspect = max_x / max_y
screen_aspect = screen_width / screen_height

if touchpad_aspect > screen_aspect:
    pad_width = screen_width * PAD_SCREEN_COVERAGE_RATIO
    pad_height = pad_width / touchpad_aspect
else:
    pad_height = screen_height * PAD_SCREEN_COVERAGE_RATIO
    pad_width = pad_height * touchpad_aspect

pad_rect = pygame.Rect(
    (screen_width - pad_width) // 2,
    (screen_height - pad_height) // 2,
    pad_width,
    pad_height
)

# === MULTITOUCH READER THREAD ===
def finger_reader():
    global finger_positions
    for fingers in touchpad_positions_generator(DEVICE_PATH):
        finger_positions = fingers.copy()

reader_thread = threading.Thread(target=finger_reader, daemon=True)
reader_thread.start()

# === MAIN LOOP ===
running = True
while running:
    screen.fill((255, 255, 255))  # White background

    # Draw the touchpad rectangle
    pygame.draw.rect(screen, PAD_COLOR, pad_rect, 2)

    active_slots = set(finger_positions.keys())

    # Remove trails of lifted fingers
    for slot in list(finger_trails.keys()):
        if slot not in active_slots:
            del finger_trails[slot]

    # Process and draw each finger
    for slot, data in finger_positions.items():
        # Normalize raw touchpad coordinates
        norm_x = data['x'] / max_x
        norm_y = data['y'] / max_y

        # Map to pad coordinates
        px = pad_rect.left + norm_x * pad_rect.width
        py = pad_rect.top + norm_y * pad_rect.height

        # Draw red circle
        pygame.draw.circle(screen, CIRCLE_COLOR, (int(px), int(py)), 12)

        # Draw trail
        if slot not in finger_trails:
            finger_trails[slot] = [(px, py)]
        else:
            finger_trails[slot].append((px, py))
            if len(finger_trails[slot]) > 300:  # Optional: trail length limit
                finger_trails[slot] = finger_trails[slot][-300:]

        # Draw trail as a polyline
        if len(finger_trails[slot]) > 1:
            pygame.draw.lines(screen, DRAW_COLOR, False, finger_trails[slot], PEN_SIZE)

    pygame.display.flip()
    clock.tick(FPS)

    # Handle quit
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_q:
            running = False

pygame.quit()
sys.exit(0)
