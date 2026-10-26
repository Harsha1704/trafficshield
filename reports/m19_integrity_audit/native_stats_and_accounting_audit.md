# TrafficShield M19 — Native Npcap Integration & Drop-Accounting Semantics Audit

**Milestone:** M19 — Frozen Artifact Integrity, Memory Policy Audit & Native Npcap Safety Review  
**Date:** 2026-10-26  
**Repository:** `D:\projects\trafficshield`  
**Gate Verdict:** **`READY FOR LOCAL DEMONSTRATION`**

---

## 1. Native API Contract & C Signature Audit

### 1.1 C API Function Specification

The native packet capture driver statistics are queried using the standard libpcap / WinPcap C API function:
```c
int pcap_stats(pcap_t *p, struct pcap_stat *ps);
```

#### Calling Conventions & ctypes Bindings:
- **Windows (`wpcap.dll` / `scapy.libs.winpcapy`):**
  - Bound via `scapy.libs.winpcapy.pcap_stats`.
  - `argtypes`: `[ctypes.c_void_p, ctypes.POINTER(pcap_stat)]`
  - `restype`: `ctypes.c_long` (32-bit signed integer in Windows C ABI, matching C `int`)
  - `struct pcap_stat` layout in `winpcapy`:
    ```python
    _fields_ = [
        ('ps_recv', ctypes.c_ulong),    # 32-bit unsigned
        ('ps_drop', ctypes.c_ulong),    # 32-bit unsigned
        ('ps_ifdrop', ctypes.c_ulong),  # 32-bit unsigned
        ('ps_capt', ctypes.c_ulong),    # Windows extension: packets captured
        ('ps_sent', ctypes.c_ulong),    # Windows extension: packets sent
        ('ps_netdrop', ctypes.c_ulong)  # Windows extension: packets dropped by net
    ]
    ```
- **POSIX / Linux (`libpcap.so`):**
  - Bound via dynamic library load `libpcap.so` or `libpcap.so.1`.
  - `argtypes`: `[ctypes.c_void_p, ctypes.POINTER(_PcapStat)]`
  - `restype`: `ctypes.c_int`
  - `struct _PcapStat` layout:
    ```python
    _fields_ = [
        ("ps_recv", ctypes.c_uint),
        ("ps_drop", ctypes.c_uint),
        ("ps_ifdrop", ctypes.c_uint),
    ]
    ```

### 1.2 Return Code Handling
- **`0` (Success):** Structure fields populated with driver counter values.
- **`-1` (`PCAP_ERROR`):** Generic driver failure. Adapter maps this to `is_available=False, status="DRIVER_QUERY_ERROR", error_message="pcap_stats() returned native error code -1"`.
- **`-3` (`PCAP_ERROR_NOT_ACTIVATED`):** Handle passed prior to `pcap_activate()`. Handled identically as query error.
- **Python Exception (`OSError`, `ValueError`, `AttributeError`):** Caught in `except Exception as exc:` block; mapped to `is_available=False, status="DRIVER_EXCEPTION", error_message=str(exc)`.

---

## 2. Handle Lifecycle & Concurrency Audit

### 2.1 Active Socket Handle Extraction from Scapy

To eliminate the latency, driver memory duplication, and miscounting of opening a secondary capture session, `LiveCaptureSource` reuses Scapy's underlying socket handle:
1. `conf.L2listen` creates an `L2pcapListenSocket` instance.
2. Inside `L2pcapListenSocket`, the unmanaged file descriptor is wrapped in `self.pcap_fd` (an instance of `_PcapWrapper_libpcap`).
3. `_PcapWrapper_libpcap` holds the actual unmanaged C pointer in `self.pcap_fd.pcap` (`pcap_t *`).
4. `LiveCaptureSource._capture_worker` initializes `self._opened_socket` and extracts:
   ```python
   if hasattr(self._opened_socket, "pcap_fd") and hasattr(self._opened_socket.pcap_fd, "pcap"):
       self._native_handle = self._opened_socket.pcap_fd.pcap
   ```
5. `NativeStatsAdapter.poll()` provides multi-layer unwrapping:
   ```python
   native_ptr = handle
   if hasattr(native_ptr, "pcap_fd"):
       native_ptr = native_ptr.pcap_fd
   if hasattr(native_ptr, "pcap"):
       native_ptr = native_ptr.pcap
   ```
   This supports passing raw pointers, `_PcapWrapper_libpcap` instances, or `L2pcapListenSocket` objects without brittle couplings.

### 2.2 Thread-Safe Teardown Ordering & Double-Close Prevention

**Audit Finding:** In concurrent multi-threaded environments, calling `pcap_stats()` on a pointer being freed by `pcap_close()` in another thread risks an OS access violation or segfault.

**M19 Hardening:**
In `LiveCaptureSource._capture_worker`'s `finally:` block:
```python
finally:
    self._running = False
    self._native_handle = None  # Immediately invalidate handle pointer BEFORE socket closing
    if self._opened_socket is not None:
        try:
            self._opened_socket.close()
        except Exception:
            pass
        self._opened_socket = None
```
Because `self._native_handle = None` is executed before `sock.close()`, any polling thread immediately receives `handle is None` and returns `UNAVAILABLE (No active capture handle)` without invoking the native C function.

---

## 3. Metric Semantics & Platform Limitations

Every native capture metric strictly differentiates between **three mutually exclusive states**:
1. **Measured numeric value:** An integer $\ge 0$ (including legitimate 0 drops).
2. **Unsupported / Unavailable:** Value is `None` with an explicit reason string.
3. **Runtime Error:** Value is `None` with driver error code or exception string.

### 3.1 The `ps_ifdrop` Windows Limitation

Under Npcap and WinPcap on Windows:
- The miniport driver (`npcap.sys` / `packet.sys`) does not query NIC hardware or NDIS driver drop counters.
- The C library always sets `ps_ifdrop = 0` in the struct.
- **Critical Semantic Rule:** A value of 0 in `ps_ifdrop` on Windows is **NOT** evidence that the NIC dropped zero packets.
- **M19 Enforcement:**
  On Windows systems using native bindings, `NativeStatsAdapter` enforces:
  - `ps_ifdrop_supported: bool = False`
  - `ps_ifdrop_status: str = "UNSUPPORTED (Npcap/WinPcap does not provide NIC drop counters on Windows)"`
  - `ps_ifdrop_cumulative = None`
  - `ps_ifdrop_delta = None`
  This guarantees that unpopulated vendor fields can never be misreported as measured zero drops.

### 3.2 Offline PCAP Replay Isolation

`PcapReplaySource` is an offline file parser that operates entirely without a kernel network filter driver.
- It returns:
  - `native_kernel_drops_available: False`
  - `native_kernel_drops: None`
  - `kernel_drop_status: "UNAVAILABLE (PCAP replay is an offline file source)"`
- This ensures offline replays never report live driver drop telemetry.

---

## 4. Pipeline Drop & Accounting Invariant Equations

Pipeline metrics are governed by strict mathematical conservation equations across every stage of ingestion, flow construction, queueing, inference, and persistence.

```mermaid
flowchart TD
    NIC["Physical NIC / Driver Filter"] -->|ps_recv| KERNEL["Kernel Capture Buffer"]
    KERNEL -->|ps_drop (Tier 1 Drops)| K_DROP["Kernel Drops (native_kernel_drops)"]
    KERNEL -->|Packets Received| INGEST_Q["Ingestion Queue"]
    INGEST_Q -->|Queue Full (Tier 2 Drops)| P_DROP["packets_dropped"]
    INGEST_Q -->|Enqueued Envelopes| BUILDER["UnidirectionalFlowBuilder"]
    
    BUILDER -->|flows_created| ACTIVE["Active Flows"]
    ACTIVE -->|Timeout / Closed / Flush| FLOWS_COMP["flows_completed"]
    
    FLOWS_COMP -->|flow_queue.put| FLOW_Q["Worker Flow Queue"]
    FLOW_Q -->|Queue Full (Tier 3 Drops)| Q_DROP["flows_queue_dropped"]
    FLOW_Q -->|Enqueued Flows| WORKER["StreamingInferenceWorker"]
    
    WORKER -->|Scored| SCORED["flows_scored"]
    WORKER -->|Incompatible| REJECTED["incompatible_flows_rejected"]
    WORKER -->|Validation Err| VAL_ERR["validation_errors"]
    WORKER -->|Inference Fail| INF_FAIL["inference_failures"]
    WORKER -->|Shutdown Interrupted| UNPROC["unprocessed_flows"]
```

### 4.1 Flow Conservation Equations
1. **Flow Completion:**
   $$\text{flows\_completed} = \text{flows\_expired\_timeout} + \text{flows\_closed\_tcp} + \text{flows\_evicted\_overflow} + \text{flows\_flushed}$$
2. **Flow Queue Ingestion:**
   $$\text{flows\_completed} = \text{flows\_queued} + \text{flows\_queue\_dropped}$$
3. **Inference Worker Terminal Outcomes:**
   $$\text{flows\_queued} = \text{flows\_scored} + \text{incompatible\_flows\_rejected} + \text{validation\_errors} + \text{inference\_failures} + \text{unprocessed\_flows}$$

### 4.2 Alert Lifecycle Conservation
For every flow where $\text{anomaly\_score} \ge 0.50$, an anomaly is registered:
$$\text{anomalies\_detected} = \text{alerts\_persisted} + \text{persistence\_failures} + \text{alerts\_deduplicated} + \text{alerts\_unpersisted\_no\_app}$$

### 4.3 Tiered Drop Accounting Isolation
Drops are partitioned into 3 isolated architectural tiers:
- **Tier 1 (Kernel Buffer Drops):** `native_kernel_drops` from `pcap_stats()`.
- **Tier 2 (Packet Queue Drops):** `packets_dropped` in `LiveCaptureSource`.
- **Tier 3 (Flow Queue Drops):** `flows_queue_dropped` in `RealTimeDetectionManager`.

---

## 5. Test Evidence & Remaining Limitations

### 5.1 Deterministic Test Verification
- Authoritative test suite [`tests/unit/test_m19_integrity_audit.py`](file:///d:/projects/trafficshield/tests/unit/test_m19_integrity_audit.py) verified 15 test cases with 100% pass rate.
- Full suite of soak, accounting, and native statistics tests (50 tests across `test_m17_soak_harness.py`, `test_m17_1_accounting_audit.py`, `test_m18_native_stats.py`, and `test_m19_integrity_audit.py`) passes 100%.

### 5.2 Remaining Operational Limitations
1. **Local Demonstration Scope:** Live captures and multi-hour soak runs require physical operator presence and separate authorization.
2. **Wi-Fi Promiscuous Mode Support:** Dependent on OEM NIC driver capabilities; BPF filtering operates in non-promiscuous mode if the hardware driver denies promiscuous activation.
3. **Release Gate:** Remains strictly **`READY FOR LOCAL DEMONSTRATION`**.
