# IHL Heat Pump Intelligence — Live Monitoring System

A real-time monitoring & alerting layer for **LB Energy's Intelligent Heat Link (IHL)**,
built on the research dataset (one climate-controlled room, 4 heat-pump units,
heating + cooling weeks).

> **One undetected fault was burning 37% of the week's heating energy.**
> Our monitor catches it in minutes, prices it in euros, and flags it for F-Gas
> compliance — then predicts the next failure *before* it happens.

## What it does — predict · detect · visualise

- **Detect** — a rule-based engine surfaces faults, refrigerant leaks, comfort
  failures, energy waste and connectivity issues, each with a **€/day cost** and a
  **recommended action**.
- **Predict** — a physics **digital twin** of the room (lumped-capacitance model,
  fit from data, RK4-validated) forecasts heat-up time for **predictive preheat**
  and isolates unexplained heat loss (open door / envelope leak).
- **Visualise** — a Streamlit dashboard with a **live-replay cursor** that streams
  the historical week as if it were arriving in real time.

## Headline findings (proven on the data)

| Finding | Impact |
|---|---|
| 🔴 Device 1 compressor down → running on 43 kW electric backup, undetected | ~1,500 kWh excess/week = **€29,665/yr avoidable** |
| ⚠️ Cooling an empty room (80% of energy while unoccupied) | Hundreds of kWh/week avoidable |
| 🌡️ Occupants below target 68% of occupied time | Comfort failure despite high energy |

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open the EDA: `eda_deep_dive.ipynb` (deep attribute-by-attribute analysis).

## Architecture

```
DataSource (interface)          <- swap ReplaySource for a live MQTT source
  └─ ReplaySource               to go real-time with ZERO detector/UI changes
data_loader.py   load + occupancy tagging + Modbus alarm decoding
thermal_twin.py  lumped-capacitance room twin: fit C, UA, dynamic COP(T_out);
                 RK4 simulate; one-step-ahead validation (MAE/RMSE/Willmott d)
monitors.py      detection engine -> Alert(severity, €/day, action, compliance tags)
kpis.py          hero KPIs: € avoidable, energy, CO₂, fleet health, comfort
app.py           Streamlit dashboard (live replay)
config.py        tariffs, emissions factors, COP model, thresholds (all tunable)
```

## Methodology note

The digital twin reuses the lumped-capacitance + Runge-Kutta + statistical-validation
methodology of Arumugam et al. (2023), *Lumped Capacitance Thermal Modelling
Approaches for Different Cylindrical Batteries*. Their finding that a **dynamic**
internal resistance outperforms a constant one is mirrored here by a **dynamic
COP(T_out)** instead of a fixed COP.

## EU compliance hooks

- **F-Gas Regulation (EU 2024/573)** — refrigerant low-pressure events auto-detected & logged.
- **EPBD / EED** — continuous technical-system performance monitoring.
- **GDPR** — occupancy inferred from aggregate CO₂ only; no individual tracking.

## Assumptions

Device airflow/rated capacity are not in the dataset; a nominal rating is assumed
(documented in `config.py`) so absolute COP/kW can be shown. All fault detection is
**fleet-relative**, so conclusions do not depend on the exact assumed values.
