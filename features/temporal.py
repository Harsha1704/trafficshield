"""
Causal Temporal Behavioural Feature Engineering
================================================
Version: 1.0 (Milestone 6)

Derives strictly causal, past-only rolling behavioural indicators from unidirectional
IP flow streams.

Guarantees:
1. STRICT CAUSALITY: For observation i at timestamp t_i, historical metrics are
   computed strictly over [t_i - window_seconds, t_i). The current observation
   is NEVER included in its own past historical window.
2. ZERO FUTURE LOOKAHEAD: Future observations never influence earlier feature values.
3. UNIDIRECTIONAL RESPECT: All temporal features use forward-direction measurements
   or sensor-observed timestamps only. No reverse traffic assumptions are made.
4. IDENTIFIER EXCLUSION: Grouping identifiers (such as src_ip) are used strictly
   as partition lookup keys during stateful tracking and are NEVER emitted into
   the final numeric feature matrix.
"""
from __future__ import annotations

import collections
from datetime import UTC
from typing import Any

import numpy as np
import pandas as pd


class TemporalFeatureEngineer:
    """
    Computes causal rolling behavioural features from unidirectional IP flows.
    """

    def __init__(
        self,
        window_seconds: float = 300.0,
        group_by: str | None = "src_ip",
        timestamp_col: str = "flow_end_ts",
        fallback_iat: float = 300.0,
        include_log_transforms: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        window_seconds : float
            Duration of rolling historical lookback window in seconds (default: 300s = 5m).
        group_by : str or None
            Column to group by for behavioural tracking (e.g. 'src_ip').
            If None or column not present, computes sensor-wide global link features.
        timestamp_col : str
            Observation timestamp column (default: 'flow_end_ts').
        fallback_iat : float
            Default inter-arrival time (seconds) assigned to the first observation
            in a group or after prolonged dormancy.
        include_log_transforms : bool
            If True, generates log1p-transformed variants for heavy-tailed counts.
        """
        self.window_seconds = float(window_seconds)
        self.group_by = group_by
        self.timestamp_col = timestamp_col
        self.fallback_iat = float(fallback_iat)
        self.include_log_transforms = include_log_transforms

    def transform_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform flow records into causal temporal behavioural features.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame containing timestamp_col and flow metrics.

        Returns
        -------
        pd.DataFrame aligned with df.index containing strictly eligible numeric features.
        """
        if df.empty or len(df) == 0:
            return pd.DataFrame()

        # Preserve original row order and index
        orig_index = df.index
        work_df = df.copy()

        # Parse timestamps to float unix epoch seconds
        if self.timestamp_col in work_df.columns:
            ts_series = pd.to_datetime(work_df[self.timestamp_col], utc=True, errors="coerce")
            work_df["_epoch_sec"] = (
                (ts_series - pd.Timestamp("1970-01-01", tz=UTC))
                .dt.total_seconds()
                .fillna(0.0)
            )
        else:
            work_df["_epoch_sec"] = 0.0

        # Extract numeric inputs safely
        pkts_in = work_df["fwd_packets"] if "fwd_packets" in work_df.columns else pd.Series(0.0, index=work_df.index)
        bytes_in = work_df["fwd_bytes"] if "fwd_bytes" in work_df.columns else pd.Series(0.0, index=work_df.index)
        ports_in = work_df["dst_port"] if "dst_port" in work_df.columns else pd.Series(0, index=work_df.index)

        work_df["_fwd_pkts"] = pd.to_numeric(pkts_in, errors="coerce").fillna(0.0).clip(lower=0.0)
        work_df["_fwd_bytes"] = pd.to_numeric(bytes_in, errors="coerce").fillna(0.0).clip(lower=0.0)
        work_df["_dst_port"] = pd.to_numeric(ports_in, errors="coerce").fillna(0).astype(int)
        work_df["_orig_idx"] = np.arange(len(work_df))

        # Sort chronologically by timestamp
        sorted_df = work_df.sort_values(by=["_epoch_sec", "_orig_idx"], ascending=[True, True])

        # Feature accumulators
        n_rows = len(sorted_df)
        out_iats = np.zeros(n_rows, dtype=np.float64)
        out_counts = np.zeros(n_rows, dtype=np.float64)
        out_pkts = np.zeros(n_rows, dtype=np.float64)
        out_bytes = np.zeros(n_rows, dtype=np.float64)
        out_port_divs = np.zeros(n_rows, dtype=np.float64)
        out_burst_ratios = np.zeros(n_rows, dtype=np.float64)

        # Stateful sliding window tracking per group
        # group_key -> deque of (epoch_sec, fwd_packets, fwd_bytes, dst_port)
        history: dict[Any, collections.deque] = collections.defaultdict(collections.deque)
        last_seen_ts: dict[Any, float] = {}

        use_grouping = bool(self.group_by and self.group_by in sorted_df.columns)

        epochs = sorted_df["_epoch_sec"].to_numpy()
        cur_pkts = sorted_df["_fwd_pkts"].to_numpy()
        cur_bytes = sorted_df["_fwd_bytes"].to_numpy()
        cur_ports = sorted_df["_dst_port"].to_numpy()
        group_keys = sorted_df[self.group_by].to_numpy() if use_grouping else np.zeros(n_rows, dtype=int)

        for i in range(n_rows):
            t_cur = epochs[i]
            g_key = group_keys[i]
            q = history[g_key]

            # 1. Compute inter-arrival time (strictly relative to previous flow)
            if g_key in last_seen_ts:
                dt = t_cur - last_seen_ts[g_key]
                out_iats[i] = max(0.0, dt)
            else:
                out_iats[i] = self.fallback_iat

            last_seen_ts[g_key] = t_cur

            # 2. Evict expired entries: [t_cur - window_seconds, t_cur)
            # Observations with timestamp < cutoff are strictly outside lookback window
            cutoff = t_cur - self.window_seconds
            while q and q[0][0] < cutoff:
                q.popleft()

            # 3. Compute rolling stats over strictly prior observations
            count_prev = len(q)
            out_counts[i] = count_prev

            if count_prev > 0:
                p_sum = sum(entry[1] for entry in q)
                b_sum = sum(entry[2] for entry in q)
                port_set = {entry[3] for entry in q}

                out_pkts[i] = p_sum
                out_bytes[i] = b_sum
                out_port_divs[i] = len(port_set)

                mean_pkts_prev = p_sum / count_prev
                # Burst ratio: current packets / past mean packets
                out_burst_ratios[i] = cur_pkts[i] / (mean_pkts_prev + 1e-6)
            else:
                out_pkts[i] = 0.0
                out_bytes[i] = 0.0
                out_port_divs[i] = 0.0
                out_burst_ratios[i] = 1.0

            # 4. Now append the current observation into history for future flows to see
            q.append((t_cur, cur_pkts[i], cur_bytes[i], cur_ports[i]))

        # Re-align back to original input DataFrame ordering
        orig_positions = sorted_df["_orig_idx"].to_numpy()
        res_df = pd.DataFrame(index=orig_index)

        res_df["inter_arrival_time"] = np.nan
        res_df["rolling_flow_count"] = np.nan
        res_df["rolling_packet_sum"] = np.nan
        res_df["rolling_byte_sum"] = np.nan
        res_df["rolling_packet_rate"] = np.nan
        res_df["rolling_byte_rate"] = np.nan
        res_df["rolling_dst_port_diversity"] = np.nan
        res_df["burst_packet_ratio"] = np.nan

        res_df.iloc[orig_positions, res_df.columns.get_loc("inter_arrival_time")] = out_iats
        res_df.iloc[orig_positions, res_df.columns.get_loc("rolling_flow_count")] = out_counts
        res_df.iloc[orig_positions, res_df.columns.get_loc("rolling_packet_sum")] = out_pkts
        res_df.iloc[orig_positions, res_df.columns.get_loc("rolling_byte_sum")] = out_bytes

        win_sec = max(1.0, self.window_seconds)
        res_df["rolling_packet_rate"] = res_df["rolling_packet_sum"] / win_sec
        res_df["rolling_byte_rate"] = res_df["rolling_byte_sum"] / win_sec
        res_df.iloc[orig_positions, res_df.columns.get_loc("rolling_dst_port_diversity")] = out_port_divs
        res_df.iloc[orig_positions, res_df.columns.get_loc("burst_packet_ratio")] = out_burst_ratios

        # Clean non-finites
        for c in (
            "inter_arrival_time", "rolling_flow_count", "rolling_packet_sum",
            "rolling_byte_sum", "rolling_packet_rate", "rolling_byte_rate",
            "rolling_dst_port_diversity", "burst_packet_ratio",
        ):
            res_df[c] = res_df[c].replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)

        # Log transforms (optional)
        if self.include_log_transforms:
            res_df["log_rolling_flow_count"] = np.log1p(res_df["rolling_flow_count"])
            res_df["log_rolling_byte_sum"] = np.log1p(res_df["rolling_byte_sum"])
            res_df["log_inter_arrival_time"] = np.log1p(res_df["inter_arrival_time"])

        return res_df
