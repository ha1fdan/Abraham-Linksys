# pi-scripts

A Raspberry Pi setup that broadcasts a Wi-Fi hotspot (`wlan0`), scans for and connects to available networks on a second adapter (`wlan1`), NATs traffic between them, and serves a status dashboard over HTTP.

## How it works

```
Clients ──► wlan0 (AP / hostapd) ──► wlan1 (client / nmcli) ──► Internet
                                           │
                                     flask_status.py
                                     http://192.168.50.1/
```

| Script | Role |
|---|---|
| `setup_ap.py` | Brings up the hotspot on `wlan0`, configures dnsmasq/hostapd, enables NAT |
| `wifi_connect.py` | Scans `wlan1` for open networks (or saved WPA profiles), connects, refreshes NAT rules |
| `flask_status.py` | Serves a live status dashboard on port 80 |

---

## Requirements

### Hardware
- Raspberry Pi with **two** Wi-Fi interfaces (`wlan0` + `wlan1`)
  - Built-in Wi-Fi acts as `wlan0` (AP)
  - A USB Wi-Fi dongle acts as `wlan1` (client/scanner)

### System packages

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq network-manager python3-pip
sudo systemctl unmask hostapd
```

### Python packages

```bash
pip3 install flask requests
```

---

## Installation

### 1. Clone / copy the scripts

```bash
sudo mkdir -p /opt/pi-scripts
sudo cp flask_status.py wifi_connect.py setup_ap.py /opt/pi-scripts/
sudo chmod +x /opt/pi-scripts/*.py
```

### 2. Configure

Edit the top of each script to match your setup:

**`setup_ap.py`**
```python
AP_INTERFACE = "wlan0"       # interface to broadcast AP on
AP_SSID      = "PiHotspot"  # hotspot name
AP_PASSWORD  = "raspberry"  # WPA2 password (min 8 chars, or "" for open)
AP_IP        = "192.168.50.1"
UPSTREAM_IF  = "wlan1"      # client/scanning interface
```

**`wifi_connect.py`**
```python
INTERFACE    = "wlan1"      # client/scanning interface
AP_INTERFACE = "wlan0"      # AP interface (for NAT refresh)
```

### 3. Create systemd services

**`/etc/systemd/system/pi-ap.service`**
```ini
[Unit]
Description=Pi Access Point
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/pi-scripts/setup_ap.py
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/pi-wifi.service`**
```ini
[Unit]
Description=Pi Wi-Fi Scanner / Connector
After=pi-ap.service
Requires=pi-ap.service

[Service]
ExecStart=/usr/bin/python3 /opt/pi-scripts/wifi_connect.py
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/pi-status.service`**
```ini
[Unit]
Description=Pi Status Web Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/pi-scripts/flask_status.py
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

Enable and start all three:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pi-ap pi-wifi pi-status
sudo systemctl start pi-ap pi-wifi pi-status
```

---

## Usage

1. Connect a device to the **`PiHotspot`** Wi-Fi network
2. Open a browser and go to **`http://192.168.50.1/`**
3. The dashboard shows the Pi's upstream connection status and IP, refreshing every 5 seconds

### Check logs

```bash
sudo journalctl -u pi-ap     -f
sudo journalctl -u pi-wifi   -f
sudo journalctl -u pi-status -f
```

---

## Connection priority

`wifi_connect.py` follows this order on each scan cycle (every 30 s):

1. **Open networks** — always preferred; MAC is randomized before connecting
2. **Saved WPA profiles** (via `nmcli connection up`)
3. **Known WPA networks in range** (matched against NetworkManager profiles)

If no network is found, it retries after 30 seconds.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Hotspot not visible | `sudo journalctl -u pi-ap` — hostapd may not support AP mode on your adapter |
| No internet on hotspot | `sudo iptables -t nat -L` — NAT rules should show a MASQUERADE rule |
| Status page offline | `sudo systemctl status pi-status` — Flask may not be running |
| `wlan1` not connecting | `nmcli dev status` — confirm the interface is unmanaged/managed correctly |
