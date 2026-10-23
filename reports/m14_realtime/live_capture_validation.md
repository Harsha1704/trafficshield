# TrafficShield M14 Real-Time — Passive Live Interface Capture Audit

**Milestone:** M14 — Real-Time Network Detection, Flow Reconstruction and Streaming SOC Alerts  
**Date:** 2026-10-23  
**Status on Current Host:** **NOT RUN (DRIVER BLOCKED)** — Full Abstraction Implemented & Audited  

---

## 1. Physical Host Driver Environment

Live network interface sniffing requires kernel-level packet filter drivers:
- **Windows:** Npcap (in WinPcap API-compatible mode) providing `wpcap.dll` and `Packet.dll`.
- **Linux:** `libpcap` providing `libpcap.so`.

### Host Audit Execution:
```python
>>> from ingestion.capture.live_source import is_capture_driver_available
>>> is_capture_driver_available()
(False, "Npcap/WinPcap driver not installed (wpcap.dll missing). Passive live interface sniffing requires Npcap on Windows. Download from https://npcap.com and install with WinPcap API-compatible mode.")
```

---

## 2. Interface Enumeration Verification

The application successfully enumerates all local network interfaces without initiating promiscuous capture:

```bash
$ curl -s http://localhost:5000/api/v1/capture/interfaces | jq .
{
  "success": true,
  "data": {
    "driver_available": false,
    "driver_status": "Npcap/WinPcap driver not installed (wpcap.dll missing)...",
    "interfaces": [
      {
        "name": "Wi-Fi",
        "description": "Realtek RTL8852BE WiFi 6 802.11ax PCIe Adapter",
        "ipv4_addresses": ["10.36.107.172"],
        "is_up": true,
        "is_loopback": false,
        "driver_available": false
      },
      {
        "name": "Ethernet",
        "description": "Realtek PCIe GbE Family Controller",
        "ipv4_addresses": ["169.254.161.234"],
        "is_up": false,
        "is_loopback": false,
        "driver_available": false
      },
      {
        "name": "Loopback Pseudo-Interface 1",
        "description": "Software Loopback Interface 1",
        "ipv4_addresses": ["127.0.0.1"],
        "is_up": true,
        "is_loopback": true,
        "driver_available": false
      }
    ]
  }
}
```

---

## 3. Strict Truthfulness Policy: Zero Silent Simulation

In accordance with TrafficShield invariants:
1. **No Fake Simulation:** The application **refuses** to silently fall back from live capture to simulated traffic or fake counters.
2. **Fail-Closed on Start:** When a client attempts to start live capture on an interface without the required kernel driver:
   ```bash
   $ curl -X POST http://localhost:5000/api/v1/capture/start-live \
       -H "Authorization: Bearer <ANALYST_TOKEN>" \
       -H "Content-Type: application/json" \
       -d '{"interface": "Wi-Fi"}'
   
   HTTP/1.1 400 Bad Request
   {
     "success": false,
     "error": {
       "code": "DRIVER_OR_SESSION_ERROR",
       "message": "Npcap/WinPcap driver not installed (wpcap.dll missing)..."
     }
   }
   ```
3. **UI Transparency:** The SOC Command Center displays an informational banner highlighting driver absence and disables the "Start Capture" button with explicit instructions.

---

## 4. Operational Instructions for Live Capture Deployment

To enable live capture in a production environment:

### Windows:
1. Download Npcap installer from `https://npcap.com`.
2. Run installer and ensure **"Install Npcap in WinPcap API-compatible Mode"** is checked.
3. Start TrafficShield backend service.
4. Navigate to **Live Detection** tab $\rightarrow$ **Passive Live Interface** $\rightarrow$ Select interface $\rightarrow$ Click **"Start Capture"**.

### Linux:
1. Install libpcap: `sudo apt-get install -y libpcap-dev`.
2. Grant packet capture capabilities to Python binary: `sudo setcap cap_net_raw,cap_net_admin=eip $(which python)`.
3. Start TrafficShield backend service.
