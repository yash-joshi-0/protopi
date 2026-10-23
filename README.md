# ProtoPi: A Raspberry Pi solution for Protogen Fursuits

| Feature   | Status    |
|---        |---        |
|MAX7219 Support    | ![static badge](https://img.shields.io/badge/Basic%20Support-29BF12)  |
|XFP111X Support    | ![static badge](https://img.shields.io/badge/Done-29BF12) |
|HUB75 Support    | ![static badge](https://img.shields.io/badge/Not%20Started-FE0B0B)  |
|Wireless Access Point    | ![static badge](https://img.shields.io/badge/In%20Progress-F0C808)  |
|Admin Console    | ![static badge](https://img.shields.io/badge/In%20Progress-F0C808)  |
|Config/Communicate Page    | ![static badge](https://img.shields.io/badge/In%20Progress-F0C808)  |

### Beginner's guide

This walks you from a blank SD card to a working face, hotspot, chat, and admin console. You don't need to know Linux or Python. Every command below is meant to be copied and pasted exactly as written; when one contains a word you need to change, the text right before it says so.

#### What you need

- A Raspberry Pi with Wi-Fi and a 40-pin header: a Pi Zero W, Zero 2 W, 3, 4, or 5. A Pi Zero needs the pin header soldered on, or buy the "WH" version that comes with one.
- A microSD card of 8 GB or more, and a way to plug it into your computer.
- A power supply for the Pi.
- 14 MAX7219 8×8 LED matrix modules chained together, a push button for the boop, and optionally an XFP111X status screen.
- A computer on the same Wi-Fi network you want the Pi to join.

#### 1. Put Raspberry Pi OS on the SD card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your computer and open it.
2. Choose your Pi model, then **Raspberry Pi OS Lite** (it's under "Raspberry Pi OS (other)"; the face doesn't need a desktop), then your SD card.
3. When Imager offers to customise the settings, say yes and fill in:
   - a **hostname**, the Pi's name on the network, for example `protopi`
   - a **username and password**, for example `pi`; you'll type these a lot, so remember them
   - your home **Wi-Fi name and password**, and your **Wi-Fi country**
   - **SSH**, switched on, with password login
4. Write the card. Imager erases it, so make sure nothing on it matters.
5. Put the card in the Pi and plug in the power. The first start takes a few minutes, especially on a Pi Zero.

#### 2. Connect to the Pi from your computer

You control the Pi by typing commands into a terminal on your computer. On Windows, open **PowerShell** from the Start menu; on a Mac, open **Terminal**. Then type this, replacing `pi` with your username and `protopi` with your hostname:

```bash
ssh pi@protopi.local
```

The first time, it asks whether you trust the Pi; type `yes` and press Enter. Then type your password. **Nothing appears on the screen while you type the password; that's normal.** When you see a line ending in `$`, you're typing commands on the Pi. To leave, type `exit`.

#### 3. Download ProtoPi and install what it needs

Paste these one block at a time and wait for each to finish. The install steps can take several minutes, and much longer on a Pi Zero.

```bash
sudo apt update
sudo apt install -y git python3-dev python3-pip python3-venv \
                    libjpeg-dev libfreetype6-dev libopenjp2-7 libtiff-dev \
                    build-essential
```

```bash
cd ~
git clone https://github.com/yash-joshi-0/protopi.git
cd ~/protopi
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The first block installs the tools ProtoPi is built from. The second downloads ProtoPi into a folder called `protopi` and installs its Python libraries into `.venv`, a private folder that only ProtoPi uses.

#### 4. Turn on SPI

SPI is how the Pi talks to the LED matrices and the status screen. Run:

```bash
sudo raspi-config
```

Use the arrow keys and Enter to pick **Interface Options**, then **SPI**, then **Yes**, then **OK**. Back on the main menu, press Tab twice to highlight **Finish** and press Enter. If you have the status screen, also run this line, which switches on the second SPI connection it uses:

```bash
echo "dtoverlay=spi1-1cs" | sudo tee -a /boot/firmware/config.txt
```

Then shut the Pi down before wiring anything:

```bash
sudo shutdown now
```

Wait until the green light on the Pi stops flashing, then unplug the power.

#### 5. Wire up the hardware

With the Pi unplugged, connect the matrices, the button, and the status screen exactly as listed in [`pin_connections.md`](pin_connections.md). The table there is laid out like the pins on the Pi itself: pin 1 is the corner pin closest to the SD card slot, and often has a square solder pad. Double-check each wire before you plug the power back in, then reconnect with `ssh` as in step 2.

#### 6. Run the face

```bash
cd ~/protopi
.venv/bin/python max7219.py
```

If you have the status screen, add ` --screen` to the end of the second line. The program first asks `Configure matrix transforms? (y/N)`:
- Type `n` and press Enter to use the saved panel layout. The face appears and starts blinking, and pressing the button makes it react.
- Type `y` if some panels look rotated or mirrored. The program goes through the 14 panels one at a time and marks the current panel with a 2×2 block of lights (the others show a single dot). Type `r` or `l` to rotate the panel, or `x` or `y` to flip it, pressing Enter after each letter, until the block sits in the panel's top-left corner as you look at it. Then press Enter on its own to move to the next panel. Your layout is saved to `matrix_config.txt`, so you only do this once.

Press **Ctrl+C** to stop the face.

#### 7. Run the hotspot, chat, and admin console

First, set your own admin password. Open the file in the `nano` text editor:

```bash
cd ~/protopi
nano access_point.py
```

The third line reads `ADMIN_PASSWORD = "change-me-before-use"`. Use the arrow keys to get there, and replace the text between the quotes with a password of your own. Save with **Ctrl+O** then **Enter**, and leave with **Ctrl+X**.

Now start the hotspot. **Your SSH connection will freeze or drop a few seconds after this; that's expected.** The hotspot takes over the Pi's Wi-Fi, so the Pi leaves your home network.

```bash
sudo nohup python3 access_point.py > access_point.log 2>&1 &
```

On your phone, join the Wi-Fi network **ProtoPi** with the password `protopi-hotspot`. Then open the browser and go to:
- `http://192.168.4.1:8080/` for the chat
- `http://192.168.4.1:8080/admin` for the admin console. Sign in as `protogen` with the password you just set. You can type the same commands there as over SSH.

To stop the hotspot, type this into the admin console:

```bash
sudo pkill -f access_point.py
```

The page stops responding, because the hotspot has just switched off. The Pi rejoins your home Wi-Fi within a minute or so, and you can connect with `ssh` again as in step 2.

#### 8. Run everything on the suit

Connect with `ssh` while the Pi is still on your home Wi-Fi, then start both programs in the background so they keep running after you disconnect:

```bash
cd ~/protopi
echo n | nohup .venv/bin/python max7219.py > face.log 2>&1 &
sudo nohup python3 access_point.py > access_point.log 2>&1 &
```

The `echo n` answers the calibration question for you. Add ` --screen` after `max7219.py` if you have the status screen. Your SSH connection drops when the hotspot starts. From then on, reach the Pi through the ProtoPi network: open the admin console as in step 7, or join ProtoPi on your computer and use `ssh pi@192.168.4.1`. If something isn't working, `face.log` and `access_point.log` in the `protopi` folder show what each program printed.

ProtoPi doesn't start by itself when the Pi powers on yet, so you need to repeat this step after every power-up, from a network the Pi already knows.

#### 9. Turn it off safely

**Never just unplug the Pi while it's on.** Pulling the power can corrupt the SD card. Instead, run this over SSH or in the admin console:

```bash
sudo shutdown now
```

Wait until the green light stops flashing (about half a minute), then unplug it.

#### If something goes wrong

- **`ssh` says it can't find `protopi.local`:** give the Pi a few more minutes after the first power-up. If it still can't be found, rewrite the card in Imager and check the Wi-Fi name, password, and country. Your router's list of connected devices also shows the Pi's address, which you can use instead of `protopi.local`.
- **`ssh` warns that the remote host identification has changed:** this happens after you rewrite the card. Run `ssh-keygen -R protopi.local` on your computer, then connect again.
- **The face doesn't light up:** check the wiring against `pin_connections.md`, and check that SPI is on: `ls /dev/spidev*` should list `/dev/spidev0.0`.
- **The status screen stays blank:** `ls /dev/spidev*` should also list `/dev/spidev1.0`. If it doesn't, run the `dtoverlay` line from step 4 and reboot.
- **The phone joins ProtoPi but the page won't load:** type the address exactly as shown, starting with `http://` and ending in `:8080/`. If the phone says the network has no internet, choose to stay connected.

### Face and status screen

1. Clone the repository into a folder of your choice with `git clone`.
2. Install the system packages and the Python dependencies:
```bash
sudo apt install python3-dev python3-pip \
                 libjpeg-dev \
                 libfreetype6-dev \
                 libopenjp2-7 \
                 libtiff-dev \
                 build-essential

python3 -m venv .venv
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

4. Configure matrix rotation with `python max7219.py`. This currently only works with 14 matrices.
```bash
python max7219.py            # face only
python max7219.py --screen   # face plus the XFP111X status screen
```

Without `--screen` the program never opens SPI1. With the flag it still falls back to the face alone when the screen is missing, and prints the `/dev/spidev` node it could not open.

### Wireless access point and admin console

`access_point.py` turns the Pi's Wi-Fi into a hotspot and serves a chat at `/` and a password-protected admin console at `/admin` for running shell commands on the suit from a phone without a keyboard or an SSH client.

1. Set the login at the very top of the file. The first two lines after the shebang are `ADMIN_USERNAME` and `ADMIN_PASSWORD`; the hotspot SSID, passphrase, interface, channel, address, and port follow under `# User Values:`.
2. Start it as root, since NetworkManager will not build a hotspot profile otherwise. If you are connected to the Pi over SSH, read [Starting over SSH](#starting-over-ssh) first:
```bash
sudo python3 access_point.py
```
3. Join the `ProtoPi` network from your phone with `ACCESS_POINT_PASSPHRASE`, then open `http://192.168.4.1:8080/` for the chat, or `http://192.168.4.1:8080/admin` to sign in to the console.

The console keeps one working directory per login, so `cd` carries between commands. Sessions idle out after 15 minutes, five bad logins lock a client out for a minute, and commands are killed after 20 seconds. Ctrl+C kills the hotspot and deletes the `protopi-ap` profile it created.

The hotspot needs NetworkManager (the default on Raspberry Pi OS Bookworm and later) with `nmcli` on the path, and the Wi-Fi radio hosting it cannot be joined to another network at the same time. If `nmcli` is missing or refuses, the script says so and still serves the console on every interface, so it stays usable over Ethernet or an existing Wi-Fi connection.

#### Starting over SSH

The hotspot takes over `wlan0`, so if you are connected to the Pi over SSH through that same Wi-Fi, your session drops the moment the hotspot comes up. The script warns about this before it starts. When the session drops, the script takes the hotspot down and deletes its profile, so the Pi rejoins your Wi-Fi and you can SSH back in. To keep the hotspot running after you disconnect, start it detached and then join the `ProtoPi` network instead:

```bash
sudo nohup python3 access_point.py > access_point.log 2>&1 &
```

Stop it later with `sudo pkill -f access_point.py`, which also cleans up. With a USB Wi-Fi adapter on your home network ([see below](#internet-over-a-usb-wi-fi-adapter)), SSH over the adapter is not affected.

#### Internet over a USB Wi-Fi adapter

Plug in a USB Wi-Fi adapter and the script uses it for the internet while the onboard radio keeps hosting the hotspot and the web pages. On start it reads `/sys/class/net` to tell the USB radio from the onboard one, joins a saved network on the USB adapter, and only then brings the hotspot up. If the USB adapter claimed `wlan0`, the hotspot moves to the onboard radio on its own and says so. Phones on the hotspot also reach the internet through the adapter, and the admin console shows `uplink wlan1` (or `uplink off`) beside the client count.

The adapter only joins networks NetworkManager already knows. Save one for it once, from the Pi or the admin console:

```bash
sudo nmcli device wifi connect "<ssid>" password "<password>" ifname wlan1
```

Without an adapter, or when no saved network is in range, the script warns and runs the hotspot alone as before. Keep `ACCESS_POINT_ADDRESS` off the subnet of the network the adapter joins; the script warns if they overlap.

### Chat

Messages are stored in `chat.db`, a SQLite file created beside `access_point.py` on first run and ignored by git. One table:

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at_ms INTEGER NOT NULL
)
```

The page asks for the newest `CHAT_HISTORY_LIMIT` messages and the server refuses a message longer than `MAXIMUM_MESSAGE_LENGTH` or a name longer than `MAXIMUM_USERNAME_LENGTH`; all three are under `# Configuration values:`. Delete `chat.db` to clear the history.

The chat is unauthenticated, so there is no way to stop anyone from sending anything, but it is covered to prevent SQL injection and the like.

### Web pages

Both pages live in [`web/`](web/) as a React app written in JSX, one component per file:

```
web/
├── index.html                     loads the stylesheet, the vendor scripts, then each component
├── console.css                    every style both pages use
├── api.js                         fetch helpers shared by the components
├── main.jsx                       mounts <App /> into #root
├── components/
│   ├── App.jsx                    routes on the address bar: /admin or the chat
│   ├── ChatPage.jsx               the main screen, holds the messages and polls
│   ├── ChatForm.jsx               name and message boxes, remembers the name
│   ├── MessageList.jsx            the stored messages with their times
│   ├── AdminPage.jsx              login card until signed in, then the console
│   ├── LoginCard.jsx              username, password, error message
│   ├── ConsoleCard.jsx            owns the transcript and runs commands
│   ├── ConsoleStatus.jsx          the ssid / ap / clients / uplink line in the header
│   ├── OutputPane.jsx             the scrolling transcript
│   └── PromptForm.jsx             the command box and its history
└── vendor/                        React, ReactDOM, and Babel, pinned and vendored
```

There is no build step. Babel compiles the JSX in the browser, so all edits are live and update on reload.

`access_point.py` serves that directory as static files, serves the page itself for `/` and `/admin`, and answers `/api/messages`, `/api/session`, `/login`, `/logout`, and `/run` as JSON.

Components are plain `function` declarations loaded as ordinary scripts, not ES modules, so there are no imports between them. A new component needs a `<script type="text/babel">` line in `index.html`, listed before whatever uses it.

#### Editing the pages on your computer

`access_point.py` uses only the Python standard library, so it runs on any computer with Python 3.10 or newer, with no venv and no `pip install`:

```bash
cd protopi
python access_point.py
```

Open `http://localhost:8080/` for the chat or `http://localhost:8080/admin` for the console, edit anything in `web/`, and reload the page to see the change. Stop it with Ctrl+C.

Off the Pi there is no `nmcli`, so the script prints warnings, skips the hotspot, and serves the pages anyway. Two things differ from the Pi:
- It listens on every network interface, not only localhost, so anyone on your local network can reach the admin console while it runs. Change `ADMIN_PASSWORD` from the default first.
- Console commands need bash. On Windows they fail with `WinError 2` until you point `CONSOLE_SHELL` at Git Bash, for example `C:/Program Files/Git/bin/bash.exe`.

### Tests

```bash
python tests/test_screen.py     # face and status screen, with fake hardware
python tests/test_console.py    # access point, chat database, console API, React render
```

Both run without the Pi. `test_console.py` starts a console on a loopback port, compiles every `.jsx` file with the vendored Babel when Node is installed, renders the page in headless Chromium or Edge, and runs real commands through bash. Each of those groups skips itself when its tool is missing, and the stop-signal check skips itself on Windows, so the suite still passes on a bare Pi or a Windows machine.

To run them automatically before every commit, install the hook once:

```bash
git config core.hooksPath tests/hooks
```

[`tests/hooks/pre-commit`](tests/hooks/pre-commit) compiles every script and runs both suites, and aborts the commit if anything fails. It uses `PROTOPI_PYTHON` if you set it, then `$VIRTUAL_ENV`, then `.venv`, then `python3`, then `python`. Skip for one commit with `git commit --no-verify`.

---
*This is a living document and will be updated with development*