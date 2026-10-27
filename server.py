import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import serial

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")
PORT_NAME = os.environ.get("SCALE_COM_PORT", "COM3")
BAUD_RATE = 115200
HTTP_PORT = 5050

state_lock = threading.Lock()
state = {
    "connected": False,
    "port": PORT_NAME,
    "error": None,
    "target_mac": "78:66:a5:25:89:cb",
    "weight_kg": 0.0,
    "weight_raw": 0,
    "is_locked": False,
    "impedance": 0,
    "seq": 0,
    "header": "0xC0",
    "proto_flag": "0x0A",
    "unit_flag": "0x01",
    "lock_flag": "0x24",
    "checksum": "0x0A",
    "rssi": 0,
    "raw_hex": "",
    "mfg_hex": "",
    "diff_str": "",
    "mfg_bytes": [],
    "raw_bytes": [],
    "last_update": None,
    "packet_count": 0,
    "packets": [],
    "logs": [],
}

last_saved_signature = None
prev_mfg_bytes = None


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history_entry(entry):
    history = load_history()
    history.insert(0, entry)
    history = history[:100]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return history


def append_log(line):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    with state_lock:
        state["logs"].append({"time": ts, "text": line})
        if len(state["logs"]) > 200:
            state["logs"] = state["logs"][-200:]


def hex_to_bytes(hex_str):
    parts = [p for p in hex_str.strip().split() if re.fullmatch(r"[0-9A-Fa-f]{2}", p)]
    return [int(p, 16) for p in parts]


def extract_mfg_from_bytes(bytes_list):
    for i in range(len(bytes_list) - 14):
        if bytes_list[i] == 0xC0:
            return bytes_list[i : i + 15]
    return bytes_list[-15:] if len(bytes_list) >= 15 else bytes_list


def compute_mfg_diff(old_mfg, new_mfg):
    if not old_mfg or len(old_mfg) != len(new_mfg):
        return "ILK PAKET"
    diffs = []
    for i in range(len(new_mfg)):
        if old_mfg[i] != new_mfg[i]:
            diffs.append(f"b[{i}]:{old_mfg[i]:02X}->{new_mfg[i]:02X}")
    return " ".join(diffs) if diffs else "AYNI"


def apply_mfg_bytes(mfg, raw_bytes=None):
    """
    15-byte Manufacturer Data layout:
      b[0]    : 0xC0 (Header)
      b[1]    : Sequence counter
      b[2..3] : Weight uint16 BE (in 0.01 kg units -> / 100.0 = kg)
      b[4..5] : Impedance / Secondary uint16 BE
      b[6]    : Protocol byte (0x0A)
      b[7]    : Unit byte (0x01 = kg)
      b[8]    : Status / Lock byte (0x24 = measuring, 0x25 = locked -> bit 0 is lock)
      b[9..14]: Scale MAC (78:66:A5:25:89:CB)
    """
    global last_saved_signature, prev_mfg_bytes
    if not mfg or len(mfg) < 15:
        return

    mfg15 = mfg[:15]
    header = mfg15[0]
    seq = mfg15[1]
    w_raw = (mfg15[2] << 8) | mfg15[3]
    imp_raw = (mfg15[4] << 8) | mfg15[5]
    proto_flag = mfg15[6]
    unit_flag = mfg15[7]
    status_flag = mfg15[8]
    mac_embedded = ":".join(f"{b:02X}" for b in mfg15[9:15])

    weight_kg = round(w_raw / 100.0, 2)
    is_locked = (status_flag & 0x01) != 0
    mfg_hex_str = " ".join(f"{b:02X}" for b in mfg15)
    ts_ms = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    mfg_diff = compute_mfg_diff(prev_mfg_bytes, mfg15)
    prev_mfg_bytes = list(mfg15)

    with state_lock:
        if raw_bytes is not None:
            state["raw_bytes"] = raw_bytes
        state["mfg_bytes"] = mfg15
        state["mfg_hex"] = mfg_hex_str
        state["header"] = f"0x{header:02X}"
        state["seq"] = seq
        state["weight_raw"] = w_raw
        state["weight_kg"] = weight_kg
        state["impedance"] = imp_raw
        state["proto_flag"] = f"0x{proto_flag:02X}"
        state["checksum"] = f"0x{proto_flag:02X}"
        state["unit_flag"] = f"0x{unit_flag:02X}"
        state["lock_flag"] = f"0x{status_flag:02X}"
        state["is_locked"] = is_locked
        state["last_update"] = ts_ms

        pkt_entry = {
            "id": state["packet_count"],
            "time": ts_ms,
            "rssi": state["rssi"],
            "raw_hex": state["raw_hex"],
            "mfg_hex": mfg_hex_str,
            "mfg_bytes": mfg15,
            "header": header,
            "seq": seq,
            "weight_raw": w_raw,
            "weight_kg": weight_kg,
            "impedance": imp_raw,
            "proto_flag": proto_flag,
            "unit_flag": unit_flag,
            "status_flag": status_flag,
            "is_locked": is_locked,
            "mac_embedded": mac_embedded,
            "mfg_diff": mfg_diff,
            "raw_diff": state["diff_str"],
        }
        state["packets"].insert(0, pkt_entry)
        if len(state["packets"]) > 200:
            state["packets"] = state["packets"][:200]

        sig = (weight_kg, imp_raw, status_flag)
        if is_locked and weight_kg > 1.0 and sig != last_saved_signature:
            last_saved_signature = sig
            entry = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "weight_kg": weight_kg,
                "impedance": imp_raw,
                "seq": seq,
                "rssi": state["rssi"],
                "raw_hex": state["raw_hex"],
            }
            threading.Thread(target=save_history_entry, args=(entry,), daemon=True).start()


def parse_serial_line(line):
    line = line.strip()
    if not line:
        return

    append_log(line)

    # [TARTI 78:66:a5:25:89:cb] RSSI:-62 ...
    m_head = re.search(r"\[TARTI\s+([0-9A-Fa-f:]+)\]\s+RSSI:(-?\d+)", line)
    if m_head:
        with state_lock:
            state["target_mac"] = m_head.group(1)
            state["rssi"] = int(m_head.group(2))
            state["packet_count"] += 1
            state["diff_str"] = ""
        return

    # [DIFF]: b[3]:4B->4D ...
    if line.startswith("[DIFF]:"):
        diff_str = line.split("[DIFF]:", 1)[1].strip()
        with state_lock:
            state["diff_str"] = diff_str
            if state["packets"]:
                state["packets"][0]["raw_diff"] = diff_str
        return

    # [RAW]: 10 FF C0 4D 04 42 00 00 0A 01 24 78 66 A5 25 89 CB
    if line.startswith("[RAW]:"):
        raw_hex = line.split("[RAW]:", 1)[1].strip()
        raw_bytes = hex_to_bytes(raw_hex)
        mfg = extract_mfg_from_bytes(raw_bytes)
        with state_lock:
            state["raw_hex"] = raw_hex
        apply_mfg_bytes(mfg, raw_bytes)
        return


def release_arduino_serial_monitor():
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "serial-monitor.exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.4)
    except Exception:
        pass


def serial_worker():
    tried_release = False
    while True:
        try:
            with serial.Serial(PORT_NAME, BAUD_RATE, timeout=1) as ser:
                with state_lock:
                    state["connected"] = True
                    state["error"] = None
                append_log(f"[SISTEM] {PORT_NAME} ({BAUD_RATE} baud) baglantisi kuruldu.")
                tried_release = False

                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    text = raw.decode("utf-8", errors="replace")
                    parse_serial_line(text)
        except serial.SerialException as e:
            err_msg = str(e)
            if ("PermissionError" in err_msg or "Erişim engellendi" in err_msg) and not tried_release:
                tried_release = True
                append_log("[SISTEM] COM3 port kilidi aciliyor...")
                release_arduino_serial_monitor()
                continue

            with state_lock:
                state["connected"] = False
                state["error"] = err_msg
            time.sleep(2.0)
        except Exception as e:
            with state_lock:
                state["connected"] = False
                state["error"] = str(e)
            time.sleep(2.0)


class ScaleHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index.html"):
            index_path = os.path.join(BASE_DIR, "index.html")
            with open(index_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        if self.path == "/api/state":
            with state_lock:
                payload = dict(state)
            payload["history"] = load_history()[:25]
            self._send_json(payload)
            return

        self.send_error(404)

    def do_POST(self):
        if self.path == "/api/simulate":
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(raw_body.decode("utf-8"))
            except Exception:
                body = {}

            weight = float(body.get("weight_kg", 76.40))
            locked = bool(body.get("is_locked", True))
            imp = int(body.get("impedance", 510 if locked else 0))

            w_raw = int(round(weight * 100))
            w_h, w_l = (w_raw >> 8) & 0xFF, w_raw & 0xFF
            imp_h, imp_l = (imp >> 8) & 0xFF, imp & 0xFF

            with state_lock:
                seq = (state["seq"] + 1) & 0xFF
            status_byte = 0x25 if locked else 0x24
            mfg = [0xC0, seq, w_h, w_l, imp_h, imp_l, 0x0A, 0x01, status_byte, 0x78, 0x66, 0xA5, 0x25, 0x89, 0xCB]
            raw_hex = "10 FF " + " ".join(f"{b:02X}" for b in mfg)

            parse_serial_line("[TARTI 78:66:a5:25:89:cb] RSSI:-62 [SIMULASYON]")
            parse_serial_line(f"[RAW]: {raw_hex}")
            parse_serial_line(f"[DIFF]: b[4]:00->{w_h:02X} b[5]:00->{w_l:02X}")

            self._send_json({"ok": True})
            return

        if self.path == "/api/clear-history":
            with state_lock:
                state["packets"] = []
                state["logs"] = []
            try:
                if os.path.exists(HISTORY_FILE):
                    os.remove(HISTORY_FILE)
            except Exception:
                pass
            self._send_json({"ok": True})
            return

        if self.path == "/api/reclaim-port":
            release_arduino_serial_monitor()
            self._send_json({"ok": True})
            return

        self.send_error(404)


if __name__ == "__main__":
    t = threading.Thread(target=serial_worker, daemon=True)
    t.start()
    server = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), ScaleHTTPHandler)
    print(f"BLE Scale Web UI running on http://localhost:{HTTP_PORT}")
    server.serve_forever()
