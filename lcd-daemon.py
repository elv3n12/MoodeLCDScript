#!/usr/bin/env python3
import os, time, glob, re, unicodedata, traceback, logging
from mpd import MPDClient

LCD_ADDR = 0x27
RIP_DIR_GLOB = "/mnt/NAS/RIP/abcde.*"
SPOTMETA = "/var/local/www/spotmeta.txt"
SPOT_TIMEOUT = 30
BACKLIGHT_ON = True
DAC_NAME = "USB Audio 2.0"

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

def clean_text(s):
    if not isinstance(s, str): return ""
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII')
    return "".join(c if 32 <= ord(c) <= 126 else " " for c in s)

def partial_scroll(fixed, scrolling, idx, scroll_len=13, line_len=20):
    if len(scrolling) <= scroll_len:
        return (fixed + scrolling).ljust(line_len)
    scrolltxt = scrolling + "   "
    pos = idx % len(scrolltxt)
    view = (scrolltxt * 2)[pos:pos+scroll_len]
    return (fixed + view).ljust(line_len)

def scroll(text, idx, line_len=20):
    if len(text) <= line_len: return text.ljust(line_len)
    text += "   "
    pos = idx % len(text)
    return (text * 2)[pos:pos+line_len]

def get_track_lengths_from_file(path="/mnt/NAS/RIP/track_durations.txt"):
    lengths = []
    try:
        with open(path) as f:
            for line in f:
                s = line.strip()
                if s.isdigit():
                    lengths.append(int(s))
    except Exception:
        pass
    return lengths

class I2C_LCD:
    def __init__(self, addr=LCD_ADDR, bus=1):
        import smbus
        self.bus = smbus.SMBus(bus)
        self.addr = addr
        self.bl = 0x08 if BACKLIGHT_ON else 0x00
        self._init_lcd()
        self.init_custom_chars()
    def _write4(self, nibble, mode=0):
        d = nibble | mode | self.bl
        self.bus.write_byte(self.addr, d)
        self.bus.write_byte(self.addr, d | 0x04)
        time.sleep(0.0005)
        self.bus.write_byte(self.addr, d)
        time.sleep(0.0005)
    def _write(self, b, mode=0):
        hi, lo = b & 0xF0, (b << 4) & 0xF0
        self._write4(hi, mode)
        self._write4(lo, mode)
    def _init_lcd(self):
        for cmd in (0x33, 0x32, 0x28, 0x0C, 0x0C, 0x06, 0x01):
            self._write(cmd)
            time.sleep(0.005)
    def write_line(self, text, line):
        addr_map = {1: 0x80, 2: 0xC0, 3: 0x94, 4: 0xD4}
        self._write(addr_map[line])
        for ch in text.ljust(20)[:20]:
            self._write(ord(ch), mode=0x01)
    def init_custom_chars(self):
        patterns = [
            [0b00000]*8, [0b10000]*8, [0b11000]*8, [0b11100]*8,
            [0b11110]*8, [0b11111]*8,
        ]
        for i, pat in enumerate(patterns):
            self._write(0x40 | (i << 3))
            for row in pat:
                self._write(row, mode=0x01)
        note1 = [0b00011,0b00010,0b00010,0b00010,0b00010,0b01110,0b01110,0b01110]
        self._write(0x40 | (6 << 3))
        for row in note1:
            self._write(row, mode=0x01)
        note2 = [0b11110,0b00010,0b00010,0b00010,0b01110,0b01110,0b01110,0b00000]
        self._write(0x40 | (7 << 3))
        for row in note2:
            self._write(row, mode=0x01)

def clean_artists(raw):
    raw = re.sub(r'[\|\u00A0]+', ',', raw)
    raw = re.sub(r'\s{2,}', ',', raw)
    artists = [a.strip() for a in raw.split(',') if a.strip()]
    return clean_text(', '.join(artists))

def ripping_cd():
    try:
        procs = os.popen("ps ax -o comm=").read()
        return any("abcde" in line for line in procs.splitlines())
    except Exception:
        return False

def usb_dac_present():
    try:
        with open("/proc/asound/cards") as f:
            content = f.read()
        return DAC_NAME in content
    except Exception:
        return False

def show_idle(lcd, reason=None):
    if reason == "no_dac":
        lcd.write_line("+------------------+", 1)
        lcd.write_line("| SELECT PC-USB IN |", 2)
        lcd.write_line("|   ON ROTEL AMP   |", 3)
        lcd.write_line("+------------------+", 4)
    else:
        lcd.write_line("+------------------+", 1)
        lcd.write_line(f"| <^_^>  {time.strftime('%H:%M:%S')}  |".ljust(20), 2)
        lcd.write_line("|LA PETITE MACHINE |", 3)
        lcd.write_line("+------------------+", 4)

def cd_tray_is_open():
    try:
        with open("/proc/sys/dev/cdrom/lock") as f:
            return f.read().strip() == "0"
    except Exception:
        return False

def read_cddbread(rip_dir):
    try:
        bread = glob.glob(os.path.join(rip_dir, "cddbread.*"))
        if not bread: return {}
        with open(bread[0]) as f:
            lines = f.readlines()
        info = {"tracks": 0, "track_titles": []}
        for l in lines:
            if l.startswith("DTITLE="):
                val = l.split("=",1)[1].strip()
                if " / " in val:
                    info['artist'], info['album'] = val.split(" / ",1)
                else:
                    info['album'] = val
            elif l.startswith("DYEAR="):
                info['year'] = l.split("=",1)[1].strip()
            elif l.startswith("TTITLE"):
                info.setdefault('tracks', 0)
                info['tracks'] += 1
                m = re.match(r'TTITLE(\d+)=(.*)', l)
                if m:
                    info.setdefault('track_titles', [])
                    info['track_titles'].append(m.group(2).strip())
        return info
    except Exception: return {}

def get_current_track_info(rip_dir):
    wavs = glob.glob(os.path.join(rip_dir, "track*.wav"))
    if not wavs:
        return None, 0, 1, 0
    wavs = sorted(wavs, key=os.path.getmtime, reverse=True)
    curfile = wavs[0]
    match = re.search(r'track(\d+).wav', curfile)
    idx = int(match.group(1)) if match else 0
    size = os.path.getsize(curfile)
    return curfile, idx, len(wavs), size

def progress_bar_cgram(elapsed, total, length=10):
    if not total or total == 0:
        return chr(0) * length
    frac = min(max(elapsed / total, 0), 1)
    blocks = int(frac * length)
    partial = int((frac * length - blocks) * 5)
    bar = ""
    for i in range(length):
        if i < blocks:
            bar += chr(5)
        elif i == blocks and partial > 0:
            bar += chr(partial)
        else:
            bar += chr(0)
    return bar

def parse_spotmeta(path):
    try:
        with open(path) as f:
            line = f.read().strip()
        fields = line.split("~~~")
        if len(fields) < 6: return None
        title, artist, album, duration_ms, covers, fmt = fields[:6]
        return {
            "title": title,
            "artist": artist,
            "album": album,
            "duration_ms": int(duration_ms) if duration_ms.isdigit() else 0,
            "format": fmt
        }
    except Exception:
        return None

def get_mpd_info():
    try:
        client = MPDClient()
        client.timeout = 2
        client.idletimeout = None
        client.connect("localhost", 6600)
        status = client.status()
        song = client.currentsong()
        if not song: client.close(); return None
        albumartist = song.get("albumartist", song.get("artist", ""))
        title = song.get("title", "")
        album = song.get("album", "")
        date = song.get("date", "")
        total = int(float(song.get("time", "0")))
        elapsed = float(status.get("elapsed", "0"))
        # Ajout : time du dernier changement de MPD
        mtime = None
        if "time" in status:
            # On n'a pas d'accès direct à la date de début du morceau, alors on approxime par "now - elapsed"
            mtime = time.time() - elapsed
        info = {
            "title": title,
            "artist": albumartist,
            "album": album,
            "elapsed": elapsed,
            "total": total,
            "mpd_mtime": mtime
        }
        client.close()
        return info
    except Exception:
        return None

def main():
    lcd = I2C_LCD()
    album_scroll_idx = 0
    track_scroll_idx = 0
    speed_samples = []
    speed_sample_window = 10
    prev_size = 0
    prev_time = time.time()

    while True:
        try:
            # 0. PRIORITÉ : Vérification DAC USB présent
            if not usb_dac_present():
                show_idle(lcd, reason="no_dac")
                time.sleep(1)
                continue

            # 1. RIP EN COURS ?
            dirs = glob.glob(RIP_DIR_GLOB)
            rip_dir = None
            if dirs:
                dirs = sorted(dirs, key=os.path.getmtime, reverse=True)
                for d in dirs:
                    wavs = glob.glob(os.path.join(d, "track*.wav"))
                    if wavs:
                        rip_dir = d
                        break

            if rip_dir:
                info = read_cddbread(rip_dir)
                track_titles = info.get('track_titles', [])
                album = clean_text(info.get('album', ''))
                artist = clean_text(info.get('artist', ''))
                year = info.get('year', '')
                track_total = info.get('tracks', 1)
                track_lengths = get_track_lengths_from_file()
                curfile, idx, wav_count, size = get_current_track_info(rip_dir)
                track_name = clean_text(track_titles[idx] if idx < len(track_titles) else f"Track {idx+1}")
                if idx < len(track_lengths) and track_lengths[idx] > 0:
                    final_size = track_lengths[idx] * 176400
                else:
                    final_size = 300 * 176400   # fallback: 5 min track
                if final_size < 1000000:
                    final_size = 1000000
                now = time.time()
                elapsed = now - prev_time
                size_delta = size - prev_size
                speed_mbps = (size_delta / (1024*1024)) / elapsed if elapsed > 0 else 0
                speed_samples.append(speed_mbps)
                if len(speed_samples) > speed_sample_window:
                    speed_samples = speed_samples[-speed_sample_window:]
                avg_speed_mbps = sum(speed_samples) / len(speed_samples) if speed_samples else 0
                speed_x = avg_speed_mbps / 0.146484375 if avg_speed_mbps > 0 else 0
                prev_size = size
                prev_time = now
                lcd.write_line("CD RIPPING...".ljust(20), 1)
                lcd.write_line(partial_scroll("Album: ", album, album_scroll_idx, 13), 2)
                album_scroll_idx += 1
                lcd.write_line(partial_scroll("Track: ", track_name, track_scroll_idx, 13), 3)
                track_scroll_idx += 1
                bar2 = progress_bar_cgram(size, final_size, length=10)
                idx_str = f"{idx+1}/{track_total}"
                lcd.write_line(f"{idx_str} {bar2[:8]} {speed_x:4.1f}x".ljust(20), 4)
                continue

            # --- LOGIQUE DERNIER ARRIVÉ ---
            spot = parse_spotmeta(SPOTMETA)
            mpd = get_mpd_info()
            now = time.time()

            spotmeta_exists = spot and spot.get("duration_ms", 0)
            spotmeta_mtime = None
            if spotmeta_exists:
                try:
                    spotmeta_mtime = os.path.getmtime(SPOTMETA)
                except Exception:
                    spotmeta_mtime = None

            mpd_active = mpd and mpd.get("total", 0) > 0 and mpd.get("elapsed", 0) < mpd.get("total", 0)
            mpd_mtime = mpd.get("mpd_mtime", 0) if mpd else 0

            # Conditions : qui afficher ?
            # Cas 1 : les 2 sont actifs
            if mpd_active and spotmeta_exists and spotmeta_mtime and mpd_mtime:
                if spotmeta_mtime > mpd_mtime:
                    # Spotify est plus récent
                    total = spot['duration_ms'] // 1000
                    elapsed = int(now - spotmeta_mtime)
                    if elapsed <= total + SPOT_TIMEOUT:
                        artist = clean_artists(spot["artist"])
                        title  = clean_text(spot["title"])
                        album  = clean_text(spot["album"])
                        lcd.write_line(scroll(artist, album_scroll_idx), 1)
                        lcd.write_line(scroll(title, track_scroll_idx), 2)
                        lcd.write_line(scroll(album, album_scroll_idx+track_scroll_idx), 3)
                        lcd.write_line(chr(6)+chr(7) + " Streaming Spotify".ljust(18), 4)
                        album_scroll_idx += 1
                        track_scroll_idx += 1
                        continue
                    # Sinon, Spotify expiré, on passe à MPD après.
                # MPD est plus récent
                artist = clean_text(mpd["artist"])
                title  = clean_text(mpd["title"])
                album  = clean_text(mpd["album"])
                bar = progress_bar_cgram(mpd["elapsed"], mpd["total"], length=10)
                lcd.write_line(scroll(artist, album_scroll_idx), 1)
                lcd.write_line(scroll(title, track_scroll_idx), 2)
                lcd.write_line(scroll(album, album_scroll_idx+track_scroll_idx), 3)
                mins, secs = divmod(int(mpd["elapsed"]), 60)
                tmins, tsecs = divmod(int(mpd["total"]), 60)
                lcd.write_line(f"{mins}:{secs:02d} {bar} {tmins}:{tsecs:02d}".ljust(20), 4)
                album_scroll_idx += 1
                track_scroll_idx += 1
                continue

            # Cas 2 : Spotify seul actif
            if spotmeta_exists and spotmeta_mtime:
                total = spot['duration_ms'] // 1000
                elapsed = int(now - spotmeta_mtime)
                if elapsed <= total + SPOT_TIMEOUT:
                    artist = clean_artists(spot["artist"])
                    title  = clean_text(spot["title"])
                    album  = clean_text(spot["album"])
                    lcd.write_line(scroll(artist, album_scroll_idx), 1)
                    lcd.write_line(scroll(title, track_scroll_idx), 2)
                    lcd.write_line(scroll(album, album_scroll_idx+track_scroll_idx), 3)
                    lcd.write_line(chr(6)+chr(7) + " Streaming Spotify".ljust(18), 4)
                    album_scroll_idx += 1
                    track_scroll_idx += 1
                    continue

            # Cas 3 : MPD seul actif
            if mpd_active:
                artist = clean_text(mpd["artist"])
                title  = clean_text(mpd["title"])
                album  = clean_text(mpd["album"])
                bar = progress_bar_cgram(mpd["elapsed"], mpd["total"], length=10)
                lcd.write_line(scroll(artist, album_scroll_idx), 1)
                lcd.write_line(scroll(title, track_scroll_idx), 2)
                lcd.write_line(scroll(album, album_scroll_idx+track_scroll_idx), 3)
                mins, secs = divmod(int(mpd["elapsed"]), 60)
                tmins, tsecs = divmod(int(mpd["total"]), 60)
                lcd.write_line(f"{mins}:{secs:02d} {bar} {tmins}:{tsecs:02d}".ljust(20), 4)
                album_scroll_idx += 1
                track_scroll_idx += 1
                continue

            # Idle sinon
            show_idle(lcd)

        except Exception as e:
            lcd.write_line("LCD error!         ", 1)
            lcd.write_line(str(e)[:20], 2)
            lcd.write_line(traceback.format_exc()[:20], 3)
            lcd.write_line("                   ", 4)
        time.sleep(0.2)

if __name__ == "__main__":
    main()
