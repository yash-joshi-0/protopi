#!/usr/bin/env python3
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import List, Sequence, Tuple

from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.led_matrix.device import max7219
import RPi.GPIO as GPIO

# User Values: These may need to be changed based on matrix configuration and layout.
NUM_MATRICES = 14
MOUTH_LEFT_START = 0
EYE_LEFT_START = 4
NOSE_LEFT = 6
NOSE_RIGHT = 7
EYE_RIGHT_START = 8
MOUTH_RIGHT_START = 10

# Configuration values: These can be changes to personal preference.
BUTTON_PIN = 17
BUTTON_DEBOUNCE_MS = 50
REACTION_TRANSITION_DURATION_MS = 500

# Constants: These should not need to be changed.
CONFIG_FILE = "matrix_config.txt"
WIDTH = NUM_MATRICES * 8
HEIGHT = 8

# Class: FaceState represents the supported animation states for the face.
class FaceState(IntEnum):
    IDLE = 0
    BLINK = 1
    REACT = 2


# Class: MatrixConfig for transformation settings per matrix.
@dataclass
class MatrixConfig:
    rotation: int = 0
    flip_x: bool = False
    flip_y: bool = False
    transform_map: List[List[Tuple[int, int]]] = field(default_factory=list)

    # Contract: Rebuild the transform lookup table for this matrix configuration.
    def rebuild_map(self) -> None:
        self.transform_map = []

        for row_index in range(8):
            row: List[Tuple[int, int]] = []

            for col_index in range(8):
                x = col_index
                y = row_index

                rotation = self.rotation % 360

                if rotation == 90:
                    x, y = 7 - y, x
                elif rotation == 180:
                    x, y = 7 - x, 7 - y
                elif rotation == 270:
                    x, y = y, 7 - x

                if self.flip_x:
                    y = 7 - y

                if self.flip_y:
                    x = 7 - x

                row.append((x, y))

            self.transform_map.append(row)


# Class: Max7219FaceController for the framebuffer, animation loop, and calibration flow.
class Max7219FaceController:
    # Contract: Initialize the controller, hardware device, and default state values.
    def __init__(
        self,
        num_matrices: int = NUM_MATRICES,
        config_path: Path | None = None,
        reaction_transition_duration_ms: int = REACTION_TRANSITION_DURATION_MS,
        button_debounce_ms: int = BUTTON_DEBOUNCE_MS,
    ) -> None:
        self.num_matrices = num_matrices
        self.config_path = config_path or Path(__file__).resolve().with_name(
            CONFIG_FILE
        )
        self.width = num_matrices * 8
        self.height = 8

        self.serial = spi(port=0, device=0, gpio=noop())
        self.device = max7219(
            self.serial,
            cascaded=self.num_matrices,
            block_orientation=0,
        )
        self.device.contrast(1)

        self.matrix_configs: List[MatrixConfig] = []
        self.framebuffer = [[0] * self.width for _ in range(self.height)]

        self.calibration_mode = False
        self.show_markers = True
        self.active_matrix = 0
        self.marker_blink = True
        self.last_marker_blink = time.monotonic()

        self.face_state = FaceState.IDLE
        self.next_blink = time.monotonic() + random.uniform(5, 10)
        self.blink_start = 0.0
        self.reaction_phase = 0
        self.mouth_step = 0
        self.reaction_timer = 0.0
        self.last_mouth_frame = 0.0
        self.boop = False
        self.button_pin = BUTTON_PIN
        self.reaction_transition_duration_ms = reaction_transition_duration_ms
        self.button_debounce_ms = button_debounce_ms
        self.reaction_transition_start = 0.0
        self.transition_active = False
        self.transition_progress = 0.0
        self._button_raw_state = False
        self._button_debounced_state = False
        self._button_last_change_time = 0.0

        if GPIO is not None:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Contract: Load per-matrix transforms from disk and fill any missing entries with defaults.
    def load_matrix_config(self) -> None:
        self.matrix_configs = []

        if self.config_path.exists():
            with self.config_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    rotation_text, flip_x_text, flip_y_text = line.split(",")
                    matrix_config = MatrixConfig(
                        rotation=int(rotation_text),
                        flip_x=bool(int(flip_x_text)),
                        flip_y=bool(int(flip_y_text)),
                    )
                    matrix_config.rebuild_map()
                    self.matrix_configs.append(matrix_config)

        while len(self.matrix_configs) < self.num_matrices:
            matrix_config = MatrixConfig()
            matrix_config.rebuild_map()
            self.matrix_configs.append(matrix_config)

    # Contract: Persist the current matrix transform settings to disk.
    def save_matrix_config(self) -> None:
        with self.config_path.open("w", encoding="utf-8") as handle:
            handle.write("# rotation,xflip,yflip\n")
            for matrix_config in self.matrix_configs:
                handle.write(
                    f"{matrix_config.rotation},"
                    f"{int(matrix_config.flip_x)},"
                    f"{int(matrix_config.flip_y)}\n"
                )

    # Contract: Clear the framebuffer contents.
    def clear(self) -> None:
        for row in self.framebuffer:
            row[:] = [0] * self.width

    # Contract: Render the current framebuffer to the attached LED device.
    def flush(self) -> None:
        with canvas(self.device) as draw:
            for y_position in range(self.height):
                for x_position in range(self.width):
                    if self.framebuffer[y_position][x_position]:
                        draw.point((x_position, y_position), fill="white")

    # Contract: Draw the calibration markers for the active matrix state.
    def draw_corner_markers(self) -> None:
        if not self.calibration_mode or not self.show_markers:
            return

        for module_index in range(self.num_matrices):
            if module_index == self.active_matrix and not self.marker_blink:
                continue

            x_position = module_index * 8
            self.framebuffer[0][x_position] = 1

    # Contract: Render a single module bitmap using the relevant transform map.
    def draw_module(self, module_index: int, bitmap: Sequence[int]) -> None:
        matrix_config = self.matrix_configs[module_index]
        offset = module_index * 8
        lookup = matrix_config.transform_map

        for row_index in range(8):
            bits = bitmap[row_index]

            for column_index in range(8):
                if bits & (1 << (7 - column_index)):
                    x_position, y_position = lookup[row_index][column_index]
                    self.framebuffer[y_position][offset + x_position] = 1

    # Contract: Clear the pixels for one module region in the framebuffer.
    def clear_module(self, module_index: int) -> None:
        offset = module_index * 8

        for y_position in range(8):
            for x_position in range(8):
                self.framebuffer[y_position][offset + x_position] = 0

    # Contract: Render the eye frames for the current blink state.
    def draw_eyes(self, blink: bool = False) -> None:
        if blink:
            self.draw_module(EYE_LEFT_START + 0, BLINK_FRAME_1)
            self.draw_module(EYE_LEFT_START + 1, BLINK_FRAME_2)
            self.draw_module(EYE_RIGHT_START + 0, BLINK_FRAME_2)
            self.draw_module(EYE_RIGHT_START + 1, BLINK_FRAME_1)
        else:
            self.draw_module(EYE_LEFT_START + 0, EYE_FRAME_1)
            self.draw_module(EYE_LEFT_START + 1, EYE_FRAME_2)
            self.draw_module(EYE_RIGHT_START + 0, EYE_FRAME_2)
            self.draw_module(EYE_RIGHT_START + 1, EYE_FRAME_1)

    # Contract: Render the nose frame into the framebuffer.
    def draw_nose(self) -> None:
        self.draw_module(NOSE_LEFT, NOSE_FRAME)
        self.draw_module(NOSE_RIGHT, NOSE_FRAME)

    # Contract: Clear the mouth area before drawing the next mouth frame.
    def clear_mouth_modules(self) -> None:
        for module_index in range(4):
            self.clear_module(MOUTH_LEFT_START + module_index)

        for module_index in range(4):
            self.clear_module(MOUTH_RIGHT_START + module_index)

    # Contract: Return the mouth module order for the reaction sweep.
    def get_transition_mouth_sequence(self) -> List[Tuple[int, int]]:
        return [
            (MOUTH_LEFT_START + 3, MOUTH_FRAME_1),
            (MOUTH_RIGHT_START + 0, MOUTH_FRAME_1),
            (MOUTH_LEFT_START + 2, MOUTH_FRAME_2),
            (MOUTH_RIGHT_START + 1, MOUTH_FRAME_2),
            (MOUTH_LEFT_START + 1, MOUTH_FRAME_3),
            (MOUTH_RIGHT_START + 2, MOUTH_FRAME_3),
            (MOUTH_LEFT_START + 0, MOUTH_FRAME_4),
            (MOUTH_RIGHT_START + 3, MOUTH_FRAME_4),
        ]

    # Contract: Render the mouth animation for the requested step.
    def draw_mouth(
        self,
        step: int = 0,
        transition_progress: float | None = None,
    ) -> None:
        self.clear_mouth_modules()

        if transition_progress is not None:
            visible_modules = int(round(max(0.0, min(1.0, transition_progress)) * 8))
            mouth_sequence = self.get_transition_mouth_sequence()

            for module_index, bitmap in mouth_sequence[:visible_modules]:
                self.draw_module(module_index, bitmap)

            return

        self.draw_module(MOUTH_LEFT_START + 0, MOUTH_FRAME_4)
        self.draw_module(MOUTH_LEFT_START + 1, MOUTH_FRAME_3)
        self.draw_module(MOUTH_LEFT_START + 2, MOUTH_FRAME_2)
        self.draw_module(MOUTH_LEFT_START + 3, MOUTH_FRAME_1)

        self.draw_module(MOUTH_RIGHT_START + 0, MOUTH_FRAME_1)
        self.draw_module(MOUTH_RIGHT_START + 1, MOUTH_FRAME_2)
        self.draw_module(MOUTH_RIGHT_START + 2, MOUTH_FRAME_3)
        self.draw_module(MOUTH_RIGHT_START + 3, MOUTH_FRAME_4)

        if step > 0:
            self.clear_module(MOUTH_LEFT_START + 3)

        if step > 1:
            self.clear_module(MOUTH_LEFT_START + 2)

        if step > 2:
            self.clear_module(MOUTH_LEFT_START + 1)

        if step > 0:
            self.clear_module(MOUTH_RIGHT_START + 0)

        if step > 1:
            self.clear_module(MOUTH_RIGHT_START + 1)

        if step > 2:
            self.clear_module(MOUTH_RIGHT_START + 2)

    # Contract: Render the complete face using the current animation state.
    def render_face(
        self,
        blink: bool = False,
        mouth_step: int = 0,
        transition_progress: float | None = None,
    ) -> None:
        self.clear()
        self.draw_eyes(blink)
        self.draw_nose()
        self.draw_mouth(mouth_step, transition_progress=transition_progress)
        self.draw_corner_markers()
        self.flush()

    # Contract: Refresh the display using the current face state.
    def redraw(self) -> None:
        if self.face_state == FaceState.BLINK:
            self.render_face(blink=True)
        elif self.face_state == FaceState.REACT:
            if self.transition_active:
                self.render_face(
                    blink=True,
                    mouth_step=0,
                    transition_progress=self.transition_progress,
                )
            else:
                self.render_face(blink=True, mouth_step=self.mouth_step)
        else:
            self.render_face()

    # Contract: Toggle the calibration marker blink state at the configured interval.
    def update_marker_blink(self) -> None:
        if not self.calibration_mode:
            return

        now = time.monotonic()
        if now - self.last_marker_blink > 0.5:
            self.marker_blink = not self.marker_blink
            self.last_marker_blink = now
            self.redraw()

    # Contract: Read the button input and trigger a reaction when booping begins.
    def update_boop_state(self) -> None:
        if GPIO is None:
            self.boop = False
            self._button_raw_state = False
            self._button_debounced_state = False
            self._button_last_change_time = time.monotonic()
            return

        button_state = GPIO.input(self.button_pin)
        raw_boop = button_state == GPIO.LOW
        now = time.monotonic()

        if raw_boop != self._button_raw_state:
            self._button_raw_state = raw_boop
            self._button_last_change_time = now

        if now - self._button_last_change_time > (self.button_debounce_ms / 1000.0):
            debounced_boop = self._button_raw_state

            if debounced_boop and not self._button_debounced_state:
                self.start_boop_reaction()

            self._button_debounced_state = debounced_boop
            self.boop = debounced_boop

    # Contract: Enter the reaction state and reset the mouth animation sequence.
    def start_boop_reaction(self, transition_duration_ms: int | None = None) -> None:
        if transition_duration_ms is None:
            transition_duration_ms = self.reaction_transition_duration_ms

        self.face_state = FaceState.REACT
        self.transition_active = False
        self.transition_progress = 0.0
        self.reaction_phase = 1
        self.mouth_step = 0
        self.reaction_transition_start = time.monotonic()
        self.reaction_transition_duration_ms = transition_duration_ms
        self.last_mouth_frame = time.monotonic()
        self.render_face(blink=True, mouth_step=0)

    # Contract: Prompt the user to calibrate matrix transforms and persist the result.
    def configure_matrices(self) -> None:
        answer = input("Configure matrix transforms? (y/N): ").strip().lower()
        if answer != "y":
            return

        self.calibration_mode = True
        self.show_markers = True
        self.redraw()

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

        for module_index in range(self.num_matrices):
            self.active_matrix = module_index
            self.redraw()

            while True:
                print(f"\rMatrix {module_index + 1}/{self.num_matrices}", end="", flush=True)
                command = input(" > ").strip().lower()

                matrix_config = self.matrix_configs[module_index]
                changed = False

                if command == "":
                    break
                if command == "r":
                    matrix_config.rotation = (matrix_config.rotation + 90) % 360
                    changed = True
                elif command == "l":
                    matrix_config.rotation = (matrix_config.rotation - 90) % 360
                    changed = True
                elif command == "x":
                    matrix_config.flip_x = not matrix_config.flip_x
                    changed = True
                elif command == "y":
                    matrix_config.flip_y = not matrix_config.flip_y
                    changed = True
                elif command == "b":
                    self.show_markers = not self.show_markers
                    changed = True

                if changed:
                    matrix_config.rebuild_map()
                    self.redraw()

            print()

        self.calibration_mode = False
        self.save_matrix_config()
        self.redraw()

        print()
        print("--------------------------------------")
        print(f"Configuration saved to {self.config_path}")
        print("--------------------------------------")
        print()

    # Contract: Refresh the display and run the marker blink update.
    def render(self) -> None:
        self.update_marker_blink()
        self.redraw()

    # Contract: Initialize configuration, run calibration, and return the next blink time.
    def start(self) -> float:
        self.load_matrix_config()
        self.configure_matrices()
        self.render()
        print("Face initialized.")
        return time.monotonic() + random.uniform(5, 10)

    # Contract: Run the main animation loop until interrupted.
    def run(self) -> None:
        self.next_blink = self.start()

        while True:
            self.update_marker_blink()
            self.update_boop_state()

            if self.face_state == FaceState.IDLE:
                if time.monotonic() >= self.next_blink:
                    self.blink_start = time.monotonic()
                    self.face_state = FaceState.BLINK
            elif self.face_state == FaceState.BLINK:
                if time.monotonic() - self.blink_start < 0.15:
                    self.render_face(blink=True)
                else:
                    self.face_state = FaceState.IDLE
                    self.next_blink = time.monotonic() + random.uniform(5, 10)
                    self.render()
            elif self.face_state == FaceState.REACT:
                if self.boop:
                    if self.reaction_phase == 1:
                        if time.monotonic() - self.last_mouth_frame > 0.080:
                            self.last_mouth_frame = time.monotonic()

                            if self.mouth_step < 3:
                                self.mouth_step += 1
                                self.render_face(blink=True, mouth_step=self.mouth_step)
                            else:
                                self.render_face(blink=True, mouth_step=3)
                else:
                    self.reaction_phase = 0
                    self.mouth_step = 0
                    self.face_state = FaceState.IDLE
                    self.transition_active = False
                    self.transition_progress = 0.0
                    self.render()

            time.sleep(0.005)


# Contract: Start the face controller from the entry point.
def main() -> None:
    controller = Max7219FaceController()

    try:
        controller.run()
    except KeyboardInterrupt:
        print()
        print("Exiting...")
    finally:
        controller.clear()
        controller.flush()


BLINK_FRAME_1 = [
    0b00000000,
    0b11000000,
    0b11111000,
    0b11111100,
    0b00001110,
    0b00000110,
    0b00000000,
    0b00000000,
]

BLINK_FRAME_2 = [
    0b00000000,
    0b00000000,
    0b00000111,
    0b00111111,
    0b11100000,
    0b10000000,
    0b00000000,
    0b00000000,
]

MOUTH_FRAME_1 = [
    0b00000100,
    0b00011110,
    0b01111000,
    0b11100000,
    0b10000000,
    0b00000000,
    0b00000000,
    0b00000000,
]

MOUTH_FRAME_2 = [
    0b00000000,
    0b00000000,
    0b00000000,
    0b00000001,
    0b00000111,
    0b00011110,
    0b01111000,
    0b11100000,
]

MOUTH_FRAME_3 = [
    0b00000000,
    0b00000000,
    0b00000000,
    0b00000000,
    0b11100000,
    0b01111000,
    0b00011110,
    0b00000111,
]

MOUTH_FRAME_4 = [
    0b00000000,
    0b00000000,
    0b00000000,
    0b00000111,
    0b00011111,
    0b01111000,
    0b11100000,
    0b10000000,
]

NOSE_FRAME = [
    0b01111000,
    0b11110000,
    0b11000000,
    0b11000000,
    0b11000000,
    0b11000000,
    0b10000000,
    0b00000000,
]

EYE_FRAME_1 = [
    0b11110000,
    0b11111100,
    0b11111110,
    0b11111111,
    0b00001111,
    0b00000110,
    0b00000000,
    0b00000000,
]

EYE_FRAME_2 = [
    0b00000000,
    0b00000111,
    0b00011111,
    0b01111111,
    0b11100000,
    0b10000000,
    0b00000000,
    0b00000000,
]


if __name__ == "__main__":
    main()