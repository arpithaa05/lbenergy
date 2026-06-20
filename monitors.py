"""
Detection engine for the IHL Heat Pump Monitoring System.

Each detector consumes telemetry (optionally only up to the live cursor) and
emits zero or more `Alert`s. Every Alert carries a euro impact and a concrete
recommended action, so the dashboard renders them uniformly and the value of
acting on them is always explicit.

Detectors:
  1. device_alarms        -- decoded Modbus alarms (F-Gas / refrigerant flagged)
  2. refrigerant_fault    -- electric-backup signature + COP deficit vs fleet
  3. envelope_leak        -- twin residual spike + CO2 drop (door/window open)
  4. comfort              -- occupied but below target / slow to reach setpoint
  5. energy_waste         -- conditioning an empty room / setback not applied
  6. connectivity         -- stale reports, compressor short-cycling
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import lbenergy.config as config
import lbenergy.data_loader as dl
import lbenergy.thermal_twin as tt


# ---------------------------------------------------------------------------
@dataclass
class Alert:
    timestamp: pd.Timestamp
    device: str
    severity: str            # "critical" | "warning" | "info"
    category: str            # e.g. "Refrigerant", "Comfort", "Energy", ...
    title: str
    detail: str
    eur_per_day: float = 0.0
    action: str = ""
    tags: list = field(default_factory=list)   # e.g. ["F-Gas", "EPBD"]

    @property
    def severity_rank(self) -> int:
        return config.SEVERITY.get(self.severity, 0)

    def as_dict(self) -> dict:
        return {
            "time": self.timestamp,
            "device": self.device,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "detail": self.detail,
            "eur_per_day": round(self.eur_per_day, 2),
            "action": self.action,
            "tags": ", ".join(self.tags),
        }


# Refrigerant-related alarms (drive the F-Gas compliance story)
_REFRIGERANT_ALARMS = {
    "Ckt1 Low Pressure Alarm", "Ckt2 Low Pressure Alarm",
    "Ckt1 Low Pressure Switch Alarm", "Ckt2 Low Pressure Switch Alarm",
    "Ckt1 High Pressure Alarm", "Ckt2 High Pressure Alarm",
    "Ckt1 High Pressure Switch Alarm", "Ckt2 High Pressure Switch Alarm",
    "A2L Gas Detector Fault",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _latest_per_device(snap: pd.DataFrame) -> pd.DataFrame:
    return snap.sort_values("last_seen_at").groupby("device_name").tail(1)


def _device_efficiency(snap: pd.DataFrame, power: pd.DataFrame) -> pd.DataFrame:
    """
    Per-device efficiency over the window: COP (over active periods), total
    energy, electric-backup fraction, and whether the unit looks faulty.
    """
    rows = []
    for dev, g in snap.groupby("device_name"):
        heat_kw = tt.device_cop(g)                       # mean delivered heat over active rows
        p = power[power["device_name"] == dev]["power_draw_kw"]
        elec_kw = float(p.mean()) if len(p) else np.nan
        energy_kwh = float(p.sum() * 5 / 60) if len(p) else 0.0
        cop = heat_kw / elec_kw if elec_kw and elec_kw > 0 else np.nan
        # electric-backup signature across the window: compressor off + big dT
        active = g[(g["status_is_heating_required"] == 1) | (g["status_is_cooling_required"] == 1)]
        if len(active):
            backup_frac = float(((active["status_is_compressor_active"] == 0)
                                 & (active["supply_return_dt"].abs() >= config.ELECTRIC_BACKUP_DELTA_T_C)).mean())
        else:
            backup_frac = 0.0
        has_refrig_alarm = bool(g["alarms"].apply(
            lambda a: any(x in _REFRIGERANT_ALARMS for x in a)).any())
        rows.append({"device": dev, "cop": cop, "energy_kwh": energy_kwh,
                     "backup_frac": backup_frac, "refrig_alarm": has_refrig_alarm})
    return pd.DataFrame(rows)


def faulty_devices(eff: pd.DataFrame) -> pd.DataFrame:
    """Devices in electric-backup or with a refrigerant alarm, with their excess
    energy vs the healthy-fleet median (the avoidable amount)."""
    faulty_mask = (eff["backup_frac"] > 0.1) | eff["refrig_alarm"]
    healthy = eff[~faulty_mask]
    healthy_median = healthy["energy_kwh"].median() if len(healthy) else 0.0
    out = eff[faulty_mask].copy()
    out["excess_kwh"] = (out["energy_kwh"] - healthy_median).clip(lower=0)
    return out


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------
def device_alarms(snap: pd.DataFrame) -> list[Alert]:
    alerts = []
    for _, row in _latest_per_device(snap).iterrows():
        for alarm in row["alarms"]:
            refrigerant = alarm in _REFRIGERANT_ALARMS
            alerts.append(Alert(
                timestamp=row["last_seen_at"], device=row["device_name"],
                severity="critical" if refrigerant else "warning",
                category="Refrigerant" if refrigerant else "Device",
                title=f"Active alarm: {alarm}",
                detail=f"{row['device_name']} reports '{alarm}'.",
                action=("Dispatch maintenance; log leak check per F-Gas Reg."
                        if refrigerant else "Schedule inspection."),
                tags=(["F-Gas EU 2024/573"] if refrigerant else []),
            ))
    return alerts


def refrigerant_fault(snap: pd.DataFrame, power: pd.DataFrame) -> list[Alert]:
    """Electric-backup signature (compressor off + huge supply-return dT, over the
    window) and fleet-relative COP deficit. Pressures are NOT trended absolutely
    (they rise with outside temp for all units) -- we compare each unit to the
    fleet. Euro impact = excess energy vs the healthy-fleet median."""
    alerts = []
    eff = _device_efficiency(snap, power)
    fleet_cop = np.nanmedian(eff[eff["backup_frac"] <= 0.1]["cop"])
    faulty = faulty_devices(eff)
    days = max((power["timestamp"].max() - power["timestamp"].min()).total_seconds() / 86400, 1e-6) \
        if not power.empty else 1.0
    latest = _latest_per_device(snap).set_index("device_name")

    for _, f in faulty.iterrows():
        dev = f["device"]
        ts = latest.loc[dev, "last_seen_at"] if dev in latest.index else snap["last_seen_at"].max()
        eur_day = f["excess_kwh"] * config.ELECTRICITY_TARIFF_EUR_PER_KWH / days
        if f["backup_frac"] > 0.1:
            alerts.append(Alert(
                timestamp=ts, device=dev, severity="critical", category="Refrigerant",
                title="Running on electric resistance backup",
                detail=(f"Compressor down for {f['backup_frac']*100:.0f}% of demand with a "
                        f"large supply-return ΔT — emergency electric heat engaged. "
                        f"COP ≈ {f['cop']:.2f}. Excess ≈ {f['excess_kwh']:.0f} kWh vs healthy units."),
                eur_per_day=eur_day,
                action="Critical: dispatch maintenance now; likely refrigerant loss / compressor trip.",
                tags=["F-Gas EU 2024/573"],
            ))

    # early-warning COP deficit on units that are NOT in full backup
    for _, e in eff[eff["backup_frac"] <= 0.1].iterrows():
        if np.isfinite(e["cop"]) and np.isfinite(fleet_cop) and fleet_cop > 0:
            deficit = 1 - e["cop"] / fleet_cop
            if deficit >= config.COP_DEFICIT_WARN:
                dev = e["device"]
                ts = latest.loc[dev, "last_seen_at"] if dev in latest.index else snap["last_seen_at"].max()
                sev = "critical" if deficit >= config.COP_DEFICIT_CRIT else "warning"
                alerts.append(Alert(
                    timestamp=ts, device=dev, severity=sev, category="Refrigerant",
                    title=f"Efficiency {deficit*100:.0f}% below fleet",
                    detail=(f"COP ≈ {e['cop']:.2f} vs fleet median {fleet_cop:.2f}. "
                            f"Possible early refrigerant leak or coil fouling."),
                    action="Inspect refrigerant charge & coils; trend pressures.",
                    tags=["F-Gas EU 2024/573"],
                ))
    return alerts


def envelope_leak(twin: tt.RoomThermalTwin, frame: pd.DataFrame) -> list[Alert]:
    """Twin residual spike (room loses heat faster than physics predicts) plus a
    CO2 drop -> a door/window left open (thermal/air leakage)."""
    if twin.params is None or len(frame) < 5:
        return []
    res = twin.residuals(frame)
    co2_drop = frame["co2"].diff()
    band = 2.5 * res.std()
    alerts = []
    flagged = (res < -band) & (co2_drop < -config.CO2_DROP_PPM)
    for ts in frame.index[flagged.fillna(False)]:
        # crude waste estimate: extra heat loss over the event
        extra_loss_kw = abs(res.loc[ts]) * twin.params.UA_W_per_C / 1000.0
        eur_day = extra_loss_kw * 24 * config.ELECTRICITY_TARIFF_EUR_PER_KWH / config.COP_BASE
        alerts.append(Alert(
            timestamp=ts, device="Room", severity="warning", category="Envelope",
            title="Possible open door/window",
            detail=(f"Room cooling faster than model predicts (residual "
                    f"{res.loc[ts]:.1f}°C) with a CO₂ drop of {co2_drop.loc[ts]:.0f} ppm."),
            eur_per_day=eur_day,
            action="Check for open doors/windows; verify envelope sealing.",
            tags=["EPBD"],
        ))
    return alerts


def comfort(snap: pd.DataFrame, events: pd.DataFrame) -> list[Alert]:
    """Occupied but room is below the comfort target."""
    room = (snap.groupby("last_seen_at")
            .agg(t_in=("status_temperature_in_celsius", "median"),
                 target=("status_target_temperature_in_celsius", "median"))
            .reset_index())
    room = dl.tag_occupancy(room, events, "last_seen_at")
    occ = room[room["is_occupied"]]
    if occ.empty:
        return []
    deficit = (occ["target"] - occ["t_in"])
    unmet = deficit[deficit > config.UNMET_COMFORT_DEFICIT_C]
    if unmet.empty:
        return []
    worst = occ.loc[deficit.idxmax()]
    pct = len(unmet) / len(occ) * 100
    return [Alert(
        timestamp=worst["last_seen_at"], device="Room", severity="warning",
        category="Comfort",
        title=f"Comfort not met for {pct:.0f}% of occupied time",
        detail=(f"Worst: room {worst['t_in']:.1f}°C vs target {worst['target']:.0f}°C "
                f"({deficit.max():.1f}°C short) while occupied."),
        action="Enable predictive preheat (twin estimates lead time) to hit target on arrival.",
        tags=["EPBD"],
    )]


def energy_waste(snap: pd.DataFrame, power: pd.DataFrame, events: pd.DataFrame) -> list[Alert]:
    """Energy spent conditioning an unoccupied room harder than the setback needs."""
    pw = dl.tag_occupancy(power, events, "timestamp")
    unocc = pw[~pw["is_occupied"]]
    if unocc.empty:
        return []
    unocc_kwh = unocc.groupby("timestamp")["power_draw_kw"].sum().sum() * 5 / 60
    total_kwh = power.groupby("timestamp")["power_draw_kw"].sum().sum() * 5 / 60
    share = unocc_kwh / total_kwh if total_kwh else 0
    if share < 0.4:
        return []
    # assume half of unoccupied energy is avoidable with proper setback
    avoidable_kwh = unocc_kwh * 0.5
    eur = avoidable_kwh * config.ELECTRICITY_TARIFF_EUR_PER_KWH
    days = (power["timestamp"].max() - power["timestamp"].min()).total_seconds() / 86400
    return [Alert(
        timestamp=power["timestamp"].max(), device="Room", severity="warning",
        category="Energy",
        title=f"{share*100:.0f}% of energy used while unoccupied",
        detail=(f"{unocc_kwh:.0f} kWh spent on an empty room. Deeper setback / "
                f"occupancy-aware control could avoid ~{avoidable_kwh:.0f} kWh."),
        eur_per_day=eur / max(days, 1),
        action="Apply occupancy-aware setback; align setpoints to the real calendar.",
        tags=["EPBD", "EED"],
    )]


def connectivity(snap: pd.DataFrame, cursor=None) -> list[Alert]:
    """Stale reports and compressor short-cycling."""
    alerts = []
    now = cursor if cursor is not None else snap["last_seen_at"].max()
    for dev, g in snap.groupby("device_name"):
        last = g["last_seen_at"].max()
        gap_min = (now - last).total_seconds() / 60
        if gap_min > config.STALE_REPORT_MINUTES:
            alerts.append(Alert(
                timestamp=last, device=dev, severity="warning", category="Connectivity",
                title=f"No data for {gap_min:.0f} min",
                detail=f"{dev} last reported at {last:%Y-%m-%d %H:%M}.",
                action="Check device network / power.",
            ))
        # short cycling within the last 2h
        recent = g[g["last_seen_at"] >= last - pd.Timedelta("2h")].sort_values("last_seen_at")
        starts = (recent["status_is_compressor_active"].diff() == 1).sum()
        if starts > config.SHORT_CYCLE_STARTS_PER_HOUR * 2:
            alerts.append(Alert(
                timestamp=last, device=dev, severity="info", category="Efficiency",
                title=f"Compressor short-cycling ({starts} starts/2h)",
                detail="Frequent compressor starts reduce efficiency and lifespan.",
                action="Review deadband / staging configuration.",
            ))
    return alerts


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_all(source: dl.ReplaySource, twin: tt.RoomThermalTwin | None = None,
            frame: pd.DataFrame | None = None, cursor=None) -> list[Alert]:
    """Run every detector against data up to `cursor` and return sorted alerts."""
    snap = source.snapshots(up_to=cursor)
    power = source.power(up_to=cursor)
    events = source.events(up_to=cursor)
    if snap.empty:
        return []

    alerts: list[Alert] = []
    alerts += device_alarms(snap)
    alerts += refrigerant_fault(snap, power)
    alerts += comfort(snap, events)
    alerts += energy_waste(snap, power, events)
    alerts += connectivity(snap, cursor=cursor)
    if twin is not None and frame is not None:
        sub = frame[frame.index <= cursor] if cursor is not None else frame
        alerts += envelope_leak(twin, sub)

    alerts.sort(key=lambda a: (-a.severity_rank, -a.eur_per_day))
    return alerts
