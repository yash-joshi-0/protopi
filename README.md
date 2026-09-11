# ProtoPi: A Raspberry Pi solution for Protogen Fursuits

| Feature   | Status    |
|---        |---        |
|MAX7219 Support    | ![static badge](https://img.shields.io/badge/Basic%20Support-29BF12)  |
|XFP111X Support    | ![static badge](https://img.shields.io/badge/Done-29BF12) |
|HUB75 Support    | ![static badge](https://img.shields.io/badge/Not%20Started-FE0B0B)  |
|Wireless Access Point    | ![static badge](https://img.shields.io/badge/In%20Progress-F0C808)  |
|Admin Console    | ![static badge](https://img.shields.io/badge/In%20Progress-F0C808)  |
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

Without `--screen` the program never opens SPI1. With the flag it still falls back to the face alone when the screen is missing, and prints the `/dev/spidev` node it could not open.

### Wireless access point and admin console

`access_point.py` turns the Pi's own Wi-Fi into a hotspot and serves a password-protected web console on it, so you can run shell commands on the suit from a phone without a keyboard or an SSH client.

1. Set the login at the very top of the file. The first two lines after the shebang are `ADMIN_USERNAME` and `ADMIN_PASSWORD`; the hotspot SSID, passphrase, interface, channel, address, and port follow under `# User Values:`.
2. Start it as root, since NetworkManager will not build an AP profile otherwise:
```bash
sudo python access_point.py
```
3. Join the `ProtoPi` network from your phone with `ACCESS_POINT_PASSPHRASE`, then open `http://192.168.4.1:8080/` and sign in.

The console keeps one working directory per login, so `cd` carries between commands. Sessions idle out after 15 minutes, five bad logins lock a client out for a minute, and commands are killed after 20 seconds. Ctrl+C kills the hotspot and deletes the `protopi-ap` profile it created.

The AP needs NetworkManager (the default on Raspberry Pi OS Bookworm and later) with `nmcli` on the path, and the Wi-Fi radio cannot be joined to another network at the same time. If `nmcli` is missing or refuses, the script says so and still serves the console on every interface, so it stays usable over Ethernet or an existing Wi-Fi connection.

The console page lives in [`web/`](web/) and is a React app written in JSX, one component per file:

```
web/
├── index.html                     loads the stylesheet, the vendor scripts, then each component
├── console.css                    every style the page uses
├── api.js                         fetch helpers shared by the components
├── main.jsx                       mounts <App /> into #root
├── components/
│   ├── App.jsx                    picks the login card or the console
│   ├── LoginCard.jsx              username, password, error message
│   ├── ConsoleCard.jsx            owns the transcript and runs commands
│   ├── ConsoleStatus.jsx          the ssid / ap / clients line in the header
│   ├── OutputPane.jsx             the scrolling transcript
│   └── PromptForm.jsx             the command box and its history
└── vendor/                        React, ReactDOM, and Babel, pinned and vendored
```

There is no build step. Babel compiles the JSX in the browser, so all edits are live and update on reload.

`access_point.py` serves that directory as static files and answers `/api/session`, `/login`, `/logout`, and `/run` as JSON.

Components are plain `function` declarations loaded as ordinary scripts, not ES modules, so there are no imports between them. A new component needs a `<script type="text/babel">` line in `index.html`, listed before whatever uses it.

### Tests

```bash
python tests/test_screen.py     # face and status screen, with fake hardware
python tests/test_console.py    # access point settings, console API, React render
```

Both run without the Pi. `test_console.py` starts a console on a loopback port, compiles every `.jsx` file with the vendored Babel when Node is installed, and renders the page in headless Chromium or Edge. Each of those two groups skips itself when its tool is missing, so the suite still passes on a bare Pi.

To run them automatically before every commit, install the hook once:

```bash
git config core.hooksPath tests/hooks
```

[`tests/hooks/pre-commit`](tests/hooks/pre-commit) compiles every script and runs both suites, and aborts the commit if anything fails. It uses `$VIRTUAL_ENV`, then `.venv`, then `python3`, then `PROTOPI_PYTHON` (user-defined) to point somewhere else. Skip for one commit with `git commit --no-verify`.

---
*This is a living document and will be updated with development*
