# TrafficShield M15 — Dynamic Network Interface Validation & Driver Requirements

**Document ID:** TS-M15-INTERFACES  
**Date:** 2026-10-26  
**Status:** VERIFIED (PASS)  
**Auditor:** TrafficShield Security & ML Engineering Team  
**Scope:** Architectural evaluation of dynamic interface enumeration, adapter properties, permission models, driver verification, and live capture operation.

---

## 1. Dynamic Hardware Interface Discovery

TrafficShield strictly avoids hardcoding network interface names. The [`enumerate_network_interfaces()`](file:///d:/projects/trafficshield/ingestion/capture/live_source.py) engine queries the Windows network adapter registry and Scapy interface subsystem dynamically:

### Representative Discovered Interfaces on Host

| Interface Name (`name`) | Description (`description`) | IPv4 Address | MAC Address | Operational Status | Loopback |
|:---|:---|:---:|:---:|:---:|:---:|
| `Wi-Fi` | Realtek RTL8852BE WiFi 6 802.11ax PCIe Adapter | `10.36.105.217` | `94:97:4f:13:0f:af` | **UP (Active - Captured)** | No |
| `Loopback Pseudo-Interface 1` | Software Loopback Interface 1 | `127.0.0.1` | *N/A* | **UP (Active)** | Yes |
| `Ethernet` | Realtek PCIe GbE Family Controller | `169.254.161.234` | `f4:3a:fa:c7:43:b2` | Down / Unlinked | No |
| `Bluetooth Network Connection`| Bluetooth Device (Personal Area Network) | `169.254.50.89` | `94:97:4f:13:0f:b0` | Down / Unlinked | No |
| `Local Area Connection* 1` | Microsoft Wi-Fi Direct Virtual Adapter | `169.254.26.72` | `96:97:4f:13:0f:af` | Down / Unlinked | No |

Total Discovered Adapters: **40 network adapter configurations** (including Hyper-V switches, WAN miniports, and Wi-Fi Direct instances).

---

## 2. Interface Selection & Authorization Policy

1. **Explicit Selection Mandate:** Live capture requires the operator to provide an explicit interface identifier (`interface: "Wi-Fi"`). TrafficShield will **never promiscuously sniff all interfaces by default**.
2. **Authorized Monitoring Links Only:** In critical-infrastructure deployments, the selected interface must correspond to a unidirectional optical tap, SPAN port, or designated mirror link.
3. **Passive Only (Zero Injection):** TrafficShield acts strictly as a passive listener. The capture worker calls Scapy `sniff(store=False)` and **never transmits packets, performs ARP probes, scans subnets, or injects traffic**.

---

## 3. Kernel Driver Status: RESOLVED & VERIFIED

Npcap has been installed and verified on this host:
- **Driver Status:** Active (`driver_available: true`)
- **System Library:** `wpcap.dll` and `Packet.dll` detected and loaded via `ctypes.util.find_library('wpcap')`.
- **Operating Interface:** `Wi-Fi` mapped to Windows NPF device `\Device\NPF_{57B0B12B-DBD6-4A1F-889F-10662755578B}`.
- **REST API Verification:**
  ```http
  GET /api/v1/capture/interfaces HTTP/1.1
  Host: 127.0.0.1:5000
  ```
  Response:
  ```json
  {
    "success": true,
    "driver_available": true,
    "interfaces": [ ... ]
  }
  ```

---

## 4. Operator Installation Reference (For New Hosts)

If deploying TrafficShield on a new Windows host:

1. **Download:** Obtain the official signed installer from [https://npcap.com](https://npcap.com).
2. **Installation Options (Critical Prerequisites):**
   - ✅ Check: **"Install Npcap in WinPcap API-compatible Mode"** (Installs `wpcap.dll` and `Packet.dll` into `System32`).
   - ✅ Check: **"Restrict Npcap driver's access to Administrators only"** (Recommended for security).
   - ❌ Do NOT enable 802.11 raw frame monitor mode unless specifically instructed for specialized wireless telemetry.
3. **Privilege Requirements:**
   - On Windows, the process running TrafficShield must either run under an account belonging to the local `Administrators` group or the `npcap` service security descriptor must grant read access to standard users.
