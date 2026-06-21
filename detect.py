"""
Anomaly detection & classification for the IHL Monitor — the "Detect" pillar.

The challenge asks the system to "reliably tell apart what is normal and what is
not": a short drop when a door opens, gradual changes during the day, a real
heater defect, or a tampering attempt — and then alert the right person.

This module turns the physics digital twin into an anomaly classifier. The key
signal is the **one-step residual** = (measured room temp) − (twin prediction).
When the room behaves as physics predicts, the residual is small (gradual daily
changes are *explained* by the model → no false alarms). When something the model
cannot explain happens, the residual spikes — and the *shape* of that spike, plus
CO₂ and the commanded heat, tells us which of the four cases it is.

Because the provided week is clean, `inject_scenario` can overlay a synthetic
door / defect / tamper / sensor event so the classifier can be demonstrated live.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import config as config

# --- classification thresholds (tunable) -----------------------------------
RESIDUAL_BAND_K = 3.0            # anomaly if |residual| > K * robust_sigma ...
RESIDUAL_BAND_FLOOR = 2.0        # ... but never below this floor (above clean noise)
CO2_DROP_PPM = config.CO2_DROP_PPM       # sudden CO2 fall => fresh air in (door)
# Real room steps top out ~1.3°C and the model rate ~2.1°C, so a true sensor spoof
# is well above that. Set above the onset-induced jumps (~5°C) but below the +8°C
# sensor injection, so only genuine spoofs are flagged as sensor tampering.
TEMP_JUMP_IMPLAUSIBLE_C = 6.0
DEFECT_MIN_STEPS = 2             # sustained cooling-under-demand to call it a defect


@dataclass
class Anomaly:
    timestamp: pd.Timestamp
    kind: str                # "Door/window open" | "Heater defect" | ...
    severity: str            # "critical" | "warning" | "info"
    residual: float          # measured - predicted (degC)
    explanation: str
    action: str
    recipient: str           # who gets alerted


def _robust_sigma(x: pd.Series) -> float:
    """Median-absolute-deviation based sigma — robust to the very outliers we hunt."""
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    return float(1.4826 * mad) if mad > 0 else float(np.nanstd(x))


def anomaly_band(twin, frame: pd.DataFrame) -> float:
    """The ± residual band that counts as 'normal' (shared by chart and classifier)."""
    if twin.params is None or len(frame) < 3:
        return RESIDUAL_BAND_FLOOR
    return max(RESIDUAL_BAND_K * _robust_sigma(twin.residuals(frame)), RESIDUAL_BAND_FLOOR)


# ---------------------------------------------------------------------------
# Scenario injection (for a live demo on the otherwise-clean week)
# ---------------------------------------------------------------------------
# Per-step ONSET *residual targets* (°C) defining each scenario. We force the room
# temp to (model prediction + target), so the residual equals the target exactly —
# deterministic and independent of the local heating dynamics. A gentle recovery
# (RECOVERY_STEP_C/step) that cancels the onset is auto-appended so the room rejoins
# its real level without a fake spike at the window edge.
_ONSET = {
    # one sharp dip (clears the band), then the door is closed
    "door": [-3.0],
    # room stays below the model for several steps -> a sustained defect signature
    "defect": [-2.6, -2.6, -2.6],
    # unauthorised warming with nothing commanded
    "tamper_control": [2.8, 2.8, 2.8],
}


def inject_scenario(twin, frame: pd.DataFrame, kind: str, at_frac: float = 0.5) -> pd.DataFrame:
    """
    Return a copy of `frame` with a synthetic anomaly overlaid, so the classifier
    can be shown telling the cases apart. `kind` in
    {"door", "defect", "tamper_sensor", "tamper_control"}.

    Anomalies are injected by *forcing the one-step residual* to a target value
    (set T_in = model_prediction + target). This makes the injected signature exact
    and independent of where in the week it lands. After the onset the residual is
    forced to 0 (the room follows physics from its new level) — realistic for a
    door left open / a heater that stays broken, and it guarantees the onset is the
    only thing flagged (no fake recovery or rejoin spikes).
    """
    df = frame.copy()
    n = len(df)
    if n < 20 or twin.params is None:
        return df
    i = int(np.clip(at_frac, 0.05, 0.80) * n)
    t_col = df.columns.get_loc("t_in")

    if kind == "tamper_sensor":
        df.iloc[i, t_col] += 8.0                       # one impossible instantaneous jump
        return df

    if kind not in _ONSET:
        return df

    onset = _ONSET[kind]
    n_onset = len(onset)
    C, UA = twin.params.C_J_per_C, twin.params.UA_W_per_C
    secs = df.index.to_series().diff().dt.total_seconds().median()
    q_col = df.columns.get_loc("q_heat_w")
    tout_col = df.columns.get_loc("t_out")
    co2_col = df.columns.get_loc("co2")

    for idx in range(i, n):
        k = idx - i
        target = onset[k] if k < n_onset else 0.0      # onset, then follow physics
        if kind == "tamper_control" and k < n_onset:   # nothing commanded -> heat off
            df.iloc[idx, q_col] = 0.0
        t_prev = df.iloc[idx - 1, t_col]
        q_prev = df.iloc[idx - 1, q_col]
        tout_prev = df.iloc[idx - 1, tout_col]
        dTdt = (q_prev - UA * (t_prev - tout_prev)) / C          # same model as residuals()
        df.iloc[idx, t_col] = t_prev + dTdt * secs + target      # force residual = target
        if kind == "door" and k < n_onset:                       # fresh air in -> CO2 falls
            df.iloc[idx, co2_col] -= 220
    return df


# ---------------------------------------------------------------------------
# The classifier
# ---------------------------------------------------------------------------
def classify_anomalies(twin, frame: pd.DataFrame) -> list[Anomaly]:
    """
    Flag points where the room defies the physics, and label each by signature:

      Door/window open  residual << 0 (cools faster than predicted) + CO2 drop
      Heater defect     residual << 0 while heat is commanded, sustained, no CO2 drop
      Tampering(sensor) room temperature jumps faster than physically possible
      Tampering(control)residual >> 0 (warms) with little/no commanded heat
    """
    if twin.params is None or len(frame) < 5:
        return []

    res = twin.residuals(frame)                       # measured - predicted
    band = anomaly_band(twin, frame)
    co2_d = frame["co2"].diff() if "co2" in frame else pd.Series(0.0, index=frame.index)
    temp_jump = frame["t_in"].diff().abs()

    out: list[Anomaly] = []
    flagged_until = None
    for ts in frame.index:
        if flagged_until is not None and ts <= flagged_until:
            continue                                  # de-bounce: one alarm per episode
        r = res.get(ts, np.nan)
        if not np.isfinite(r):
            continue
        jump = temp_jump.get(ts, 0.0)

        # 1) sensor tampering: a non-physical instantaneous jump
        if jump > TEMP_JUMP_IMPLAUSIBLE_C:
            out.append(Anomaly(
                ts, "Tampering (sensor)", "critical", float(r),
                f"Room temperature jumped {jump:.1f}°C in one step — faster than "
                f"physically possible; the sensor reading was likely manipulated.",
                "Verify sensor integrity; check for unauthorised access.",
                "Technician"))
            flagged_until = ts + pd.Timedelta(hours=1)
            continue

        if abs(r) <= band:
            continue                                  # within normal physics -> not an alarm

        cd = co2_d.get(ts, 0.0)
        if r < 0:                                     # room colder than predicted
            # sustained? look at the next few steps — a defect persists, a door recovers
            loc = frame.index.get_loc(ts)
            ahead = res.iloc[loc:loc + 6]
            sustained = int((ahead < -0.5 * band).sum()) >= DEFECT_MIN_STEPS
            if cd < -CO2_DROP_PPM:
                out.append(Anomaly(
                    ts, "Door/window open", "warning", float(r),
                    f"Room cooling {abs(r):.1f}°C faster than the model predicts with "
                    f"a CO₂ drop of {cd:.0f} ppm — classic open-door signature.",
                    "Check doors/windows; close to stop the heat leak.",
                    "Superintendent"))
            elif sustained:
                out.append(Anomaly(
                    ts, "Heater defect", "critical", float(r),
                    f"Room {abs(r):.1f}°C below the model and staying there — the unit "
                    f"is not delivering the expected heat. Likely defect / electric backup.",
                    "Dispatch maintenance now; check compressor / refrigerant.",
                    "Technician"))
            else:
                out.append(Anomaly(
                    ts, "Unexplained cooling", "warning", float(r),
                    f"Room {abs(r):.1f}°C colder than predicted with no door or sustained "
                    f"signature — investigate.",
                    "Inspect the space and recent control actions.",
                    "Superintendent"))
        else:                                         # room warmer than predicted
            out.append(Anomaly(
                ts, "Tampering (control)", "warning", float(r),
                f"Room {r:.1f}°C warmer than the model with little/no commanded heat — "
                f"possible unauthorised heater or a manual override.",
                "Check for rogue heaters / manual setpoint overrides.",
                "Superintendent"))

        flagged_until = ts + pd.Timedelta(hours=1)    # de-bounce one episode per hour

    return out


# ---------------------------------------------------------------------------
# Early-warning: predict a comfort breach before it happens
# ---------------------------------------------------------------------------
def early_warning(twin, frame: pd.DataFrame, setpoint_c: float,
                  horizon_min: int = 60) -> dict | None:
    """
    Free-run the twin from the latest state under the *currently delivered* heat.
    If the room is heading for (or sitting below) the setpoint and not recovering,
    warn before students feel it. Returns a dict or None.
    """
    if twin.params is None or len(frame) < 4:
        return None
    last = frame.iloc[-1]
    t_now, t_out = float(last["t_in"]), float(last["t_out"])
    q = float(last["q_heat_w"]) + float(last.get("q_people_w", 0.0))
    UA, C = twin.params.UA_W_per_C, twin.params.C_J_per_C
    t_ss = t_out + q / UA                              # where it's heading
    # projected temp in horizon_min
    tau_s = C / UA
    proj = t_ss + (t_now - t_ss) * np.exp(-(horizon_min * 60) / tau_s)
    if proj >= setpoint_c - config.UNMET_COMFORT_DEFICIT_C:
        return None
    return {
        "t_now": t_now, "projected": float(proj), "setpoint": setpoint_c,
        "horizon_min": horizon_min, "t_ss": float(t_ss),
        "message": (f"Projected room temp in {horizon_min} min is {proj:.1f}°C, "
                    f"below the {setpoint_c:.0f}°C setpoint and not recovering at the "
                    f"current heat output — likely comfort breach ahead."),
    }


# ---------------------------------------------------------------------------
# Notification routing (the "automatically alerts the technician" requirement)
# ---------------------------------------------------------------------------
def route_notifications(anomalies: list[Anomaly], alerts=None) -> list[dict]:
    """
    Turn classified anomalies (and optional monitor Alerts) into routed
    notifications: critical -> Technician (SMS), warning -> Superintendent (email).
    """
    notes: list[dict] = []
    for a in anomalies:
        notes.append({
            "severity": a.severity,
            "channel": "📱 SMS" if a.severity == "critical" else "✉️ Email",
            "recipient": a.recipient,
            "subject": a.kind,
            "body": f"{a.timestamp:%Y-%m-%d %H:%M} — {a.explanation} → {a.action}",
        })
    for al in (alerts or []):
        notes.append({
            "severity": al.severity,
            "channel": "📱 SMS" if al.severity == "critical" else "✉️ Email",
            "recipient": "Technician" if al.severity == "critical" else "Superintendent",
            "subject": f"{al.category}: {al.title}",
            "body": f"{al.device} — {al.detail}",
        })
    rank = {"critical": 0, "warning": 1, "info": 2}
    notes.sort(key=lambda x: rank.get(x["severity"], 3))
    return notes
