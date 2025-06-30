import turtle
import threading
import time
import sys

# Ensure multitouch_reader is in the same directory or accessible in your Python path
from multitouch_reader import touchpad_positions_generator, get_max_xy


# ==== CONFIGURATION ====
DEVICE_PATH = '/dev/input/event6'  # !!! IMPORTANT: Verify this is your touchpad device path !!!
PAD_COLOR = "black"             # Color of the touchpad representation rectangle
DRAW_COLOR = "blue"                 # Color of the lines drawn by fingers
PEN_SIZE = 5                        # Thickness of the drawing lines
PAD_SCREEN_COVERAGE_RATIO = 0.6     # Max proportion of screen width/height the pad can take

# Get actual touchpad bounds (max X and Y raw values from device)
max_x, max_y = get_max_xy(DEVICE_PATH)
if max_x is None or max_y is None:
    print(f"Error: Could not get touchpad dimensions from {DEVICE_PATH}.")
    print("Please ensure the device path is correct and you have read permissions.")
    sys.exit(1)

# Store current finger positions (thread-safe access)
# Key: slot ID (finger ID from kernel), Value: {'x': raw_x, 'y': raw_y}
finger_positions = {}

# Set up the turtle screen for fullscreen display
screen = turtle.Screen()
screen.setup(width=1.0, height=1.0, startx=0, starty=0) # Set to fullscreen
screen.title("Multitouch Finger Tracker with Drawing")
screen.tracer(0) # Turn off screen updates for manual control

# Hide the default mouse cursor in the turtle window
screen.cv.config(cursor='none')

# Create a hidden turtle for general cursor operations (not drawing)
cursor = turtle.Turtle()
cursor.hideturtle()

# Dictionary to store a red circle turtle for each active finger
finger_turtles = {}

# Dictionary to store a pen turtle for drawing trails for each active finger
finger_pens = {}

# Calculate actual screen dimensions after setup
SCREEN_WIDTH = screen.window_width()
SCREEN_HEIGHT = screen.window_height()

# Calculate the dimensions of the visual touchpad rectangle,
# preserving the actual touchpad's aspect ratio and fitting it within the screen.
touchpad_aspect_ratio = max_x / max_y
screen_aspect_ratio = SCREEN_WIDTH / SCREEN_HEIGHT

if touchpad_aspect_ratio > screen_aspect_ratio:
    # If the touchpad is "wider" (more landscape) than the screen's aspect,
    # its width will be limited by the screen's width.
    pad_width = SCREEN_WIDTH * PAD_SCREEN_COVERAGE_RATIO
    pad_height = pad_width / touchpad_aspect_ratio
else:
    # If the touchpad is "taller" (more portrait) or square relative to the screen's aspect,
    # its height will be limited by the screen's height.
    pad_height = SCREEN_HEIGHT * PAD_SCREEN_COVERAGE_RATIO
    pad_width = pad_height * touchpad_aspect_ratio

# Draw the central rectangle representing the touchpad
pad_turtle = turtle.Turtle()
pad_turtle.penup()
pad_turtle.color(PAD_COLOR)
pad_turtle.goto(-pad_width / 2, -pad_height / 2) # Start at bottom-left corner of the rectangle
pad_turtle.pendown()
pad_turtle.setheading(90) # Face up
pad_turtle.forward(pad_height)
pad_turtle.setheading(0)  # Face right
pad_turtle.forward(pad_width)
pad_turtle.setheading(270) # Face down
pad_turtle.forward(pad_height)
pad_turtle.setheading(180) # Face left
pad_turtle.forward(pad_width)
pad_turtle.penup()
pad_turtle.hideturtle() # Hide the turtle icon used to draw the pad

# Function to continuously read finger positions from the touchpad device
def finger_reader():
    global finger_positions
    gen = touchpad_positions_generator(DEVICE_PATH)
    for fingers in gen:
        # Update the shared finger_positions dictionary
        finger_positions = fingers

# Function for the main drawing loop
def draw_loop():
    while True:
        # Get a set of currently active finger slot IDs
        active_slots = set(finger_positions.keys())

        # Clean up: Remove turtles and pens for fingers that are no longer detected
        for slot in list(finger_turtles.keys()): # Iterate over a copy to allow modification
            if slot not in active_slots:
                # Hide and delete the finger circle turtle
                finger_turtles[slot].hideturtle()
                del finger_turtles[slot]
                # If a pen exists for this slot, lift it to stop drawing
                if slot in finger_pens:
                    finger_pens[slot].penup() # Important to stop drawing when finger is lifted
                    # Optionally, uncomment the next line to delete the pen for a fresh start on next touch
                    # del finger_pens[slot]

        # Process active fingers: update their position and draw their trails
        for slot, data in finger_positions.items():
            # Normalize touchpad coordinates to a 0.0 to 1.0 range
            norm_x = data['x'] / max_x
            norm_y = data['y'] / max_y

            # Map normalized coordinates to the screen coordinates within the pad rectangle
            # (0.0 maps to left/bottom edge of pad, 1.0 maps to right/top edge of pad)
            mapped_x = (norm_x - 0.5) * pad_width
            mapped_y = (0.5 - norm_y) * pad_height # Y-axis inverted for turtle graphics

            # Update the finger circle turtle's position
            if slot not in finger_turtles:
                t = turtle.Turtle()
                t.penup()
                t.shape("circle")
                t.color("red")
                t.shapesize(1.5) # Size of the red circle representing the finger
                t.hideturtle()
                finger_turtles[slot] = t
            t = finger_turtles[slot]
            t.goto(mapped_x, mapped_y)
            t.showturtle()

            # Handle drawing with a separate pen turtle for each finger
            if slot not in finger_pens:
                p = turtle.Turtle()
                p.penup() # Start with pen up to avoid initial line
                p.color(DRAW_COLOR)
                p.pensize(PEN_SIZE)
                p.speed(0) # Set to fastest drawing speed
                p.hideturtle() # !!! HIDE THE PEN'S ARROW ICON !!!
                finger_pens[slot] = p
            p = finger_pens[slot]
            p.goto(mapped_x, mapped_y) # Move the pen to the current finger position
            p.pendown() # Put the pen down to draw the trail

        # Update the screen once per frame
        screen.update()
        # Control the frame rate (e.g., 60 frames per second)
        time.sleep(1 / 60)

# Function to handle quitting the application gracefully
def quit_app():
    screen.cv.config(cursor='arrow')  # Show the mouse cursor again
    turtle.bye() # Close the turtle graphics window
    sys.exit(0) # Exit the Python script

# Bind the 'q' key to the quit_app function
screen.onkey(quit_app, "q")
screen.listen() # Start listening for keyboard events

# Start the multitouch reader in a separate daemon thread
# A daemon thread exits automatically when the main program exits
threading.Thread(target=finger_reader, daemon=True).start()

# Start the drawing loop in the main thread (this call is blocking)
draw_loop()
