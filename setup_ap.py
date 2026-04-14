#!/usr/bin/env python3
"""
setup_ap.py — Bring up a Wi-Fi Access Point on wlan1 using hostapd + dnsmasq.
Run once at boot as root.

Requirements:
    sudo apt install hostapd dnsmasq -y
"""

import subprocess
import sys
import logging
import os
import time

# ── Config ────────────────────────────────────────────────────────────────────
AP_INTERFACE = "wlan0"
AP_SSID      = "Abraham Linksys"
AP_PASSWORD  = "raspberry"        # min 8 chars; set "" for open AP
AP_CHANNEL   = "6"
AP_IP        = "192.168.50.1"     # Pi's IP on the hotspot network
DHCP_RANGE   = "192.168.50.10,192.168.50.50,24h"
UPSTREAM_IF  = "wlan1"            # interface with internet (scanner/client interface)

HOSTAPD_CONF  = "/etc/hostapd/hostapd_ap.conf"
DNSMASQ_CONF  = "/etc/dnsmasq.d/hotspot.conf"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


# ── Config writers ────────────────────────────────────────────────────────────

def write_hostapd_conf():
    wpa_lines = ""
    if AP_PASSWORD:
        wpa_lines = f"""
wpa=2
wpa_passphrase={AP_PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
"""
    conf = f"""interface={AP_INTERFACE}
driver=nl80211
ssid={AP_SSID}
hw_mode=g
channel={AP_CHANNEL}
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
{wpa_lines}
"""
    with open(HOSTAPD_CONF, "w") as f:
        f.write(conf)
    log.info(f"Wrote {HOSTAPD_CONF}")


def write_dnsmasq_conf():
    conf = f"""interface={AP_INTERFACE}
dhcp-range={DHCP_RANGE}
dhcp-option=3,{AP_IP}
dhcp-option=6,{AP_IP}
server=1.1.1.1
log-queries
log-dhcp
listen-address={AP_IP}
bind-interfaces
"""
    with open(DNSMASQ_CONF, "w") as f:
        f.write(conf)
    log.info(f"Wrote {DNSMASQ_CONF}")


# ── Network setup ─────────────────────────────────────────────────────────────

def run(cmd: list[str], check=True):
    log.info(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        log.info(result.stdout.strip())
    if result.stderr.strip():
        log.warning(result.stderr.strip())
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


# ── NAT / IP forwarding ───────────────────────────────────────────────────────

def get_upstream_if() -> str:
    """Return the interface that currently has a default route (internet)."""
    result = subprocess.run(
        ["ip", "route", "show", "default"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        parts = line.split()
        if "dev" in parts:
            return parts[parts.index("dev") + 1]
    return UPSTREAM_IF   # fall back to config value


def enable_nat(upstream: str):
    """Enable IP forwarding and add iptables NAT masquerade rule."""
    # Enable kernel IP forwarding
    with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
        f.write("1")

    # Make it persist across reboots
    sysctl_line = "net.ipv4.ip_forward=1"
    sysctl_path = "/etc/sysctl.d/99-ipforward.conf"
    try:
        existing = open(sysctl_path).read() if os.path.exists(sysctl_path) else ""
        if sysctl_line not in existing:
            with open(sysctl_path, "a") as f:
                f.write(sysctl_line + "\n")
    except Exception:
        pass

    # Flush any old NAT rules for this upstream
    run(["iptables", "-t", "nat", "-D", "POSTROUTING",
         "-o", upstream, "-j", "MASQUERADE"], check=False)
    run(["iptables", "-D", "FORWARD",
         "-i", AP_INTERFACE, "-o", upstream,
         "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"], check=False)
    run(["iptables", "-D", "FORWARD",
         "-i", upstream, "-o", AP_INTERFACE, "-j", "ACCEPT"], check=False)

    # Add fresh rules
    run(["iptables", "-t", "nat", "-A", "POSTROUTING",
         "-o", upstream, "-j", "MASQUERADE"])
    run(["iptables", "-A", "FORWARD",
         "-i", AP_INTERFACE, "-o", upstream,
         "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])
    run(["iptables", "-A", "FORWARD",
         "-i", upstream, "-o", AP_INTERFACE, "-j", "ACCEPT"])

    log.info(f"NAT enabled: {AP_INTERFACE} → {upstream}")


def setup_ap():
    # Unblock Wi-Fi in case rfkill is active
    run(["rfkill", "unblock", "wifi"], check=False)

    # Stop NetworkManager from managing the AP interface (prevents interference)
    run(["nmcli", "device", "set", AP_INTERFACE, "managed", "no"], check=False)

    # Bring interface up
    run(["ip", "link", "set", AP_INTERFACE, "up"])

    # Assign static IP
    run(["ip", "addr", "flush", "dev", AP_INTERFACE], check=False)
    run(["ip", "addr", "add", f"{AP_IP}/24", "dev", AP_INTERFACE])

    # Write configs
    write_hostapd_conf()
    write_dnsmasq_conf()

    # Restart dnsmasq
    run(["systemctl", "restart", "dnsmasq"])

    # Start hostapd in background (daemon mode)
    run(["systemctl", "stop", "hostapd"], check=False)
    time.sleep(1)

    log.info(f"Starting hostapd on {AP_INTERFACE} (SSID={AP_SSID}) ...")
    proc = subprocess.Popen(
        ["hostapd", HOSTAPD_CONF],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(3)
    if proc.poll() is not None:
        log.error("hostapd exited immediately — check your driver supports AP mode.")
        sys.exit(1)

    # Enable NAT so AP clients can reach the internet via the upstream interface
    upstream = get_upstream_if()
    enable_nat(upstream)

    log.info(f"AP is up. Connect to '{AP_SSID}' and SSH to {AP_IP}")
    proc.wait()   # keep process alive (systemd will restart on crash)


if __name__ == "__main__":
    if os.geteuid() != 0:
        log.error("Must be run as root.")
        sys.exit(1)
    setup_ap()
