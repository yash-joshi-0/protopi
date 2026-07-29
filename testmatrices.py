#!/usr/bin/env python3

import os
import random
import time
from dataclasses import dataclass, field

from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.led_matrix.device import max7219

# ==========================================================
# Constants
# ==========================================================

NUM_MATRICES = 14
CONFIG_FILE = "matrix_config.txt"

WIDTH = NUM_MATRICES * 8
HEIGHT = 8

# Face layout

MOUTH_L_START = 0
EYE_L_START = 4
NOSE_L = 6
NOSE_R = 7
EYE_R_START = 8
MOUTH_R_START = 10

# Face states

IDLE = 0
BLINK = 1
REACT = 2

# ==========================================================
# Device
# ==========================================================

serial = spi(port=0, device=0, gpio=noop())

device = max7219(
    serial,
    cascaded=NUM_MATRICES,
    block_orientation=0
)

device.contrast(1)

# ==========================================================
# Matrix configuration
# ==========================================================

@dataclass
class MatrixConfig:

    rotation: int = 0
    flip_x: bool = False
    flip_y: bool = False

    # 8x8 lookup table
    transform_map: list = field(default_factory=list)

    def rebuild_map(self):

        self.transform_map = []

        for r in range(8):

            row = []

            for c in range(8):

                x = c
                y = r

                rot = self.rotation % 360

                if rot == 90:
                    x, y = 7 - y, x

                elif rot == 180:
                    x, y = 7 - x, 7 - y

                elif rot == 270:
                    x, y = y, 7 - x

                if self.flip_x:
                    y = 7 - y

                if self.flip_y:
                    x = 7 - x

                row.append((x, y))

            self.transform_map.append(row)


matrix_configs = []


# ==========================================================
# Config file
# ==========================================================

def load_matrix_config():

    global matrix_configs

    matrix_configs = []

    if os.path.exists(CONFIG_FILE):

        with open(CONFIG_FILE) as f:

            for line in f:

                line = line.strip()

                if not line:
                    continue

                if line.startswith("#"):
                    continue

                rot, fx, fy = line.split(",")

                cfg = MatrixConfig(
                    rotation=int(rot),
                    flip_x=bool(int(fx)),
                    flip_y=bool(int(fy))
                )

                cfg.rebuild_map()

                matrix_configs.append(cfg)

    while len(matrix_configs) < NUM_MATRICES:

        cfg = MatrixConfig()
        cfg.rebuild_map()

        matrix_configs.append(cfg)


def save_matrix_config():

    with open(CONFIG_FILE, "w") as f:

        f.write("# rotation,xflip,yflip\n")

        for cfg in matrix_configs:

            f.write(
                f"{cfg.rotation},"
                f"{int(cfg.flip_x)},"
                f"{int(cfg.flip_y)}\n"
            )


# ==========================================================
# Framebuffer
# ==========================================================

framebuffer = [
    [0] * WIDTH
    for _ in range(HEIGHT)
]


def clear():

    for row in framebuffer:
        row[:] = [0] * WIDTH


def flush():

    with canvas(device) as draw:

        for y in range(HEIGHT):

            for x in range(WIDTH):

                if framebuffer[y][x]:
                    draw.point((x, y), fill="white")


# ==========================================================
# Calibration state
# ==========================================================

calibration_mode = False

show_markers = True

active_matrix = 0

marker_blink = True

last_marker_blink = time.monotonic()


# ==========================================================
# Helpers
# ==========================================================

def draw_corner_markers():

    # Markers should ONLY ever appear during calibration.
    if not calibration_mode:
        return

    if not show_markers:
        return

    for module in range(NUM_MATRICES):

        if module == active_matrix and not marker_blink:
            continue

        x = module * 8
        framebuffer[0][x] = 1


def draw_module(module, bitmap):

    cfg = matrix_configs[module]

    offset = module * 8

    lookup = cfg.transform_map

    for r in range(8):

        bits = bitmap[r]

        for c in range(8):

            if bits & (1 << (7 - c)):

                x, y = lookup[r][c]

                framebuffer[y][offset + x] = 1


def clear_module(module):

    offset = module * 8

    for y in range(8):
        for x in range(8):
            framebuffer[y][offset + x] = 0

# ==========================================================
# Graphics
# ==========================================================

Blink1 = [
    0b00000000,
    0b11000000,
    0b11111000,
    0b11111100,
    0b00001110,
    0b00000110,
    0b00000000,
    0b00000000
]

Blink2 = [
    0b00000000,
    0b00000000,
    0b00000111,
    0b00111111,
    0b11100000,
    0b10000000,
    0b00000000,
    0b00000000
]

M1 = [
    0b00000100,
    0b00011110,
    0b01111000,
    0b11100000,
    0b10000000,
    0b00000000,
    0b00000000,
    0b00000000
]

M2 = [
    0b00000000,
    0b00000000,
    0b00000000,
    0b00000001,
    0b00000111,
    0b00011110,
    0b01111000,
    0b11100000
]

M3 = [
    0b00000000,
    0b00000000,
    0b00000000,
    0b00000000,
    0b11100000,
    0b01111000,
    0b00011110,
    0b00000111
]

M4 = [
    0b00000000,
    0b00000000,
    0b00000000,
    0b00000111,
    0b00011111,
    0b01111000,
    0b11100000,
    0b10000000
]

N1 = [
    0b01111000,
    0b11110000,
    0b11000000,
    0b11000000,
    0b11000000,
    0b11000000,
    0b10000000,
    0b00000000
]

E1 = [
    0b11110000,
    0b11111100,
    0b11111110,
    0b11111111,
    0b00001111,
    0b00000110,
    0b00000000,
    0b00000000
]

E2 = [
    0b00000000,
    0b00000111,
    0b00011111,
    0b01111111,
    0b11100000,
    0b10000000,
    0b00000000,
    0b00000000
]

# ==========================================================
# Face state
# ==========================================================

face_state = IDLE

next_blink = time.monotonic() + random.uniform(5, 10)

blink_start = 0

reaction_phase = 0

mouth_step = 0

reaction_timer = 0

last_mouth_frame = 0

# ==========================================================
# Rendering
# ==========================================================

def draw_eyes(blink=False):

    if blink:

        draw_module(EYE_L_START + 0, Blink1)
        draw_module(EYE_L_START + 1, Blink2)

        draw_module(EYE_R_START + 0, Blink2)
        draw_module(EYE_R_START + 1, Blink1)

    else:

        draw_module(EYE_L_START + 0, E1)
        draw_module(EYE_L_START + 1, E2)

        draw_module(EYE_R_START + 0, E2)
        draw_module(EYE_R_START + 1, E1)


def draw_nose():

    draw_module(NOSE_L, N1)
    draw_module(NOSE_R, N1)


def draw_mouth(step=0):

    draw_module(MOUTH_L_START + 0, M4)
    draw_module(MOUTH_L_START + 1, M3)
    draw_module(MOUTH_L_START + 2, M2)
    draw_module(MOUTH_L_START + 3, M1)

    draw_module(MOUTH_R_START + 0, M1)
    draw_module(MOUTH_R_START + 1, M2)
    draw_module(MOUTH_R_START + 2, M3)
    draw_module(MOUTH_R_START + 3, M4)

    #
    # Mouth animation
    #

    if step > 0:
        clear_module(MOUTH_L_START + 3)

    if step > 1:
        clear_module(MOUTH_L_START + 2)

    if step > 2:
        clear_module(MOUTH_L_START + 1)

    if step > 0:
        clear_module(MOUTH_R_START + 0)

    if step > 1:
        clear_module(MOUTH_R_START + 1)

    if step > 2:
        clear_module(MOUTH_R_START + 2)


def render_face(blink=False, mouth_step=0):

    clear()

    draw_eyes(blink)

    draw_nose()

    draw_mouth(mouth_step)

    #
    # Calibration overlay
    #

    draw_corner_markers()

    flush()

# ==========================================================
# Calibration renderer
# ==========================================================

def redraw():

    if face_state == BLINK:

        render_face(
            blink=True
        )

    elif face_state == REACT:

        render_face(
            blink=True,
            mouth_step=mouth_step
        )

    else:

        render_face()

# ==========================================================
# Calibration helper
# ==========================================================

def update_marker_blink():

    global marker_blink
    global last_marker_blink

    if not calibration_mode:
        return

    now = time.monotonic()

    if now - last_marker_blink > 0.5:

        marker_blink = not marker_blink

        last_marker_blink = now

        redraw()

# ==========================================================
# Matrix configuration
# ==========================================================

def configure_matrices():

    global calibration_mode
    global active_matrix
    global show_markers

    answer = input(
        "Configure matrix transforms? (y/N): "
    ).strip().lower()

    if answer != "y":
        return

    calibration_mode = True

    show_markers = True

    redraw()

    print()

    print("Commands")
    print("--------")
    print("r : rotate clockwise")
    print("l : rotate counterclockwise")
    print("x : flip horizontally")
    print("y : flip vertically")
    print("b : toggle markers")
    print("Enter : next matrix")
    print()

    for module in range(NUM_MATRICES):

        active_matrix = module

        redraw()

        print(
            f"Configuring matrix {module+1}/{NUM_MATRICES}"
        )

        while True:

            cmd = input("> ").strip().lower()

            cfg = matrix_configs[module]

            if cmd == "":
                break

            elif cmd == "r":

                cfg.rotation = (
                    cfg.rotation + 90
                ) % 360

            elif cmd == "l":

                cfg.rotation = (
                    cfg.rotation - 90
                ) % 360

            elif cmd == "x":

                cfg.flip_x = not cfg.flip_x

            elif cmd == "y":

                cfg.flip_y = not cfg.flip_y

            elif cmd == "b":

                show_markers = not show_markers

            else:
                continue

            cfg.rebuild_map()

            redraw()

        print()

    calibration_mode = False

    redraw()

    save_matrix_config()

    print()
    print(
        f"Matrix configuration saved to {CONFIG_FILE}"
    )

# ==========================================================
# Render wrapper
# ==========================================================

def render():

    update_marker_blink()

    redraw()


# ==========================================================
# Calibration
# ==========================================================

def configure_matrices():

    global calibration_mode
    global active_matrix
    global show_markers

    answer = input(
        "Configure matrix transforms? (y/N): "
    ).strip().lower()

    if answer != "y":
        return

    calibration_mode = True
    show_markers = True

    print()

    print("--------------------------------------")
    print(" Matrix Calibration")
    print("--------------------------------------")
    print()
    print("Commands")
    print("--------")
    print("r : rotate clockwise")
    print("l : rotate counter-clockwise")
    print("x : reflect across X")
    print("y : reflect across Y")
    print("b : toggle corner markers")
    print("Enter : accept matrix")
    print()

    render()

    for module in range(NUM_MATRICES):

        active_matrix = module

        render()

        while True:

            print(
                f"\rMatrix {module + 1}/{NUM_MATRICES}",
                end="",
                flush=True
            )

            cmd = input(" > ").strip().lower()

            cfg = matrix_configs[module]

            changed = False

            if cmd == "":
                break

            elif cmd == "r":

                cfg.rotation = (
                    cfg.rotation + 90
                ) % 360

                changed = True

            elif cmd == "l":

                cfg.rotation = (
                    cfg.rotation - 90
                ) % 360

                changed = True

            elif cmd == "x":

                cfg.flip_x = not cfg.flip_x

                changed = True

            elif cmd == "y":

                cfg.flip_y = not cfg.flip_y

                changed = True

            elif cmd == "b":

                show_markers = not show_markers

                changed = True

            if changed:

                cfg.rebuild_map()

                render()

        print()

    calibration_mode = False

    save_matrix_config()

    render()

    print()
    print("--------------------------------------")
    print(f"Configuration saved to {CONFIG_FILE}")
    print("--------------------------------------")
    print()


# ==========================================================
# Startup
# ==========================================================

def startup():

    load_matrix_config()

    configure_matrices()

    render()

    print("Face initialized.")

    return time.monotonic() + random.uniform(5, 10)


# ==========================================================
# Main loop
# ==========================================================

def main():

    global next_blink

    next_blink = startup()

    while True:

        #
        # Marker animation (only active during calibration)
        #

        update_marker_blink()

        #
        # Face state machine
        #

        if face_state == IDLE:

            if time.monotonic() >= next_blink:

                globals()["blink_start"] = time.monotonic()
                globals()["face_state"] = BLINK

        elif face_state == BLINK:

            if time.monotonic() - blink_start < 0.15:

                render_face(
                    blink=True
                )

            else:

                globals()["face_state"] = IDLE

                next_blink = (
                    time.monotonic()
                    + random.uniform(5, 10)
                )

                render()

        elif face_state == REACT:

            #
            # Phase 0
            #

            if reaction_phase == 0:

                globals()["reaction_phase"] = 1
                globals()["mouth_step"] = 0
                globals()["last_mouth_frame"] = (
                    time.monotonic()
                )

                render_face(
                    blink=True,
                    mouth_step=0
                )

            #
            # Phase 1
            #

            elif reaction_phase == 1:

                if (
                    time.monotonic()
                    - last_mouth_frame
                ) > 0.020:

                    globals()["last_mouth_frame"] = (
                        time.monotonic()
                    )

                    if mouth_step < 4:

                        globals()["mouth_step"] += 1

                        render_face(
                            blink=True,
                            mouth_step=mouth_step
                        )

                    else:

                        globals()["reaction_phase"] = 2
                        globals()["reaction_timer"] = (
                            time.monotonic()
                        )

            #
            # Phase 2
            #

            elif reaction_phase == 2:

                if (
                    time.monotonic()
                    - reaction_timer
                ) > 0.150:

                    globals()["reaction_phase"] = 0
                    globals()["mouth_step"] = 0
                    globals()["face_state"] = IDLE

                    render()

        time.sleep(0.005)


# ==========================================================
# Entry
# ==========================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()

        print("Exiting...")

    finally:

        clear()

        flush()
