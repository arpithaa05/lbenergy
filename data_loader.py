"""
Data access layer for the IHL Heat Pump Monitoring System.

Design goal: the rest of the app talks to a DataSource, never to CSV paths.
- ReplaySource reads the historical dataset and can emit it up to any cursor
  time, so the dashboard can "play" the week as if it were live.
- A future LiveSource (MQTT / REST from the IHL box) implements the same
  interface, so going real-time requires zero changes to monitors or UI.
"""

from __future__ import annotations

import pandas as pd

import lbenergy.config as config

# ---------------------------------------------------------------------------
# Alarm-register decoding (Modbus registers 1901-1904, see dataset README)
# ---------------------------------------------------------------------------
_REGISTERS = [
    {  # 1901
        0: "Outside Air Humidity Sensor Fault", 1: "Ckt1 High Pressure Switch Alarm",
        2: "Ckt1 Low Pressure Switch Alarm", 3: "Ckt1 Compressor 1 Alarm",
        4: "Ckt1 Compressor 2 Alarm", 5: "Ckt1 Compressor 3 Alarm",
        6: "Ckt1 Discharge Pressure Sensor Fault", 7: "Ckt1 Suction Pressure Sensor Fault",
        8: "General Alarm", 9: "Temperature Sensor Fault", 10: "Supply Fan Fault",
        11: "Return Fan Fault", 12: "Supply Air Temp Sensor Fault",
        13: "Return Air Temp Sensor Fault", 14: "Outside Air Temp Sensor Fault",
        15: "Return Air Humidity Sensor Fault",
    },
    {  # 1902
        0: "Filter Alarm 2", 1: "Heat Recovery System Fault", 2: "Hot Water Coil Fault",
        3: "Gas-Fired Fault", 4: "Electrical Heater Fault", 5: "Ckt1 High Pressure Alarm",
        6: "Ckt1 Low Pressure Alarm", 7: "Ckt2 High Pressure Alarm",
        8: "Ckt2 High Pressure Switch Alarm", 9: "Ckt2 Low Pressure Switch Alarm",
        10: "Ckt2 Compressor 1 Alarm", 11: "Ckt2 Compressor 2 Alarm",
        12: "Ckt2 Compressor 3 Alarm", 13: "Ckt2 Discharge Pressure Sensor Fault",
        14: "Ckt2 Suction Pressure Sensor Fault", 15: "Filter Alarm 1",
    },
    {  # 1903
        0: "Ckt1 Comp1 Maintenance", 1: "Ckt1 Comp2 Maintenance", 2: "Ckt1 Comp3 Maintenance",
        3: "Ckt2 Comp1 Maintenance", 4: "Ckt2 Comp2 Maintenance", 5: "Ckt2 Comp3 Maintenance",
        6: "Ckt1 Suction Temp Sensor Fault", 7: "Ckt2 Suction Temp Sensor Fault",
        8: "Ckt2 Low Pressure Alarm", 9: "Fire Detector Alarm", 10: "Supply Air Flow Sensor Fault",
        11: "Return Air Flow Sensor Fault", 12: "Phase Fault Alarm",
        13: "Pre-Electrical Heater Alarm", 14: "Supply Fan Maintenance", 15: "Exhaust Fan Maintenance",
    },
    {  # 1904
        0: "A2L Gas Detector Fault", 1: "Additional Board Fault",
        8: "Ckt1 EEV Driver Alarm", 9: "Ckt2 EEV Driver Alarm",
        10: "Ckt1 EEV Driver Connection Alarm", 11: "Ckt2 EEV Driver Connection Alarm",
        12: "Exhaust Air Flow Sensor Fault", 13: "Plate Heat Exchanger Temp Sensor Fault",
        14: "Ckt1 Condenser Fan Alarm", 15: "Ckt2 Condenser Fan Alarm",
    },
]


def decode_error_registers(value) -> list[str]:
    """Turn a "1901,1902,1903,1904" bitfield string into a list of active alarms."""
    if not isinstance(value, str) or value.strip() in ("", "0,0,0,0"):
        return []
    try:
        parts = [int(x) for x in value.split(",")]
    except ValueError:
        return []
    alarms = []
    for reg_val, reg_def in zip(parts, _REGISTERS):
        for bit, meaning in reg_def.items():
            if reg_val & (1 << bit):
                alarms.append(meaning)
    return alarms


def _device_map() -> dict:
    dev = pd.read_csv(config.DEVICES_CSV)
    return dict(zip(dev["device_id"], dev["label"]))


class DataSource:
    """Interface every data backend implements."""

    def snapshots(self, up_to=None) -> pd.DataFrame:
        raise NotImplementedError

    def power(self, up_to=None) -> pd.DataFrame:
        raise NotImplementedError

    def events(self) -> pd.DataFrame:
        raise NotImplementedError

    @property
    def time_bounds(self):
        raise NotImplementedError


class ReplaySource(DataSource):
    """Replays one historical window (heating/cooling) as if it were streaming."""

    def __init__(self, window: str = "heating"):
        if window not in config.WINDOWS:
            raise ValueError(f"window must be one of {list(config.WINDOWS)}")
        self.window = window
        self._dir = config.WINDOWS[window]
        self._dmap = _device_map()
        self._snap = self._load_snapshots()
        self._power = self._load_power()
        self._events = self._load_events()

    # -- loading -----------------------------------------------------------
    def _load_snapshots(self) -> pd.DataFrame:
        df = pd.read_csv(self._dir / "heat_pump_snapshots.csv", parse_dates=["last_seen_at"])
        df["device_name"] = df["device_id"].map(self._dmap)
        df["alarms"] = df["status_error_registers"].apply(decode_error_registers)
        df["has_alarm"] = df["alarms"].apply(len) > 0
        df["supply_return_dt"] = (
            df["status_temperature_supply_in_celsius"] - df["status_temperature_return_in_celsius"]
        )
        df = df.sort_values("last_seen_at").reset_index(drop=True)
        return df

    def _load_power(self) -> pd.DataFrame:
        df = pd.read_csv(self._dir / "power_draw.csv", parse_dates=["timestamp"])
        if "device_name" not in df.columns:
            df["device_name"] = df["device_id"].map(self._dmap)
        return df.sort_values("timestamp").reset_index(drop=True)

    def _load_events(self) -> pd.DataFrame:
        df = pd.read_csv(self._dir / "space_events.csv", parse_dates=["starts_at", "ends_at"])
        return df.sort_values("starts_at").reset_index(drop=True)

    # -- DataSource interface ---------------------------------------------
    def snapshots(self, up_to=None) -> pd.DataFrame:
        if up_to is None:
            return self._snap
        return self._snap[self._snap["last_seen_at"] <= up_to]

    def power(self, up_to=None) -> pd.DataFrame:
        if up_to is None:
            return self._power
        return self._power[self._power["timestamp"] <= up_to]

    def events(self, up_to=None) -> pd.DataFrame:
        if up_to is None:
            return self._events
        # an event is "known" once it has started
        return self._events[self._events["starts_at"] <= up_to]

    @property
    def time_bounds(self):
        return self._snap["last_seen_at"].min(), self._snap["last_seen_at"].max()

    @property
    def devices(self) -> list[str]:
        return sorted(self._snap["device_name"].dropna().unique().tolist())


# ---------------------------------------------------------------------------
# Occupancy helpers
# ---------------------------------------------------------------------------
def tag_occupancy(df: pd.DataFrame, events: pd.DataFrame, time_col: str) -> pd.DataFrame:
    """Add a boolean `is_occupied` column based on space events."""
    df = df.copy()
    occupied = pd.Series(False, index=df.index)
    for _, ev in events.iterrows():
        occupied |= (df[time_col] >= ev["starts_at"]) & (df[time_col] <= ev["ends_at"])
    df["is_occupied"] = occupied.values
    return df


def estimate_occupants(co2_ppm: float) -> float:
    """Rough occupant count from CO2 above the empty-room baseline."""
    rise = max(0.0, co2_ppm - config.CO2_BASELINE_PPM)
    return rise / config.CO2_PER_PERSON_PPM
