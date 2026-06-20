"""
Lumped-capacitance "digital twin" of the climate-controlled room.

Physical model (single-node RC, from the lumped-capacitance approach):

    C * dT/dt = Q_heat - UA * (T_in - T_out) + Q_people

    C        thermal capacitance (J/degC)  -- room volume + furniture mass
    UA       heat-loss coefficient (W/degC) -- envelope leakiness
    Q_heat   delivered heating/cooling power (W) = COP(T_out) * electrical_W
    Q_people internal gains (W) ~ occupants * sensible_gain
    T_out    outside temperature (degC)

We estimate C and UA from the data by fitting the model to the observed room
temperature, then integrate it forward with the classic 4th-order Runge-Kutta
method and validate the fit with MAE / RMSE / Willmott's index of agreement.

Methodology reference: Arumugam et al. (2023), "Lumped Capacitance Thermal
Modelling Approaches for Different Cylindrical Batteries" -- we reuse their
numerical RK4 integration, their parameter-fit-by-least-squares strategy, and
their statistical validation suite. Their key finding (a *dynamic* internal
resistance fits far better than a constant one) is mirrored here by modelling a
*dynamic* COP(T_out) instead of a single fixed COP.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import config as config


# ---------------------------------------------------------------------------
# Dynamic COP (the "dynamic parameter" parallel to the paper's R(T))
# ---------------------------------------------------------------------------
def cop_for_outside_temp(t_out: float) -> float:
    cop = config.COP_BASE + config.COP_SLOPE * (t_out - config.COP_REF_T)
    return float(np.clip(cop, config.COP_MIN, config.COP_MAX))


# ---------------------------------------------------------------------------
# Heat delivered by a unit from its own telemetry (absolute, kW)
# Q = m_dot * cp * (T_supply - T_return); m_dot scales with fan %.
# ---------------------------------------------------------------------------
def delivered_heat_kw(supply_c, return_c, fan_supply_pct) -> np.ndarray:
    frac = np.clip(np.asarray(fan_supply_pct, dtype=float) / 100.0, 0, 1)
    m_dot = (config.RATED_AIRFLOW_M3_PER_H / 3600.0) * config.AIR_DENSITY_KG_PER_M3 * frac  # kg/s
    dt = np.asarray(supply_c, dtype=float) - np.asarray(return_c, dtype=float)
    return m_dot * config.AIR_CP_KJ_PER_KG_K * dt  # kJ/s == kW


def device_cop(dev_snap) -> float:
    """COP of one device over its *active* periods (heating or cooling demanded).
    Averaging only over active rows avoids diluting COP with idle samples."""
    active = dev_snap[(dev_snap["status_is_heating_required"] == 1)
                      | (dev_snap["status_is_cooling_required"] == 1)]
    if active.empty:
        active = dev_snap
    q = delivered_heat_kw(
        active["status_temperature_supply_in_celsius"],
        active["status_temperature_return_in_celsius"],
        active["status_air_flow_supply_in_percent"],
    )
    heat_kw = float(np.nanmean(np.abs(q)))
    return heat_kw  # caller divides by electrical power


# ---------------------------------------------------------------------------
# Statistical validation (the paper's error-criterion suite)
# ---------------------------------------------------------------------------
def validation_metrics(observed: np.ndarray, predicted: np.ndarray) -> dict:
    o = np.asarray(observed, dtype=float)
    p = np.asarray(predicted, dtype=float)
    mask = np.isfinite(o) & np.isfinite(p)
    o, p = o[mask], p[mask]
    if len(o) < 2:
        return {"mae": np.nan, "rmse": np.nan, "willmott_d": np.nan, "n": len(o)}
    err = p - o
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err**2)))
    obar = o.mean()
    denom = np.sum((np.abs(p - obar) + np.abs(o - obar)) ** 2)
    d = float(1 - np.sum(err**2) / denom) if denom > 0 else np.nan
    return {"mae": mae, "rmse": rmse, "willmott_d": d, "n": len(o)}


# ---------------------------------------------------------------------------
# The twin
# ---------------------------------------------------------------------------
@dataclass
class TwinParams:
    C_J_per_C: float          # thermal capacitance
    UA_W_per_C: float         # heat-loss coefficient
    tau_hours: float          # time constant C/UA, for intuition

    @property
    def summary(self) -> str:
        return (
            f"C = {self.C_J_per_C/1e6:.1f} MJ/degC, "
            f"UA = {self.UA_W_per_C:.0f} W/degC, "
            f"tau = {self.tau_hours:.1f} h"
        )


class RoomThermalTwin:
    """Fit + simulate the room's temperature."""

    def __init__(self, params: TwinParams | None = None):
        self.params = params

    # -- fitting -----------------------------------------------------------
    def fit(self, ts: pd.DataFrame) -> TwinParams:
        """
        Fit C and UA from a regularly-sampled frame with columns:
            t_in, t_out, q_heat_w, q_people_w   (index = datetime)

        Strategy: discretise dT/dt and solve the linear least-squares problem
            C * (dT/dt) = Q_total - UA * (T_in - T_out)
        for (C, UA). This is the lumped-capacitance energy balance written per
        timestep -- the same balance the paper integrates, fit directly.
        """
        df = ts.dropna(subset=["t_in", "t_out"]).copy()
        dt_s = df.index.to_series().diff().dt.total_seconds()
        dTdt = df["t_in"].diff() / dt_s                      # degC/s
        q_total = df["q_heat_w"].fillna(0) + df["q_people_w"].fillna(0)
        delta = df["t_in"] - df["t_out"]

        valid = dTdt.notna() & dt_s.notna() & (dt_s > 0)
        y = q_total[valid].values                            # W
        # model: y = C*dTdt + UA*delta  -> solve [dTdt, delta] @ [C, UA] = y
        A = np.column_stack([dTdt[valid].values, delta[valid].values])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        C, UA = float(coef[0]), float(coef[1])

        # guard against degenerate fits; fall back to physically plausible values
        if not np.isfinite(C) or C <= 0:
            C = 5.0e6
        if not np.isfinite(UA) or UA <= 0:
            UA = 200.0
        self.params = TwinParams(C_J_per_C=C, UA_W_per_C=UA, tau_hours=C / UA / 3600.0)
        return self.params

    # -- one-step-ahead prediction (the monitoring workhorse) --------------
    def predict_one_step(self, ts: pd.DataFrame) -> pd.Series:
        """
        Predict each step's room temperature from the *previous actual*
        temperature plus one model step. This is the right tool for anomaly
        detection: the residual (actual - predicted) isolates what the physics
        cannot explain at that moment (e.g. an opened door inflating heat loss).
        """
        if self.params is None:
            raise RuntimeError("twin must be fit() before predict_one_step()")
        C, UA = self.params.C_J_per_C, self.params.UA_W_per_C
        secs = ts.index.to_series().diff().dt.total_seconds()
        q = ts["q_heat_w"].fillna(0) + ts["q_people_w"].fillna(0)
        dTdt = (q - UA * (ts["t_in"] - ts["t_out"])) / C
        pred_next = ts["t_in"] + dTdt * secs
        return pred_next.shift(1).rename("t_in_predicted")  # align to the step it predicts

    def validate(self, ts: pd.DataFrame) -> dict:
        """One-step-ahead validation metrics (MAE/RMSE/Willmott's d)."""
        pred = self.predict_one_step(ts)
        return validation_metrics(ts["t_in"].values, pred.values)

    def residuals(self, ts: pd.DataFrame) -> pd.Series:
        """actual - one-step-prediction; large values flag unmodelled heat loss."""
        return (ts["t_in"] - self.predict_one_step(ts)).rename("residual")

    # -- simulation (RK4) --------------------------------------------------
    def simulate(self, ts: pd.DataFrame, t0: float | None = None) -> pd.Series:
        """
        Integrate the model forward with RK4 over the rows of `ts`
        (needs columns t_out, q_heat_w, q_people_w; index = datetime).
        Returns the predicted room temperature series.
        """
        if self.params is None:
            raise RuntimeError("twin must be fit() before simulate()")
        C, UA = self.params.C_J_per_C, self.params.UA_W_per_C

        def deriv(T, t_out, q):
            return (q - UA * (T - t_out)) / C   # degC/s

        idx = ts.index
        t_out = ts["t_out"].values
        q = (ts["q_heat_w"].fillna(0) + ts["q_people_w"].fillna(0)).values
        secs = idx.to_series().diff().dt.total_seconds().fillna(0).values

        T = ts["t_in"].iloc[0] if t0 is None else t0
        out = np.empty(len(idx))
        out[0] = T
        for i in range(1, len(idx)):
            h = secs[i]
            if h <= 0:
                out[i] = T
                continue
            # hold inputs constant across the step (zero-order hold)
            to, qi = t_out[i], q[i]
            k1 = deriv(T, to, qi)
            k2 = deriv(T + 0.5 * h * k1, to, qi)
            k3 = deriv(T + 0.5 * h * k2, to, qi)
            k4 = deriv(T + h * k3, to, qi)
            T = T + (h / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)
            out[i] = T
        return pd.Series(out, index=idx, name="t_in_predicted")

    # -- forward trajectory (closed form, for the live simulator) ----------
    def trajectory(self, t_start, t_out, q_heat_w, q_people_w=0.0,
                   minutes=240, step_min=2.0):
        """
        Room temperature over time under *constant* inputs, as the exact analytic
        solution of the ODE (identical to a converged RK4 step-through, but instant
        so it can recompute on every slider move):

            T(t) = T_ss + (T_start - T_ss) * exp(-t / tau)
            T_ss = T_out + (Q_heat + Q_people)/UA,   tau = C/UA

        Returns (minutes_array, temperature_array).
        """
        if self.params is None:
            raise RuntimeError("twin must be fit() before trajectory()")
        C, UA = self.params.C_J_per_C, self.params.UA_W_per_C
        t_ss = t_out + (q_heat_w + q_people_w) / UA
        tau_s = C / UA
        mins = np.arange(0.0, minutes + step_min, step_min)
        temps = t_ss + (t_start - t_ss) * np.exp(-(mins * 60.0) / tau_s)
        return mins, temps

    # -- time-to-target (closed form, for preheat scheduling) --------------
    # max preheat lead time we treat as practically useful (minutes)
    MAX_PREHEAT_MIN = 8 * 60

    def time_to_target(self, t_start, t_target, t_out, q_heat_w, q_people_w=0.0):
        """
        Closed-form minutes to go from t_start to t_target under constant inputs:
            T_ss = T_out + (Q_heat + Q_people)/UA,  tau = C/UA
            t = -tau * ln((T_target - T_ss)/(T_start - T_ss))
        Returns minutes, or None if the target is unreachable with this power.

        Note: as T_target approaches the steady-state T_ss, the room only reaches
        the target asymptotically and t -> infinity. A target that is technically
        reachable but needs an impractical lead time (> MAX_PREHEAT_MIN) is treated
        as "effectively unreachable" so the planner never returns absurd values
        like 10000 minutes -- the caller should prompt for more power instead.
        """
        if self.params is None:
            raise RuntimeError("twin must be fit() before time_to_target()")
        C, UA = self.params.C_J_per_C, self.params.UA_W_per_C
        # already at/above the target -> no preheat needed
        if t_start >= t_target:
            return 0.0
        t_ss = t_out + (q_heat_w + q_people_w) / UA
        # The room moves monotonically from T_start toward the steady state T_ss,
        # so it only ever passes through T_target if T_target lies between T_start
        # and T_ss. With ratio = (T_target - T_ss)/(T_start - T_ss):
        #   ratio <= 0  -> target on the far side of T_ss  (unreachable)
        #   ratio  > 1  -> target beyond T_start, away from T_ss (unreachable:
        #                  e.g. asking for 21C when this power can only hold 16C)
        #   0 < ratio <= 1 -> reachable; ratio == 1 means already at target (0 min)
        denom = t_start - t_ss
        if denom == 0:                       # already sitting at steady state
            return 0.0 if t_target == t_start else None
        ratio = (t_target - t_ss) / denom
        if ratio <= 0 or ratio > 1:
            return None
        tau_s = C / UA
        minutes = max(0.0, -tau_s * np.log(ratio) / 60.0)
        # barely reachable (T_ss only just above target) -> impractical lead time
        if minutes > self.MAX_PREHEAT_MIN:
            return None
        return minutes


# ---------------------------------------------------------------------------
# Convenience: build the twin-input frame from a ReplaySource window
# ---------------------------------------------------------------------------
def build_twin_frame(source, freq: str = "15min") -> pd.DataFrame:
    """
    Aggregate raw telemetry into a regular time grid for fitting/simulation.
    Room temp & outside temp are shared (median across devices); delivered heat
    is summed across the healthy fleet; Q_people is inferred from CO2.
    """
    snap = source.snapshots()
    power = source.power()

    grid = (
        snap.set_index("last_seen_at")
        .groupby(pd.Grouper(freq=freq))
        .agg(
            t_in=("status_temperature_in_celsius", "median"),
            t_out=("status_temperature_outside_in_celsius", "median"),
            co2=("status_carbon_dioxide_in_ppm", "median"),
        )
    )

    # delivered heat (kW) summed over devices, then to W
    heat = []
    for _, g in snap.groupby("device_name"):
        q = delivered_heat_kw(
            g["status_temperature_supply_in_celsius"],
            g["status_temperature_return_in_celsius"],
            g["status_air_flow_supply_in_percent"],
        )
        # signed: positive in heating, negative in cooling (do NOT clip)
        s = pd.Series(q, index=g["last_seen_at"])
        heat.append(s.groupby(pd.Grouper(freq=freq)).mean())
    q_heat_kw = pd.concat(heat, axis=1).sum(axis=1)
    grid["q_heat_w"] = (q_heat_kw.reindex(grid.index).fillna(0) * 1000.0)

    occupants = ((grid["co2"] - config.CO2_BASELINE_PPM) / config.CO2_PER_PERSON_PPM).clip(lower=0)
    grid["q_people_w"] = occupants * config.SENSIBLE_GAIN_PER_PERSON_W

    return grid.dropna(subset=["t_in", "t_out"])


# ---------------------------------------------------------------------------
# Schedule-driven preheat planning (the actual "when to switch on" answer)
# ---------------------------------------------------------------------------
def preheat_schedule(twin, frame, events, cursor, units, target_c,
                     people=0, t_out_forecast=None):
    """
    For every lecture/event that has not yet started, work out when the fleet
    should switch on so the room hits `target_c` exactly at the event start.

    twin           a fitted RoomThermalTwin
    frame          the twin-input frame (for current room/outside temp)
    events         space_events DataFrame (columns starts_at, ends_at)
    cursor         "now" -- only events with starts_at > cursor are scheduled
    units          number of heat-pump units assumed running for the preheat
    target_c       comfort setpoint to reach on arrival
    people         expected occupants during preheat (their body heat helps)
    t_out_forecast outside temp to assume; defaults to the latest measured value
                   (a naive persistence forecast -- swap for a real forecast later)

    Returns a list of dicts, one per upcoming event:
        {starts_at, switch_on_at, lead_min, t_now, t_out, reachable}
    """
    # current room temperature = most recent value at/before the cursor
    sub = frame[frame.index <= cursor]
    t_now = float(sub["t_in"].iloc[-1]) if len(sub) else target_c
    if t_out_forecast is None:
        t_out_forecast = float(sub["t_out"].iloc[-1]) if len(sub) else 5.0

    q_heat_w = units * config.HEAT_PUMP_DELIVERED_KW_PER_UNIT * 1000.0
    q_people_w = people * config.SENSIBLE_GAIN_PER_PERSON_W

    upcoming = events[events["starts_at"] > cursor].sort_values("starts_at")
    rows = []
    for _, ev in upcoming.iterrows():
        lead = twin.time_to_target(t_now, target_c, t_out_forecast, q_heat_w, q_people_w)
        rows.append({
            "starts_at": ev["starts_at"],
            "switch_on_at": (ev["starts_at"] - pd.Timedelta(minutes=lead)
                             if lead is not None else None),
            "lead_min": lead,
            "t_now": t_now,
            "t_out": t_out_forecast,
            "reachable": lead is not None,
        })
    return rows
