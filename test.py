from time import sleep

from luma.core.interface.serial import spi
from luma.led_matrix.device import max7219
from luma.core.render import canvas

# SPI bus 0, chip-select CE0
serial = spi(port=0, device=0)

device = max7219(
    serial,
    cascaded=1,
    block_orientation=90,
    rotate=0
)

device.contrast(20)

# Draw a border
with canvas(device) as draw:
    draw.rectangle(device.bounding_box, outline="white", fill="black")

sleep(2)

# Draw an X
with canvas(device) as draw:
    draw.line((0, 0, 7, 7), fill="white")
    draw.line((0, 7, 7, 0), fill="white")

sleep(2)

# Draw a smiley
with canvas(device) as draw:
    draw.point((2, 2), fill="white")
    draw.point((5, 2), fill="white")

    draw.point((1, 5), fill="white")
    draw.point((2, 6), fill="white")
    draw.point((3, 6), fill="white")
    draw.point((4, 6), fill="white")
    draw.point((5, 6), fill="white")
    draw.point((6, 5), fill="white")

sleep(5)

device.clear()
