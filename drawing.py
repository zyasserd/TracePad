import pygame
import threading
import time
import sys
import os

from multitouch_reader import touchpad_positions_generator, get_max_xy

# === CONFIGURATION ===
DEVICE_PATH = '/dev/input/event6'
PAD_COLOR = (0, 0, 0)         # Black rectangle for touchpad representation
CIRCLE_COLOR = (255, 0, 0)    # Red finger circle for active touches
PEN_SIZE = 5                  # Default pen size
PAD_SCREEN_COVERAGE_RATIO = 0.6
FPS = 60

# --- Key Bindings ---
QUIT_KEY = pygame.K_q       # Key to quit the application
CLEAR_KEY = pygame.K_c      # Key to clear the canvas
SAVE_KEY = pygame.K_s       # Key to save the drawing as PNG
ROTATE_PEN_KEY = pygame.K_TAB # Key to rotate through pen types (Tab key)

# === PEN DEFINITIONS ===
# Each pen is a dictionary with its properties
PENS = [
    {
        "mode": "draw",
        "color": (0, 0, 0), # Blue
        "size": 5,
    },
    {
        "mode": "draw",
        "color": (0, 0, 255), # Blue
        "size": 5,
    },
    {
        "mode": "pointer",
        "color": (255, 0, 0), # Red (will be used for temporary outline if we wanted)
        "size": 0, # No size for drawing, just pointer
    }
]

current_pen_index = 0 # Start with the first pen in the list

# === INIT TOUCHPAD BOUNDS ===
max_x, max_y = get_max_xy(DEVICE_PATH)
if max_x is None or max_y is None:
    print(f"Error: Could not get touchpad dimensions from {DEVICE_PATH}.")
    sys.exit(1)

# === FINGER STATE ===
finger_positions = {}
# Stores the last *drawn* position for each finger, used for smooth line segments.
finger_last_drawn_pos = {}

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
    # Handle events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == QUIT_KEY:
                running = False
            elif event.key == CLEAR_KEY:
                drawing_surface.fill((0, 0, 0, 0)) # Clear the drawing surface
                finger_last_drawn_pos.clear() # Clear last drawn positions
                print("Canvas cleared.")
            elif event.key == SAVE_KEY:
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                filename = f"drawing_{timestamp}.png"
                try:
                    pygame.image.save(drawing_surface, filename)
                    print(f"Drawing saved as {filename}")
                except pygame.error as e:
                    print(f"Error saving image: {e}")
            elif event.key == ROTATE_PEN_KEY:
                current_pen_index = (current_pen_index + 1) % len(PENS)
                # When switching pens, clear last_drawn_pos to prevent spurious lines
                # when resuming drawing with a new pen after a pointer.
                finger_last_drawn_pos.clear()

    screen.fill((255, 255, 255))  # White background for current frame elements

    # Draw the touchpad rectangle on the main screen
    pygame.draw.rect(screen, PAD_COLOR, pad_rect, 2)

    active_slots = set(finger_positions.keys())

    # Remove last drawn positions for lifted fingers
    for slot in list(finger_last_drawn_pos.keys()):
        if slot not in active_slots:
            del finger_last_drawn_pos[slot]

    # Get current pen properties
    current_pen = PENS[current_pen_index]
    draw_mode = current_pen["mode"] == "draw"
    pen_color = current_pen["color"]
    pen_size = current_pen["size"]

    # Process and draw each finger
    for slot, data in finger_positions.items():
        # Normalize raw touchpad coordinates
        norm_x = data['x'] / max_x
        norm_y = data['y'] / max_y

        # Map to pad coordinates
        current_px = pad_rect.left + norm_x * pad_rect.width
        current_py = pad_rect.top + norm_y * pad_rect.height
        current_pos = (int(current_px), int(current_py))

        # Always draw the red finger circle on the main screen for active touches
        pygame.draw.circle(screen, CIRCLE_COLOR, current_pos, 12)

        # Handle drawing based on current pen mode
        if draw_mode: # If the current pen is a 'draw' type
            if slot not in finger_last_drawn_pos:
                # If this is a new finger down, start its trail from current position
                finger_last_drawn_pos[slot] = current_pos
            else:
                # Draw a line segment from the last drawn position to the current position
                last_pos = finger_last_drawn_pos[slot]
                if last_pos != current_pos: # Only draw if position changed
                    pygame.draw.line(drawing_surface, pen_color, last_pos, current_pos, pen_size)
                    finger_last_drawn_pos[slot] = current_pos # Update last drawn position
        else: # If the current pen is a 'pointer' type (or any other non-drawing mode)
            # Ensure last_drawn_pos is cleared if this slot was previously drawing,
            # so that when we switch back to a draw mode, it doesn't connect to old points.
            if slot in finger_last_drawn_pos:
                del finger_last_drawn_pos[slot]

    # Blit the persistent drawing surface onto the main screen
    screen.blit(drawing_surface, (0, 0))

    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
sys.exit(0)
