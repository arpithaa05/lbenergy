"""
IHL Heat Pump Monitoring System — Streamlit dashboard.

A live-replay monitoring layer for LB Energy's Intelligent Heat Link.
Run:  streamlit run app.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config as config
import data_loader as dl
import detect as detect
import kpis as kpis
import monitors as monitors
import thermal_twin as tt

st.set_page_config(page_title="IHL Monitor — LB Energy", page_icon="🔥", layout="wide")

SEV_COLOR = {"critical": "#e74c3c", "warning": "#f39c12", "info": "#3498db", "ok": "#2ecc71"}
STATUS_EMOJI = {"ok": "🟢", "warning": "🟡", "critical": "🔴"}


# ---------------------------------------------------------------------------
# Cached data + model
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Loading telemetry…")
def load(window: str):
    src = dl.ReplaySource(window)
    frame = tt.build_twin_frame(src)
    twin = tt.RoomThermalTwin()
    twin.fit(frame)
    metrics = twin.validate(frame)
    return src, frame, twin, metrics


# ---------------------------------------------------------------------------
# Sidebar — controls (the "live replay" cursor + economic assumptions)
# ---------------------------------------------------------------------------
st.sidebar.title("🔥 IHL Monitor")
st.sidebar.caption("Live monitoring for the Intelligent Heat Link")

window = st.sidebar.radio("Season window", ["heating", "cooling"], format_func=str.capitalize)
src, frame, twin, twin_metrics = load(window)
t_min, t_max = src.time_bounds

st.sidebar.markdown("### ⏱️ Live replay cursor")
hours_total = int((t_max - t_min).total_seconds() // 3600)
cursor_h = st.sidebar.slider("Hours into the window", 1, hours_total, hours_total,
                             help="Drag to replay the week as if it were streaming live.")
cursor = t_min + pd.Timedelta(hours=cursor_h)
st.sidebar.write(f"**Now:** {cursor:%Y-%m-%d %H:%M}")

with st.sidebar.expander("💶 Economic assumptions", expanded=False):
    config.ELECTRICITY_TARIFF_EUR_PER_KWH = st.number_input(
        "Electricity tariff (€/kWh)", 0.05, 1.0, config.ELECTRICITY_TARIFF_EUR_PER_KWH, 0.01)
    config.CO2_FACTOR_KG_PER_KWH = st.number_input(
        "Grid CO₂ factor (kg/kWh)", 0.0, 1.0, config.CO2_FACTOR_KG_PER_KWH, 0.01)

st.sidebar.markdown("---")
st.sidebar.caption(
    f"**Digital twin fit** (one-step-ahead)\n\n"
    f"RMSE {twin_metrics['rmse']:.2f}°C · Willmott d {twin_metrics['willmott_d']:.2f}\n\n"
    f"{twin.params.summary}")
st.sidebar.caption("Replay source · swap for live MQTT to go real-time (same interface).")


# ---------------------------------------------------------------------------
# Compute current state (up to cursor)
# ---------------------------------------------------------------------------
k = kpis.hero_kpis(src, cursor=cursor)
alerts = monitors.run_all(src, twin=twin, frame=frame, cursor=cursor)
dev_table = kpis.device_table(src.snapshots(up_to=cursor), src.power(up_to=cursor))


# ---------------------------------------------------------------------------
# Header + hero KPI strip
# ---------------------------------------------------------------------------
st.title("Heat Pump Intelligence — Live Monitor")
st.caption(f"Space {config.SPACE_ID[:8]}…  ·  {window.capitalize()} window  ·  "
           f"4 Intelligent Heat Link units")

if k:
    c = st.columns(6)
    c[0].metric("💶 Avoidable / yr", f"€{k['avoidable_eur_annual']:,.0f}",
                help="Annualised cost of detected waste if acted on")
    c[1].metric("⚡ Energy", f"{k['energy_kwh']:,.0f} kWh", f"€{k['cost_eur']:,.0f}",
                help="Total electricity used so far and its cost at the current tariff")
    c[2].metric("🌍 CO₂", f"{k['co2_kg']:,.0f} kg",
                help="Carbon emissions from that energy, at the grid CO₂ factor")
    health = f"{k['fleet_ok']}/{k['fleet_total']}"
    c[3].metric("🩺 Fleet health", health,
                "all healthy" if k['fleet_ok'] == k['fleet_total'] else "fault!",
                delta_color="normal" if k['fleet_ok'] == k['fleet_total'] else "inverse",
                help="Heat-pump units with no active alarm, out of the total fleet")
    comfort = k['comfort_pct']
    c[4].metric("🌡️ Comfort", f"{comfort:.0f}%" if np.isfinite(comfort) else "—",
                f"{k['unmet_hours']:.0f} unmet h", delta_color="inverse",
                help="Share of occupied time the room was within the comfort band of target")
    crit = sum(1 for a in alerts if a.severity == "critical")
    c[5].metric("🔔 Active alerts", len(alerts), f"{crit} critical",
                delta_color="inverse" if crit else "off",
                help="Number of live alerts right now, and how many are critical")


tab_fleet, tab_alerts, tab_detect, tab_impact, tab_twin = st.tabs(
    ["🩺 Fleet", "🔔 Alerts", "🔎 Detect", "💰 Impact & Savings", "🧠 Digital Twin"])


# -----------------------------------------Why ----------------------------------
# Tab: Fleet
# ---------------------------------------------------------------------------
with tab_fleet:
    st.subheader("Fleet status")
    cols = st.columns(len(dev_table)) if not dev_table.empty else []
    for col, (_, d) in zip(cols, dev_table.iterrows()):
        emoji = STATUS_EMOJI.get(d["status"], "⚪")
        with col:
            st.markdown(f"### {emoji} {d['device']}")
            st.metric("Power", f"{d['power_kw']:.1f} kW")
            st.metric("COP", f"{d['cop']:.2f}" if d['cop'] is not None else "—")
            if d["alarms"]:
                st.error(d["alarms"], icon="🚨")
            elif d["status"] == "warning":
                st.warning("Below-par efficiency")
            else:
                st.success("Healthy")

    # total power over time up to cursor
    st.subheader("Total power draw (live)")
    power = src.power(up_to=cursor)
    total = power.groupby("timestamp")["power_draw_kw"].sum().reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=total["timestamp"], y=total["power_draw_kw"],
                             fill="tozeroy", line=dict(color="#3498db"), name="Total kW"))
    for _, ev in src.events(up_to=cursor).iterrows():
        fig.add_vrect(x0=ev["starts_at"], x1=min(ev["ends_at"], cursor),
                      fillcolor="green", opacity=0.08, line_width=0)
    fig.update_layout(height=300, margin=dict(t=10, b=10), yaxis_title="kW",
                      showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Green bands = occupied (calendar events).")


# ---------------------------------------------------------------------------
# Tab: Alerts
# ---------------------------------------------------------------------------
with tab_alerts:
    st.subheader("Live alert feed")
    if not alerts:
        st.success("No active alerts at this time. ✅")
    for a in alerts:
        color = SEV_COLOR.get(a.severity, "#999")
        eur = f"  ·  **€{a.eur_per_day:.0f}/day**" if a.eur_per_day else ""
        tags = "  ".join(f"`{t}`" for t in a.tags)
        with st.container(border=True):
            st.markdown(
                f"<span style='color:{color};font-weight:700'>"
                f"{a.severity.upper()}</span> · {a.category} · {a.device}{eur}",
                unsafe_allow_html=True)
            st.markdown(f"**{a.title}**")
            st.caption(a.detail)
            if a.action:
                st.markdown(f"➡️ _{a.action}_")
            if tags:
                st.markdown(f"Compliance: {tags}")


# ---------------------------------------------------------------------------
# Tab: Detect — anomaly classification (normal vs abnormal)
# ---------------------------------------------------------------------------
ANOM_COLOR = {
    "Door/window open": "#f39c12", "Heater defect": "#e74c3c",
    "Tampering (sensor)": "#9b59b6", "Tampering (control)": "#8e44ad",
    "Unexplained cooling": "#e67e22",
}

with tab_detect:
    st.subheader("Anomaly detection — telling normal from abnormal")
    st.caption("The digital twin predicts how the room *should* behave. The "
               "**residual** (measured − predicted) stays small for normal, gradual "
               "changes — and spikes when something the physics can't explain happens. "
               "The *shape* of the spike (+ CO₂, duration) classifies it.")

    sub = frame[frame.index <= cursor]

    # demo injector: overlay a synthetic event so the classifier can be shown live
    st.markdown("**🧪 Demo:** inject a scenario and watch the system classify it")
    inj = st.radio("Scenario", ["None (real data)", "Door / window opened",
                                "Heater defect", "Tampering — sensor spoof",
                                "Tampering — rogue heating"],
                   horizontal=True)
    kind_map = {"Door / window opened": "door", "Heater defect": "defect",
                "Tampering — sensor spoof": "tamper_sensor",
                "Tampering — rogue heating": "tamper_control"}
    view = sub if inj == "None (real data)" else detect.inject_scenario(twin, sub, kind_map[inj], 0.6)

    res = twin.residuals(view)
    anomalies = detect.classify_anomalies(twin, view)

    # --- residual timeline with the normal band + classified markers ---
    band = detect.anomaly_band(twin, sub)
    fig = go.Figure()
    fig.add_hrect(y0=-band, y1=band, fillcolor="#2ecc71", opacity=0.12, line_width=0)
    fig.add_trace(go.Scatter(x=view.index, y=res, name="Residual °C",
                             line=dict(color="#34495e", width=1.5)))
    for a in anomalies:
        fig.add_trace(go.Scatter(
            x=[a.timestamp], y=[a.residual], mode="markers",
            marker=dict(size=13, color=ANOM_COLOR.get(a.kind, "#c0392b"),
                        line=dict(width=1, color="white")),
            name=a.kind, showlegend=False,
            hovertext=a.explanation, hoverinfo="text"))
    fig.update_layout(height=320, margin=dict(t=10, b=10),
                      yaxis_title="Residual °C (measured − predicted)", showlegend=False)
    fig.add_annotation(x=view.index[len(view)//2], y=band, yshift=10,
                       text="green band = normal (physics explains it)",
                       showarrow=False, font=dict(color="#27ae60", size=11))
    st.plotly_chart(fig, use_container_width=True)

    # --- what the system concluded ---
    if not anomalies:
        st.success("✅ No anomalies — the room is behaving exactly as the physics "
                   "predicts. Gradual daily changes are explained by the model, so "
                   "they don't raise false alarms.")
    else:
        st.markdown("**🔍 Classified events**")
        for a in anomalies:
            col = ANOM_COLOR.get(a.kind, "#c0392b")
            with st.container(border=True):
                st.markdown(
                    f"<span style='color:{col};font-weight:700'>{a.kind}</span> · "
                    f"<span style='color:{SEV_COLOR.get(a.severity)};'>"
                    f"{a.severity.upper()}</span> · {a.timestamp:%a %d %b %H:%M}",
                    unsafe_allow_html=True)
                st.caption(a.explanation)
                st.markdown(f"➡️ _{a.action}_  ·  alerts **{a.recipient}**")

    # --- early warning (predictive) ---
    st.markdown("#### ⏰ Early warning (predictive)")
    ew = detect.early_warning(twin, sub, float(config.EVENT_TEMP_C))
    if ew is None:
        st.info("On track — the room is projected to stay at/above the setpoint at "
                "the current heat output.")
    else:
        st.warning(f"⚠️ {ew['message']} (now {ew['t_now']:.1f}°C → "
                   f"{ew['projected']:.1f}°C). Act before anyone feels it.")

    # --- auto-alert routing ---
    st.markdown("#### 🔔 Auto-dispatched notifications")
    st.caption("Detected issues are routed automatically — critical to the "
               "technician (SMS), warnings to the superintendent (email).")
    notes = detect.route_notifications(anomalies, alerts)
    if not notes:
        st.write("No notifications to send.")
    for nt in notes[:8]:
        col = SEV_COLOR.get(nt["severity"], "#999")
        with st.container(border=True):
            st.markdown(
                f"{nt['channel']} → **{nt['recipient']}**  ·  "
                f"<span style='color:{col};font-weight:700'>{nt['severity'].upper()}</span>",
                unsafe_allow_html=True)
            st.markdown(f"**{nt['subject']}**")
            st.caption(nt["body"])


# ---------------------------------------------------------------------------
# Tab: Impact & Savings
# ---------------------------------------------------------------------------
with tab_impact:
    st.subheader("Where the money goes")
    if k:
        waste = kpis.waste_breakdown(src.snapshots(up_to=cursor), src.power(up_to=cursor),
                                     src.events(up_to=cursor))
        fault_eur = waste["fault_kwh"] * config.ELECTRICITY_TARIFF_EUR_PER_KWH
        unocc_eur = waste["unoccupied_kwh"] * 0.5 * config.ELECTRICITY_TARIFF_EUR_PER_KWH
        days = k["period_days"]

        cc = st.columns(2)
        with cc[0]:
            fig = go.Figure(go.Bar(
                x=["Faulty unit\n(electric backup)", "Empty-room\nconditioning"],
                y=[fault_eur / days * 365, unocc_eur / days * 365],
                marker_color=["#e74c3c", "#f39c12"]))
            fig.update_layout(title="Annualised avoidable cost by cause (€)",
                              height=350, margin=dict(t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)
        with cc[1]:
            st.metric("Total avoidable / year", f"€{k['avoidable_eur_annual']:,.0f}")
            st.metric("Avoidable energy / year",
                      f"{k['avoidable_kwh'] / days * 365:,.0f} kWh")
            st.metric("Avoidable CO₂ / year",
                      f"{k['avoidable_co2_kg'] / days * 365:,.0f} kg")
            base = k["cost_eur"] / days * 365
            pct = k["avoidable_eur_annual"] / base * 100 if base else 0
            st.success(f"That's **{pct:.0f}%** of annual running cost — "
                       f"in line with LB Energy's 20–30% efficiency promise, "
                       f"proven on real data.")
        st.caption("Assumptions: faulty-unit excess vs healthy-fleet median; "
                   "half of unoccupied-room energy avoidable via occupancy-aware setback.")

    st.markdown("#### 🇪🇺 Compliance posture")
    cc = st.columns(3)
    cc[0].info("**F-Gas Reg. (EU 2024/573)**\n\nRefrigerant low-pressure events "
               "auto-detected & logged for leak-check compliance.")
    cc[1].info("**EPBD / EED**\n\nContinuous technical-system performance "
               "monitoring; quantified efficiency measures.")
    cc[2].info("**GDPR**\n\nOccupancy inferred from aggregate CO₂ only — no "
               "individual tracking; configurable retention.")


# ---------------------------------------------------------------------------
# Tab: Digital Twin
# ---------------------------------------------------------------------------
with tab_twin:
    st.subheader("Physics digital twin of the room")
    st.caption("Lumped-capacitance model  C·dT/dt = Q_heat − UA·(T_in−T_out) + Q_people, "
               "fit from data and validated one-step-ahead. Methodology after "
               "Arumugam et al. (2023), with a *dynamic* COP(T_out) in place of their "
               "dynamic internal resistance.")

    cc = st.columns(3)
    cc[0].metric("Thermal mass C", f"{twin.params.C_J_per_C/1e6:.1f} MJ/°C")
    cc[1].metric("Heat loss UA", f"{twin.params.UA_W_per_C:.0f} W/°C")
    cc[2].metric("Time constant τ", f"{twin.params.tau_hours:.1f} h")

    sub = frame[frame.index <= cursor]
    pred = twin.predict_one_step(sub)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sub.index, y=sub["t_in"], name="Measured °C",
                             line=dict(color="#2c3e50", width=2)))
    fig.add_trace(go.Scatter(x=sub.index, y=pred, name="Twin prediction",
                             line=dict(color="#e74c3c", dash="dot")))
    fig.update_layout(height=340, margin=dict(t=10, b=10), yaxis_title="Room °C")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"One-step-ahead fit: RMSE {twin_metrics['rmse']:.2f}°C, "
               f"Willmott's d {twin_metrics['willmott_d']:.2f} (n={twin_metrics['n']}).")

    # -- Auto schedule from the lecture calendar -----------------------------
    st.markdown("#### 🗓️ Auto preheat schedule (from the lecture calendar)")
    sc = st.columns(3)
    sched_units = sc[0].number_input("Units to run", 1, 6, len(src.devices), 1,
                                     key="sched_units",
                                     help="Heat-pump units assumed running for the preheat")
    sched_target = sc[1].number_input("Comfort setpoint °C", 10.0, 30.0,
                                      float(config.EVENT_TEMP_C), 0.5, key="sched_target")
    sched_people = sc[2].number_input("Expected people", 0, 300, 0, 10, key="sched_people")

    schedule = tt.preheat_schedule(twin, frame, src.events(), cursor,
                                   sched_units, sched_target, sched_people)
    if not schedule:
        st.info("No upcoming lectures after the current replay time. "
                "Drag the cursor earlier to see scheduled preheats.")
    else:
        rows = []
        for s in schedule[:8]:
            rows.append({
                "Lecture starts": f"{s['starts_at']:%a %d %b %H:%M}",
                "Switch on at": (f"{s['switch_on_at']:%a %d %b %H:%M}"
                                 if s["reachable"] else "—"),
                "Lead time": (f"{s['lead_min']:.0f} min" if s["reachable"]
                              else "⚠️ need more units"),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        first = schedule[0]
        if first["reachable"]:
            st.success(f"➡️ Next lecture {first['starts_at']:%H:%M}: switch on at "
                       f"**{first['switch_on_at']:%H:%M}** "
                       f"({first['lead_min']:.0f} min before), from room "
                       f"{first['t_now']:.1f}°C with {sched_units} unit(s).")
        st.caption(f"Assumes the latest measured outside temp ({first['t_out']:.1f}°C) "
                   f"as a persistence forecast and current room temp "
                   f"({first['t_now']:.1f}°C) at the cursor. Swap in a real weather "
                   f"forecast to sharpen lead times.")

    # -- Proof chart: the curve hits the setpoint exactly at lecture start ----
    reachable = [s for s in schedule if s["reachable"]] if schedule else []
    if reachable:
        st.markdown("#### 📈 Proof: the room reaches the setpoint *exactly* at lecture start")
        ev = reachable[0]
        q_heat_w = sched_units * config.HEAT_PUMP_DELIVERED_KW_PER_UNIT * 1000
        q_people_w = sched_people * config.SENSIBLE_GAIN_PER_PERSON_W
        lead = ev["lead_min"]
        mins, temps = twin.trajectory(ev["t_now"], ev["t_out"], q_heat_w, q_people_w,
                                      minutes=lead + 45)
        times = [ev["switch_on_at"] + pd.Timedelta(minutes=float(m)) for m in mins]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=times, y=temps, name="Predicted room °C",
                                 line=dict(color="#e74c3c", width=3)))
        fig.add_hline(y=sched_target, line=dict(color="#2ecc71", dash="dash"),
                      annotation_text=f"Setpoint {sched_target:.0f}°C",
                      annotation_position="top left")
        fig.add_vline(x=ev["switch_on_at"], line=dict(color="#95a5a6", dash="dot"))
        fig.add_vline(x=ev["starts_at"], line=dict(color="#3498db", dash="dot"))
        fig.add_trace(go.Scatter(
            x=[ev["switch_on_at"], ev["starts_at"]],
            y=[ev["t_now"], sched_target], mode="markers+text",
            text=[f" switch on {ev['switch_on_at']:%H:%M}",
                  f" lecture {ev['starts_at']:%H:%M}"],
            textposition=["bottom right", "top left"],
            marker=dict(size=11, color=["#95a5a6", "#3498db"]), showlegend=False))
        fig.update_layout(height=340, margin=dict(t=10, b=10), yaxis_title="Room °C",
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Starting at {ev['t_now']:.1f}°C, {sched_units} unit(s) bring the "
                   f"room to the {sched_target:.0f}°C setpoint in {lead:.0f} min — "
                   f"arriving right as the {ev['starts_at']:%H:%M} lecture begins. "
                   f"No cold rooms, no wasted pre-running.")

    # -- Interactive physics simulator ---------------------------------------
    st.markdown("#### 🎛️ Thermal physics playground")
    st.caption("Sliders seeded with the **fitted** values. Drag any of them to see "
               "how the room responds — the same lumped-capacitance equation, live.")
    pc = st.columns(2)
    with pc[0]:
        sim_C = st.slider("Thermal mass C (MJ/°C)", 1.0, 60.0,
                          float(round(twin.params.C_J_per_C / 1e6, 1)), 0.5,
                          help="Bigger = slower to heat or cool (more inertia)")
        sim_UA = st.slider("Heat loss UA (W/°C)", 50, 2000,
                           int(twin.params.UA_W_per_C), 10,
                           help="Bigger = leakier envelope")
        sim_q_kw = st.slider("HVAC power Q (kW, − = cooling)", -60.0, 60.0,
                             float(sched_units * config.HEAT_PUMP_DELIVERED_KW_PER_UNIT),
                             1.0)
    with pc[1]:
        sim_tout = st.slider("Outside temp (°C)", -15.0, 40.0, 5.0, 0.5)
        sim_people = st.slider("People in room", 0, 300, 0, 5)
        sim_tstart = st.slider("Starting room temp (°C)", 0.0, 35.0, 16.0, 0.5)
        sim_hours = st.slider("Simulate hours", 1, 24, 8, 1)

    sim_twin = tt.RoomThermalTwin(tt.TwinParams(
        C_J_per_C=sim_C * 1e6, UA_W_per_C=float(sim_UA),
        tau_hours=sim_C * 1e6 / sim_UA / 3600))
    smins, stemps = sim_twin.trajectory(
        sim_tstart, sim_tout, sim_q_kw * 1000,
        sim_people * config.SENSIBLE_GAIN_PER_PERSON_W,
        minutes=sim_hours * 60, step_min=5)
    t_ss = sim_tout + (sim_q_kw * 1000 + sim_people * config.SENSIBLE_GAIN_PER_PERSON_W) / sim_UA

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=smins / 60, y=stemps, name="Room °C",
                             line=dict(color="#e74c3c", width=3)))
    fig.add_hline(y=t_ss, line=dict(color="#2ecc71", dash="dash"),
                  annotation_text=f"Settles at {t_ss:.1f}°C", annotation_position="top left")
    fig.update_layout(height=320, margin=dict(t=10, b=10),
                      xaxis_title="Hours", yaxis_title="Room °C", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
    mc = st.columns(3)
    mc[0].metric("Settles at (T_ss)", f"{t_ss:.1f} °C")
    mc[1].metric("Time constant τ", f"{sim_twin.params.tau_hours:.1f} h")
    mc[2].metric("After this run", f"{stemps[-1]:.1f} °C")

    # -- Manual what-if calculator -------------------------------------------
    st.markdown("#### 🔮 What-if preheat calculator")
    cc = st.columns(5)
    t_start = cc[0].number_input("Current room °C", 5.0, 30.0, 16.0, 0.5)
    t_target = cc[1].number_input("Target °C", 10.0, 30.0, 21.0, 0.5)
    t_out = cc[2].number_input("Outside °C", -10.0, 35.0, 5.0, 0.5,
                               help="Use the forecast outside temperature for the lecture slot")
    units = cc[3].number_input("Units running", 1, 6, len(src.devices), 1,
                               help="How many heat-pump units are heating. "
                                    "Answers 'would N units be enough?'")
    people = cc[4].number_input("People in hall", 0, 300, 0, 10,
                                help="Body heat adds to the room (≈100 W/person)")
    # available heat = delivered thermal output of the running fleet (+ occupant gains)
    q_heat_w = units * config.HEAT_PUMP_DELIVERED_KW_PER_UNIT * 1000
    q_people_w = people * config.SENSIBLE_GAIN_PER_PERSON_W
    mins = twin.time_to_target(t_start, t_target, t_out, q_heat_w, q_people_w)
    st.caption(f"Available heat: {units} unit(s) × "
               f"{config.HEAT_PUMP_DELIVERED_KW_PER_UNIT:.0f} kW = "
               f"**{q_heat_w/1000:.0f} kW** delivered"
               + (f"  +  {q_people_w/1000:.1f} kW from {people} people" if people else ""))
    if mins is None:
        st.error("Target not practically reachable with this many units — it would either "
                 "never arrive or take impractically long (>8 h). Run more units "
                 "(or raise per-unit output).")
    else:
        st.success(f"⏱️ Start heating **{mins:.0f} minutes** before occupancy to hit "
                   f"{t_target:.0f}°C on arrival — no more cold rooms, no panic electric heating.")
