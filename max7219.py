#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import List, Sequence, Tuple

from luma.core.error import DeviceNotFoundError
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.led_matrix.device import max7219

try:
    from luma.oled.device import sh1106
except ImportError:  # pragma: no cover - optional dependency for non-OLED setups
    sh1106 = None

from PIL import Image, ImageDraw, ImageFont

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - non-Raspberry Pi environments
    GPIO = None

# User Values: These may need to be changed based on matrix configuration and layout.
NUM_MATRICES = 14
MOUTH_LEFT_START = 0
EYE_LEFT_START = 4
NOSE_LEFT = 6
NOSE_RIGHT = 7
EYE_RIGHT_START = 8
MOUTH_RIGHT_START = 10

# Configuration values: These can be changes to personal preference.
BUTTON_PIN = 27
BUTTON_DEBOUNCE_MS = 50
BUTTON_ACTIVE_STATE = GPIO.HIGH if GPIO is not None else 1
# Set this to GPIO.LOW if the button circuit is wired as active-low.
STATUS_SCREEN_SPI_PORT = 1
STATUS_SCREEN_SPI_DEVICE = 0
STATUS_SCREEN_DC_PIN = 24
STATUS_SCREEN_RST_PIN = 25
STATUS_SCREEN_REFRESH_MS = 0
STATUS_SCREEN_PROBE_INTERVAL_MS = 1000
STATUS_SCREEN_BUS_SPEED_HZ = 4000000


# Constants: These should not need to be changed.
CONFIG_FILE = "matrix_config.txt"
WIDTH = NUM_MATRICES * 8
HEIGHT = 8
STATUS_SCREEN_WIDTH = 128
STATUS_SCREEN_HEIGHT = 64

if GPIO is not None:
    BUTTON_PULL = GPIO.PUD_DOWN if BUTTON_ACTIVE_STATE == GPIO.HIGH else GPIO.PUD_UP
else:
    BUTTON_PULL = None


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
        button_debounce_ms: int = BUTTON_DEBOUNCE_MS,
        use_status_screen: bool = True,
    ) -> None:
        self.num_matrices = num_matrices
        self.config_path = config_path or Path(__file__).resolve().with_name(
            CONFIG_FILE
        )
        self.width = num_matrices * 8
        self.height = 8
        self.use_status_screen = use_status_screen

        if GPIO is not None:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

        self.max7219_serial = spi(port=0, device=0, gpio=noop())
        self.device = max7219(
            self.max7219_serial,
            cascaded=self.num_matrices,
            block_orientation=0,
        )
        self.device.contrast(1)

        self.status_device = None
        self.status_font = None
        self.status_serial = None
        self.status_last_update = 0.0
        self.status_last_probe_attempt = 0.0
        self.status_probe_interval_ms = STATUS_SCREEN_PROBE_INTERVAL_MS
        self.status_refresh_ms = STATUS_SCREEN_REFRESH_MS
        self._status_failure_reported = False

        if self.use_status_screen and sh1106 is None:
            print(
                "Warning: luma.oled is not installed, continuing without the "
                "status screen."
            )
            self.use_status_screen = False

        if self.use_status_screen:
            self._initialize_status_screen()

        self.matrix_configs: List[MatrixConfig] = []
        self.framebuffer = [[0] * self.width for _ in range(self.height)]
        self.load_matrix_config()

        self.calibration_mode = False
        self.show_markers = True
        self.active_matrix = 0

        self.face_state = FaceState.IDLE
        self.next_blink = time.monotonic() + random.uniform(5, 10)
        self.blink_start = 0.0
        self.reaction_phase = 0
        self.mouth_step = 0
        self.reaction_timer = 0.0
        self.last_mouth_frame = 0.0
        self.boop = False
        self.button_pin = BUTTON_PIN
        self.button_debounce_ms = button_debounce_ms
        self._button_raw_state = False
        self._button_debounced_state = False
        self._button_last_change_time = time.monotonic()
        self._gpio_configured = False

        if GPIO is not None:
            GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=BUTTON_PULL)
            self._gpio_configured = True

    # Contract: Initialize the OLED status screen on the configured SPI chip select.
    def _initialize_status_screen(self) -> bool:
        if not self.use_status_screen:
            return False

        if GPIO is None:
            self.use_status_screen = False
            return False

        try:
            self.status_serial = spi(
                port=STATUS_SCREEN_SPI_PORT,
                device=STATUS_SCREEN_SPI_DEVICE,
                gpio=GPIO,
                gpio_DC=STATUS_SCREEN_DC_PIN,
                gpio_RST=STATUS_SCREEN_RST_PIN,
                bus_speed_hz=STATUS_SCREEN_BUS_SPEED_HZ,
                reset_hold_time=0.2,
                reset_release_time=0.2,
            )
            self.status_device = sh1106(
                self.status_serial,
                width=STATUS_SCREEN_WIDTH,
                height=STATUS_SCREEN_HEIGHT,
                rotate=0,
            )
            self.status_font = self.load_status_font()
            self.blank_status_screen()
        except (DeviceNotFoundError, FileNotFoundError, OSError) as error:
            self.report_status_failure(error)
            self.status_serial = None
            self.status_device = None
            self.status_font = None
            return False

        if self._status_failure_reported:
            print(
                f"Status screen reconnected on /dev/spidev"
                f"{STATUS_SCREEN_SPI_PORT}.{STATUS_SCREEN_SPI_DEVICE}."
            )
            self._status_failure_reported = False

        return True

    # Contract: Report the first status screen failure and stay quiet while retrying.
    def report_status_failure(self, error: Exception) -> None:
        if self._status_failure_reported:
            return

        print(
            f"Warning: no status screen on /dev/spidev"
            f"{STATUS_SCREEN_SPI_PORT}.{STATUS_SCREEN_SPI_DEVICE} ({error}). "
            f"The face keeps running; retrying every "
            f"{self.status_probe_interval_ms} ms."
        )
        self._status_failure_reported = True

    # Contract: Load the bitmap font for the status screen, or None when unavailable.
    def load_status_font(self) -> ImageFont.ImageFont | None:
        try:
            return ImageFont.load_default()
        except OSError:  # pragma: no cover - fallback when fonts are unavailable
            return None

    # Contract: Push an all-off frame to the status screen.
    def blank_status_screen(self) -> None:
        if self.status_device is None:
            return

        self.status_device.display(
            Image.new("1", (STATUS_SCREEN_WIDTH, STATUS_SCREEN_HEIGHT), 0)
        )

    # Contract: Return the status lines, listing the face state plus whatever is active.
    def get_status_lines(self) -> List[str]:
        lines = [f"face_state={self.face_state.name}"]

        if self.face_state == FaceState.BLINK:
            lines.append("blink")

        if self.boop:
            lines.append("boop")

        if self.reaction_phase:
            lines.append(f"reaction_phase={self.reaction_phase}")

        if self.mouth_step:
            lines.append(f"mouth_step={self.mouth_step}")

        return lines

    # Contract: Draw the given lines into a status screen sized image.
    def render_status_image(self, lines: List[str]) -> Image.Image:
        image = Image.new("1", (STATUS_SCREEN_WIDTH, STATUS_SCREEN_HEIGHT), 0)
        draw = ImageDraw.Draw(image)
        text = "\n".join(lines)

        if self.status_font is not None:
            draw.text((0, 0), text, font=self.status_font, fill=1)
        else:
            draw.text((0, 0), text, fill=1)

        return image

    # Contract: Update the attached status screen with the current controller state.
    def update_status_screen(self) -> None:
        if not self.use_status_screen:
            return

        now = time.monotonic()
        if self.status_device is None:
            probe_interval_s = self.status_probe_interval_ms / 1000.0
            if now - self.status_last_probe_attempt >= probe_interval_s:
                self.status_last_probe_attempt = now
                self._initialize_status_screen()
            if self.status_device is None:
                return

        if now - self.status_last_update < (self.status_refresh_ms / 1000.0):
            return

        self.status_last_update = now

        try:
            self.status_device.display(
                self.render_status_image(self.get_status_lines())
            )
        except OSError as error:
            self.report_status_failure(error)
            self.status_serial = None
            self.status_device = None
            self.status_font = None

    # Contract: Load per-matrix transforms from disk, skipping unusable lines.
    def load_matrix_config(self) -> None:
        self.matrix_configs = []

        if self.config_path.exists():
            with self.config_path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if len(self.matrix_configs) >= self.num_matrices:
                        print(
                            f"Warning: {self.config_path.name} line {line_number}: "
                            f"more than {self.num_matrices} entries, ignoring the rest."
                        )
                        break

                    matrix_config = self.parse_matrix_config_line(line, line_number)
                    matrix_config.rebuild_map()
                    self.matrix_configs.append(matrix_config)

        while len(self.matrix_configs) < self.num_matrices:
            matrix_config = MatrixConfig()
            matrix_config.rebuild_map()
            self.matrix_configs.append(matrix_config)

    # Contract: Parse one config line into a MatrixConfig, falling back to defaults.
    def parse_matrix_config_line(self, line: str, line_number: int) -> MatrixConfig:
        location = f"{self.config_path.name} line {line_number}"

        try:
            rotation_text, flip_x_text, flip_y_text = line.split(",")
            matrix_config = MatrixConfig(
                rotation=int(rotation_text),
                flip_x=bool(int(flip_x_text)),
                flip_y=bool(int(flip_y_text)),
            )
        except ValueError:
            print(
                f"Warning: {location}: expected rotation,xflip,yflip "
                f"but found {line!r}, using defaults."
            )
            return MatrixConfig()

        if matrix_config.rotation % 90 != 0:
            print(
                f"Warning: {location}: rotation {matrix_config.rotation} is not a "
                f"multiple of 90, using 0."
            )
            matrix_config.rotation = 0

        return matrix_config

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

    # Contract: Mark each module's transformed origin during calibration.
    def draw_corner_markers(self) -> None:
        if not self.calibration_mode or not self.show_markers:
            return

        for module_index in range(self.num_matrices):
            lookup = self.matrix_configs[module_index].transform_map
            offset = module_index * 8

            marker_size = 2 if module_index == self.active_matrix else 1

            for row_index in range(marker_size):
                for column_index in range(marker_size):
                    x_position, y_position = lookup[row_index][column_index]
                    self.framebuffer[y_position][offset + x_position] = 1

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

    # Contract: Render the mouth animation for the requested step.
    def draw_mouth(self, step: int = 0) -> None:
        self.clear_mouth_modules()

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
    def render_face(self, blink: bool = False, mouth_step: int = 0) -> None:
        self.clear()
        self.draw_eyes(blink)
        self.draw_nose()
        self.draw_mouth(mouth_step)
        self.draw_corner_markers()
        self.flush()
        self.update_status_screen()

    # Contract: Refresh the display using the current face state.
    def redraw(self) -> None:
        if self.face_state == FaceState.BLINK:
            self.render_face(blink=True)
        elif self.face_state == FaceState.REACT:
            self.render_face(blink=True, mouth_step=self.mouth_step)
        else:
            self.render_face()

    # Contract: Read the button input and trigger a reaction when booping begins.
    def update_boop_state(self) -> None:
        if GPIO is None:
            self.boop = False
            self._button_raw_state = False
            self._button_debounced_state = False
            self._button_last_change_time = time.monotonic()
            return

        button_state = GPIO.input(self.button_pin)
        raw_boop = button_state == BUTTON_ACTIVE_STATE
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
    def start_boop_reaction(self) -> None:
        self.face_state = FaceState.REACT
        self.reaction_phase = 1
        self.mouth_step = 0
        self.last_mouth_frame = time.monotonic()
        self.render_face(blink=True, mouth_step=0)
        self.update_status_screen()

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
                print(
                    f"\rMatrix {module_index + 1}/{self.num_matrices}",
                    end="",
                    flush=True,
                )
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

    # Contract: Blank every attached display and release the claimed GPIO channel.
    def shutdown(self) -> None:
        self.clear()
        self.flush()

        try:
            self.blank_status_screen()
        except OSError as error:
            print(f"Warning: could not blank the status screen: {error}")

        if GPIO is not None and self._gpio_configured:
            GPIO.cleanup(self.button_pin)
            self._gpio_configured = False

    # Contract: Run calibration and return the next blink time.
    def start(self) -> float:
        self.configure_matrices()
        self.redraw()
        print("Face initialized.")
        return time.monotonic() + random.uniform(5, 10)

    # Contract: Run the main animation loop until interrupted.
    def run(self) -> None:
        self.next_blink = self.start()

        while True:
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
                    self.redraw()
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
                    self.redraw()

                self.update_status_screen()

            time.sleep(0.005)


# Contract: Parse the command line options for the entry point.
def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Animate the Protogen face on the cascaded MAX7219 matrices."
    )
    parser.add_argument(
        "--screen",
        action="store_true",
        help="also drive the XFP111X status screen wired to SPI1 CE0",
    )
    return parser.parse_args(argv)


# Contract: Start the face controller from the entry point.
def main() -> None:
    arguments = parse_arguments()
    controller = Max7219FaceController(use_status_screen=arguments.screen)

    try:
        controller.run()
    except KeyboardInterrupt:
        print()
        print("Exiting...")
    finally:
        controller.shutdown()


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
