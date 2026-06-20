"""
Synthetic data generator for the lumped-capacitance room model.

We *choose* ground-truth C and UA, build realistic driving inputs (outside
temperature, heat-pump input, occupancy), then integrate the governing ODE
forward with RK4 to produce the room temperature:

    C * dT/dt = Q_heat - UA*(T_in - T_out) + Q_people

The result is a frame with exactly the columns RoomThermalTwin.fit() expects
(t_in, t_out, q_heat_w, q_people_w on a datetime index), plus the underlying
co2 signal. Because the data is generated *from* the model, fitting it back
should recover C and UA closely -- a clean validation that the formula is right.

Run:  python make_synthetic.py
Output: synthetic_room.csv  +  a fit-recovery report printed to stdout.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config as config
import thermal_twin as tt

# ---------------------------------------------------------------------------
# 1. Ground-truth physical parameters (what we hope to recover by fitting)
# ---------------------------------------------------------------------------
C_TRUE = 6.0e6      # J/degC  (~6 MJ/degC -> a smallish well-furnished room)
UA_TRUE = 180.0     # W/degC  (envelope leakiness)
TAU_TRUE_H = C_TRUE / UA_TRUE / 3600.0
NOISE_C = 0.05      # sensor noise std on room temp (degC); set 0 for a perfect fit

# ---------------------------------------------------------------------------
# 2. Time grid: 7 days at 15-minute resolution (matches build_twin_frame)
# ---------------------------------------------------------------------------
rng = np.random.default_rng(42)
start = pd.Timestamp("2026-03-30 00:00:00")
idx = pd.date_range(start, periods=7 * 24 * 4, freq="15min")
n = len(idx)
hours = (idx - start).total_seconds().to_numpy() / 3600.0
hod = hours % 24                      # hour of day
dow = (idx.dayofweek).to_numpy()      # 0=Mon..6=Sun

# ---------------------------------------------------------------------------
# 3. Driving inputs
# ---------------------------------------------------------------------------
# Outside temperature: diurnal swing around a cool spring mean + slow drift + noise
t_out = (8.0
         + 5.0 * np.sin(2 * np.pi * (hod - 9) / 24)     # coldest ~3am, warmest ~3pm
         + 1.5 * np.sin(2 * np.pi * hours / (24 * 7))   # weekly drift
         + rng.normal(0, 0.3, n))

# Occupancy: people present on weekday working hours (9-18), few stragglers else
occupied = ((dow < 5) & (hod >= 9) & (hod < 18))
people = np.where(occupied, rng.integers(4, 12, n), rng.integers(0, 2, n)).astype(float)
q_people_w = people * config.SENSIBLE_GAIN_PER_PERSON_W

# CO2 follows occupancy (so it is internally consistent with q_people)
co2 = config.CO2_BASELINE_PPM + people * config.CO2_PER_PERSON_PPM + rng.normal(0, 8, n)

# Heat-pump input: a simple thermostat-like schedule.
# Preheat hard before occupancy, hold during, setback at night. (W, signed +heating)
q_heat_w = np.full(n, 1500.0)                       # trickle baseline
q_heat_w[(hod >= 6) & (hod < 9)] = 9000.0           # morning preheat
q_heat_w[(hod >= 9) & (hod < 18)] = 5000.0          # daytime hold
q_heat_w[(hod >= 18) & (hod < 22)] = 3000.0         # evening
q_heat_w += rng.normal(0, 200, n)                   # modulation noise

# ---------------------------------------------------------------------------
# 4. Integrate the ODE forward with RK4 to produce the TRUE room temperature
# ---------------------------------------------------------------------------
def deriv(T, q, to):
    return (q - UA_TRUE * (T - to)) / C_TRUE        # degC/s

dt_s = 15 * 60                                       # 15 min in seconds
t_in = np.empty(n)
t_in[0] = 16.0                                       # cold start
for i in range(1, n):
    # zero-order hold on inputs across the step (use step i's inputs)
    q, to = q_heat_w[i], t_out[i]
    T = t_in[i - 1]
    k1 = deriv(T, q, to)
    k2 = deriv(T + 0.5 * dt_s * k1, q, to)
    k3 = deriv(T + 0.5 * dt_s * k2, q, to)
    k4 = deriv(T + dt_s * k3, q, to)
    t_in[i] = T + (dt_s / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)

t_in_clean = t_in.copy()
t_in = t_in + rng.normal(0, NOISE_C, n)             # add sensor noise

# ---------------------------------------------------------------------------
# 5. Assemble the twin frame and save
# ---------------------------------------------------------------------------
frame = pd.DataFrame(
    {"t_in": t_in, "t_out": t_out, "q_heat_w": q_heat_w,
     "q_people_w": q_people_w, "co2": co2},
    index=idx,
)
frame.index.name = "timestamp"
frame.to_csv("synthetic_room.csv")

# ---------------------------------------------------------------------------
# 6. Fit it back and report recovery vs ground truth
# ---------------------------------------------------------------------------
twin = tt.RoomThermalTwin()
params = twin.fit(frame)
metrics = twin.validate(frame)

print("Synthetic room dataset written to synthetic_room.csv")
print(f"  rows={n}  span={hours[-1]/24:.1f} days  noise={NOISE_C} degC")
print()
print("Ground truth  ->  Recovered by fit()")
print(f"  C  : {C_TRUE/1e6:6.2f} MJ/degC  ->  {params.C_J_per_C/1e6:6.2f} MJ/degC"
      f"   ({100*params.C_J_per_C/C_TRUE:5.1f}%)")
print(f"  UA : {UA_TRUE:6.1f} W/degC   ->  {params.UA_W_per_C:6.1f} W/degC"
      f"   ({100*params.UA_W_per_C/UA_TRUE:5.1f}%)")
print(f"  tau: {TAU_TRUE_H:6.2f} h       ->  {params.tau_hours:6.2f} h")
print()
print("One-step validation:")
print(f"  RMSE {metrics['rmse']:.3f} degC   MAE {metrics['mae']:.3f} degC"
      f"   Willmott d {metrics['willmott_d']:.3f}   (n={metrics['n']})")
