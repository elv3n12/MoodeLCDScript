# LCD Daemon for Raspberry Pi – Audio Player & CD Ripper Display

This Python script controls a 4x20 I2C LCD screen connected to a Raspberry Pi, displaying in real time :

- The status of your USB DAC 
- CD audio ripping activity (abcde integration)
- Spotify playback info (from a spotmeta file)
- MPD (Music Player Daemon) playback info
- A custom idle/home splash screen

## Features

- **USB DAC detection** : Shows "SELECT PC-USB IN ON ROTEL AMP" if the USB DAC is not detected. (To be custimsed for your needs)
- **Automatic CD Ripping Display** : Shows rip progress and status (integration with abcde). 
- **Spotify Streaming Display** : Shows title, artist, album from a spotmeta file.
- **MPD Display** : Shows track, artist, album and real-time progress bar (Custom CGRAM Characters).
- **Text scrolling** : Titles/artists/albums scroll if too long for the display.
- **Custom Idle Mode** : Splash screen with current time.

## Compatible Hardware

- Raspberry Pi (tested on Pi 3/4/5)
- I2C HD44780 LCD 4x20 characters (typically at address 0x27)
- USB DAC (tested with Rotel, USB Audio 2.0…)

## Requirements

- Python 3
- [python-mpd2](https://pypi.org/project/python-mpd2/)
- [smbus](https://pypi.org/project/smbus2/) (or system package : `python3-smbus`)
- abcde (for CD ripping, if used)
- MPD and/or Spotifyd (for music playback)
- Access to the spotmeta file for Spotify (optional)

## Installation

```bash
# Clone the repo
git clone https://github.com/tonuser/MoodeLCDScript.git
cd MoodeLCDScript

# Install Python dependencies (adapt for your distro)
sudo apt-get install python3-smbus python3-pip
pip3 install python-mpd2

# Copy the script
sudo cp lcd-daemon.py /usr/local/bin/lcd-daemon.py
sudo chmod +x /usr/local/bin/lcd-daemon.py

# (Optional) Add the systemd service (see below)
# sudo cp lcd-daemon.service /etc/systemd/system/
# sudo systemctl enable --now lcd-daemon
```

For automatic launch, add the provided systemd service or create your own:

```bash
# /etc/systemd/system/lcd-daemon.service
[Unit]
Description=LCD Daemon for Audio Display

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/lcd-daemon.py
Restart=always
User=moode

[Install]
WantedBy=multi-user.target
```

Then enable it

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lcd-daemon
```

Customization
	•	DAC Name : set the DAC_NAME variable at the top of the script to match your output from cat /proc/asound/cards.
	•	LCD Address : change LCD_ADDR if needed (default 0x27).
	•	CD rip or spotmeta paths : adjust as needed for your setup.

Troubleshooting
	•	Nothing on screen? Check I2C connection (see i2cdetect -y 1).
	•	DAC not detected? Double-check the DAC_NAME variable.
	•	For any error, check logs (errors are displayed on the LCD, or redirect the script’s output to a log file).

Author

Script and README adapted by Vincent Beneche and ChatGPT.
