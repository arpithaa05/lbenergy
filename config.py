"""
Central configuration for the IHL Heat Pump Monitoring System.

All tunable constants live here so the dashboard can expose them as sliders and
so every module (twin, monitors, KPIs) reads one source of truth.

NOTE ON ASSUMPTIONS: a few physical ratings (airflow, rated capacity) are not in
the dataset and are assumed here. They are clearly labelled and surfaced on the
dashboard. The relative/fleet-comparison logic does not depend on their exact
values; they only set the absolute scale of COP and delivered-heat figures.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATASET_DIR = BASE_DIR / "ihl_research_dataset (1)"

WINDOWS = {
    "heating": DATASET_DIR / "heating_2026-03-30_to_2026-04-05",
    "cooling": DATASET_DIR / "cooling_2026-05-25_to_2026-05-31",
}
DEVICES_CSV = DATASET_DIR / "devices.csv"

SPACE_ID = "3dbed10b-9e88-4163-916d-3182e2ecc69f"

# ---------------------------------------------------------------------------
# Economics & emissions (German / EU defaults — configurable on the dashboard)
# ---------------------------------------------------------------------------
ELECTRICITY_TARIFF_EUR_PER_KWH = 0.30   # German commercial average
CO2_FACTOR_KG_PER_KWH = 0.38            # German grid intensity (~2023)

# ---------------------------------------------------------------------------
# Heat-pump efficiency reference
# ---------------------------------------------------------------------------
# COP modelled as a function of outside temperature (dynamic, not constant).
# COP(T_out) = COP_BASE + COP_SLOPE * (T_out - COP_REF_T), clipped to bounds.
# This mirrors the paper's "dynamic internal resistance" insight: a single
# constant under-fits; a temperature-dependent parameter fits real behaviour.
COP_BASE = 3.2          # nominal heating COP at the reference outside temp
COP_SLOPE = 0.06        # COP improves as it gets warmer outside (heating)
COP_REF_T = 7.0         # reference outside temp (deg C)
COP_MIN, COP_MAX = 1.8, 5.0
ELECTRIC_BACKUP_COP = 1.0   # resistance heating: 1 kWh elec -> 1 kWh heat

# ---------------------------------------------------------------------------
# Device physical ratings (ASSUMED — see module docstring)
# ---------------------------------------------------------------------------
RATED_AIRFLOW_M3_PER_H = 5000.0   # supply airflow per unit at 100% fan
                                  # (calibrated so a healthy unit's COP lands ~3)
AIR_DENSITY_KG_PER_M3 = 1.2
AIR_CP_KJ_PER_KG_K = 1.005

# ---------------------------------------------------------------------------
# Space control settings (from dataset README)
# ---------------------------------------------------------------------------
EVENT_TEMP_C = 21.0        # comfort setpoint while occupied
MIN_TEMP_C = 11.0          # setback setpoint while unoccupied
COMFORT_BAND_C = 0.5       # +/- tolerance counted as "in comfort"

# ---------------------------------------------------------------------------
# Occupancy / internal-gain model (for the Q_people term)
# ---------------------------------------------------------------------------
CO2_BASELINE_PPM = 450.0       # empty-room CO2 floor
CO2_PER_PERSON_PPM = 15.0      # rough rise per person at steady ventilation
SENSIBLE_GAIN_PER_PERSON_W = 100.0   # sensible heat per occupant
IAQ_CO2_LIMIT_PPM = 1000.0     # indoor-air-quality guideline

# ---------------------------------------------------------------------------
# Detector thresholds
# ---------------------------------------------------------------------------
# Refrigerant-leak / efficiency: how far below fleet-median efficiency before we alarm
COP_DEFICIT_WARN = 0.25        # 25% below fleet median efficiency
COP_DEFICIT_CRIT = 0.50        # 50% below
ELECTRIC_BACKUP_DELTA_T_C = 25.0   # supply-return dT above this with compressor off => resistance backup

# Thermal/envelope leak: relative jump in estimated UA
UA_JUMP_WARN = 1.5             # UA 50% above its own baseline
CO2_DROP_PPM = 60.0            # sudden CO2 drop suggesting an opened door/window

# Comfort
UNMET_COMFORT_DEFICIT_C = 1.0  # occupied but >1C below target
TIME_TO_SETPOINT_WARN_MIN = 60 # took longer than this to reach target

# Connectivity / data health
STALE_REPORT_MINUTES = 10      # no report for longer than this => stale
SHORT_CYCLE_STARTS_PER_HOUR = 6  # compressor starts/hour above this => short-cycling

# Severity levels
SEVERITY = {"critical": 3, "warning": 2, "info": 1}
