# TrafficShield — Dataset Acquisition Guide

## Overview
This document explains how to obtain the datasets used by TrafficShield, storage requirements, and preparation steps. **No dataset is downloaded automatically.** You must run the provided scripts explicitly.

## UGR'16 (Primary Dataset)

### About
- Full name: UGR'16 — A New Dataset for the Evaluation of Cyclostationarity-Based Network IDSs
- Source: Network Engineering & Security Group (NESG), University of Granada, Spain
- Official page: https://nesg.ugr.es/nesg-ugr16/index.php
- Paper: Maciá-Fernández et al., "UGR'16: A New Dataset for the Evaluation of Cyclostationarity-Based Network IDSs", Computer Networks, Elsevier, 2018
- License: Academic/research use. Contact nesg@ugr.es to obtain access credentials.

### Format
Raw files are nfcapd (nfdump binary) format. The official preprocessed CSV files exported via nfdump contain exactly 13 columns:

```
te, td, sa, da, sp, dp, pr, flg, fwd, stos, pkt, byt, class
```

| Column | Description | Type | Notes |
|--------|-------------|------|-------|
| te | Flow end timestamp | datetime string | YYYY-MM-DD HH:MM:SS.sss |
| td | Flow duration (seconds) | float | >= 0 |
| sa | Source IP address | IPv4 string | Anonymized with CryptoPan |
| da | Destination IP address | IPv4 string | Anonymized with CryptoPan |
| sp | Source port | int | 0–65535 |
| dp | Destination port | int | 0–65535 |
| pr | Protocol | string | TCP, UDP, ICMP, etc. |
| flg | TCP flags (cumulative) | string | e.g. .A., .S., .FSA. |
| fwd | Forwarding status | int | NetFlow forwarding status byte |
| stos | Type of Service (ToS) | int | IP header ToS/DSCP byte |
| pkt | Packet count | int | >= 1 |
| byt | Byte count | int | >= 1 |
| class | Traffic label | string | 'background', 'dos', 'scan11', 'scan12', 'nerisbotnet', 'spam', 'blacklist' |

### Dataset Periods
| Period | Months | Purpose | Contains Attacks |
|--------|--------|---------|-----------------|
| Calibration (training) | March – June 2016 | Learn normal behaviour | No (background only) |
| Test | July – August 2016 | Evaluate detection | Yes |

### Storage Requirements
| Format | Approximate Size |
|--------|-----------------|
| Raw nfcapd (all months) | ~341 GB |
| Preprocessed CSV (all months) | ~13–15 GB |
| Single month CSV (calibration) | ~1.5–3 GB |
| Processed feature vectors (1-min aggregates) | ~1.5 GB total |

**Minimum recommended free disk space before downloading: 20 GB for a single month CSV, 350 GB for the full dataset.**

### One-Way Observability Note
UGR'16 records are NetFlow v9 records collected at ISP router interfaces. Each record represents traffic observed at that interface. The `td` (duration), `pkt`, and `byt` fields reflect the aggregated forward direction as seen by that sensor. The dataset does NOT provide explicit reverse-direction fields; however, the `class` label and the flow records themselves describe bidirectional session activity as captured from a single vantage point.

**TrafficShield treats UGR'16 as providing forward-direction observations only.** The `class` column is excluded from model features and used only for post-prediction evaluation.

### Acquisition Steps

1. Visit the official page: https://nesg.ugr.es/nesg-ugr16/index.php
2. Register and request access credentials from the NESG team.
3. Once credentials are received, use the acquisition script:

```bash
# Install dependencies from requirements.txt:
pip install -r requirements.txt

# Inspect dataset metadata without downloading:
python scripts/acquire_dataset.py info ugr16

# Explicit download command (with credentials and resume support):
python scripts/acquire_dataset.py download ugr16 \
    --dest datasets/raw/ugr16 \
    --username YOUR_USERNAME \
    --password-env NESG_PASSWORD \
    --month 2016-03 \
    --verify-checksum
```

4. Prepare raw files for the adapter:

```bash
python scripts/prepare_ugr16.py \
    --src datasets/raw/ugr16 \
    --dest datasets/interim/ugr16 \
    --month 2016-03
```

5. Validate the manifest:

```bash
python scripts/check_manifest.py datasets/interim/ugr16/manifest.json
```

### Recommended Download Order (start small)
1. `2016-03` — March (first calibration month, ~1.5 GB CSV). Verify the adapter works.
2. `2016-04`, `2016-05`, `2016-06` — Remaining calibration months.
3. `2016-07` — First test month (contains attacks).
4. `2016-08` — Second test month.

---

## CICIDS2017 (Secondary Validation Dataset)

- Source: Canadian Institute for Cybersecurity, University of New Brunswick
- Official page: https://www.unb.ca/cic/datasets/ids-2017.html
- Format: Pre-extracted flow features in CSV format (CICFlowMeter output)
- Size: ~900 MB CSV total
- License: Academic use. Attribution required.
- Note: Contains explicit bidirectional flow features. TrafficShield filters out reverse-direction features before use.

```bash
python scripts/acquire_dataset.py download cicids2017 --dest datasets/raw/cicids2017
```

---

## UNSW-NB15 (Independent Validation)

- Source: UNSW Canberra Cyber
- Official page: https://research.unsw.edu.au/projects/unsw-nb15-dataset
- Format: CSV (ARGUS tool output + manual features)
- Size: ~100 MB CSV

```bash
python scripts/acquire_dataset.py download unswnb15 --dest datasets/raw/unswnb15
```

---

## What is NEVER committed to Git

The `.gitignore` excludes:
- `datasets/raw/`
- `datasets/interim/`
- `datasets/processed/`
- All `*.csv.gz`, `*.pcap`, `*.nfcapd` files

Manifests and checksums in `datasets/canonical/` are safe to commit (they are small JSON files, no raw data).
