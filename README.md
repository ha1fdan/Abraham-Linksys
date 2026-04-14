# Abraham Linksys - Raspberry Pi WiFi Gateway

A Raspberry Pi that automatically hunts for open WiFi networks, connects with a randomized MAC address, and shares the connection via a local access point. Includes a web dashboard showing live connection status.

---

## How It Works

```
[ Open WiFi / WPA Network ]
          ↓
       wlan1  ←── scans & connects (random MAC on open networks)
          ↓
      Raspberry Pi
          ↓
       wlan0  ──→ AP: "Abraham Linksys"  ──→ your devices
          ↓
    Flask dashboard @ :80
```

**Priority order:**
1. Open networks (random MAC, no credentials needed)
2. Saved WPA profiles (e.g. your home network)

---

## Files

| File | Description |
|------|-------------|
| `wifi_connect.py` | Main loop — scans, connects, updates Flask status, refreshes NAT |
| `setup_ap.py` | Brings up the hostapd access point on `wlan0` + NAT routing |
| `flask_status.py` | Web dashboard + `/status` JSON API |
| `wifi-connect.service` | systemd unit for `wifi_connect.py` |
| `wifi-ap.service` | systemd unit for `setup_ap.py` |
| `flask-status.service` | systemd unit for `flask_status.py` |
| `status.json` | Fallback status file if Flask HTTP is unreachable |

---

## Requirements

```bash
sudo apt install hostapd dnsmasq python3-flask python3-requests -y
```

---

## Installation

```bash
# Copy scripts
sudo mkdir -p /opt/pi-scripts
sudo cp wifi_connect.py setup_ap.py flask_status.py status.json /opt/pi-scripts/

# Copy and enable services
sudo cp wifi-ap.service wifi-connect.service flask-status.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wifi-ap.service wifi-connect.service flask-status.service
sudo systemctl start wifi-ap.service wifi-connect.service flask-status.service
```

---

## Configuration

### `setup_ap.py`
| Variable | Default | Description |
|----------|---------|-------------|
| `AP_INTERFACE` | `wlan0` | Interface to run the AP on (built-in chip) |
| `AP_SSID` | `PiHotspot` | AP network name |
| `AP_PASSWORD` | `raspberry` | AP password — set `""` for open AP |
| `AP_CHANNEL` | `6` | WiFi channel |
| `AP_IP` | `192.168.50.1` | Pi's IP on the hotspot network |
| `UPSTREAM_IF` | `wlan1` | Client/scanner interface |

### `wifi_connect.py`
| Variable | Default | Description |
|----------|---------|-------------|
| `INTERFACE` | `wlan1` | Interface used for scanning/connecting |
| `AP_INTERFACE` | `wlan0` | AP interface (for NAT rule updates) |
| `FLASK_STATUS_URL` | `http://localhost/status` | Flask endpoint to POST status updates |
| `RETRY_INTERVAL` | `30` | Seconds between scan cycles |
| `CONNECT_TIMEOUT` | `30` | Seconds before giving up on a connection attempt |

---

## Interfaces

| Interface | Role | Notes |
|-----------|------|-------|
| `wlan0` | Access Point | Built-in BCM chip — `dc:a6:32:...` |
| `wlan1` | Client / Scanner | USB dongle (RTL8192EU) — `d0:37:45:...` |
| `eth0` | Ethernet | Available as fallback |
| `tailscale0` | VPN | Remote SSH access |

---

## Web Dashboard

Access at `http://192.168.50.1` from any device connected to the AP, or `http://<pi-eth0-ip>` over ethernet.

- Live online/offline status with animated indicator
- Current IP address
- Event log of connection changes
- Auto-refreshes every 5 seconds

**API endpoints:**

```
GET  /status   → {"status": "online"|"offline", "ip": "x.x.x.x"|null}
POST /status   → update status (called by wifi_connect.py)
GET  /history  → list of all status change events since boot
```

---

## MAC Randomization

When connecting to open networks, `wlan1` is assigned a random locally-administered MAC before each attempt:

- Locally administered bit set (`0x02`) — signals a software-generated address
- Unicast bit clear (`& 0xFE`)
- New random MAC generated for every open network attempt
- WPA connections use the real hardware MAC

---

## NAT / Internet Sharing

`setup_ap.py` enables IP forwarding and sets up iptables masquerade so devices on the AP can reach the internet through whatever upstream `wlan1` is connected to. Rules are refreshed automatically whenever `wlan1` switches networks.

To persist iptables rules across reboots:
```bash
sudo apt install iptables-persistent -y
sudo netfilter-persistent save
```

---

## Troubleshooting

**wlan1 shows NO-CARRIER / not scanning:**
```bash
sudo nmcli device set wlan1 managed yes
sudo nmcli dev wifi list ifname wlan1
```

**AP not visible / hostapd fails:**
```bash
iw phy phy0 info | grep -A 10 "Supported interface modes"
# wlan0 must support AP mode
sudo journalctl -u wifi-ap.service -f
```

**Status stuck at offline:**
```bash
curl localhost/status
sudo journalctl -u wifi-connect.service -f
sudo journalctl -u flask-status.service -f
```

**Check all services:**
```bash
sudo systemctl status wifi-ap.service wifi-connect.service flask-status.service
```
