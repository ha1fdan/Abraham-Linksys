#!/usr/bin/env python3
"""
wifi_connect.py — Scan for open networks on wlan0, connect, and update Flask status.
Run as root (required for nmcli/iwconfig).
"""

import subprocess
import time
import json
import logging
import os
import sys
import random
import requests

# ── Config ────────────────────────────────────────────────────────────────────
INTERFACE       = "wlan1"
AP_INTERFACE    = "wlan0"           # AP interface to refresh NAT rules for
FLASK_STATUS_URL = "http://localhost/status"   # your Flask endpoint
STATUS_FILE     = "/opt/pi-scripts/status.json"     # fallback file if Flask HTTP fails
RETRY_INTERVAL  = 30   # seconds between scan retries
CONNECT_TIMEOUT = 30   # seconds to wait for IP after connecting

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def randomize_mac(interface: str):
    """Assign a random locally-administered unicast MAC to the interface."""
    # First byte: locally administered (bit 1 set) + unicast (bit 0 clear)
    first_byte = (random.randint(0x00, 0xFF) & 0xFE) | 0x02
    mac = "{:02x}:{}".format(
        first_byte,
        ":".join(f"{random.randint(0x00, 0xFF):02x}" for _ in range(5))
    )
    try:
        subprocess.run(["ip", "link", "set", interface, "down"], check=True)
        subprocess.run(["ip", "link", "set", interface, "address", mac], check=True)
        subprocess.run(["ip", "link", "set", interface, "up"], check=True)
        log.info(f"MAC randomized → {mac}")
    except subprocess.CalledProcessError as e:
        log.error(f"Failed to set MAC address: {e}")


def try_saved_connections(interface: str) -> bool:
    """Tell NetworkManager to explicitly connect saved profiles on this interface.
    Handles cases where the profile is bound to a different interface name."""
    try:
        # Ensure NM is managing this interface
        subprocess.run(
            ["nmcli", "device", "set", interface, "managed", "yes"],
            capture_output=True, check=False
        )

        # Get all saved wifi profiles that use WPA (skip open ones)
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=10
        )
        profiles = [
            line.split(":")[0].strip()
            for line in result.stdout.splitlines()
            if "802-11-wireless" in line
        ]

        # Filter to only WPA profiles (those with a psk or key-mgmt set)
        wpa_profiles = []
        for profile in profiles:
            detail = subprocess.run(
                ["nmcli", "-t", "-f", "802-11-wireless-security.key-mgmt",
                 "connection", "show", profile],
                capture_output=True, text=True, timeout=5
            )
            key_mgmt = detail.stdout.strip().split(":")[-1]
            if key_mgmt and key_mgmt not in ("--", ""):
                wpa_profiles.append(profile)

        for profile in wpa_profiles:
            log.info(f"Trying saved profile '{profile}' on {interface} ...")
            result = subprocess.run(
                ["nmcli", "connection", "up", profile, "ifname", interface],
                capture_output=True, text=True, timeout=CONNECT_TIMEOUT
            )
            if result.returncode == 0:
                time.sleep(5)
                ip = get_ip(interface)
                if ip:
                    log.info(f"Profile '{profile}' connected on {interface}, IP={ip}")
                    return True
        return False
    except Exception as e:
        log.error(f"try_saved_connections failed: {e}")
        return False


def scan_known_wpa_networks(interface: str) -> list[str]:
    """Return SSIDs that are both in range AND have a saved WPA profile in NetworkManager."""
    try:
        # Get all SSIDs currently in range with their security type
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SECURITY", "dev", "wifi", "list", "ifname", interface],
            capture_output=True, text=True, timeout=15
        )
        in_range_wpa = set()
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                ssid     = parts[0].strip()
                security = parts[1].strip()
                if ssid and security not in ("", "--"):   # has encryption
                    in_range_wpa.add(ssid)

        # Get SSIDs that have a saved connection profile in NetworkManager
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=10
        )
        saved_ssids = set()
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1].strip() == "802-11-wireless":
                saved_ssids.add(parts[0].strip())

        known = list(in_range_wpa & saved_ssids)
        log.info(f"Found {len(known)} known WPA network(s) in range: {known}")
        return known
    except Exception as e:
        log.error(f"Known WPA scan failed: {e}")
        return []


def scan_open_networks(interface: str) -> list[str]:
    """Return a list of SSIDs for open (no encryption) networks."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SECURITY", "dev", "wifi", "list", "ifname", interface],
            capture_output=True, text=True, timeout=15
        )
        open_ssids = []
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                ssid     = parts[0].strip()
                security = parts[1].strip()
                if ssid and security in ("", "--"):   # open network
                    open_ssids.append(ssid)
        log.info(f"Found {len(open_ssids)} open network(s): {open_ssids}")
        return open_ssids
    except Exception as e:
        log.error(f"Scan failed: {e}")
        return []


def connect_to_ssid(ssid: str, interface: str) -> bool:
    """Attempt to connect to an SSID using nmcli."""
    try:
        log.info(f"Trying to connect to '{ssid}' ...")
        subprocess.run(
            ["nmcli", "dev", "wifi", "connect", ssid, "ifname", interface],
            capture_output=True, text=True, timeout=CONNECT_TIMEOUT, check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        log.warning(f"nmcli connect failed for '{ssid}': {e.stderr.strip()}")
        return False
    except subprocess.TimeoutExpired:
        log.warning(f"Connection to '{ssid}' timed out.")
        return False


def get_ip(interface: str) -> str | None:
    """Return the IPv4 address of the interface, or None."""
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", interface],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1].split("/")[0]
    except Exception:
        pass
    return None


def ensure_status_file():
    """Create the fallback status file if it doesn't exist yet."""
    if not os.path.exists(STATUS_FILE):
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w") as f:
            json.dump({"status": "offline", "ip": None}, f, indent=2)
        log.info(f"Created {STATUS_FILE}")


def update_flask_status(ip: str):
    """POST/PATCH the Flask server to flip status → online."""
    payload = {"status": "online", "ip": ip}

    # Option A: HTTP request to Flask
    try:
        resp = requests.post(FLASK_STATUS_URL, json=payload, timeout=5)
        log.info(f"Flask updated via HTTP: {resp.status_code} {resp.text}")
        return
    except requests.RequestException as e:
        log.warning(f"HTTP update failed ({e}), falling back to file write.")

    # Option B: Write directly to the JSON file Flask serves
    try:
        with open(STATUS_FILE, "r+") as f:
            data = json.load(f)
            data["status"] = "online"
            data["ip"]     = ip
            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
        log.info(f"Status file updated: {STATUS_FILE}")
    except Exception as e:
        log.error(f"File update also failed: {e}")


def is_connected(interface: str) -> bool:
    return get_ip(interface) is not None


def refresh_nat(upstream: str):
    """Update iptables NAT rules to forward AP traffic via the new upstream."""
    try:
        # Remove old rules (ignore errors if they don't exist yet)
        for ipt_args in [
            ["-t", "nat", "-D", "POSTROUTING", "-o", upstream, "-j", "MASQUERADE"],
            ["-D", "FORWARD", "-i", AP_INTERFACE, "-o", upstream,
             "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
            ["-D", "FORWARD", "-i", upstream, "-o", AP_INTERFACE, "-j", "ACCEPT"],
        ]:
            subprocess.run(["iptables"] + ipt_args,
                           capture_output=True, check=False)

        # Add fresh rules
        subprocess.run(
            ["iptables", "-t", "nat", "-A", "POSTROUTING",
             "-o", upstream, "-j", "MASQUERADE"], check=True)
        subprocess.run(
            ["iptables", "-A", "FORWARD", "-i", AP_INTERFACE, "-o", upstream,
             "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"], check=True)
        subprocess.run(
            ["iptables", "-A", "FORWARD", "-i", upstream, "-o", AP_INTERFACE,
             "-j", "ACCEPT"], check=True)

        log.info(f"NAT refreshed: {AP_INTERFACE} → {upstream}")
    except Exception as e:
        log.error(f"NAT refresh failed: {e}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    log.info(f"wifi_connect starting on interface {INTERFACE}")
    ensure_status_file()

    connected_to_open = False   # track whether current connection is an open network

    while True:
        # Always scan for open networks — they take priority over everything
        open_ssids = scan_open_networks(INTERFACE)

        if open_ssids:
            # If we're already on an open network, stay unless a better one appears
            if connected_to_open and is_connected(INTERFACE):
                ip = get_ip(INTERFACE)
                log.info(f"Already on open network, IP={ip}")
                update_flask_status(ip)
                time.sleep(RETRY_INTERVAL)
                continue

            # Try to connect to an open network
            for ssid in open_ssids:
                # Disconnect from current network first if needed
                if is_connected(INTERFACE):
                    log.info(f"Open network '{ssid}' found — dropping current connection to switch.")
                    subprocess.run(["nmcli", "device", "disconnect", INTERFACE],
                                   capture_output=True, check=False)
                    time.sleep(2)

                randomize_mac(INTERFACE)
                # Rescan after MAC change so nmcli cache reflects the new MAC
                log.info("Rescanning after MAC randomization ...")
                subprocess.run(["nmcli", "dev", "wifi", "rescan", "ifname", INTERFACE],
                               capture_output=True, check=False, timeout=10)
                time.sleep(8)
                # Verify network is actually visible before attempting connect
                check = subprocess.run(
                    ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list", "ifname", INTERFACE],
                    capture_output=True, text=True
                )
                visible = [l.strip() for l in check.stdout.splitlines()]
                if ssid not in visible:
                    log.warning(f"'{ssid}' not visible after rescan, skipping.")
                    continue
                if connect_to_ssid(ssid, INTERFACE):
                    # Give DHCP more time on slow/open networks
                    for _ in range(6):
                        time.sleep(2)
                        ip = get_ip(INTERFACE)
                        if ip:
                            break
                    if ip:
                        log.info(f"Connected to open network '{ssid}', IP={ip}")
                        update_flask_status(ip)
                        refresh_nat(INTERFACE)
                        connected_to_open = True
                        break
                    else:
                        log.warning(f"Connected to '{ssid}' but got no IP, trying next.")
            else:
                # All open networks failed — fall through to WPA below
                connected_to_open = False

        else:
            connected_to_open = False

        # No open networks available (or all failed) — use WPA
        if not connected_to_open:
            if is_connected(INTERFACE):
                ip = get_ip(INTERFACE)
                log.info(f"No open networks. Staying on current connection, IP={ip}")
                update_flask_status(ip)
            else:
                # Not connected at all — try saved profiles then known WPA
                connected = False
                if try_saved_connections(INTERFACE):
                    ip = get_ip(INTERFACE)
                    update_flask_status(ip)
                    refresh_nat(INTERFACE)
                    connected = True

                if not connected:
                    known_wpa = scan_known_wpa_networks(INTERFACE)
                    for ssid in known_wpa:
                        if connect_to_ssid(ssid, INTERFACE):
                            time.sleep(5)
                            ip = get_ip(INTERFACE)
                            if ip:
                                log.info(f"Connected to known WPA '{ssid}', IP={ip}")
                                update_flask_status(ip)
                                refresh_nat(INTERFACE)
                                connected = True
                                break
                            else:
                                log.warning(f"Connected to '{ssid}' but got no IP, trying next.")

                if not connected:
                    log.info(f"No usable network found. Retrying in {RETRY_INTERVAL}s ...")

        time.sleep(RETRY_INTERVAL)


if __name__ == "__main__":
    main()
