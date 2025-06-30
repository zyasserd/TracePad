import pygame
import threading
import time
import sys

from multitouch_reader import touchpad_positions_generator, get_max_xy

# === CONFIGURATION ===
DEVICE_PATH = '/dev/input/event6'
PAD_COLOR = (0, 0, 0)         # Black rectangle for touchpad representation
DRAW_COLOR = (0, 0, 255)      # Blue for drawing trails
CIRCLE_COLOR = (255, 0, 0)    # Red finger circle
PEN_SIZE = 5
PAD_SCREEN_COVERAGE_RATIO = 0.6
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

# Hide the mouse cursor
pygame.mouse.set_visible(False)

# Create a drawing surface that persists
drawing_surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA) # SRCALPHA for transparency
drawing_surface.fill((0, 0, 0, 0)) # Fill with transparent black initially

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
    # Handle quit
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_q:
            running = False

    screen.fill((255, 255, 255))  # White background for current frame elements

    # Draw the touchpad rectangle on the main screen
    pygame.draw.rect(screen, PAD_COLOR, pad_rect, 2)

    active_slots = set(finger_positions.keys())

    # Remove trails of lifted fingers - this now clears from the finger_trails data,
    # but the drawing on drawing_surface remains.
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

        # Draw red circle on the main screen
        pygame.draw.circle(screen, CIRCLE_COLOR, (int(px), int(py)), 12)

        # Update and draw trail on the drawing_surface
        if slot not in finger_trails:
            finger_trails[slot] = [(px, py)]
        else:
            # Draw the line segment from the last point to the current point
            last_pos = finger_trails[slot][-1]
            pygame.draw.line(drawing_surface, DRAW_COLOR, last_pos, (px, py), PEN_SIZE)
            finger_trails[slot].append((px, py))

            # Optional: trail length limit for the stored points, not the drawing itself
            if len(finger_trails[slot]) > 300:
                finger_trails[slot] = finger_trails[slot][-300:]

    # Blit the persistent drawing surface onto the main screen
    screen.blit(drawing_surface, (0, 0))

    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
sys.exit(0)
