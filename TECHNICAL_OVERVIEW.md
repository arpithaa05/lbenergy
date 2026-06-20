# IHL Heat Pump Monitoring System — Technical Overview

An end-to-end explanation of *what* this system calculates, *how* the data flows
from raw CSVs to dashboard numbers, and *what every function does*.

The system is a live-replay monitoring layer for LB Energy's **Intelligent Heat
Link (IHL)** — a fleet of 4 heat-pump units conditioning a single space. It reads
historical telemetry, replays it as if it were streaming, fits a physics model of
the room, and surfaces KPIs, fault/efficiency alerts, and a predictive preheat
planner.

---

## 1. The big picture — how everything connects

```
                    config.py   (one source of truth: constants, paths, thresholds)
                        │
                        ▼
   CSV files  ──►  data_loader.py  ──►  ReplaySource  ──┐
   (telemetry)     (load, decode,       (emit data         │
                    occupancy)           up to a cursor)    │
                                                            ▼
                                  ┌─────────────────────────┼──────────────────────────┐
                                  ▼                         ▼                          ▼
                          thermal_twin.py            kpis.py                    monitors.py
                          (physics model:            (€ / kWh / CO₂,            (6 detectors →
                           fit, predict,              comfort, fleet            Alerts with €
                           simulate, preheat)         health, waste)            impact + action)
                                  └─────────────────────────┼──────────────────────────┘
                                                            ▼
                                                         app.py
                                            (Streamlit dashboard: 5 tabs +
                                             live-replay cursor + KPI strip)
```

**Key design choice:** the rest of the app never touches CSV paths — it talks to a
`DataSource` interface. Today that's `ReplaySource` (historical replay); swapping in
a live MQTT/REST `LiveSource` later would require **zero** changes to the KPIs,
monitors, or UI.

**The "live replay cursor":** the dashboard has a slider for "hours into the
window". Every data query is filtered to `up_to=cursor`, so dragging the slider
replays the week as if it were streaming in real time. Every number on screen is
computed only from data that existed at the cursor moment.

---

## 2. The underlying physics — what is actually being modelled

The room is modelled as a single "bucket" of heat (a one-node RC / lumped-
capacitance model). The governing equation:

```
C · dT/dt = Q_heat − UA · (T_in − T_out) + Q_people
```

| Symbol     | Meaning                          | Units  | Intuition                                   |
|------------|----------------------------------|--------|---------------------------------------------|
| `C`        | Thermal capacitance              | J/°C   | Energy to warm the room 1°C (mass/furniture)|
| `UA`       | Heat-loss coefficient            | W/°C   | How leaky the envelope is                   |
| `Q_heat`   | Delivered heating/cooling power  | W      | What the heat pumps put into the air        |
| `Q_people` | Internal gains from occupants    | W      | Body heat                                   |
| `T_in`     | Room temperature                 | °C     | What we predict                             |
| `T_out`    | Outside temperature              | °C     | The driving disturbance                     |
| `τ = C/UA` | Time constant                    | s      | "How slow" the room responds                |

This system **estimates `C` and `UA` from the data** (least squares), then uses the
model for anomaly detection, validation, and preheat scheduling.

Methodology is borrowed from Arumugam et al. (2023), a lumped-capacitance battery-
thermal paper: RK4 integration, least-squares parameter fitting, and a statistical
validation suite (MAE / RMSE / Willmott's *d*). Their key insight — a *dynamic*
parameter fits far better than a constant one — is mirrored here by modelling a
**dynamic COP(T_out)** instead of a single fixed COP.

---

## 3. `config.py` — central configuration

Every tunable constant lives here so (a) the dashboard can expose sliders and (b)
every module reads one source of truth. Grouped as:

- **Paths** — `DATASET_DIR`, the two `WINDOWS` (heating/cooling), `DEVICES_CSV`.
- **Economics & emissions** — `ELECTRICITY_TARIFF_EUR_PER_KWH` (0.30), `CO2_FACTOR_KG_PER_KWH` (0.38). German/EU defaults, editable on the dashboard.
- **COP model** — `COP_BASE`, `COP_SLOPE`, `COP_REF_T`, `COP_MIN/MAX`, and `ELECTRIC_BACKUP_COP = 1.0` (resistance heating is 1:1, hence wasteful).
- **Device ratings (ASSUMED, not in dataset)** — `RATED_AIRFLOW_M3_PER_H`, air density, air specific heat. These only set the *absolute* scale of COP/heat figures; the fleet-relative comparisons don't depend on their exact values.
- **Space control** — `EVENT_TEMP_C = 21` (occupied setpoint), `MIN_TEMP_C = 11` (setback), `COMFORT_BAND_C = 0.5`.
- **Occupancy / internal-gain model** — `CO2_BASELINE_PPM`, `CO2_PER_PERSON_PPM`, `SENSIBLE_GAIN_PER_PERSON_W`, `IAQ_CO2_LIMIT_PPM`.
- **Detector thresholds** — COP-deficit warn/crit, electric-backup ΔT, UA-jump, CO₂-drop, comfort deficit, stale-report minutes, short-cycle rate.
- **Severity ranking** — `SEVERITY = {critical:3, warning:2, info:1}` for sorting alerts.

---

## 4. `data_loader.py` — the data access layer

Loads the CSVs, decodes alarm bitfields, and serves data "up to a cursor".

### Alarm decoding

- **`_REGISTERS`** — a lookup table mapping the 4 Modbus alarm registers (1901–1904) and each bit position to a human-readable fault name (e.g. bit 2 of register 1901 = "Ckt1 Low Pressure Switch Alarm").
- **`decode_error_registers(value)`** — takes a `"1901,1902,1903,1904"` bitfield string from telemetry and returns the **list of active alarm names**. For each register value it checks every bit (`reg_val & (1 << bit)`) and collects the matching meanings. Returns `[]` for empty/`"0,0,0,0"`.

### Device naming

- **`_device_map()`** — reads `devices.csv` and returns `{device_id: label}` so internal IDs become "Device 1"…"Device 4".

### The DataSource interface

- **`DataSource`** — abstract base declaring the contract: `snapshots(up_to)`, `power(up_to)`, `events()`, and `time_bounds`. Any backend (replay or live) implements this.
- **`ReplaySource(window)`** — the concrete historical backend. On construction it loads three tables for the chosen window:
  - **`_load_snapshots()`** — reads `heat_pump_snapshots.csv` (the per-minute device status). Adds derived columns: `device_name` (mapped), `alarms` (decoded list), `has_alarm` (bool), and `supply_return_dt` (supply − return temperature — the key signature for electric-backup detection).
  - **`_load_power()`** — reads `power_draw.csv` (electrical draw per device, ~5-min samples).
  - **`_load_events()`** — reads `space_events.csv` (the occupancy calendar: when the space was booked/occupied).
  - **`snapshots/power/events(up_to=...)`** — return the full table or only rows at/before the cursor. Events are "known" once they have *started*.
  - **`time_bounds`** — (min, max) timestamp, used to size the replay slider.
  - **`devices`** — sorted list of device names.

### Occupancy helpers

- **`tag_occupancy(df, events, time_col)`** — adds a boolean `is_occupied` column by OR-ing together every calendar event's `[starts_at, ends_at]` interval against each row's timestamp. Used by comfort/energy-waste logic to separate occupied vs empty-room behaviour.
- **`estimate_occupants(co2_ppm)`** — rough head-count from CO₂ above the empty-room baseline: `(co2 − baseline) / ppm_per_person`. The privacy-friendly occupancy signal (aggregate CO₂, no individual tracking).

---

## 5. `thermal_twin.py` — the physics digital twin

The heart of the system. Fits the RC model and uses it three ways.

### Efficiency / heat-flow primitives

- **`cop_for_outside_temp(t_out)`** — the *dynamic* COP: `COP_BASE + COP_SLOPE·(t_out − COP_REF_T)`, clamped to `[COP_MIN, COP_MAX]`. Heat pumps get less efficient as it gets colder; this captures that as a line in outside temperature.
- **`delivered_heat_kw(supply_c, return_c, fan_supply_pct)`** — how much heat a unit actually moves into the air, from first principles:
  ```
  Q = ṁ · cp · (T_supply − T_return)      [kW]
  ```
  where mass flow `ṁ` scales with fan %. **Signed** — positive in heating, negative in cooling.
- **`device_cop(dev_snap)`** — mean delivered heat (kW) for one device, averaged **only over active rows** (heating or cooling demanded). Averaging over idle samples would dilute and understate the true efficiency. The caller divides by electrical power to get the dimensionless COP.

### Validation

- **`validation_metrics(observed, predicted)`** — the model's report card. Returns:
  - **MAE** — mean absolute error (°C).
  - **RMSE** — root-mean-square error (°C) — penalizes large misses harder.
  - **Willmott's d** — index of agreement, 0…1, where 1 = perfect. This is the headline accuracy number shown in the UI.
  - **n** — number of valid points (NaNs masked out).

### The model

- **`TwinParams`** — dataclass holding fitted `C_J_per_C`, `UA_W_per_C`, and derived `tau_hours` (= C/UA/3600). `.summary` is the human-readable string in the sidebar.
- **`RoomThermalTwin`** — fit + simulate the room:
  - **`fit(ts)`** — learns `C` and `UA`. Instead of nonlinear optimization it rewrites the ODE per timestep as a **linear** system:
    ```
    Q_total = C·(dT/dt) + UA·(T_in − T_out)
    ```
    Everything except C and UA is measured, so it's `y = A·[C, UA]` solved in one shot with ordinary least squares (`np.linalg.lstsq`). `dT/dt` is a finite difference. Degenerate fits (negative/NaN) fall back to physically plausible defaults (C = 5 MJ/°C, UA = 200 W/°C).
  - **`predict_one_step(ts)`** — the anomaly-detection workhorse. Predicts each step's temperature from the **previous actual** temperature plus one model step. Because it re-anchors on reality every step, the residual (actual − predicted) isolates exactly what the physics *can't* explain at that instant (e.g. an opened door inflating heat loss). The `.shift(1)` aligns each prediction to the step it predicts.
  - **`validate(ts)`** — runs `predict_one_step` and returns the MAE/RMSE/Willmott metrics.
  - **`residuals(ts)`** — `actual − one-step-prediction`. Large negative values = the room is losing heat faster than physics predicts → unmodelled leak. Consumed by the envelope-leak detector.
  - **`simulate(ts, t0)`** — free-running forward integration with **4th-order Runge-Kutta (RK4)**. Unlike one-step prediction, it integrates from a single starting temperature and never peeks at actuals, so it's the "what-if" engine. Uses a zero-order hold (inputs constant across each step).
  - **`time_to_target(t_start, t_target, t_out, q_heat_w, q_people_w)`** — the **preheat planner**, using the closed-form analytic solution of the RC ODE rather than stepping:
    ```
    T_ss = T_out + (Q_heat + Q_people)/UA      (steady state this power can hold)
    τ    = C/UA
    t    = −τ · ln((T_target − T_ss)/(T_start − T_ss))
    ```
    Returns minutes to reach target, or `None` if the target exceeds what the power can ever reach (then the UI says "increase power").

### Data shaping

- **`build_twin_frame(source, freq="15min")`** — bridges raw telemetry → the clean regular grid the twin needs. It:
  1. Resamples everything onto a regular 15-minute grid (the fit assumes regular sampling).
  2. Takes the **median across the 4 devices** for room temp, outside temp, CO₂.
  3. **Sums delivered heat** across devices (signed — cooling stays negative), converts kW → W.
  4. **Infers `Q_people` from CO₂**: `(co2 − baseline)/ppm_per_person × sensible_gain_per_person`.

  Output columns: `t_in, t_out, q_heat_w, q_people_w` on a datetime index — exactly what `fit`, `predict_one_step`, and `simulate` consume.

---

## 6. `kpis.py` — the dashboard numbers

Everything is computed against data **up to the cursor**, so figures advance as the
week replays.

- **`_energy_kwh(power)`** — total energy: sum power across devices per timestamp, then `× 5/60` (5-minute samples → kWh).
- **`energy_cost_co2(power)`** — wraps energy into `{energy_kwh, cost_eur, co2_kg}` using the tariff and grid CO₂ factor.
- **`waste_breakdown(snap, power, events)`** — the **avoidable-cost engine**, summing two causes:
  1. **Fault waste** — excess energy of any backup/alarm device vs the healthy-fleet median (from `monitors.faulty_devices`).
  2. **Unoccupied conditioning** — energy spent while the room is empty; **half** assumed avoidable with proper setback.
  Returns avoidable kWh, €, and CO₂.
- **`comfort_score(snap, events)`** — over occupied time only: `% of samples within ±COMFORT_BAND_C of target` (comfort %), estimated `unmet_hours` (fraction of time >1°C below target × span), and `mean_deficit`.
- **`fleet_health(snap)`** — from each device's *latest* report: how many are OK vs faulty (any active alarm).
- **`device_table(snap, power)`** — the per-device fleet view: latest status, mean power, **computed COP** (delivered heat ÷ electrical power), and a status of `critical` (alarm or electric-backup signature) / `warning` (COP near the floor) / `ok`.
- **`annualize(eur_for_period, period_days)`** — scales a period figure to a yearly rate (`× 365/days`).
- **`hero_kpis(source, cursor)`** — bundles the top-strip KPIs: energy/cost/CO₂, avoidable €/kWh/CO₂ (annualized), comfort %, unmet hours, fleet OK/total, and the period length in days.

---

## 7. `monitors.py` — the detection engine

Six detectors, each consuming telemetry up to the cursor and emitting `Alert`s.
Every alert carries a **euro impact** and a **concrete recommended action**, plus
compliance **tags** (F-Gas, EPBD, EED), so the value of acting is always explicit.

### The Alert object

- **`Alert`** — dataclass: timestamp, device, severity, category, title, detail, `eur_per_day`, action, tags. `severity_rank` maps to the numeric ranking for sorting; `as_dict()` flattens it for tables.
- **`_REFRIGERANT_ALARMS`** — the set of pressure/gas alarms that drive the F-Gas compliance story (escalated to critical).

### Helpers

- **`_latest_per_device(snap)`** — most recent row per device.
- **`_device_efficiency(snap, power)`** — per-device summary over the window: COP (active periods), total energy, **electric-backup fraction** (compressor off + large ΔT while demand exists), and whether it has a refrigerant alarm.
- **`faulty_devices(eff)`** — devices in backup (`backup_frac > 0.1`) or with a refrigerant alarm, plus their **excess energy vs the healthy-fleet median** (the avoidable amount).

### The 6 detectors

1. **`device_alarms(snap)`** — raw decoded Modbus alarms from the latest report. Refrigerant-related → `critical` + F-Gas tag; others → `warning`.
2. **`refrigerant_fault(snap, power)`** — two signals:
   - **Electric-backup running** (critical): compressor down during demand with a huge supply-return ΔT → emergency resistance heat (COP ≈ 1, very expensive). € impact = excess kWh × tariff / days.
   - **Early COP deficit** (warning/critical): a unit whose COP is ≥25%/50% below the fleet median → possible early refrigerant leak or coil fouling. Pressures are compared *fleet-relative*, not absolutely (they rise with outside temp for everyone).
3. **`envelope_leak(twin, frame)`** — combines the **twin residual** (room cooling faster than physics predicts, beyond 2.5σ) with a **CO₂ drop** → a door/window left open. € impact estimated from the extra heat loss (`|residual| × UA`).
4. **`comfort(snap, events)`** — occupied but below target by more than the deficit threshold. Reports the worst sample and the % of occupied time that was uncomfortable; recommends predictive preheat.
5. **`energy_waste(snap, power, events)`** — fires when ≥40% of energy is spent while unoccupied; assumes half is avoidable with deeper setback / occupancy-aware control.
6. **`connectivity(snap, cursor)`** — **stale reports** (no data beyond `STALE_REPORT_MINUTES`) and **compressor short-cycling** (too many starts in 2h, hurting efficiency and lifespan).

### Orchestration

- **`run_all(source, twin, frame, cursor)`** — runs every detector against data up to the cursor, adds the twin-based envelope-leak alerts when a fitted twin is provided, then **sorts** by severity (descending) and euro impact (descending). This single call powers the entire Alerts tab and the alert-count KPI.

---

## 8. `app.py` — the Streamlit dashboard

The presentation layer. Flow:

1. **`load(window)`** (cached) — builds the `ReplaySource`, the twin input frame, fits the twin, and validates it.
2. **Sidebar** — season window (heating/cooling), the live-replay cursor slider, editable economic assumptions (tariff, CO₂ factor), and the twin-fit quality (RMSE / Willmott's d).
3. **Compute current state** — `hero_kpis`, `run_all` (alerts), `device_table`, all at the cursor.
4. **Hero KPI strip** — avoidable €/yr, energy, CO₂, fleet health, comfort, active alerts.
5. **Five tabs:**
   - **🩺 Fleet** — per-device status cards + total power draw over time (with green occupancy bands).
   - **🔔 Alerts** — the sorted live alert feed with severity, € impact, action, and compliance tags.
   - **🔍 Device detail** — per-device charts: supply/return temps, refrigerant pressures, power draw, air quality (CO₂/humidity).
   - **💰 Impact & Savings** — annualized avoidable cost by cause, savings metrics, and EU compliance posture (F-Gas / EPBD-EED / GDPR).
   - **🧠 Digital Twin** — fitted C/UA/τ, measured-vs-predicted temperature chart, validation metrics, and the **predictive preheat planner** (`time_to_target`).

---

## 9. End-to-end example: one number's journey

**"€X avoidable per year" (top-left KPI):**

1. `app.py` calls `hero_kpis(src, cursor)`.
2. `hero_kpis` calls `waste_breakdown(snap, power, events)`.
3. `waste_breakdown` asks `monitors._device_efficiency` for per-device COP/energy/backup, then `monitors.faulty_devices` for the **excess kWh** of faulty units vs the healthy median — **fault waste**.
4. It tags power with `data_loader.tag_occupancy`, sums empty-room kWh, halves it — **unoccupied waste**.
5. Sum × tariff = avoidable € for the period.
6. `annualize(..., period_days)` scales it to a year.
7. `app.py` renders it in the KPI strip.

Every figure on the dashboard traces back through this same chain: **CSV → ReplaySource (cursor-filtered) → twin/kpis/monitors → app**.

---

## 10. Run it

```bash
cd lbenergy
streamlit run app.py
```

Requires the dataset unzipped at `lbenergy/ihl_research_dataset (1)/` (the path
`config.DATASET_DIR` points to). Dependencies are in `requirements.txt`.
