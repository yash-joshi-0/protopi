# Raspberry Pi 40-pin header reference

This table lists every physical header connection, with the GPIO/BCM number in the middle columns and the signal name on the outer columns.

| Pin 1 connection | Pin 1 GPIO | Pin 2 GPIO | Pin 2 connection |
| --- | --- | --- | --- |
| 3.3V | — | — | 5V |
| GPIO2 (SDA1) | GPIO2 | GPIO3 | GPIO3 (SCL1) |
| GND | — | GPIO4 | GPIO4 (GPCLK0) |
| GPIO14 (TXD0) | GPIO14 | GND | GND |
| GPIO15 (RXD0) | GPIO15 | GPIO17 | GPIO17 |
| GPIO18 (PWM0) | GPIO18 | GND | GND |
| GPIO27 (Button) | GPIO27 | GPIO22 | GPIO22 |
| 3.3V | — | GPIO23 | GPIO23 |
| GPIO24 (OLED DC) | GPIO24 | GND | GND |
| GPIO10 (MOSI / MAX7219 DIN) | GPIO10 | GPIO9 (MISO) | GPIO9 (MISO) |
| GPIO25 (OLED RST) | GPIO25 | GPIO11 (SCLK / MAX7219 CLK) | GPIO11 (SCLK) |
| GPIO8 (MAX7219 CS / SPI0 CE0) | GPIO8 | GND | GND |
| GPIO7 (OLED CS / SPI1 CE1) | GPIO7 | ID_SD | GPIO0 |
| ID_SC | GPIO1 | GPIO5 | GPIO5 |
| GND | — | GPIO6 | GPIO6 |
| GPIO12 (PWM0) | GPIO12 | GPIO13 (PWM1) | GPIO13 (PWM1) |
| GND | — | GPIO19 | GPIO19 |
| GPIO16 | GPIO16 | GPIO26 | GPIO26 |
| GPIO20 (PCM_DIN) | GPIO20 | GND | GND |
| GPIO21 (PCM_DOUT) | GPIO21 | — | 5V (reserved) |

### Notes
- Pins 1, 17, and 27 are 3.3V power pins.
- Pins 2, 4, and 40 are 5V power pins.
- Pins 6, 9, 14, 20, 25, 30, 34, and 39 are ground.
- The current OLED wiring uses GPIO24 for DC, GPIO25 for reset, GPIO10 for MOSI, GPIO11 for SCLK, and GPIO8/GPIO7 for chip select.
- The MAX7219 face display uses the SPI0 path on the header and the OLED uses the SPI1 path when available.