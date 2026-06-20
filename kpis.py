"""
KPI computation for the IHL Heat Pump Monitoring System.

Produces the hero-strip numbers and the detailed per-category metrics the
dashboard renders. Everything is computed against data up to the live cursor so
the figures advance as the week "plays".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import lbenergy.config as config
import lbenergy.data_loader as dl
import lbenergy.thermal_twin as tt


def _energy_kwh(power: pd.DataFrame) -> float:
    """Total kWh from 5-minute power samples summed across devices."""
    if power.empty:
        return 0.0
    total = power.groupby("timestamp")["power_draw_kw"].sum()
    return float(total.sum() * 5 / 60)


def energy_cost_co2(power: pd.DataFrame) -> dict:
    kwh = _energy_kwh(power)
    return {
        "energy_kwh": kwh,
        "cost_eur": kwh * config.ELECTRICITY_TARIFF_EUR_PER_KWH,
        "co2_kg": kwh * config.CO2_FACTOR_KG_PER_KWH,
    }


def waste_breakdown(snap: pd.DataFrame, power: pd.DataFrame, events: pd.DataFrame) -> dict:
    """Avoidable energy/€ from the two big causes: faulty electric backup and
    conditioning an empty room."""
    import lbenergy.monitors as monitors  # local import to avoid a module cycle
    out = {"fault_kwh": 0.0, "unoccupied_kwh": 0.0, "avoidable_kwh": 0.0}

    # fault: excess energy of any backup/alarm device vs the healthy-fleet median
    eff = monitors._device_efficiency(snap, power)
    out["fault_kwh"] = float(monitors.faulty_devices(eff)["excess_kwh"].sum())

    # unoccupied conditioning (half assumed avoidable with proper setback)
    pw = dl.tag_occupancy(power, events, "timestamp")
    unocc_kwh = pw[~pw["is_occupied"]].groupby("timestamp")["power_draw_kw"].sum().sum() * 5 / 60
    out["unoccupied_kwh"] = unocc_kwh
    out["avoidable_kwh"] = out["fault_kwh"] + unocc_kwh * 0.5
    out["avoidable_eur"] = out["avoidable_kwh"] * config.ELECTRICITY_TARIFF_EUR_PER_KWH
    out["avoidable_co2_kg"] = out["avoidable_kwh"] * config.CO2_FACTOR_KG_PER_KWH
    return out


def comfort_score(snap: pd.DataFrame, events: pd.DataFrame) -> dict:
    """% of occupied time the room is within the comfort band of target."""
    room = (snap.groupby("last_seen_at")
            .agg(t_in=("status_temperature_in_celsius", "median"),
                 target=("status_target_temperature_in_celsius", "median"))
            .reset_index())
    room = dl.tag_occupancy(room, events, "last_seen_at")
    occ = room[room["is_occupied"]]
    if occ.empty:
        return {"comfort_pct": np.nan, "unmet_hours": 0.0, "mean_deficit": np.nan}
    in_band = (occ["t_in"] - occ["target"]).abs() <= config.COMFORT_BAND_C
    deficit = (occ["target"] - occ["t_in"]).clip(lower=0)
    # occupied samples ~1/min; approximate hours from sample count
    span_h = (occ["last_seen_at"].max() - occ["last_seen_at"].min()).total_seconds() / 3600
    unmet_frac = (deficit > config.UNMET_COMFORT_DEFICIT_C).mean()
    return {
        "comfort_pct": float(in_band.mean() * 100),
        "unmet_hours": float(unmet_frac * span_h),
        "mean_deficit": float(deficit.mean()),
    }


def fleet_health(snap: pd.DataFrame) -> dict:
    """Devices OK / total, based on active alarms in the latest report."""
    latest = snap.sort_values("last_seen_at").groupby("device_name").tail(1)
    total = len(latest)
    faulty = int(latest["has_alarm"].sum())
    return {"ok": total - faulty, "total": total, "faulty": faulty}


def device_table(snap: pd.DataFrame, power: pd.DataFrame) -> pd.DataFrame:
    """Per-device snapshot for the fleet view: status, power, COP, alarms."""
    latest = snap.sort_values("last_seen_at").groupby("device_name").tail(1).set_index("device_name")
    rows = []
    for dev, row in latest.iterrows():
        p = power[power["device_name"] == dev]["power_draw_kw"]
        mean_kw = float(p.mean()) if len(p) else np.nan
        heat_kw = tt.device_cop(snap[snap["device_name"] == dev])  # mean delivered heat, active rows
        cop = heat_kw / mean_kw if mean_kw and mean_kw > 0 else np.nan
        backup = (row["status_is_compressor_active"] == 0
                  and abs(row["supply_return_dt"]) >= config.ELECTRIC_BACKUP_DELTA_T_C)
        if row["has_alarm"] or backup:
            status = "critical"
        elif np.isfinite(cop) and cop < config.COP_MIN + 0.3:
            status = "warning"
        else:
            status = "ok"
        rows.append({
            "device": dev, "status": status, "power_kw": round(mean_kw, 2),
            "cop": round(cop, 2) if np.isfinite(cop) else None,
            "room_c": row["status_temperature_in_celsius"],
            "alarms": "; ".join(row["alarms"]) if row["alarms"] else "",
        })
    return pd.DataFrame(rows)


def annualize(eur_for_period: float, period_days: float) -> float:
    if period_days <= 0:
        return 0.0
    return eur_for_period / period_days * 365


def hero_kpis(source: dl.ReplaySource, cursor=None) -> dict:
    """The top-strip KPI bundle."""
    snap = source.snapshots(up_to=cursor)
    power = source.power(up_to=cursor)
    events = source.events(up_to=cursor)
    if snap.empty:
        return {}

    ecc = energy_cost_co2(power)
    waste = waste_breakdown(snap, power, events)
    comfort = comfort_score(snap, events)
    health = fleet_health(snap)
    days = max((power["timestamp"].max() - power["timestamp"].min()).total_seconds() / 86400, 1e-6) \
        if not power.empty else 1.0

    return {
        **ecc,
        "avoidable_eur": waste["avoidable_eur"],
        "avoidable_eur_annual": annualize(waste["avoidable_eur"], days),
        "avoidable_kwh": waste["avoidable_kwh"],
        "avoidable_co2_kg": waste["avoidable_co2_kg"],
        "comfort_pct": comfort["comfort_pct"],
        "unmet_hours": comfort["unmet_hours"],
        "fleet_ok": health["ok"],
        "fleet_total": health["total"],
        "fault_kwh": waste["fault_kwh"],
        "period_days": days,
    }
