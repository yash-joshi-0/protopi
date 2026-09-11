#!/usr/bin/env python3
# Fake-hardware checks for max7219.py so the script can be exercised off the Pi.
# Run from the repository root: python tests/test_screen.py
from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import time
import types
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Constants: These should not need to be changed.
REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_SCRIPT = "max7219.py"
MATRIX_COUNT = 14
TEMP_DIR = Path(tempfile.mkdtemp())
GOOD_CONFIG_BODY = "# rotation,xflip,yflip\n" + "270,1,0\n" * MATRIX_COUNT
BAD_CONFIG_BODY = (
    "# rotation,xflip,yflip\n270,1,0\nbanana\n45,0,0\n90,0\n" + "0,0,0\n" * 20
)


# Class: CheckRecorder prints each check as it runs and tracks the failures.
class CheckRecorder:
    def __init__(self) -> None:
        self.total = 0
        self.failures: List[str] = []

    # Contract: Record one check outcome and print it.
    def check(self, label: str, condition: Any, detail: str = "") -> None:
        self.total += 1
        passed = bool(condition)

        if not passed:
            self.failures.append(label)

        mark = "PASS" if passed else "FAIL"
        suffix = f"  {detail}" if detail else ""
        print(f"{mark}  {label}{suffix}")

    # Contract: Print the tally and return the exit code for the process.
    def summary(self) -> int:
        print()
        print(f"{self.total - len(self.failures)}/{self.total} checks passed")

        for label in self.failures:
            print(f"  failed: {label}")

        return 1 if self.failures else 0


# Class: FakeDraw records the points that would have been lit on the matrices.
class FakeDraw:
    def __init__(self) -> None:
        self.points: List[Tuple[int, int]] = []

    # Contract: Record one drawn point.
    def point(self, xy, fill=None) -> None:
        self.points.append(xy)


# Class: FakeCanvas stands in for the luma canvas context manager.
class FakeCanvas:
    last_draw: FakeDraw | None = None

    def __init__(self, device) -> None:
        self.device = device

    # Contract: Start a fresh draw surface for this frame.
    def __enter__(self) -> FakeDraw:
        FakeCanvas.last_draw = FakeDraw()
        return FakeCanvas.last_draw

    # Contract: Leave the frame without suppressing exceptions.
    def __exit__(self, *args) -> bool:
        return False


# Class: FakeMatrix stands in for the cascaded MAX7219 device.
class FakeMatrix:
    def __init__(self, *args, **kwargs) -> None:
        self.kwargs = kwargs
        self.contrast_value = None

    # Contract: Record the requested contrast.
    def contrast(self, value) -> None:
        self.contrast_value = value


# Class: FakeDeviceNotFound mirrors the luma error raised for a missing SPI node.
class FakeDeviceNotFound(Exception):
    pass


# Class: SpiTouched marks a status screen bus access that should not have happened.
class SpiTouched(Exception):
    pass


# Class: FakeHardware installs stand-in luma and RPi modules for one scenario.
class FakeHardware:
    load_counter = 0

    def __init__(
        self,
        gpio_present: bool = True,
        oled_present: bool = True,
        spi_mode: str = "ok",
    ) -> None:
        self.gpio_present = gpio_present
        self.oled_present = oled_present
        self.spi_mode = spi_mode
        self.opened: Dict[str, Any] = {}
        self.frames: List[Any] = []
        self.gpio: types.ModuleType | None = None
        self.install()

    # Contract: Open a fake SPI bus, recording or rejecting the status screen bus.
    def open_spi(self, **kwargs) -> object:
        if "gpio_DC" not in kwargs:
            return object()

        self.opened.update(kwargs)

        if self.spi_mode == "forbidden":
            raise SpiTouched(f"status screen bus opened: {kwargs}")

        if self.spi_mode == "missing":
            raise FakeDeviceNotFound("SPI device not found")

        return object()

    # Contract: Build the fake SH1106 class bound to this scenario.
    def build_screen_class(self) -> type:
        harness = self

        # Class: FakeScreen stands in for the SH1106 status screen.
        class FakeScreen:
            def __init__(self, *args, **kwargs) -> None:
                self.kwargs = kwargs

            # Contract: Record the frame, or fail if this scenario kills the screen.
            def display(self, image) -> None:
                if harness.spi_mode == "dies":
                    raise OSError(5, "Input/output error")

                harness.frames.append(image)

        return FakeScreen

    # Contract: Build a fake RPi.GPIO module that records its setup and cleanup calls.
    def build_gpio_module(self) -> types.ModuleType:
        gpio = types.ModuleType("RPi.GPIO")
        gpio.BCM, gpio.IN, gpio.HIGH, gpio.LOW = "BCM", "IN", 1, 0
        gpio.PUD_UP, gpio.PUD_DOWN = "PUD_UP", "PUD_DOWN"
        gpio.setup_calls = []
        gpio.cleanup_calls = []
        gpio.setmode = lambda mode: None
        gpio.setwarnings = lambda flag: None
        gpio.setup = lambda pin, mode, pull_up_down=None: gpio.setup_calls.append(
            (pin, pull_up_down)
        )
        gpio.cleanup = lambda channel=None: gpio.cleanup_calls.append(channel)
        gpio.input = lambda pin: 0
        return gpio

    # Contract: Replace the luma and RPi packages in sys.modules with fakes.
    def install(self) -> None:
        for name in list(sys.modules):
            if name.startswith(("luma", "RPi")):
                del sys.modules[name]

        luma = types.ModuleType("luma")
        core = types.ModuleType("luma.core")
        interface = types.ModuleType("luma.core.interface")
        serial = types.ModuleType("luma.core.interface.serial")
        render = types.ModuleType("luma.core.render")
        error = types.ModuleType("luma.core.error")
        led_matrix = types.ModuleType("luma.led_matrix")
        led_device = types.ModuleType("luma.led_matrix.device")
        oled = types.ModuleType("luma.oled")
        oled_device = types.ModuleType("luma.oled.device")

        error.DeviceNotFoundError = FakeDeviceNotFound
        render.canvas = FakeCanvas
        led_device.max7219 = FakeMatrix
        serial.spi = lambda **kwargs: self.open_spi(**kwargs)
        serial.noop = lambda *args, **kwargs: object()
        oled_device.sh1106 = self.build_screen_class() if self.oled_present else None
        luma.core = core
        core.error = error

        modules = {
            "luma": luma,
            "luma.core": core,
            "luma.core.interface": interface,
            "luma.core.interface.serial": serial,
            "luma.core.render": render,
            "luma.core.error": error,
            "luma.led_matrix": led_matrix,
            "luma.led_matrix.device": led_device,
            "luma.oled": oled,
            "luma.oled.device": oled_device,
        }
        sys.modules.update(modules)

        if self.gpio_present:
            rpi = types.ModuleType("RPi")
            self.gpio = self.build_gpio_module()
            rpi.GPIO = self.gpio
            sys.modules["RPi"] = rpi
            sys.modules["RPi.GPIO"] = self.gpio

    # Contract: Import a fresh copy of the target script against the current fakes.
    def load_target(self) -> types.ModuleType:
        FakeHardware.load_counter += 1
        name = f"protopi_target_{FakeHardware.load_counter}"
        spec = importlib.util.spec_from_file_location(name, REPO_ROOT / TARGET_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


# Contract: Write a matrix config file into the temporary directory and return it.
def write_config(name: str, body: str) -> Path:
    path = TEMP_DIR / name
    path.write_text(body, encoding="utf-8")
    return path


# Contract: Build a controller wired to a known good matrix config.
def build_controller(module, use_status_screen: bool):
    return module.Max7219FaceController(
        config_path=write_config("matrix_config.txt", GOOD_CONFIG_BODY),
        use_status_screen=use_status_screen,
    )


# Contract: Check the module imports off-Pi and derives its pin configuration.
def check_imports_and_wiring(recorder: CheckRecorder) -> None:
    hardware = FakeHardware(gpio_present=False)
    module = hardware.load_target()
    recorder.check("imports without RPi.GPIO", module.GPIO is None)
    recorder.check("BUTTON_PULL is None off-Pi", module.BUTTON_PULL is None)

    hardware = FakeHardware()
    module = hardware.load_target()
    recorder.check("active-HIGH derives PUD_DOWN", module.BUTTON_PULL == "PUD_DOWN")
    recorder.check("button pin is GPIO27", module.BUTTON_PIN == 27)
    recorder.check(
        "status screen on SPI1 CE0",
        (module.STATUS_SCREEN_SPI_PORT, module.STATUS_SCREEN_SPI_DEVICE) == (1, 0),
        f"{module.STATUS_SCREEN_SPI_PORT}.{module.STATUS_SCREEN_SPI_DEVICE}",
    )
    recorder.check(
        "driver is sh1106, not ssd1306",
        hasattr(module, "sh1106") and not hasattr(module, "ssd1306"),
    )

    controller = build_controller(module, use_status_screen=True)
    recorder.check(
        "spi opened on 1.0 with the configured pins",
        (
            hardware.opened.get("port"),
            hardware.opened.get("device"),
            hardware.opened.get("gpio_DC"),
            hardware.opened.get("gpio_RST"),
        )
        == (1, 0, 24, 25),
    )
    recorder.check(
        "setup used the derived pull", hardware.gpio.setup_calls[-1] == (27, "PUD_DOWN")
    )
    recorder.check(
        "config loaded in __init__", len(controller.matrix_configs) == MATRIX_COUNT
    )
    recorder.check("redraw works before start()", controller.redraw() or True)


# Contract: Check that an unusable matrix config warns and falls back to defaults.
def check_matrix_config(recorder: CheckRecorder) -> None:
    module = FakeHardware().load_target()
    path = write_config("bad.txt", BAD_CONFIG_BODY)
    buffer = io.StringIO()

    with redirect_stdout(buffer):
        controller = module.Max7219FaceController(
            config_path=path, use_status_screen=False
        )

    output = buffer.getvalue()
    recorder.check("malformed config does not raise", True)
    recorder.check(
        "truncated to num_matrices", len(controller.matrix_configs) == MATRIX_COUNT
    )
    recorder.check(
        "bad rotation coerced to 0", controller.matrix_configs[2].rotation == 0
    )
    recorder.check(
        "warnings name file and line",
        output.count("Warning:") >= 3,
        str(output.count("Warning:")),
    )


# Contract: Check that calibration markers follow each module's transform.
def check_calibration_markers(recorder: CheckRecorder) -> None:
    module = FakeHardware().load_target()

    # Contract: Return the lit marker pixels for one rotation and active module.
    def marker_pixels(rotation: int, active: int = 99) -> List[Tuple[int, int]]:
        controller = build_controller(module, use_status_screen=False)
        controller.calibration_mode = True
        controller.show_markers = True
        controller.active_matrix = active

        for config in controller.matrix_configs:
            config.rotation = rotation
            config.flip_x = False
            config.flip_y = False
            config.rebuild_map()

        controller.clear()
        controller.draw_corner_markers()
        return [
            (x, y)
            for y in range(controller.height)
            for x in range(8)
            if controller.framebuffer[y][x]
        ]

    recorder.check("marker at origin unrotated", marker_pixels(0) == [(0, 0)])
    recorder.check("marker follows 180 rotation", marker_pixels(180) == [(7, 7)])
    recorder.check("active module draws 2x2", len(marker_pixels(0, active=0)) == 4)
    recorder.check(
        "no blink machinery",
        not hasattr(module.Max7219FaceController, "update_marker_blink"),
    )


# Contract: Check that the deleted transition machinery has not come back.
def check_removed_code(recorder: CheckRecorder) -> None:
    module = FakeHardware().load_target()
    controller = build_controller(module, use_status_screen=False)
    recorder.check("no transition_active", not hasattr(controller, "transition_active"))
    recorder.check(
        "no REACTION_TRANSITION_DURATION_MS",
        not hasattr(module, "REACTION_TRANSITION_DURATION_MS"),
    )


# Contract: Check the status screen lists the face state plus only what is active.
def check_status_lines(recorder: CheckRecorder) -> None:
    module = FakeHardware().load_target()
    controller = build_controller(module, use_status_screen=False)

    controller.face_state = module.FaceState.IDLE
    controller.boop = False
    controller.reaction_phase = 0
    controller.mouth_step = 0
    idle = controller.get_status_lines()
    recorder.check("idle shows only the state", idle == ["face_state=IDLE"], str(idle))

    controller.face_state = module.FaceState.BLINK
    blinking = controller.get_status_lines()
    recorder.check(
        "blink adds a marker", blinking == ["face_state=BLINK", "blink"], str(blinking)
    )

    controller.face_state = module.FaceState.REACT
    controller.boop = True
    controller.reaction_phase = 1
    controller.mouth_step = 2
    reacting = controller.get_status_lines()
    recorder.check(
        "reacting shows boop, phase, step",
        reacting == ["face_state=REACT", "boop", "reaction_phase=1", "mouth_step=2"],
        str(reacting),
    )

    controller.boop = False
    controller.reaction_phase = 0
    controller.mouth_step = 0
    recorder.check(
        "inactive fields drop out",
        controller.get_status_lines() == ["face_state=REACT"],
    )


# Contract: Check the status screen repaints every call and still honours a throttle.
def check_status_refresh(recorder: CheckRecorder) -> None:
    hardware = FakeHardware()
    module = hardware.load_target()
    recorder.check("refresh interval is 0", module.STATUS_SCREEN_REFRESH_MS == 0)

    controller = build_controller(module, use_status_screen=True)
    recorder.check(
        "no change-detection state",
        not hasattr(controller, "status_shown_lines")
        and not hasattr(controller, "status_last_redraw"),
    )

    hardware.frames.clear()
    for _ in range(25):
        controller.update_status_screen()
    recorder.check(
        "every call paints a frame",
        len(hardware.frames) == 25,
        str(len(hardware.frames)),
    )

    controller.status_refresh_ms = 10_000
    controller.status_last_update = time.monotonic()
    hardware.frames.clear()
    for _ in range(10):
        controller.update_status_screen()
    recorder.check(
        "raising the interval still throttles",
        len(hardware.frames) == 0,
        str(len(hardware.frames)),
    )


# Contract: Check that the status screen is opt-in behind the --screen flag.
def check_command_line(recorder: CheckRecorder) -> None:
    hardware = FakeHardware()
    module = hardware.load_target()

    recorder.check(
        "no flag means no screen", module.parse_arguments([]).screen is False
    )
    recorder.check(
        "--screen enables the screen",
        module.parse_arguments(["--screen"]).screen is True,
    )

    try:
        with redirect_stdout(io.StringIO()):
            module.parse_arguments(["--bogus"])
        recorder.check("unknown flag is rejected", False)
    except SystemExit:
        recorder.check("unknown flag is rejected", True)

    try:
        with redirect_stdout(io.StringIO()):
            module.parse_arguments(["--help"])
        recorder.check("--help exits cleanly", False)
    except SystemExit as exit_request:
        recorder.check("--help exits cleanly", exit_request.code == 0)

    face_only = build_controller(
        module, use_status_screen=module.parse_arguments([]).screen
    )
    recorder.check(
        "default run initialises no screen",
        face_only.status_device is None and face_only.use_status_screen is False,
    )
    recorder.check(
        "default run never opens SPI1", hardware.opened == {}, str(hardware.opened)
    )

    hardware.frames.clear()
    face_only.redraw()
    face_only.update_status_screen()
    recorder.check("face-only run paints nothing to the screen", hardware.frames == [])
    face_only.shutdown()
    recorder.check("face-only shutdown is safe", True)

    with_screen = build_controller(
        module, use_status_screen=module.parse_arguments(["--screen"]).screen
    )
    recorder.check("--screen run initialises the screen", with_screen.status_device)


# Contract: Check that a face-only run never opens the status screen bus at all.
def check_screen_stays_closed(recorder: CheckRecorder) -> None:
    hardware = FakeHardware(spi_mode="forbidden")
    module = hardware.load_target()
    controller = None

    try:
        controller = build_controller(
            module, use_status_screen=module.parse_arguments([]).screen
        )
        controller.redraw()

        for state in (
            module.FaceState.IDLE,
            module.FaceState.BLINK,
            module.FaceState.REACT,
        ):
            controller.face_state = state
            for _ in range(20):
                controller.render_face(
                    blink=state == module.FaceState.BLINK, mouth_step=1
                )
                controller.update_status_screen()

        controller.start_boop_reaction()
        controller.status_last_probe_attempt = 0.0
        for _ in range(20):
            controller.update_status_screen()

        controller.calibration_mode = True
        controller.render_face()
        controller.shutdown()
        recorder.check("face-only run never touches SPI1, end to end", True)
    except SpiTouched as touched:
        recorder.check(
            "face-only run never touches SPI1, end to end", False, str(touched)
        )

    recorder.check(
        "face-only run leaves status_serial unset",
        controller is not None and controller.status_serial is None,
    )


# Contract: Check that a missing or failing status screen degrades and is reported once.
def check_screen_failures(recorder: CheckRecorder) -> None:
    module = FakeHardware(oled_present=False).load_target()
    buffer = io.StringIO()

    with redirect_stdout(buffer):
        degraded = build_controller(module, use_status_screen=True)

    recorder.check(
        "missing luma.oled degrades, no raise", degraded.use_status_screen is False
    )
    recorder.check("and says so", "luma.oled is not installed" in buffer.getvalue())

    module = FakeHardware(spi_mode="missing").load_target()
    buffer = io.StringIO()

    with redirect_stdout(buffer):
        absent = build_controller(module, use_status_screen=True)

    output = buffer.getvalue()
    recorder.check("missing device is reported", "Warning: no status screen" in output)
    recorder.check("names the spidev node", "/dev/spidev1.0" in output)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        for _ in range(5):
            absent.status_last_probe_attempt = 0.0
            absent.update_status_screen()
    recorder.check(
        "retries do not spam", buffer.getvalue() == "", repr(buffer.getvalue()[:40])
    )

    module = FakeHardware(spi_mode="dies").load_target()
    buffer = io.StringIO()

    with redirect_stdout(buffer):
        dying = build_controller(module, use_status_screen=True)

    recorder.check("screen dying during init is handled", dying.status_device is None)
    recorder.check(
        "reported exactly once",
        buffer.getvalue().count("Warning: no status screen") == 1,
    )


# Contract: Check that shutdown blanks the screen and releases the button pin once.
def check_shutdown(recorder: CheckRecorder) -> None:
    hardware = FakeHardware()
    module = hardware.load_target()
    controller = build_controller(module, use_status_screen=True)

    hardware.gpio.cleanup_calls.clear()
    hardware.frames.clear()
    controller.shutdown()
    recorder.check(
        "shutdown blanks the screen",
        len(hardware.frames) == 1 and hardware.frames[0].getbbox() is None,
    )
    recorder.check(
        "shutdown releases the button pin", hardware.gpio.cleanup_calls == [27]
    )

    controller.shutdown()
    recorder.check("shutdown is idempotent", hardware.gpio.cleanup_calls == [27])


# Contract: Check that the face still renders and that blinking differs from idle.
def check_face_rendering(recorder: CheckRecorder) -> None:
    module = FakeHardware().load_target()
    controller = build_controller(module, use_status_screen=False)

    controller.render_face()
    idle_points = sorted(FakeCanvas.last_draw.points)
    controller.render_face(blink=True, mouth_step=2)
    blink_points = sorted(FakeCanvas.last_draw.points)

    recorder.check(
        "idle render produces pixels", len(idle_points) > 50, f"{len(idle_points)} px"
    )
    recorder.check("blink differs from idle", blink_points != idle_points)


# Contract: Run every check group and return the exit code for the process.
def main() -> int:
    recorder = CheckRecorder()
    check_imports_and_wiring(recorder)
    check_matrix_config(recorder)
    check_calibration_markers(recorder)
    check_removed_code(recorder)
    check_status_lines(recorder)
    check_status_refresh(recorder)
    check_command_line(recorder)
    check_screen_stays_closed(recorder)
    check_screen_failures(recorder)
    check_shutdown(recorder)
    check_face_rendering(recorder)
    return recorder.summary()


if __name__ == "__main__":
    sys.exit(main())
