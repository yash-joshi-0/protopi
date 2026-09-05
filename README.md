# ProtoPi: A Raspberry Pi solution for Protogen Fursuits

| Feature   | Status    |
|---        |---        |
|MAX7219 Support    | ![static badge](https://img.shields.io/badge/Basic%20Support-29BF12)  |
|XFP111X Support    | ![static badge](https://img.shields.io/badge/Done-29BF12) |
|HUB75 Support    | ![static badge](https://img.shields.io/badge/Not%20Started-FE0B0B)  |
|Wireless Access Point    | ![static badge](https://img.shields.io/badge/Not%20Started-FE0B0B)  |
|Config/Communicate Page    | ![static badge](https://img.shields.io/badge/Not%20Started-FE0B0B)  |

### How to use:
1. `git clone` into folder of your choice.
2. run
```bash
sudo apt install python3-dev python3-pip \
                 libjpeg-dev \
                 libfreetype6-dev \
                 libopenjp2-7 \
                 libtiff-dev \
                 build-essential

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
``` 
3. Enable SPI. The MAX7219 face uses SPI0; the XFP111X status screen uses SPI1, which needs an extra overlay:
```bash
sudo raspi-config   # Interface Options -> SPI -> Yes

# Only if you are using the status screen:
echo "dtoverlay=spi1-1cs" | sudo tee -a /boot/firmware/config.txt

sudo reboot
```
After rebooting, check that `/dev/spidev0.0` exists, and `/dev/spidev1.0` if you are using the status screen. **Without `dtoverlay=spi1-1cs` the `/dev/spidev1.0` node never appears and the status screen cannot be opened.** See `pin_connections.md` for the wiring.

4. Configure matrix rotation with `python max7219.py` (This only works for 14 matrix runs currently)

```bash
python max7219.py            # face only
python max7219.py --screen   # face plus the XFP111X status screen
```

The status screen is opt-in: without `--screen` the program never opens SPI1 at all, so you do not need the overlay or the screen wired up. With the flag it still falls back to the face alone when the screen is missing, and prints the `/dev/spidev` node it could not open.

---
*This is a living document and will be updated with development*
