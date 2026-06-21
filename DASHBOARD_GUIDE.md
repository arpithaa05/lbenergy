# IHL Monitor — Dashboard Guide

A component-by-component walkthrough of the Streamlit dashboard
([app.py](app.py)): what every element on screen means, how it is calculated,
and where the number comes from in the code.

> **Mental model:** the dashboard is a *live replay*. A cursor (slider) sets the
> "current time". **Every** number, chart, and alert is computed only from data
> that existed at/before the cursor. Drag the cursor → the whole dashboard
> advances as if the week were streaming live.

---

## Layout at a glance

```
┌──────────────┬──────────────────────────────────────────────────────┐
│  SIDEBAR     │  TITLE + caption                                       │
│              │                                                        │
│  • Season    │  HERO KPI STRIP (6 metrics)                            │
│  • Cursor    │  💶 Avoidable │ ⚡ Energy │ 🌍 CO₂ │ 🩺 Fleet │ 🌡️ … │ 🔔 │
│  • Economics │                                                        │
│  • Twin fit  │  TABS:  🩺 Fleet │ 🔔 Alerts │ 🔎 Detect │ 💰 Impact │ 🧠 Twin │
│              │  ──────────────────────────────────────────────────── │
│              │  (selected tab content)                                │
└──────────────┴──────────────────────────────────────────────────────┘
```

---

## 1. Sidebar — controls

### Season window  (`heating` / `cooling`)
Picks which historical dataset window to replay. Switching reloads everything
(`load(window)` is cached per window) and re-fits the digital twin on that
window's data.

### ⏱️ Live replay cursor
A slider "Hours into the window". The chosen hour is added to the window start to
produce `cursor`, a timestamp. **This is the single most important control** — it
is passed as `up_to=cursor` to every data query, so it defines "now".
- `hours_total` = full span of the window in hours.
- The current cursor time is printed as **Now: YYYY-MM-DD HH:MM**.

### 💶 Economic assumptions (expander)
Two editable inputs that overwrite the config constants live:
- **Electricity tariff (€/kWh)** → `config.ELECTRICITY_TARIFF_EUR_PER_KWH` (default 0.30).
- **Grid CO₂ factor (kg/kWh)** → `config.CO2_FACTOR_KG_PER_KWH` (default 0.38).

Changing these instantly re-prices every € and CO₂ figure on the dashboard.

### Digital-twin fit caption
Shows the quality of the fitted physics model: **RMSE** (°C), **Willmott's d**
(0–1 agreement index), and the fitted parameters `C`, `UA`, `τ`. Computed once in
`load()` via `twin.validate(frame)`.

---

## 2. Hero KPI strip — the 6 headline numbers

All six come from `kpis.hero_kpis(src, cursor)`. Each is computed on data up to the
cursor.

| KPI | What it means | How it's calculated |
|-----|---------------|---------------------|
| **💶 Avoidable / yr** | Annualised cost of detected waste if acted on | `waste_breakdown` → (fault excess + ½ unoccupied) kWh × tariff, then `annualize(× 365/days)` |
| **⚡ Energy** | Total electricity used (kWh) + its cost (€) | Sum of device power per timestamp × 5/60 (5-min samples → kWh); cost = kWh × tariff |
| **🌍 CO₂** | Emissions from that energy | kWh × grid CO₂ factor |
| **🩺 Fleet health** | Healthy units / total | From each device's *latest* report: OK = no active alarm. Delta shows "all healthy" or "fault!" |
| **🌡️ Comfort** | % of occupied time within the comfort band; unmet hours | `comfort_score`: share of occupied samples within ±0.5°C of target; unmet hours ≈ fraction >1°C below target × span |
| **🔔 Active alerts** | Count of live alerts + how many are critical | `len(run_all(...))`; critical count colours the delta |

**Key formulas:**
- **Energy:** `Σ_timestamp Σ_device power_draw_kw × (5/60)` — 5-minute samples integrated to kWh.
- **Avoidable waste:** `fault_kwh + 0.5 × unoccupied_kwh`, where
  - `fault_kwh` = excess energy of faulty/backup units vs the **healthy-fleet median**,
  - `unoccupied_kwh` = energy used while the calendar shows the room empty (half assumed recoverable with proper setback).

---

## 3. Tab: 🩺 Fleet

### Per-device status cards
One card per unit, from `kpis.device_table(...)`:
- **🟢/🟡/🔴 status** — `ok` / `warning` / `critical`:
  - **critical** = an active alarm, **or** the electric-backup signature (compressor off **and** |supply−return ΔT| ≥ 25°C).
  - **warning** = COP near the floor (`< COP_MIN + 0.3`).
  - **ok** = otherwise.
- **Power (kW)** — mean electrical draw over the window.
- **COP** — **delivered heat ÷ electrical power**. Delivered heat = `ṁ·cp·(T_supply−T_return)` averaged over *active* rows (`thermal_twin.device_cop`); electrical = mean power. A unit on resistance backup shows COP ≈ 1.
- **Alarm / efficiency banner** — decoded Modbus alarm text, or "Below-par efficiency", or "Healthy".

### Total power draw (live) chart
Area chart of **total kW across all devices vs time** (up to the cursor), built by
`power.groupby("timestamp")["power_draw_kw"].sum()`. **Green vertical bands** mark
occupied periods from the space-events calendar (`src.events`). Lets you eyeball
whether power tracks occupancy.

---

## 4. Tab: 🔔 Alerts

The live alert feed, from `monitors.run_all(src, twin, frame, cursor)`. Alerts are
**sorted by severity (desc) then € impact (desc)**. Each card shows:
- **Severity** (colour-coded: critical red / warning orange / info blue) · **category** · **device**.
- **€/day** impact (when applicable).
- **Title** and **detail** (the human explanation).
- **➡️ Recommended action**.
- **Compliance tags** (e.g. `F-Gas EU 2024/573`, `EPBD`, `EED`).

### The 6 detectors feeding this tab
| Detector | Fires when | € impact |
|----------|-----------|----------|
| **device_alarms** | Any decoded Modbus alarm in the latest report (refrigerant ones → critical) | — |
| **refrigerant_fault** | Electric-backup running (compressor off + big ΔT) **or** COP ≥25%/50% below fleet median | excess kWh × tariff / days |
| **envelope_leak** | Twin residual spike (room cools faster than physics) **+** CO₂ drop → open door/window | `\|residual\|·UA` heat loss × tariff |
| **comfort** | Occupied but >1°C below target | — |
| **energy_waste** | ≥40% of energy used while unoccupied | ½ unoccupied kWh × tariff |
| **connectivity** | No report >10 min (stale) or compressor short-cycling | — |

If there are no alerts, a green "No active alerts" message shows instead.

---

## 5. Tab: 🔎 Detect — telling normal from abnormal

The Detect pillar. It uses the digital twin's **residual** (measured − predicted
room temp) to separate normal behaviour from anomalies, and classifies each
anomaly by its signature. Powered by [detect.py](detect.py).

### Residual timeline + normal band
A chart of the residual over time with a green **"normal" band** (`±` a robust
multiple of the clean-fit noise). Inside the band = the room behaves as physics
predicts, including *gradual daily changes* → **no false alarms**. Spikes outside
the band are anomalies, marked and colour-coded by class.

### 🧪 Demo injector
A radio control overlays a synthetic event so the classifier can be shown live
(`detect.inject_scenario`): **door opened**, **heater defect**, **sensor spoof**,
**rogue heating**. "None (real data)" shows the real week (which is clean).

### How each class is told apart (`detect.classify_anomalies`)
| Class | Signature |
|---|---|
| **Door/window open** | residual ≪ 0 (cools faster than predicted) **+ a CO₂ drop** (fresh air in) |
| **Heater defect** | residual ≪ 0 **and sustained** over several steps, no CO₂ drop |
| **Tampering (sensor)** | room temp jumps faster than physically possible (> 6 °C/step) |
| **Tampering (control)** | residual ≫ 0 (room *warms*) with little/no commanded heat |
| **Normal / gradual** | within the band → not flagged |

### ⏰ Early warning (predictive)
`detect.early_warning` free-runs the twin from the latest state at the current
heat output; if the room is projected to fall below the setpoint and not recover,
it warns **before** anyone feels it ("know before freezing students").

### 🔔 Auto-dispatched notifications
`detect.route_notifications` routes detected issues automatically — **critical →
Technician (SMS)**, **warning → Superintendent (email)** — shown as mock messages.
This is the challenge's "automatically alerts the superintendent/technician".

---

## 6. Tab: 💰 Impact & Savings

### "Where the money goes" bar chart
From `kpis.waste_breakdown(...)`, annualised. Two bars:
- **Faulty unit (electric backup)** = `fault_kwh × tariff`, annualised.
- **Empty-room conditioning** = `unoccupied_kwh × 0.5 × tariff`, annualised.

### Savings metrics (right column)
- **Total avoidable / year** — `avoidable_eur_annual` (same as the hero KPI).
- **Avoidable energy / year** — `avoidable_kwh` annualised.
- **Avoidable CO₂ / year** — `avoidable_co2_kg` annualised.
- **% of running cost** — `avoidable_annual / total_annual_cost × 100`, framed against LB Energy's 20–30% efficiency promise.

> **Assumptions surfaced in the caption:** faulty-unit excess is measured vs the
> healthy-fleet median; half of unoccupied-room energy is treated as avoidable via
> occupancy-aware setback.

### 🇪🇺 Compliance posture (3 info cards)
- **F-Gas Reg. (EU 2024/573)** — refrigerant low-pressure events auto-detected & logged for leak-check compliance.
- **EPBD / EED** — continuous technical-system performance monitoring; quantified efficiency measures.
- **GDPR** — occupancy inferred from aggregate CO₂ only; no individual tracking.

---

## 7. Tab: 🧠 Digital Twin

### Fitted model parameters
Three metrics from the least-squares fit (`thermal_twin.RoomThermalTwin.fit`):
- **Thermal mass C** (MJ/°C) — energy to warm the room 1°C.
- **Heat loss UA** (W/°C) — envelope leakiness.
- **Time constant τ** (h) = C/UA — how slowly the room responds.

### Measured vs Twin prediction chart
- **Measured °C** — actual room temperature (`t_in`).
- **Twin prediction** — `twin.predict_one_step(sub)`: each point predicted from the *previous actual* temperature plus one physics step. Tight tracking ⇒ good model; gaps ⇒ unmodelled events.
- Caption shows the **one-step-ahead RMSE, Willmott's d, and n**.

### 🗓️ Auto preheat schedule (from the lecture calendar)
The headline Predict feature, via `twin.preheat_schedule(...)`. It reads the
**lecture calendar** (`space_events`) and, for every lecture still ahead of the
replay cursor, computes when the fleet should switch on.
- Controls: **units to run**, **comfort setpoint °C**, **expected people**.
- Inputs it pulls automatically: **current room temp** (from telemetry at the
  cursor) and **outside temp** (latest measured value, used as a persistence
  forecast — clearly labelled).
- Output: a table of upcoming lectures with **recommended switch-on times** and a
  headline for the next one ("Next lecture 09:00 → switch on at 07:35").
- The *units* control also answers the challenge's **"would N units be enough?"**
  question — drop units and watch lead times grow or flip to "need more units".

### 📈 Proof chart — "reaches the setpoint exactly at lecture start"
For the next reachable lecture, plots the predicted room-temp curve (via
`twin.trajectory(...)`) from the switch-on moment, with the **setpoint line**, the
**switch-on marker**, and the **lecture-start marker**. By construction the curve
crosses the setpoint precisely when the lecture begins — the visible proof of
"right temperature at the right time."

### 🎛️ Thermal physics playground
Interactive simulator, sliders seeded with the **fitted** values:
- Sliders: **C, UA, Q_HVAC (± for cooling), outside temp, people, start temp, duration**.
- Plots the live room-temp curve (`twin.trajectory(...)`, the exact analytic
  solution of the same ODE) plus metrics: **settles at T_ss**, **τ**, **final temp**.
- Drag outside temp down or power off to demo cold-morning / what-if scenarios live.

### 🔮 What-if preheat calculator
Manual sandbox version of the same maths, via `twin.time_to_target(...)`:
- Inputs: **current room °C**, **target °C**, **outside °C**, **units running**, **people**.
- Output: **"Start heating N minutes before occupancy"** to hit the target on arrival.
- Available heat = `units × HEAT_PUMP_DELIVERED_KW_PER_UNIT` (delivered thermal),
  plus occupant body heat.
- Formula (closed-form RC solution):
  ```
  T_ss = T_out + (Q_heat + Q_people)/UA   (steady state this power holds)
  τ    = C/UA
  t    = −τ · ln((T_target − T_ss)/(T_start − T_ss))
  ```
- Reachability guard: if the target sits above `T_ss`, or the lead time would
  exceed 8 h, it shows "run more units" instead of an absurd or impossible time.

---

## 8. Quick reference: where each number comes from

| Dashboard element | Source function | File |
|-------------------|-----------------|------|
| Hero KPI strip | `hero_kpis` | [kpis.py](kpis.py) |
| Energy / cost / CO₂ | `energy_cost_co2` | [kpis.py](kpis.py) |
| Avoidable waste | `waste_breakdown` | [kpis.py](kpis.py) |
| Comfort % / unmet h | `comfort_score` | [kpis.py](kpis.py) |
| Fleet health | `fleet_health` | [kpis.py](kpis.py) |
| Fleet cards (status/COP) | `device_table` | [kpis.py](kpis.py) |
| Alert feed | `run_all` (6 detectors) | [monitors.py](monitors.py) |
| Anomaly classify / inject | `classify_anomalies`, `inject_scenario` | [detect.py](detect.py) |
| Early warning / routing | `early_warning`, `route_notifications` | [detect.py](detect.py) |
| Twin params / chart | `fit`, `predict_one_step`, `validate` | [thermal_twin.py](thermal_twin.py) |
| Auto preheat schedule | `preheat_schedule` | [thermal_twin.py](thermal_twin.py) |
| Proof chart / playground | `trajectory` | [thermal_twin.py](thermal_twin.py) |
| What-if preheat calc | `time_to_target` | [thermal_twin.py](thermal_twin.py) |
| Cursor-filtered data | `ReplaySource.snapshots/power/events(up_to=cursor)` | [data_loader.py](data_loader.py) |

For the deeper physics and full function reference, see
[TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md).
