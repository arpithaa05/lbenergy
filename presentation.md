# 🧠 Digital Twin · 🔎 Detect · 💰 Impact — Explainer & Presentation

> A physics model of the room, fit to one week of the building's own telemetry,
> powering the challenge's **three pillars**:
>
> 1. **Predict** — *"When do we switch the heating on so the room is comfortable
>    exactly when the lecture starts?"* (the Digital Twin)
> 2. **Detect** — *"Is the room behaving normally, or is this a door, a defect, or
>    tampering?"* — and alert the right person automatically.
> 3. **Visualize** — *"What does intelligent control actually deliver in € / kWh /
>    CO₂, and what if we changed something?"* (Impact & Savings)
>
> The link between them: the twin predicts how the room *should* behave, so the
> gap between prediction and reality (the **residual**) drives Detect, while the
> waste it quantifies drives the Impact numbers.

All numbers below are the **real fitted values** from the heating-season window
(30 Mar – 5 Apr 2026, 4 devices, 670 fifteen-minute samples).

**Document map:**
- **Part 1 (§1–6)** — the Digital Twin: physics, fitted room, preheat worked examples.
- **Part 2 (§7–10)** — the Detect pillar: residual-based anomaly classification.
- **Part 3 (§11–13)** — Impact & Savings: the savings story and what-if scenarios.
- **Shared (§14–16)** — constants, the one-line story, and anticipated Q&A.

## 0. The dashboard at a glance (orientation for the team)

Before the deep-dives, the shape of the app:

- **Live replay cursor** (sidebar) — sets "now". *Every* number, chart and alert is
  computed only from data up to the cursor, so dragging it replays the week as if
  streaming live. Defaults to hour 80 (mid-week, so the schedule shows lectures).
- **Hero KPI strip** (always visible) — six headline metrics: Avoidable €/yr,
  Energy, CO₂, Fleet health, Comfort %, Active alerts. Each has a hover "?".
- **Five tabs:**
  - **Fleet** — per-unit status cards (power, COP, alarms) + total power draw with
    occupied bands. This is where the faulty **Device 1** shows (COP 1.6, electric
    backup) against three healthy units (COP 2.3–3.2).
  - **Alerts** — the live, severity-sorted feed, each alert with € impact, an action,
    and the compliance regime it supports.
  - **Detect** — Part 2.
  - **Impact & Savings** — Part 3.
  - **Digital Twin** — Part 1.

---

# PART 1 — 🧠 The Digital Twin (predict & preheat)

## 1. The one idea behind everything

The whole tab is driven by a single equation — a "lumped-capacitance" (single-node
RC) model of the room:

```
C · dT/dt  =  Q_heat  −  UA·(T_in − T_out)  +  Q_people
```

In plain English:

> **How fast the room's temperature changes** = heat we pump in − heat leaking out
> through the walls + body heat from people.

| Symbol | Name | Meaning |
|---|---|---|
| `C` | Thermal mass (capacitance) | Energy needed to warm the room 1 °C (air + walls + furniture) |
| `UA` | Heat-loss coefficient | Watts lost per 1 °C indoor–outdoor difference (envelope leakiness) |
| `Q_heat` | Delivered heating power | What the heat-pump fleet actually puts into the room |
| `Q_people` | Internal gains | Body heat from occupants (~100 W each) |
| `T_in / T_out` | Room / outside temperature | |

That's it. Every chart, slider, and calculator on the tab is this equation with
different inputs.

---

## 2. The room, as the model sees it (the fitted parameters)

We don't guess `C` and `UA` — we **fit them from real telemetry** by least-squares,
then validate the fit one-step-ahead.

| Parameter | Fitted value | What it says about *this* room |
|---|---|---|
| Thermal mass **C** | **25.7 MJ/°C** | Takes 25.7 million joules to warm the room 1 °C |
| Heat loss **UA** | **1085 W/°C** | Loses 1085 W for every 1 °C indoor–outdoor gap |
| Time constant **τ** | **6.6 h** | `τ = C / UA` — the room's natural response speed |

**How trustworthy is it?**

| Metric | Value | Meaning |
|---|---|---|
| RMSE | **0.64 °C** | Average prediction error |
| Willmott's *d* | **0.94** | Index of agreement (1.0 = perfect) |
| n | 670 | Samples validated |

> 🗣️ **Talking point:** *"We didn't invent these numbers — they're fit from a week
> of the building's own data and validated to within ⅔ of a degree."*

**Why τ = 6.6 h matters:** it's a fairly heavy, somewhat leaky room. That's *why*
preheat lead times come out in hours, not minutes — it's the honest consequence of
the fit, not a modelling artefact.

---

## 3. Worked example — "How early do we switch on?"

**Scenario:** Room is **16 °C**, the lecture needs **21 °C**, it's **5 °C** outside,
and we run **2 units** (2 × 15 kW = **30 kW** delivered).

### Step 1 — Where will the room settle? (steady state)

```
T_ss = T_out + Q_heat / UA
     = 5 + 30000 / 1085
     = 5 + 27.6
     = 32.6 °C
```

The room *wants* to drift to 32.6 °C — comfortably above our 21 °C target, so the
target is **reachable**. ✅

### Step 2 — How fast does it get there? (time constant)

```
τ = C / UA = 25.7×10⁶ / 1085 = 23,700 s = 6.6 h
```

### Step 3 — Time to reach 21 °C

```
t = −τ · ln( (T_target − T_ss) / (T_start − T_ss) )
  = −6.6 · ln( (21 − 32.6) / (16 − 32.6) )
  = −6.6 · ln(0.70)
  = 141 minutes
```

> ✅ **Answer: switch on 2 hours 21 minutes before the lecture.**

---

## 4. Why sizing matters (same room, varying units)

Same start (16 °C → 21 °C, 5 °C outside), only changing how many units run:

| Units | Delivered | Settles at (T_ss) | Lead time | Verdict |
|---|---|---|---|---|
| **1** | 15 kW | **18.8 °C** | — | ❌ **never reaches 21 °C** — settles below target |
| **2** | 30 kW | 32.6 °C | **141 min** | ✅ comfortable but slow |
| **3** | 45 kW | 46.5 °C | **71 min** | ✅ good |
| **4** | 60 kW | 60.3 °C | **47 min** | ✅ fast |

> 🗣️ **Killer talking point:** *"With one unit, the room **physically cannot** reach
> 21 °C on a 5 °C day — it tops out at 18.8 °C. The twin catches this before you've
> wasted an hour pre-running a unit that was never going to be enough."*
> (That's the `⚠️ need more units` flag in the app.)

---

## 5. People are free heat

Same 2-unit scenario, but the hall fills up (each person ≈ 100 W):

| Occupants | Extra heat | Lead time | Saving vs empty |
|---|---|---|---|
| 0 | 0 kW | 141 min | baseline |
| 50 | 5 kW | **106 min** | −35 min |
| 100 | 10 kW | **85 min** | **−56 min** |

> 🗣️ **Talking point:** *"100 students add 10 kW of body heat — that alone cuts nearly
> an hour off the preheat. The twin accounts for it; a fixed timer can't."*

---

## 6. The tab, section by section (for your teammates)

The Digital Twin tab has four parts. **All four use the exact same equation** — they
just differ in inputs and outputs.

### A. Fitted parameters + validation chart
The three metrics from §2, plus a chart overlaying **measured °C** vs the **twin's
prediction**. This is the "is the model trustworthy?" proof (RMSE / Willmott's d).

### B. 🗓️ Auto preheat schedule — *the automated answer*
Reads the **lecture calendar** and computes, for every upcoming lecture, when to
switch on. Three inputs:

| Input | Default | Controls |
|---|---|---|
| Units to run | = device count | More units → more kW → shorter lead |
| Comfort setpoint °C | 21.0 | Target temp by lecture start |
| Expected people | 0 | Anticipated body heat helps |

> Caveat shown in-app: it uses the **latest measured** outside temp as a naive
> "persistence forecast." Swap in a real weather forecast for production accuracy.

### C. 🎛️ Thermal physics playground — *intuition builder*
A free sandbox. Seven sliders (seeded with the fitted values) let you invent any
room and watch the curve:

| Slider | Effect |
|---|---|
| Thermal mass C | Bigger = slower to heat/cool (more inertia) |
| Heat loss UA | Bigger = leakier envelope |
| HVAC power Q (− = cooling) | Heat delivered; negative = cooling mode |
| Outside temp | Colder = more loss, lower settling point |
| People in room | ~100 W of body heat each |
| Starting room temp | Where the sim begins |
| Simulate hours | Length of the run |

Readouts: **Settles at (T_ss)**, **Time constant τ**, **temperature after the run**.

### D. 🔮 What-if preheat calculator — *manual one-off answer*
The manual version of B. Punch in any scenario (current temp, target, outside temp,
units, people) and it returns either *"start N minutes before occupancy"* or
*"target not practically reachable — run more units."*

---

# PART 2 — 🔎 The Detect Pillar (normal vs abnormal)

> The challenge: *"reliably tell apart what is normal and what is not — a short drop
> when a door opens, gradual changes during the day, a real heater defect, or a
> tampering attempt — and automatically alert the superintendent/technician."*

---

## 7. The core insight — let physics define "normal"

We don't set thresholds on raw temperature (that would false-alarm every cold
morning). Instead we use the twin's **one-step residual**:

```
residual  =  measured room temp  −  twin's prediction
```

- **Gradual daily changes** are *explained* by the model → residual stays ~0 → **no
  false alarm**. (This is the bit a naive threshold gets wrong.)
- **Anything physics can't explain** → residual spikes. The **shape** of that spike
  (sign, duration, and what CO₂ / commanded heat are doing) tells us *which* of the
  four cases it is.

The "normal" band is **±2.0 °C** of residual — set deliberately above the clean-fit
noise (RMSE 0.64 °C, max ~1.8 °C), so real gradual behaviour never trips it.

> 🗣️ **Talking point:** *"We let the physics define normal. Gradual daily drift is
> predicted, so it's silent. We only alarm on what the model genuinely can't
> explain — that's how we avoid the false-alarm fatigue that kills these systems."*

---

## 8. The four signatures (how it classifies)

| Class | Signature | Severity | Alerts |
|---|---|---|---|
| **Door / window open** | residual ≪ 0 (cools faster than predicted) **+ CO₂ drop** | warning | Superintendent |
| **Heater defect** | residual ≪ 0 **sustained** (≥ 2 steps), **no CO₂ drop** | critical | Technician |
| **Tampering (sensor)** | temp jumps **> 6 °C in one step** — physically impossible | critical | Technician |
| **Tampering (control)** | residual ≫ 0 (room *warms*) with **~no commanded heat** | warning | Superintendent |
| **Normal / gradual** | within ±2 °C band | — | (silent) |

The CO₂ drop is the clever discriminator: a door and a defect both make the room
cool, but **only the door lets fresh air in**, so a simultaneous CO₂ fall separates
the two.

---

## 9. Live demo — inject a scenario, watch it classify

The provided week is *clean* (no faults/tampering in the real data), so the Detect
tab has a **🧪 demo injector** that overlays a synthetic event. The detector logic is
real; only the trigger is synthetic (say this on stage — it's the honest framing).

These are the **actual classifier outputs** when each scenario is injected:

| Injected scenario | Detected as | Residual | Severity | Routed to |
|---|---|---|---|---|
| Door / window opened | ✅ Door/window open | −3.0 °C | warning | 📱→ Superintendent |
| Heater defect | ✅ Heater defect | −2.6 °C | critical | 📱 SMS → Technician |
| Tampering — sensor spoof | ✅ Tampering (sensor) | +7.0 °C | critical | 📱 SMS → Technician |
| Tampering — rogue heating | ✅ Tampering (control) | +2.8 °C | warning | ✉️ → Superintendent |
| **None (real data)** | ✅ **No anomalies** | — | — | — |

> 🗣️ **Killer talking point:** *"Four different faults, four correct labels, each
> routed to the right person automatically — and zero false alarms on the clean week.
> A validation sweep of **224 checks (8 cursor positions × 7 injection points × 4
> scenarios) produced 0 misclassifications.**"*

**Why injection is done by forcing the residual** (a build detail worth knowing if
asked): we set `T_in = prediction + target`, so the injected signature is exact and
independent of where in the week it lands. Naive additive offsets failed because
they competed with the model's time-of-day expected change. (Full dead-ends are in
[DETECT_NOTES.md](DETECT_NOTES.md).)

---

## 10. Two more pieces: early warning + auto-routing

**⏰ Early warning (predictive).** Beyond reacting to anomalies, the twin *free-runs*
from the current state under the current heat output and projects the temperature
forward. If the room is heading below setpoint and **not recovering**, it warns
*before* students feel it — "know before freezing," not "report after."

**🔔 Auto-dispatched notifications.** Every detected issue is routed automatically by
severity — the literal answer to the challenge's "automatically alert" requirement:

| Severity | Channel | Recipient |
|---|---|---|
| critical | 📱 SMS | Technician |
| warning | ✉️ Email | Superintendent |

> Honest limitation to state: notifications are **mocked** (SMS/email panels), not
> actually delivered — wiring a real Twilio/webhook is a small, obvious next step.

---

# PART 3 — 💰 Impact & Savings (visualize the value)

> The challenge: *"site managers need a visualization that clearly shows what
> intelligent control delivers in kWh saved, money saved, and CO₂ avoided… and
> answers what-ifs like 'what if I lower the temperature 2 °C?' or 'would N units be
> enough?'"*

All figures below are the **full heating week** (drag the cursor to the end); they
scale with the cursor like everything else.

## 11. Baseline vs intelligent control (the headline)

The money slide: annual running cost **as-is** vs **after acting on the waste the
system detects** (the faulty unit on electric backup + conditioning empty rooms).

| | Annual cost | Annual CO₂ |
|---|---|---|
| **Without IHL action** | **€62,700** | 79,400 kg |
| **With IHL control** | **€33,000** | 41,900 kg |
| **Saved** | **≈ €29,700 / yr (47%)** | **≈ 37,600 kg / yr** |

> 🗣️ **Honesty point (say it, it's a strength):** *"This week shows 47% because it
> includes **fixing a genuinely faulty unit** plus occupancy-aware setback. LB
> Energy's steady-state efficiency promise is 20–30%; we're transparent that this
> particular window also has a fault to fix."* The app says exactly this.

## 12. Where the money goes + the "lower the setpoint" what-if

**By cause (annualised):**

| Cause | €/yr | Fix |
|---|---|---|
| Faulty unit (electric backup) | **≈ €23,500** | Dispatch maintenance (Detect already flags it) |
| Empty-room conditioning | **≈ €6,100** | Occupancy-aware setback (the preheat scheduler) |

**"What if we lower the setpoint by X °C?"** — an interactive slider. Lowering the
indoor target shrinks the indoor–outdoor gap that drives heat loss, so heating
energy falls roughly in proportion:

| Setpoint change | Annual saving | (on this week) |
|---|---|---|
| −1 °C (21→20) | **≈ €5,500/yr** | ~9% |
| −2 °C (21→19) | **≈ €10,900/yr** | ~17% |

> Rule of thumb on this data: **~9% saving per °C**, because the mean indoor–outdoor
> gap is ≈ 11.5 °C (saving ≈ ΔT / gap). Heating season; comfort trade-off applies.

> 🗣️ **Talking point:** *"Two of the challenge's literal what-if questions are live,
> not hand-waved: drag the units field to answer 'would N units be enough?' (Digital
> Twin tab), and the setpoint slider to answer 'what if we lower the temperature
> 2 °C?' — €10,900/yr here."*

## 13. Compliance posture (trust for stakeholders)

Three cards, each linking to the **official EU regulation text** so a site manager
can verify directly:

| Card | What we do | Links to |
|---|---|---|
| **F-Gas (EU 2024/573)** | Refrigerant low-pressure events auto-detected & logged for leak checks | EUR-Lex regulation |
| **EPBD / EED** | Continuous technical-system performance monitoring; quantified measures | EUR-Lex directives |
| **GDPR (EU 2016/679)** | Occupancy from aggregate CO₂ only — no individual tracking | EUR-Lex regulation |

> 🗣️ **Talking point:** *"It's not just savings — every claim is tied to a named EU
> regulation a stakeholder can click through and verify."*

---

# SHARED — constants, story, and Q&A

## 14. The constants behind the numbers

So nobody asks "where did that come from?":

*Digital Twin:*

| Constant | Value | Source |
|---|---|---|
| Delivered heat per unit | 15 kW | `config.HEAT_PUMP_DELIVERED_KW_PER_UNIT` |
| Sensible heat per person | 100 W | `config.SENSIBLE_GAIN_PER_PERSON_W` |
| Heat-pump efficiency | COP = 3.2 + 0.06·(T_out − 7), clamped 1.8–5.0 | `config.COP_*` |
| CO₂ → occupancy | 450 ppm baseline, +15 ppm/person | `config.CO2_*` |

*Detect (tuning knobs, top of `detect.py`):*

| Constant | Value | Meaning |
|---|---|---|
| `RESIDUAL_BAND_K` / `_FLOOR` | 3.0 σ / 2.0 °C floor | Normal band = max(3·robust σ, 2 °C) |
| `TEMP_JUMP_IMPLAUSIBLE_C` | 6.0 °C/step | Above this = sensor spoof (physically impossible) |
| `DEFECT_MIN_STEPS` | 2 | Sustained cooling steps to call it a defect vs a transient |
| `CO2_DROP_PPM` | 60 ppm | Sudden CO₂ fall ⇒ fresh air in ⇒ door signature |

**Dynamic COP:** efficiency improves as it warms up outside — mirroring the
"dynamic parameter" idea from Arumugam et al. (2023), the methodology reference for
the RK4 integration and least-squares fit.

---

## 15. The one-line story for the deck

> *"One physics model, fit to a week of the building's own data and validated to
> 0.64 °C, does three jobs: it tells us **exactly when to switch the heating on**
> (start 2 h 21 min before, with 2 units); the **same prediction-vs-reality gap
> catches doors, defects, and tampering — auto-routing each to the right person**
> with zero false alarms; and it **quantifies the value — ≈ €29,700/yr saved (47%)
> on this week** — with every what-if (units, setpoint) live, not hand-waved."*

---

## 16. Anticipated questions (and answers)

**Q: Why are the lead times hours long?**
The room's time constant is τ = 6.6 h — it's heavy and somewhat leaky. Long preheat
windows are physically correct for this building, which is exactly why planning them
matters.

**Q: What about a cold snap / changing weather?**
Today it assumes the last measured outside temp (persistence forecast). The code
already accepts a `t_out_forecast` argument — drop in a real forecast to sharpen it.

**Q: How do you know the model is right?**
One-step-ahead validation on held-out telemetry: RMSE 0.64 °C, Willmott's d 0.94.
The prediction-vs-measured chart shows it visually.

**Q: 47% savings seems higher than LB Energy's 20–30% claim — is that inflated?**
No, and we say so up-front. This particular week includes a **faulty unit running on
electric backup**, so ~€23,500/yr of the saving is one-off fault-fixing, not
steady-state efficiency. Strip that out and the recurring setback/occupancy savings
land squarely in the 20–30% range. We show both honestly rather than hiding the fault.

**Q: How is the "lower setpoint" saving calculated?**
Heat loss is `UA·(T_in − T_out)`, so lowering the indoor target by ΔT cuts the loss
roughly by `ΔT / (mean indoor–outdoor gap)`. The gap here is ≈ 11.5 °C → ~9% per °C.
It's a first-order estimate with an explicit comfort trade-off, not a precise
guarantee.

**Q: Where do C and UA come from?**
Least-squares fit of the energy-balance equation to the observed room temperature —
no manual tuning. (See `thermal_twin.py → RoomThermalTwin.fit`.)

**Q: If the real week has no faults, are the anomalies fake?**
The *trigger data* is injected (clearly labelled "Demo"), but the **detector logic is
real** and runs on whatever data it's given. We separate the two honestly: the
classifier scored 224/224 on a validation sweep and 0 false alarms on the untouched
week.

**Q: How do you avoid false alarms on normal daily temperature swings?**
That's the whole point of using the *residual* instead of raw temperature. Gradual
daily changes are predicted by the physics, so the residual stays inside the ±2 °C
band and nothing fires. We only alarm on what the model can't explain.

**Q: How does it tell a door from a heater defect — both cool the room?**
CO₂. A door lets fresh air in, so the room cools **and** CO₂ drops together → "door."
A defect cools the room with **no** CO₂ drop and the cooling is **sustained** →
"defect." Different signatures, different recipients.

**Q: Are the alerts actually sent?**
Routing logic is real (critical → Technician/SMS, warning → Superintendent/email);
delivery is currently mocked in the UI. Wiring Twilio/email/webhook is a small,
well-scoped next step.
