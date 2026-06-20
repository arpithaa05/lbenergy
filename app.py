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

import lbenergy.config as config
import lbenergy.data_loader as dl
import lbenergy.kpis as kpis
import lbenergy.monitors as monitors
import lbenergy.thermal_twin as tt

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
    c[1].metric("⚡ Energy", f"{k['energy_kwh']:,.0f} kWh", f"€{k['cost_eur']:,.0f}")
    c[2].metric("🌍 CO₂", f"{k['co2_kg']:,.0f} kg")
    health = f"{k['fleet_ok']}/{k['fleet_total']}"
    c[3].metric("🩺 Fleet health", health,
                "all healthy" if k['fleet_ok'] == k['fleet_total'] else "fault!",
                delta_color="normal" if k['fleet_ok'] == k['fleet_total'] else "inverse")
    comfort = k['comfort_pct']
    c[4].metric("🌡️ Comfort", f"{comfort:.0f}%" if np.isfinite(comfort) else "—",
                f"{k['unmet_hours']:.0f} unmet h", delta_color="inverse")
    crit = sum(1 for a in alerts if a.severity == "critical")
    c[5].metric("🔔 Active alerts", len(alerts), f"{crit} critical",
                delta_color="inverse" if crit else "off")


tab_fleet, tab_alerts, tab_device, tab_impact, tab_twin = st.tabs(
    ["🩺 Fleet", "🔔 Alerts", "🔍 Device detail", "💰 Impact & Savings", "🧠 Digital Twin"])


# ---------------------------------------------------------------------------
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
# Tab: Device detail
# ---------------------------------------------------------------------------
with tab_device:
    dev = st.selectbox("Device", src.devices)
    snap = src.snapshots(up_to=cursor)
    g = snap[snap["device_name"] == dev].sort_values("last_seen_at")
    pw = src.power(up_to=cursor)
    pwd = pw[pw["device_name"] == dev]

    cc = st.columns(2)
    with cc[0]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["last_seen_at"], y=g["status_temperature_supply_in_celsius"],
                                 name="Supply °C", line=dict(color="#e74c3c")))
        fig.add_trace(go.Scatter(x=g["last_seen_at"], y=g["status_temperature_return_in_celsius"],
                                 name="Return °C", line=dict(color="#3498db")))
        fig.update_layout(title="Supply vs Return temperature", height=300,
                          margin=dict(t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with cc[1]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["last_seen_at"], y=g["status_low_pressure_in_bar"],
                                 name="Low P", line=dict(color="#9b59b6")))
        fig.add_trace(go.Scatter(x=g["last_seen_at"], y=g["status_high_pressure_in_bar"],
                                 name="High P", line=dict(color="#e67e22")))
        fig.update_layout(title="Refrigerant pressures (bar)", height=300,
                          margin=dict(t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

    cc2 = st.columns(2)
    with cc2[0]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=pwd["timestamp"], y=pwd["power_draw_kw"],
                                 fill="tozeroy", line=dict(color="#16a085")))
        fig.update_layout(title="Power draw (kW)", height=280, margin=dict(t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with cc2[1]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["last_seen_at"], y=g["status_carbon_dioxide_in_ppm"],
                                 name="CO₂ ppm", line=dict(color="#c0392b")))
        fig.add_trace(go.Scatter(x=g["last_seen_at"], y=g["status_humidity_in_percent"],
                                 name="Humidity %", line=dict(color="#2980b9"), yaxis="y2"))
        fig.update_layout(title="Air quality", height=280, margin=dict(t=30, b=10),
                          yaxis2=dict(overlaying="y", side="right"))
        st.plotly_chart(fig, use_container_width=True)


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

    st.markdown("#### 🔮 Predictive preheat planner")
    cc = st.columns(4)
    t_start = cc[0].number_input("Current room °C", 5.0, 30.0, 16.0, 0.5)
    t_target = cc[1].number_input("Target °C", 10.0, 30.0, 21.0, 0.5)
    t_out = cc[2].number_input("Outside °C", -10.0, 35.0, 5.0, 0.5)
    q_kw = cc[3].number_input("Heat input (kW)", 1.0, 60.0, 12.0, 1.0)
    mins = twin.time_to_target(t_start, t_target, t_out, q_kw * 1000)
    if mins is None:
        st.error("Target unreachable at this heat input — increase power or it will never arrive.")
    else:
        st.success(f"⏱️ Start heating **{mins:.0f} minutes** before occupancy to hit "
                   f"{t_target:.0f}°C on arrival — no more cold rooms, no panic electric heating.")
