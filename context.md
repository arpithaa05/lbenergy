# Project Context — IHL Smart Monitoring System (TUM Hackathon, LB Energy)

> Handoff doc to resume work in a fresh chat. Read this top-to-bottom before continuing.

## 1. The challenge

Sponsor: **LB Energy (LBenergy GmbH)** — makers of the **Intelligent Heat Link (IHL)**, a system
to remotely control heat pumps in tents, halls, and temporary buildings. These structures waste
energy because heating runs continuously or is controlled by hand. IHL already cuts operating
costs 20–30%; the hackathon asks teams to push further.

Motivating scenario: TUM Aerospace campus in Ottobrunn — **11 lecture halls, 29 heat pumps**.
Halls fill at different times; pumps should heat each hall to the right temp exactly when a
lecture starts, and waste nothing otherwise.

The PDF defines **three possible building blocks** (teams may do one deeply or combine):
1. **Predictive control** — predict optimal heat-pump start time per event (weather, humidity, occupancy).
2. **Smart fault / anomaly detection (early-warning)** — distinguish normal vs abnormal from sensor
   data (door-open vs real defect vs tampering), auto-alert the technician.
3. **Impact visualization** — dashboard of kWh / € / CO₂ saved, by event/hall/season; what-if scenarios.

## 2. Our scope decision (IMPORTANT)

The team is building **ONLY Block 2 — the smart monitoring / early-warning system.**
Rationale: LB Energy reportedly already has predictive control + visualization, so we differentiate
on monitoring. **~20 hours total build time.**

Decisions locked via Q&A:
- **Deliverable:** Live dashboard + alerts (replay data as a live stream, anomalies on a timeline, alert feed).
- **Detection method:** Rules + physics first, then add ML/statistical layer if time permits.
- **Stack:** Python full-stack (Streamlit + Plotly is the chosen fast path to demo).

## 3. The differentiator (how we beat "most teams")

Most teams will build generic anomaly detection (isolation forest + red/green dashboard). We
differentiate with a **physics-based digital twin** as the detection backbone:

- Build a **lumped-capacitance (RC) thermal model** of the room → it predicts what the room temp
  *should* be at any moment. **Anomaly = residual** (actual − predicted).
- This gives, for free: **explainable alerts** ("heater ON 32 min, room should be 20.5°C, it's 17.2°C → defect"),
  clean **door-open vs defect** separation (transient self-correcting residual vs growing persistent residual),
  and **robustness across heating & cooling** regimes.

Three extra distinctive features:
1. **Cross-device consensus** — 4 pumps in ONE room. If one sensor disagrees with the other 3, it's a
   sensor fault / tampering, not a room event. (Single-device teams can't do this.)
2. **Early-WARNING (predictive maintenance)** — detect degradation trends (compressor taking longer to
   reach target across days, rising pressure, more frequent cycling) → predict failure before it happens.
3. **Consequence-aware alerts** — not "anomaly" but "Heater defect on Device 3 → Hall misses 21°C for
   Event 7 (08:00 lecture) by ~3°C, burning ~X kWh → dispatch now." Speaks comfort + €.

## 4. The "saving money" simulation (key winning demo)

Monitoring saves money by **killing the cost of faults that run undetected.** Demo it as a
counterfactual race:
- **Without monitoring:** fault runs until a human notices (next inspection / complaint) → wasted-€ climbs.
- **With monitoring:** twin flags it in minutes → intervention → waste curve flattens.
- **Gap between the two curves = money saved**, shown as a live ticking € counter + shaded area.

Money model:
```
savings  = excess_power(kW) × (t_manual_discovery − t_smart_detection) × price
CO2_avoided = wasted_kWh × grid_factor
```
Constants (German, citable): electricity ≈ **€0.30/kWh**, grid CO₂ ≈ **0.38 kg/kWh**.

Make `t_manual_discovery` a **slider** (4h / 1 day / 3 days / weekend) → live sensitivity analysis = credibility.
Headline slide: extrapolate 1 room/1 week → **29 pumps × 1 year** for a big annual €/CO₂ figure.

## 5. The dataset

Location: this folder (`ihl_research_dataset (1)`). Space ID `3dbed10b-9e88-4163-916d-3182e2ecc69f`.
**4 heat pump devices** (`devices.csv`), one climate-controlled room. Two one-week windows:
- `heating_2026-03-30_to_2026-04-05/` (cold, outside ~7°C avg)
- `cooling_2026-05-25_to_2026-05-31/` (warm, outside ~22°C avg)

Per window:
| File | What | Scale |
|---|---|---|
| `heat_pump_snapshots.csv` | Full-res sensor dump, ~1 row/90s/device, 37 cols (room/target/outside temp, humidity, CO₂, VOC, supply/return temps, compressor on/off, heat/cool demand, pressures, **error registers**, connectivity, firmware) | ~29,000 rows |
| `heat_pump_intervals.csv` | Pre-aggregated 15min/1h/6h/1day buckets (medians + maxima) | smaller |
| `power_draw.csv` | Electrical draw **kW every 5 min** per device | 8,064 rows |
| `space_events.csv` | When room is booked/occupied → 21°C applies (else 11°C min). GROUND TRUTH for demand. | 13 (heat) / 15 (cool) |

Control config: room target **21°C when occupied (event), 11°C minimum when empty**. Limits 11–30°C.
Booleans are 1/0; timestamps UTC `YYYY-MM-DD HH:MM:SS`.

`status_error_registers` = 4 Modbus 16-bit bitfields `1901,1902,1903,1904` (e.g. `3,0,512,0`); each bit
is a specific alarm (full decode table in `README.md`). `0,0,0,0` = no alarm.

### Key data realities (already explored)
- Sampling: snapshots ~every 1.5 min; power every 5 min.
- `status_is_alarm_active` is **0 everywhere** in both weeks → real faults are rare/subtle.
  **Therefore we need a fault-injection harness** to synthesize heater-fail / sensor-tamper / door-open
  events on the real stream, to prove + measure the detector (confusion matrix).
- Heating week: room held ~19–20°C; target flips 11↔21; events are big all-day blocks (04:30–21:30).
- Cooling week: most rows still report mode HEAT (only 1,379/29,079 actually COOL); events are realistic
  back-to-back 90-min lecture slots (better for predictive-start demo).
- All 4 device temp sensors report **identical** room temp (synthetic) — std between devices ≈ 0.
- Power is large/industrial: Device 1 avg **12.6 kW** (peak 43), Devices 2–4 ~3–4.5 kW; sum of 4 ≈ 24 kW
  avg, 86 kW peak. **Device 1 does ~3× the others** — itself a monitoring insight / possible anomaly.
- No occupancy column, but **CO₂ (`status_carbon_dioxide_in_ppm`) is an occupancy proxy** (rises with people).
  CO₂ range observed ~397–494 ppm.

## 6. The physics model (digital twin) — DERIVED & FITTED

Lumped-capacitance RC model of the room:
```
C dT/dt = Q_heater − UA·(T_in − T_out) + Q_people
```
- **C** = thermal capacitance (J/°C) — set by room volume/mass.
- **UA** = heat-loss coefficient ("heat leak", W/°C) — set by insulation/envelope.
- **Q_heater** = COP × electrical power.  **Q_people** ≈ 100 W/person (estimate N from CO₂).
- **τ = C / UA** = time constant (room's reaction time).

Closed-form time-to-heat:
```
T_ss = T_out + (Q_heater + Q_people)/UA          # steady-state temp
t = −τ · ln[ (T_target − T_ss) / (T_0 − T_ss) ]   # time to reach target
```

### Fitted values from THIS room's data (do not re-derive from scratch; verify if needed)
| Quantity | Value | How |
|---|---|---|
| **τ (time constant)** | **≈ 2.8 h** (median of 27 heat-up ramp fits, IQR 2.5–3.4) | exponential `curve_fit` on ramps where target jumps 11→21 |
| **Heat leak (assumption-free)** | **≈ 2.5 kW_electric / °C** | 31 kW total draw ÷ 12.6°C gap during steady hold |
| **UA (thermal)** | **≈ 7.4 kW/°C** at COP 3 (range 6.2–8.6 for COP 2.5–3.5) | steady-state balance `UA = Q_heater/(T_in−T_out)` |
| **Design heat loss** | **≈ 155 kW** at 21°C in / 0°C out (COP 3) | UA × ΔT |
| **C (thermal mass)** | **≈ 74 MJ/°C (~20 kWh/°C)**, "effective" | C = UA × τ |

Fitting notes / gotchas:
- Naive regression over ALL rows fails (R²≈0) because the regulated room sits flat ~95% of the time —
  the signal is only in the **heat-up ramps**. Fit the exponential to isolated ramps (target step 11→21).
- **COP is the main uncertainty** for thermal UA. Prefer the **electrical** number (2.5 kW/°C) for cost/CO₂
  since it needs no COP assumption. Could tighten COP later via supply/return temps or a nameplate value.
- τ ≈ 2.8 h means the room is **sluggish** — must pre-heat ~1–2 h before a lecture, which is *why*
  predictive timing matters.

These two constants (τ ≈ 2.8 h, leak ≈ 2.5 kW/°C) fully define the twin → they drive the expected-temp
curve, the time-to-heat, AND the wasted-energy/€. A failed heater shows up as measured leak suddenly
disagreeing with the calibrated 2.5 kW/°C baseline.

## 7. Architecture

```
CSV data ──> Replay engine ──> Detection pipeline ──> Alert manager ──> Streamlit dashboard
(snapshots)  (streams rows     (rules + physics       (dedupe,          (live status cards,
             in time order,     digital-twin           severity,         temp/target/outside
             adjustable speed)  residual, then ML)     cooldown)         timeline w/ anomaly
                  ▲                                                       markers, alert feed,
          Fault-injection harness                                        savings curves + €)
          (heater fail / sensor tamper / door open,
           toggled live from dashboard sidebar)
```
Demo money shot: flip fault toggle → alert fires with diagnosis → two cost-curves split → € counter
spins up → drag discovery-time slider → campus extrapolation.

## 8. 20-hour plan

| Phase | Hrs | What |
|---|---|---|
| 0. Foundation | 2 | Data loader, unified 4-device timeline, EDA to calibrate thresholds. (Twin already partly fitted — see §6.) |
| 1. Detection core (rules+physics) | 5 | 6-state classifier: heater-defect, sensor/tamper, door-transient, daily-drift, alarm-register decode, normal. Each returns state + reason + severity. Built on twin residual. |
| 2. Replay + fault injection | 3 | Stream rows in time order at adjustable speed; injectable synthetic faults on the real stream. |
| 3. Streamlit dashboard | 5 | Live per-device status cards, temp timeline w/ anomaly markers, scrolling alert feed, fault-injection sidebar, **savings curves + € counter + discovery slider**. |
| 4. ML layer | 2 | Isolation forest / temp-residual model on "normal" windows as a second-opinion anomaly score; validate it agrees with rules. |
| 5. Polish + eval | 3 | Confusion matrix on injected faults, demo script, README, mock alert toast (email/Slack-style). |

Cuttable if behind: ML layer (Phase 4), email integration. **Must-protect:** door-vs-defect distinction,
live injection toggle, savings curves.

## 9. Suggested next concrete step

Build a reusable **`ThermalModel`** class so the detector, start-time calc, and savings sim all import
the same calibrated physics:
- `.fit(data)` — fit τ from heat-up ramps.
- `.fit_UA()` / `.heat_leak()` — steady-state heat leak (per room AND per device, to flag Device-1 asymmetry).
- `.time_to_target(T0, T_target, T_out, n_people)` — closed-form heat-up time.
- `.predict_trajectory(...)` — expected-temp curve for residual detection.
- CO₂→occupancy estimator wired into Q_people.

Then proceed to Phase 1 (detection core) on top of it.

## 10. Environment notes
- Windows, working dir = this folder. Python 3.13 available; `pandas`, `numpy`, `scipy` installed
  (`pypdf` installed to read the challenge PDF — it was empty-password "encrypted").
- Challenge PDF: `20260603_ChallengeTUMhackathon_LBenergy (1).pdf` (text extracted to `_challenge.txt`).
- Full data schema + error-register bit decode: `README.md`.
