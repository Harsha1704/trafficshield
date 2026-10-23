# TrafficShield Milestone 10: Limitations & Next Steps
**Date:** 2026-10-23  

---

## 1. Documented Limitations

1. **Absence of Local Raw CICIDS2017 Dataset:**  
   The raw multi-gigabyte PCAP/CSV files for CICIDS2017 are not stored on local disk. While a tested, fully compliant ingestion adapter and schema contract were built, Track A native training on real CICIDS2017 data remains unexecuted.
2. **Feature Set Asymmetry Across Toolchains:**  
   ARGUS (UNSW-NB15) captures IP header TTL, while CICFlowMeter (CICIDS2017) discards it. Furthermore, public CICIDS2017 CSVs strip IP addresses. This prevents identical feature representation without compromising causal observability.
3. **Volumetric Domain Shift:**  
   Network speeds and testbed topology differ substantially between cyber ranges. Thresholds learned on one network cannot be transferred without calibration or normalization.

---

## 2. Recommended Next Steps for Milestone 11 & Milestone 12

1. **Opt-in CICIDS2017 Acquisition:** Provide a CLI workflow (`scripts/acquire_dataset.py cicids2017`) for operators with sufficient disk space (~3 GB) to download and run native Track A training.
2. **Unsupervised Domain Adaptation:** Implement feature-wise percentile matching (e.g. CDF alignment) so that common volumetric features can be normalized without requiring destination attack labels.
3. **Database & Incident Management (M11):** Transition from CSV-based evaluation to PostgreSQL persistent incident storage for enterprise SOC alerting.
