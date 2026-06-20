# Predict Pillar — Investigation & Fix Record

**Date:** 2026-06-20
**Context:** LB Energy "Building of the Future" challenge. This document records
why the predictive preheat planner was showing wrong/"unreachable" values, what
we investigated, what we *thought* was wrong vs. what was *actually* wrong, and
the change we made. Written so the whole team has the context.

---

## 1. The challenge, in our words

LB Energy's challenge has three pillars:

1. **Predict** — "*When should each heat pump switch on, so that every hall
   reaches the right temperature exactly when the lecture starts and holds it
   until the end?*" Relevant factors: weather forecast, humidity, number of
   students. Must cope with unseen conditions (cold morning, heatwave).
2. **Detect** — early-warning anomaly detection (door open vs gradual change vs
   real defect vs tampering) that auto-alerts the technician.
3. **Visualize** — kWh / money / CO₂ saved, broken down by event/hall/season,
   plus what-if scenarios ("lower temp by 2 °C?", "4 units instead of 6?").

This record is about **Predict**.

## 2. Honest progress snapshot (at time of writing)

| Pillar | State | ~% |
|---|---|---|
| Predict | Physics twin + validated one-step + **auto schedule-driven preheat planner** + **proof chart** + **interactive simulator** + what-if calculator. | ~90% |
| Detect | 6 detectors (door/envelope, refrigerant/electric-backup defect, comfort, energy waste, connectivity). | ~60% |
| Visualize | Impact tab (€/kWh/CO₂, avoidable waste), Fleet, Alerts, twin charts. | ~55% |

> **Update:** steps 1 and 3 of §7 are done — auto-planner (§9) and proof chart +
> live simulator (§10). Only a real weather-forecast trajectory (§7.2) remains.

**Are we predicting both the right temperature AND the right time?**
- **Time:** yes — `time_to_target` computes the lead time. (Was a manual calculator;
  now realistic, but still not auto-tied to the lecture schedule — see §7.)
- **Temperature:** the *target* is the comfort setpoint (a given, not predicted).
  We *can* predict the temperature trajectory (`predict_one_step`, `simulate`),
  but we don't yet show "predicted curve hits 21 °C exactly at lecture start."

## 3. The symptom

Preheat planner with **room 16 °C, target 21 °C, outside 10.5 °C, heat input 13 kW**
returned **"Target not practically reachable."** Earlier, other inputs returned a
nonsensical **"0 minutes."**

## 4. What we first thought (and why it was WRONG)

Initial hypothesis: *"The fit produces a non-physical UA = 1085 W/°C and time
constant τ = 6.6 h. Recalibrate the assumed airflow (`RATED_AIRFLOW_M3_PER_H`) to
bring UA/τ down and the planner will give sensible times."*

We tested this directly. **It is false:**

| Test | Result |
|---|---|
| Scale delivered heat ×4 (as if airflow ×4) and re-fit | τ = 6.60 h vs 6.58 h — **unchanged** |

**Why τ is invariant to heat scaling:** the fit solves
`Q = C·(dT/dt) + UA·(T_in − T_out)` by least squares. If you multiply all `Q` by
k, the best-fit `C` and `UA` both multiply by k, so **τ = C/UA is unchanged.**
τ is a property of the *dynamics* (how fast temperature responds), not of the heat
*scale*. So airflow recalibration cannot fix τ. (Our earlier advice was wrong; this
is the correction.)

## 5. What is ACTUALLY going on (verified against the data)

1. **The fit is self-consistent.** Steady-state heat balance checks out:
   `UA · mean(T_in − T_out) = 1085 × 11.5 ≈ 12.5 kW` ≈ mean delivered heat 14.5 kW.
2. **Per-device COP is realistic** (1.84, 2.83, 3.08, 2.31 — avg ≈ 2.5). So the
   airflow assumption is already well-calibrated; there is **no COP bug**.
3. **τ = 6.6 h is physically plausible** for a thermally-massive hall (heavy
   walls/slab; building time constants of several hours are normal). It is **not**
   a bug and should **not** be faked smaller.
4. **The real problem was the planner's heat-input field.** It defaulted to
   **12 kW** (≈ one unit), but the 4-unit fleet actually delivers **up to ~67 kW**
   (median 9 kW idle-diluted, p90 44 kW, max 67 kW). Under-powering the scenario
   pushed the required lead time over the 8 h practicality cap → "unreachable".

**Proof** — same scenario (16→21 °C, outside 10.5 °C), varying fleet power:

| Units × 15 kW | Delivered | Preheat time |
|---|---|---|
| 1 × 15 | 15 kW | 362 min |
| 2 × 15 | 30 kW | 101 min |
| 3 × 15 | 45 kW | 59 min |
| 4 × 15 | 60 kW | 42 min |

With realistic fleet power the planner produces sensible times **even with τ = 6.6 h.**

## 6. The change we made (and why)

**We did NOT touch the fit** — it is correct. We fixed the planner's input model so
it reflects the real fleet, and made the units/people explicit.

1. **`config.py`** — added `HEAT_PUMP_DELIVERED_KW_PER_UNIT = 15.0`
   (representative full-output delivered thermal heat per unit, grounded in the
   per-device numbers from the data).
2. **`app.py` preheat planner** — replaced the single "Heat input (kW)" box with:
   - **Units running (1–6)** → available heat = `units × 15 kW` (delivered thermal).
   - **People in hall** → occupant heat `people × 100 W` feeds `Q_people`.
   - A caption showing the resulting kW so it is transparent.
   - Outside-°C help text noting it should be the *forecast* for the slot.

   This makes realistic scenarios reachable, uses the occupancy term the model
   already supports, and **directly answers the challenge's "would N units be
   enough?" question** (vary the units field and watch the preheat time / "more
   units needed" message change).

### Why this is the honest fix
- τ = 6.6 h is real; the planner just needed realistic available power.
- Framing input as *units* matches how the building is actually operated (you turn
  units on/off, you don't dial an arbitrary kW), and unlocks a scenario story.
- The 8 h reachability/practicality guard stays — it now triggers only when the
  chosen units genuinely can't do the job, which is correct behaviour.

## 7. What is still missing to call Predict "complete" (next steps)

In priority order:

1. ~~**Auto, schedule-driven planner.**~~ ✅ **DONE — see §9.**
2. **Real-forecast inputs.** The auto-planner now pulls current room temp from
   telemetry and uses the latest outside temp as a *persistence* forecast. Swap in
   a real weather forecast trajectory (and CO₂-based expected occupancy) to sharpen
   lead times. *(Only remaining Predict item.)*
3. ~~**The "money shot" chart.**~~ ✅ **DONE — see §10** (proof chart + live simulator).
4. **Unseen-conditions story** (cold morning / heatwave): the interactive simulator
   already lets you drag outside temp and watch the curve/τ respond, which covers
   the "never seen before" question live on stage.

Predict is now ~90% and stage-ready. After Predict we move to the **Detect** pillar.

## 8. Key takeaways for the team

- The digital twin and its fit are **sound**; don't "fix" τ — it's real physics.
- τ is **invariant to heat scaling** — remember this if anyone proposes airflow
  tweaks to change the dynamics. It won't.
- The planner now thinks in **units + people**, not a raw kW guess — more honest,
  more operational, and demo-ready for the "4 vs 6 units" question.

## 9. Auto schedule-driven planner (shipped)

This is the literal thing the challenge asks for: *"when should each heat pump
switch on so the hall is warm exactly when the lecture starts?"*

**New function** `thermal_twin.preheat_schedule(twin, frame, events, cursor, units,
target_c, people, t_out_forecast=None)`:
- Looks at every `space_event` whose `starts_at` is **after the current replay
  cursor** ("upcoming lectures").
- Reads the **current room temperature** from the twin frame at the cursor (no
  longer typed by hand).
- Uses the **latest measured outside temp as a persistence forecast** (clearly
  labelled; this is the obvious next thing to upgrade — see §7.2).
- For each lecture, calls `time_to_target(...)` to get the lead time and computes
  `switch_on_at = starts_at − lead`.
- Returns one row per lecture: `{starts_at, switch_on_at, lead_min, t_now, t_out,
  reachable}`.

**Dashboard (Digital Twin tab):** a new "🗓️ Auto preheat schedule" section with
controls for *units to run*, *comfort setpoint*, and *expected people*. It renders
a table of upcoming lectures with their recommended switch-on times and a headline
for the next lecture ("Next lecture 09:00 → switch on at 07:35"). The old manual
planner remains underneath as a "🔮 What-if preheat calculator".

**Why this matters:** inputs are now driven by the actual calendar and telemetry,
not manual guesses — so it demonstrably answers the challenge's core Predict
question, and the *units* control also covers the "would N units be enough?"
scenario.

**Known limitation (be honest on stage):** the outside-temp forecast is currently
persistence (last measured value). A genuine forecast trajectory is the next
upgrade and would make lead times more accurate for cold-morning / heatwave cases.

## 10. Proof chart + interactive simulator (shipped)

Two additions to the Digital Twin tab, both **native Streamlit + Plotly** and both
**grounded in the real fitted twin** (no separate JS app, no arbitrary defaults).

**New method** `RoomThermalTwin.trajectory(t_start, t_out, q_heat_w, q_people_w,
minutes, step_min)` — returns the room-temperature curve under constant inputs as
the **exact analytic solution** of the ODE
`T(t) = T_ss + (T_start − T_ss)·exp(−t/τ)`. It's instant (no stepping), so it can
recompute on every slider move, and it's mathematically identical to a converged
RK4 run for constant inputs.

**📈 Proof chart** — for the next reachable lecture, it plots the predicted curve
from the switch-on moment, with the **setpoint line**, **switch-on marker**, and
**lecture-start marker**. The curve crosses the setpoint *exactly* at lecture start
by construction (verified: at the 44-min lead the curve reads 21.02 °C vs a 21 °C
setpoint). This is the visible proof of "right temperature at the right time."

**🎛️ Thermal physics playground** — sliders for **C, UA, Q_HVAC (±, so cooling
too), T_out, people, start temp, duration**, seeded with the fitted C/UA. The curve
and the "settles at T_ss / τ / final temp" metrics update live. This is our version
of the teammate's interactive simulator, but driven by the same equation and the
real fit — great for answering "what if it's a cold morning?" or "what if we cut
power?" on stage.

**Why this lands with judges:** it shows (1) we understand the physics
interactively, (2) the model is fitted to real data, and (3) the prediction
literally delivers the room warm exactly when the lecture starts.
