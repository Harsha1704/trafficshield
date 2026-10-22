"""
Synthetic UGR'16 CSV fixtures for unit tests.

These are CLEARLY LABELLED as synthetic data.
They must NEVER be used to claim real-world detection performance.
They exist solely to exercise the adapter and schema code paths
without requiring the actual (large, credential-gated) dataset.

All fixture values are plausible (matching UGR'16 schema constraints)
but are invented for testing purposes.
"""
from __future__ import annotations

import io
from pathlib import Path

# ─── Column header ────────────────────────────────────────────────────────────
UGR16_HEADER = "te,td,sa,da,sp,dp,pr,flg,fwd,stos,pkt,byt,class"

# ─── Synthetic records ────────────────────────────────────────────────────────
# Each tuple: (te, td, sa, da, sp, dp, pr, flg, fwd, stos, pkt, byt, class)
SYNTHETIC_UGR16_ROWS: list[tuple[str, ...]] = [
    # Normal background TCP flow
    (
        "2016-03-01 00:00:01.123", "0.240", "42.219.150.10", "42.219.156.20",
        "443", "51234", "TCP", ".A..S.", "0", "0", "5", "300", "background",
    ),
    # Normal background UDP flow
    (
        "2016-03-01 00:00:05.000", "0.001", "42.219.150.11", "8.8.8.8",
        "53234", "53", "UDP", "......", "0", "0", "1", "64", "background",
    ),
    # Normal background ICMP (ports 0)
    (
        "2016-03-01 00:00:10.500", "0.000", "42.219.150.12", "42.219.156.30",
        "0", "0", "ICMP", "......", "0", "0", "1", "84", "background",
    ),
    # DoS attack flow
    (
        "2016-07-01 14:00:01.000", "0.010", "198.51.100.1", "42.219.156.50",
        "80", "45678", "TCP", ".S....", "0", "0", "100", "6400", "dos",
    ),
    # Port scan (scan11)
    (
        "2016-07-02 09:30:00.000", "0.001", "203.0.113.5", "42.219.150.1",
        "12345", "22", "TCP", ".S....", "0", "0", "1", "60", "scan11",
    ),
    # Nerisbotnet
    (
        "2016-08-01 03:15:00.000", "2.500", "42.219.151.1", "91.108.4.1",
        "49152", "80", "TCP", ".A....", "0", "0", "10", "800", "nerisbotnet",
    ),
    # Scan12
    (
        "2016-07-15 16:00:00.000", "0.001", "198.51.100.99", "42.219.150.2",
        "23456", "443", "TCP", ".S....", "0", "0", "1", "60", "scan12",
    ),
    # Spam flow
    (
        "2016-08-10 08:00:00.000", "1.000", "42.219.155.1", "1.2.3.4",
        "12345", "25", "TCP", ".A..S.", "0", "0", "3", "240", "spam",
    ),
    # Background with no sub-second precision
    (
        "2016-04-15 12:00:00", "0.500", "10.0.0.1", "10.0.0.2",
        "8080", "54321", "TCP", ".A....", "0", "0", "4", "400", "background",
    ),
    # Large byte count background
    (
        "2016-05-20 23:59:59.999", "60.000", "42.219.150.20", "42.219.157.1",
        "445", "49153", "TCP", ".A....", "0", "16", "500", "750000", "background",
    ),
]


def make_ugr16_csv_content(
    rows: list[tuple[str, ...]] | None = None,
    header: str = UGR16_HEADER,
    include_header: bool = True,
) -> str:
    """
    Build a UGR'16-format CSV string from row tuples.

    Parameters
    ----------
    rows : list of row tuples; defaults to SYNTHETIC_UGR16_ROWS
    header : column header line
    include_header : whether to prepend the header row
    """
    rows = rows if rows is not None else SYNTHETIC_UGR16_ROWS
    lines = []
    if include_header:
        lines.append(header)
    for row in rows:
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


def write_ugr16_csv_fixture(
    dest: Path,
    rows: list[tuple[str, ...]] | None = None,
    filename: str = "synthetic_ugr16_sample.csv",
) -> Path:
    """Write a synthetic UGR'16 CSV fixture to disk for integration tests."""
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / filename
    out.write_text(make_ugr16_csv_content(rows), encoding="utf-8")
    return out


def make_ugr16_csv_io(
    rows: list[tuple[str, ...]] | None = None,
) -> io.StringIO:
    """Return a StringIO containing synthetic UGR'16 CSV (for in-memory tests)."""
    return io.StringIO(make_ugr16_csv_content(rows))


# ── Edge-case fixtures ────────────────────────────────────────────────────────

MALFORMED_ROWS: list[tuple[str, ...]] = [
    # Missing timestamp
    ("", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background"),
    # Invalid IP
    ("2016-03-01 00:00:01.000", "0.1", "NOT_AN_IP", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background"),
    # Negative packet count
    ("2016-03-01 00:00:02.000", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "-5", "100", "background"),
    # Non-numeric packet count
    ("2016-03-01 00:00:03.000", "0.1", "1.2.3.4", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "abc", "100", "background"),
    # Port out of range
    ("2016-03-01 00:00:04.000", "0.1", "1.2.3.4", "5.6.7.8", "99999", "80", "TCP", ".A.", "0", "0", "1", "100", "background"),
    # Missing src IP
    ("2016-03-01 00:00:05.000", "0.1", "", "5.6.7.8", "80", "80", "TCP", ".A.", "0", "0", "1", "100", "background"),
]

EMPTY_CSV = UGR16_HEADER + "\n"  # header only, no data rows

WRONG_HEADER_CSV = "wrong,columns,here\n2016-03-01 00:00:01.000,foo,bar\n"

EXTRA_COLUMNS_CSV = (
    "te,td,sa,da,sp,dp,pr,flg,fwd,stos,pkt,byt,class,extra_col\n"
    "2016-03-01 00:00:01.000,0.1,1.2.3.4,5.6.7.8,80,80,TCP,.A.,0,0,1,100,background,ignored\n"
)
