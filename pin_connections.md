# Raspberry Pi 40-pin header reference

The middle columns name each physical pin. The outer columns show what this build
connects to it, or — when the pin is unused.

Rows follow the physical header: the first row is pins 1 and 2, the second is pins 3
and 4, and so on down to pins 39 and 40.

| Connection  | GPIO               | GPIO               | Connection  |
| ----------- | ------------------ | ------------------ | ----------- |
| —           | 3.3V               | 5V                 | —           |
| —           | GPIO2 (SDA1)       | 5V                 | —           |
| —           | GPIO3 (SCL1)       | GND                | —           |
| —           | GPIO4 (GPCLK0)     | GPIO14 (TXD0)      | —           |
| —           | GND                | GPIO15 (RXD0)      | —           |
| —           | GPIO17             | GPIO18 (SPI1 CE0)  | XFP111X CS  |
| Button      | GPIO27             | GND                | —           |
| —           | GPIO22             | GPIO23             | —           |
| —           | 3.3V               | GPIO24             | XFP111X DC  |
| MAX7219 DIN | GPIO10 (SPI0 MOSI) | GND                | —           |
| —           | GPIO9 (SPI0 MISO)  | GPIO25             | XFP111X RST |
| MAX7219 CLK | GPIO11 (SPI0 SCLK) | GPIO8 (SPI0 CE0)   | MAX7219 CS  |
| —           | GND                | GPIO7 (SPI0 CE1)   | —           |
| —           | ID_SD (GPIO0)      | ID_SC (GPIO1)      | —           |
| —           | GPIO5              | GND                | —           |
| —           | GPIO6              | GPIO12 (PWM0)      | —           |
| —           | GPIO13 (PWM1)      | GND                | —           |
| —           | GPIO19 (SPI1 MISO) | GPIO16 (SPI1 CE2)  | —           |
| —           | GPIO26             | GPIO20 (SPI1 MOSI) | XFP111X DIN |
| —           | GND                | GPIO21 (SPI1 SCLK) | XFP111X CLK |

### Notes
- 3.3V power is on pins 1 and 17. 5V power is on pins 2 and 4.
- Ground is on pins 6, 9, 14, 20, 25, 30, 34, and 39.
- Supply and ground wiring for the two displays is not recorded per pin here; only the signal lines are.
- The MAX7219 face display is on **SPI0** (`/dev/spidev0.0`): GPIO10 for MOSI, GPIO11 for SCLK, GPIO8 for chip select.
- The XFP111X status screen is on **SPI1 CE0** (`/dev/spidev1.0`): GPIO20 for MOSI, GPIO21 for SCLK, GPIO18 for chip select, plus GPIO24 for DC and GPIO25 for reset. Confirmed working on this wiring.
- SPI0 is enabled with `dtparam=spi=on` (or `sudo raspi-config` under Interface Options).
- **SPI1 additionally needs `dtoverlay=spi1-1cs` in `/boot/firmware/config.txt`.** Without it `/dev/spidev1.0` never appears and the status screen cannot be opened, no matter how the code is configured. Reboot after adding it.