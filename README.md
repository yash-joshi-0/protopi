# ProtoPi: A Raspberry Pi solution for Protogen Fursuits

| Feature   | Status    |
|---        |---        |
|MAX7219 Support    | ![static badge](https://img.shields.io/badge/Basic%20Support-29BF12)  |
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
3. Configure matrix rotation with `python max7219.py` (This only works for 14 matrix runs currently)

---
*This is a living document and will be updated with development*
