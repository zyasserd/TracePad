import turtle
import threading
import time
import sys

from multitouch_reader import touchpad_positions_generator, get_max_xy


# ==== CONFIG ====
DEVICE_PATH = '/dev/input/event6'
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600

# Get touchpad bounds
max_x, max_y = get_max_xy(DEVICE_PATH)

# Store current fingers (thread-safe access)
finger_positions = {}

# Set up turtle
screen = turtle.Screen()
screen.title("Multitouch Finger Tracker")
screen.setup(SCREEN_WIDTH, SCREEN_HEIGHT)
screen.tracer(0)

# Hide mouse cursor
screen.cv.config(cursor='none')

# Hide the default turtle
cursor = turtle.Turtle()
cursor.hideturtle()

# Dictionary of turtles for each finger slot
finger_turtles = {}

# Reader thread: updates shared finger_positions
def finger_reader():
    global finger_positions
    gen = touchpad_positions_generator(DEVICE_PATH)
    for fingers in gen:
        finger_positions = fingers

# Drawing loop: clears and redraws fingers each frame
def draw_loop():
    while True:
        cursor.clear()
        active_slots = set(finger_positions.keys())

        # Remove turtles for lifted fingers
        for slot in list(finger_turtles):
            if slot not in active_slots:
                finger_turtles[slot].hideturtle()
                del finger_turtles[slot]

        # Draw active fingers
        for slot, data in finger_positions.items():
            norm_x = data['x'] / max_x
            norm_y = data['y'] / max_y
            x = (norm_x - 0.5) * SCREEN_WIDTH
            y = (0.5 - norm_y) * SCREEN_HEIGHT

            if slot not in finger_turtles:
                t = turtle.Turtle()
                t.penup()
                t.shape("circle")
                t.color("red")
                t.shapesize(1.5)
                t.hideturtle()
                finger_turtles[slot] = t
            t = finger_turtles[slot]
            t.goto(x, y)
            t.showturtle()

        screen.update()
        time.sleep(1 / 60)

# Quit handler
def quit_app():
    screen.cv.config(cursor='arrow')  # show mouse again
    turtle.bye()
    sys.exit(0)

# Bind 'q' to quit
screen.onkey(quit_app, "q")
screen.listen()

# Start multitouch reader
threading.Thread(target=finger_reader, daemon=True).start()

# Start drawing loop (blocking)
draw_loop()
