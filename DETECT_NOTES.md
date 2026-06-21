# Detect Pillar — Design & Build Notes

**Date:** 2026-06-21
**Context:** LB Energy challenge, "Detect" pillar — *"reliably tell apart what is
normal and what is not: a short drop when a door opens, gradual changes during the
day, a real heater defect, or a tampering attempt"* and *"automatically alert the
superintendent/technician."* Team-shareable record of what we built and why.

## 1. Starting point (what already existed)

`monitors.py` had 6 detectors feeding the Alerts tab: device alarms,
refrigerant/electric-backup fault, envelope leak, comfort, energy waste,
connectivity. On the heating window these fire **3 alerts** — notably the planted
fault on **Device 1** (electric backup 86% of the time, COP 1.84). Heater-defect
detection was therefore already strong.

## 2. Gaps we found vs the challenge's exact wording

| Challenge category | Before |
|---|---|
| Heater defect | ✅ detected (Device 1) |
| Door open | ⚠️ detector existed but nothing fires in this clean week |
| Gradual daily changes | ⚠️ handled implicitly (twin explains them) but never *shown* |
| Tampering | ❌ missing entirely (data is clean: mode always HEAT, never disabled, setpoint follows the 11/21 policy) |
| Auto-alert technician | ❌ only a passive dashboard feed |

The core ask — a visible "normal vs abnormal" story — did not exist. That became
the focus.

## 3. What we built (`detect.py` + new 🔎 Detect tab)

The key idea: the digital twin predicts how the room *should* behave, so the
**one-step residual** (measured − predicted) is ~0 for normal/gradual behaviour
and spikes for anything physics can't explain. The *shape* of the spike classifies
it.

- **`classify_anomalies(twin, frame)`** — flags points where |residual| exceeds a
  band and labels each:
  | Class | Signature |
  |---|---|
  | Door/window open | residual ≪ 0 **+ CO₂ drop** |
  | Heater defect | residual ≪ 0 **sustained**, no CO₂ drop |
  | Tampering (sensor) | room temp jump > 6 °C/step (physically impossible) |
  | Tampering (control) | residual ≫ 0 (warms) with ~no commanded heat |
  | Normal/gradual | within band → not flagged |
- **`inject_scenario(twin, frame, kind, at_frac)`** — overlays a synthetic anomaly
  for live demos (the real week is clean). It injects by **forcing the one-step
  residual to a target** (`T_in = prediction + target`), then forces residual = 0
  after the onset so the room follows physics from its new level. This makes the
  signature exact and location-independent.
- **`early_warning(twin, frame, setpoint)`** — free-runs the twin from the latest
  state; warns if the room is projected below setpoint and not recovering
  ("know before freezing students").
- **`route_notifications(anomalies, alerts)`** — routes issues automatically:
  critical → Technician (SMS), warning → Superintendent (email).

The **Detect tab** shows: residual timeline + normal band + classified markers;
the demo injector radio; a classified-events list; the early-warning box; and the
auto-dispatched notifications panel.

## 4. The hard part — making injection/classification robust

This took several iterations; recorded so nobody repeats the dead-ends:

1. **Additive offsets failed** — adding a fixed temp drop competes with the model's
   expected change (which varies by time of day), so anomalies washed out or
   misfired depending on where they landed.
2. **Cumulative offsets created a fake "recovery jump"** at the episode end that
   misclassified as sensor tampering.
3. **Forcing the residual directly** fixed location-dependence, but a one-step 3 °C
   residual *is* a ~3 °C temp jump → tripped the sensor rule. We separated the
   thresholds: real steps ≤ 1.3 °C, model rate ≤ 2.1 °C, onset jumps ≤ 5 °C, sensor
   spoof = +8 °C, so the **impossible-jump threshold = 6 °C** cleanly separates them.
4. **Recovery rejoin spikes** (the UA feedback prevents an exact rejoin) caused
   secondary false anomalies. Fixed by **dropping the artificial recovery**: after
   the onset, force residual = 0 (room follows physics from its new, offset level) —
   also realistic (a door left open / a heater that stays broken).

**Result:** a sweep across 8 cursor positions × 7 injection points × 4 scenarios
(+ clean checks) = **224 checks, 0 misclassifications, 0 false alarms on clean
data.** Each scenario yields exactly its expected single label.

## 5. Tuning knobs (top of `detect.py`)

- `RESIDUAL_BAND_K = 3.0`, `RESIDUAL_BAND_FLOOR = 2.0` — anomaly band (floor sits
  above the clean-fit noise max of ~1.8 °C, so gradual changes never false-alarm).
- `TEMP_JUMP_IMPLAUSIBLE_C = 6.0` — sensor-spoof threshold.
- `DEFECT_MIN_STEPS = 2` — how sustained a cooling episode must be to be a defect
  vs a transient.

## 6. Honest limitations (say these on stage)

- The real provided week contains **no tampering or door events**, so those classes
  are demonstrated via injection (clearly labelled "Demo"). The detector logic is
  real; the trigger data is synthetic.
- Device-level faults (Device 1) are caught by `monitors.py` at the device level;
  the room-residual classifier is complementary (room-behaviour anomalies). Both
  feed the notification routing.
- Notifications are mocked (SMS/email panels), not actually sent — wiring a real
  webhook/Twilio/email is a small, obvious next step.

## 7. Status

Detect ~85%. Remaining polish: real notification delivery, and folding the
classifier/early-warning into the live `run_all` feed so the hero "Active alerts"
KPI reflects them too.
