"""
IHL Heat Pump Monitoring System — Streamlit dashboard.

A live-replay monitoring layer for LB Energy's Intelligent Heat Link.
Run:  streamlit run app.py
"""

from __future__ import annotations

import html as _html

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

st.set_page_config(page_title="IHL Monitor — LB Energy", page_icon="◼", layout="wide")

SEV_COLOR = {"critical": "#ef4444", "warning": "#f59e0b", "info": "#3b82f6", "ok": "#22c55e"}
STATUS_DOT = {"ok": "#22c55e", "warning": "#f59e0b", "critical": "#ef4444"}
ANOM_COLOR = {
    "Door/window open": "#f59e0b", "Heater defect": "#ef4444",
    "Tampering (sensor)": "#a855f7", "Tampering (control)": "#8b5cf6",
    "Unexplained cooling": "#fb923c",
}


# ---------------------------------------------------------------------------
# Professional theme (CSS) + small helpers
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{ --accent:#3b82f6; }
html, body, [class*="css"], .stApp{ font-family:'Inter',system-ui,sans-serif; }

/* page content fade-in */
.block-container{ animation:fadein .45s ease both; padding-top:2rem; }
@keyframes fadein{ from{opacity:0;transform:translateY(8px);} to{opacity:1;transform:none;} }

/* metric cards — theme-agnostic (translucent, never overrides text colour) */
div[data-testid="stHorizontalBlock"]{ align-items:stretch; }
div[data-testid="stHorizontalBlock"] [data-testid="stMetric"]{ height:100%; }
[data-testid="stMetric"],[data-testid="metric-container"]{
  background:rgba(128,128,128,.08);
  border:1px solid rgba(128,128,128,.20); border-radius:14px;
  padding:14px 16px; min-height:158px;
  display:flex; flex-direction:column; justify-content:center;
  box-shadow:0 1px 2px rgba(0,0,0,.10);
  transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease; }
[data-testid="stMetric"]:hover,[data-testid="metric-container"]:hover{
  transform:translateY(-3px); box-shadow:0 10px 26px rgba(0,0,0,.20);
  border-color:rgba(59,130,246,.5); }
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p{
  font-size:.74rem !important; font-weight:600 !important; letter-spacing:.06em;
  text-transform:uppercase; opacity:.62; }
[data-testid="stMetricValue"]{
  font-size:1.5rem !important; font-weight:700 !important;
  white-space:nowrap; overflow:visible !important; text-overflow:clip !important; }

/* tabs: equal width, spaced, pill-style */
div[data-baseweb="tab-list"]{ gap:8px; }
button[data-baseweb="tab"]{
  flex:1 1 0; justify-content:center; height:48px; border-radius:10px 10px 0 0;
  font-weight:600; font-size:.95rem; letter-spacing:.02em; opacity:.65;
  transition:background .15s ease, opacity .15s ease; }
button[data-baseweb="tab"]:hover{ background:rgba(128,128,128,.10); opacity:1; }
button[data-baseweb="tab"][aria-selected="true"]{ opacity:1; background:rgba(59,130,246,.13); }
div[data-baseweb="tab-highlight"]{ background:var(--accent); height:3px; }

/* bordered containers */
[data-testid="stVerticalBlockBorderWrapper"]{
  border-radius:12px; transition:border-color .15s ease; }
[data-testid="stVerticalBlockBorderWrapper"]:hover{ border-color:rgba(128,128,128,.30); }

/* section header with INSTANT css tooltip */
.sec-head{ display:flex; align-items:center; gap:9px; margin:1.1rem 0 .35rem; }
.sec-title{ font-size:1.16rem; font-weight:700; letter-spacing:.01em; }
.hint{ position:relative; display:inline-flex; align-items:center; justify-content:center;
  width:17px; height:17px; border-radius:50%; font-size:11px; font-weight:700;
  background:rgba(128,128,128,.22); opacity:.85; cursor:help; user-select:none;
  transition:background .12s ease, opacity .12s ease; }
.hint:hover{ background:var(--accent); color:#fff; opacity:1; }
.hint::after{ content:attr(data-tip); position:absolute; left:50%; top:155%;
  transform:translateX(-50%); background:#111827; color:#f9fafb; padding:8px 11px;
  border-radius:8px; font-size:12px; font-weight:500; line-height:1.4;
  width:max-content; max-width:300px; box-shadow:0 8px 24px rgba(0,0,0,.40);
  opacity:0; pointer-events:none; transition:opacity .1s ease; z-index:1000;
  text-transform:none; letter-spacing:normal; }
.hint:hover::after{ opacity:1; }

/* fleet device header dot */
.dev-head{ font-size:1.05rem; font-weight:700; margin:.2rem 0 .4rem; display:flex; align-items:center; }
.dot{ width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:8px;
  box-shadow:0 0 9px currentColor; }

/* buttons */
.stButton>button{ border-radius:8px; transition:transform .15s ease, box-shadow .15s ease; }
.stButton>button:hover{ transform:translateY(-1px); }

/* sidebar title */
section[data-testid="stSidebar"] h1{ font-size:1.35rem; font-weight:800; }
</style>
""", unsafe_allow_html=True)


def section(title: str, hint: str | None = None):
    """Section header with an optional hover '?' showing an instant one-line explanation."""
    h = (f"<span class='hint' data-tip=\"{_html.escape(hint)}\">?</span>") if hint else ""
    st.markdown(f"<div class='sec-head'><span class='sec-title'>{title}</span>{h}</div>",
                unsafe_allow_html=True)


def style_fig(fig, height: int = 320):
    """Apply a consistent, theme-agnostic Plotly look (transparent bg, neutral grid)."""
    fig.update_layout(
        height=height, margin=dict(t=30, b=12, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#64748b", size=12),
        legend=dict(bgcolor="rgba(0,0,0,0)"))
    fig.update_xaxes(gridcolor="rgba(128,128,128,.18)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,.18)", zeroline=False)
    return fig


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
st.sidebar.title("IHL Monitor")
st.sidebar.caption("Live monitoring for the Intelligent Heat Link")

window = st.sidebar.radio("Season window", ["heating", "cooling"], format_func=str.capitalize,
                          help="Which historical week to replay — heating or cooling season.")
src, frame, twin, twin_metrics = load(window)
t_min, t_max = src.time_bounds

st.sidebar.markdown("### Live replay cursor")
hours_total = int((t_max - t_min).total_seconds() // 3600)
cursor_h = st.sidebar.slider("Hours into the window", 1, hours_total, min(80, hours_total),
                             help="Sets the 'current time'. Every number, chart and alert is "
                                  "computed only from data up to this point — drag to replay "
                                  "the week as if it were streaming live.")
cursor = t_min + pd.Timedelta(hours=cursor_h)
st.sidebar.write(f"**Now:** {cursor:%Y-%m-%d %H:%M}")

with st.sidebar.expander("Economic assumptions", expanded=False):
    config.ELECTRICITY_TARIFF_EUR_PER_KWH = st.number_input(
        "Electricity tariff (€/kWh)", 0.05, 1.0, config.ELECTRICITY_TARIFF_EUR_PER_KWH, 0.01,
        help="Price of electricity — drives every € figure on the dashboard.")
    config.CO2_FACTOR_KG_PER_KWH = st.number_input(
        "Grid CO₂ factor (kg/kWh)", 0.0, 1.0, config.CO2_FACTOR_KG_PER_KWH, 0.01,
        help="Carbon intensity of the grid — drives every CO₂ figure.")

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
    c[0].metric("Avoidable / yr", f"€{k['avoidable_eur_annual']:,.0f}",
                help="Annualised cost of detected waste that smart control could avoid.")
    c[1].metric("Energy", f"{k['energy_kwh']:,.0f} kWh", f"€{k['cost_eur']:,.0f}",
                help="Total electricity used so far and its cost at the current tariff.")
    c[2].metric("CO₂", f"{k['co2_kg']:,.0f} kg",
                help="Carbon emissions from that energy, at the grid CO₂ factor.")
    health = f"{k['fleet_ok']}/{k['fleet_total']}"
    c[3].metric("Fleet health", health,
                "all healthy" if k['fleet_ok'] == k['fleet_total'] else "fault!",
                delta_color="normal" if k['fleet_ok'] == k['fleet_total'] else "inverse",
                help="Heat-pump units with no active alarm, out of the total fleet.")
    comfort = k['comfort_pct']
    c[4].metric("Comfort", f"{comfort:.0f}%" if np.isfinite(comfort) else "—",
                f"{k['unmet_hours']:.0f} unmet h", delta_color="inverse",
                help="Share of occupied time the room was within the comfort band of target.")
    crit = sum(1 for a in alerts if a.severity == "critical")
    c[5].metric("Active alerts", len(alerts), f"{crit} critical",
                delta_color="inverse" if crit else "off",
                help="Number of live alerts right now, and how many are critical.")


tab_fleet, tab_alerts, tab_detect, tab_impact, tab_twin = st.tabs(
    ["Fleet", "Alerts", "Detect", "Impact & Savings", "Digital Twin"])


# ---------------------------------------------------------------------------
# Tab: Fleet
# ---------------------------------------------------------------------------
with tab_fleet:
    section("Fleet Status", "Latest status of each heat-pump unit: power draw, efficiency "
                            "(COP) and any active alarms.")
    cols = st.columns(len(dev_table)) if not dev_table.empty else []
    for col, (_, d) in zip(cols, dev_table.iterrows()):
        with col:
            st.markdown(
                f"<div class='dev-head'><span class='dot' style='color:{STATUS_DOT.get(d['status'],'#888')};"
                f"background:{STATUS_DOT.get(d['status'],'#888')}'></span>{d['device']}</div>",
                unsafe_allow_html=True)
            st.metric("Power", f"{d['power_kw']:.1f} kW",
                      help="Mean electrical draw of this unit over the window.")
            st.metric("COP", f"{d['cop']:.2f}" if d['cop'] is not None else "—",
                      help="Coefficient of performance = heat delivered ÷ electricity used. "
                           "~3 is healthy; near 1 means it is running on electric backup.")
            if d["alarms"]:
                st.error(d["alarms"])
            elif d["status"] == "warning":
                st.warning("Below-par efficiency")
            else:
                st.success("Healthy")

    section("Total power draw (live)", "Combined electricity draw of all units over time. "
                                       "Shaded bands mark occupied periods from the calendar.")
    power = src.power(up_to=cursor)
    total = power.groupby("timestamp")["power_draw_kw"].sum().reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=total["timestamp"], y=total["power_draw_kw"],
                             fill="tozeroy", line=dict(color="#3b82f6"), name="Total kW"))
    for _, ev in src.events(up_to=cursor).iterrows():
        fig.add_vrect(x0=ev["starts_at"], x1=min(ev["ends_at"], cursor),
                      fillcolor="#22c55e", opacity=0.08, line_width=0)
    fig.update_layout(yaxis_title="kW", showlegend=False)
    st.plotly_chart(style_fig(fig, 300), use_container_width=True)
    st.caption("Shaded bands = occupied (calendar events).")


# ---------------------------------------------------------------------------
# Tab: Alerts
# ---------------------------------------------------------------------------
with tab_alerts:
    section("Live Alert Feed", "Every detected issue, sorted by severity then € impact, with a "
                               "recommended action and the compliance regime it supports.")
    if not alerts:
        st.success("No active alerts at this time.")
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
                st.markdown(f"→ _{a.action}_")
            if tags:
                st.markdown(f"Compliance: {tags}")


# ---------------------------------------------------------------------------
# Tab: Detect — anomaly classification (normal vs abnormal)
# ---------------------------------------------------------------------------
with tab_detect:
    section("Anomaly Detection",
            "The twin predicts how the room should behave; the residual (measured − predicted) "
            "stays small for normal/gradual changes and spikes for anything physics can't "
            "explain. The shape of the spike classifies it.")

    sub = frame[frame.index <= cursor]

    st.markdown("**Demo:** inject a scenario and watch the system classify it.")
    inj = st.radio("Scenario", ["None (real data)", "Door / window opened",
                                "Heater defect", "Tampering — sensor spoof",
                                "Tampering — rogue heating"],
                   horizontal=True,
                   help="Overlay a synthetic event (the real week is clean) to show the "
                        "classifier telling the four cases apart.")
    kind_map = {"Door / window opened": "door", "Heater defect": "defect",
                "Tampering — sensor spoof": "tamper_sensor",
                "Tampering — rogue heating": "tamper_control"}
    view = sub if inj == "None (real data)" else detect.inject_scenario(twin, sub, kind_map[inj], 0.6)

    res = twin.residuals(view)
    anomalies = detect.classify_anomalies(twin, view)

    section("Residual timeline", "Inside the green band the room behaves as physics predicts "
                                 "(normal). Dots outside the band are classified anomalies — "
                                 "hover a dot for the explanation.")
    band = detect.anomaly_band(twin, sub)
    fig = go.Figure()
    fig.add_hrect(y0=-band, y1=band, fillcolor="#22c55e", opacity=0.12, line_width=0)
    fig.add_trace(go.Scatter(x=view.index, y=res, name="Residual °C",
                             line=dict(color="#94a3b8", width=1.5)))
    for a in anomalies:
        fig.add_trace(go.Scatter(
            x=[a.timestamp], y=[a.residual], mode="markers",
            marker=dict(size=13, color=ANOM_COLOR.get(a.kind, "#ef4444"),
                        line=dict(width=1, color="white")),
            name=a.kind, showlegend=False,
            hovertext=a.explanation, hoverinfo="text"))
    fig.update_layout(yaxis_title="Residual °C (measured − predicted)", showlegend=False)
    st.plotly_chart(style_fig(fig, 320), use_container_width=True)

    if not anomalies:
        st.success("No anomalies — the room is behaving exactly as the physics predicts. "
                   "Gradual daily changes are explained by the model, so they don't raise "
                   "false alarms.")
    else:
        section("Classified events", "What the system concluded for each anomaly, plus the "
                                     "recommended action and who gets notified.")
        for a in anomalies:
            col = ANOM_COLOR.get(a.kind, "#ef4444")
            with st.container(border=True):
                st.markdown(
                    f"<span style='color:{col};font-weight:700'>{a.kind}</span> · "
                    f"<span style='color:{SEV_COLOR.get(a.severity)};'>"
                    f"{a.severity.upper()}</span> · {a.timestamp:%a %d %b %H:%M}",
                    unsafe_allow_html=True)
                st.caption(a.explanation)
                st.markdown(f"→ _{a.action}_  ·  alerts **{a.recipient}**")

    section("Early warning (predictive)",
            "Projects the room temperature forward at the current heat output; warns if a "
            "comfort breach is coming before anyone feels it.")
    ew = detect.early_warning(twin, sub, float(config.EVENT_TEMP_C))
    if ew is None:
        st.info("On track — the room is projected to stay at/above the setpoint at the "
                "current heat output.")
    else:
        st.warning(f"{ew['message']} (now {ew['t_now']:.1f}°C → "
                   f"{ew['projected']:.1f}°C). Act before anyone feels it.")

    section("Auto-dispatched notifications",
            "Detected issues are routed automatically — critical to the technician (SMS), "
            "warnings to the superintendent (email).")
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
    if k:
        days = k["period_days"]
        current_annual = k["cost_eur"] / days * 365
        current_co2_annual = k["co2_kg"] / days * 365
        avoid_eur = k["avoidable_eur_annual"]
        avoid_co2 = k["avoidable_co2_kg"] / days * 365
        optimized_annual = max(current_annual - avoid_eur, 0.0)
        pct = avoid_eur / current_annual * 100 if current_annual else 0

        # --- #1 Baseline vs smart control (the headline before/after) ---
        section("Baseline vs Intelligent Control",
                "Annual running cost as-is versus after acting on the waste the system "
                "detects (faulty-unit backup + conditioning empty rooms). The gap is what "
                "IHL unlocks.")
        cc = st.columns([2, 1])
        with cc[0]:
            fig = go.Figure(go.Bar(
                x=["Without IHL action", "With IHL control"],
                y=[current_annual, optimized_annual],
                marker_color=["#64748b", "#22c55e"],
                text=[f"€{current_annual:,.0f}", f"€{optimized_annual:,.0f}"],
                textposition="outside"))
            fig.update_layout(title="Annual running cost (€/year)", yaxis_title="€/year",
                              showlegend=False)
            st.plotly_chart(style_fig(fig, 340), use_container_width=True)
        with cc[1]:
            st.metric("Saved / year", f"€{avoid_eur:,.0f}", f"-{pct:.0f}% vs today",
                      help="Annual € saved by acting on detected waste.")
            st.metric("CO₂ cut / year", f"{avoid_co2:,.0f} kg",
                      help="Annual carbon avoided alongside those savings.")
            st.success(f"**{pct:.0f}%** lower running cost on this week — fixing the faulty "
                       f"unit plus occupancy-aware setback. LB Energy's steady-state "
                       f"efficiency promise is 20–30%; this window also includes a unit fault.")

        # --- where the money goes (by cause) ---
        section("Where the money goes",
                "The avoidable cost split by its two causes, annualised.")
        waste = kpis.waste_breakdown(src.snapshots(up_to=cursor), src.power(up_to=cursor),
                                     src.events(up_to=cursor))
        fault_eur = waste["fault_kwh"] * config.ELECTRICITY_TARIFF_EUR_PER_KWH
        unocc_eur = waste["unoccupied_kwh"] * 0.5 * config.ELECTRICITY_TARIFF_EUR_PER_KWH
        cc = st.columns([2, 1])
        with cc[0]:
            fig = go.Figure(go.Bar(
                x=["Faulty unit (electric backup)", "Empty-room conditioning"],
                y=[fault_eur / days * 365, unocc_eur / days * 365],
                marker_color=["#ef4444", "#f59e0b"]))
            fig.update_layout(title="Annualised avoidable cost by cause (€)", yaxis_title="€/year",
                              showlegend=False)
            st.plotly_chart(style_fig(fig, 320), use_container_width=True)
        with cc[1]:
            st.metric("Avoidable energy / yr", f"{k['avoidable_kwh'] / days * 365:,.0f} kWh",
                      help="Electricity that smart control could save each year.")
            st.metric("Avoidable CO₂ / yr", f"{avoid_co2:,.0f} kg")
        st.caption("Assumptions: faulty-unit excess vs healthy-fleet median; half of "
                   "unoccupied-room energy avoidable via occupancy-aware setback.")

        # --- #2 setpoint what-if ---
        section("What if we lower the setpoint?",
                "A lower indoor target shrinks the indoor-outdoor gap that drives heat loss, "
                "so heating energy falls roughly in proportion. Drag to see the yearly saving.")
        gap = max(float((frame["t_in"] - frame["t_out"]).mean()), 1.0)
        sc = st.columns([1, 2])
        with sc[0]:
            d_set = st.slider("Lower setpoint by (°C)", 0.0, 3.0, 1.0, 0.5,
                              help="How much to drop the occupied comfort target (e.g. 21→20°C).")
            frac = min(d_set / gap, 0.6)
            sp_eur = current_annual * frac
            sp_co2 = current_co2_annual * frac
            st.metric("Saved / year", f"€{sp_eur:,.0f}",
                      f"-{frac*100:.0f}%" if frac else None,
                      help="Estimated annual saving from the lower setpoint.")
            st.metric("CO₂ cut / year", f"{sp_co2:,.0f} kg")
            st.caption(f"New target ≈ {config.EVENT_TEMP_C - d_set:.1f}°C "
                       f"(from {config.EVENT_TEMP_C:.0f}°C).")
        with sc[1]:
            fig = go.Figure(go.Bar(
                x=[f"-{d:.1f}°C" for d in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]],
                y=[current_annual * min(d / gap, 0.6) for d in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]],
                marker_color="#3b82f6"))
            fig.update_layout(title="Annual saving by setpoint reduction (€)",
                              yaxis_title="€/year saved", showlegend=False)
            st.plotly_chart(style_fig(fig, 300), use_container_width=True)
        st.caption(f"Rule of thumb on this data: ~{100/gap:.0f}% saving per °C "
                   f"(indoor-outdoor gap ≈ {gap:.1f}°C). Heating season; comfort trade-off applies.")

    section("Compliance posture", "How the system supports the relevant EU regulations. "
                                  "Each card links to the official regulation text.")
    cc = st.columns(3)
    cc[0].info(
        "**F-Gas Regulation (EU 2024/573)**\n\nRefrigerant low-pressure events "
        "auto-detected & logged for leak-check compliance.\n\n"
        "Click here for the official text → "
        "[EUR-Lex: Reg. (EU) 2024/573](https://eur-lex.europa.eu/eli/reg/2024/573/oj)")
    cc[1].info(
        "**EPBD / EED**\n\nContinuous technical-system performance monitoring; "
        "quantified efficiency measures.\n\n"
        "Click here for the official texts → "
        "[EPBD (EU) 2024/1275](https://eur-lex.europa.eu/eli/dir/2024/1275/oj) · "
        "[EED (EU) 2023/1791](https://eur-lex.europa.eu/eli/dir/2023/1791/oj)")
    cc[2].info(
        "**GDPR (EU 2016/679)**\n\nOccupancy inferred from aggregate CO₂ only — no "
        "individual tracking; configurable retention.\n\n"
        "Click here for the official text → "
        "[EUR-Lex: GDPR](https://eur-lex.europa.eu/eli/reg/2016/679/oj)")


# ---------------------------------------------------------------------------
# Tab: Digital Twin
# ---------------------------------------------------------------------------
with tab_twin:
    section("Physics Digital Twin of the Room",
            "A lumped-capacitance model fit from data and validated one-step-ahead. It learns "
            "two constants: thermal mass C and heat-loss UA.")
    st.caption("Lumped-capacitance model  C·dT/dt = Q_heat − UA·(T_in−T_out) + Q_people, "
               "fit from data and validated one-step-ahead. Methodology after "
               "Arumugam et al. (2023), with a dynamic COP(T_out) in place of their "
               "dynamic internal resistance.")

    cc = st.columns(3)
    cc[0].metric("Thermal mass C", f"{twin.params.C_J_per_C/1e6:.1f} MJ/°C",
                 help="Energy to warm the room 1°C — its thermal inertia.")
    cc[1].metric("Heat loss UA", f"{twin.params.UA_W_per_C:.0f} W/°C",
                 help="Watts lost per °C of indoor-outdoor gap — envelope leakiness.")
    cc[2].metric("Time constant τ", f"{twin.params.tau_hours:.1f} h",
                 help="C/UA — how slowly the room responds to changes.")

    sub = frame[frame.index <= cursor]
    pred = twin.predict_one_step(sub)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sub.index, y=sub["t_in"], name="Measured °C",
                             line=dict(color="#64748b", width=2)))
    fig.add_trace(go.Scatter(x=sub.index, y=pred, name="Twin prediction",
                             line=dict(color="#ef4444", dash="dot")))
    fig.update_layout(yaxis_title="Room °C")
    st.plotly_chart(style_fig(fig, 340), use_container_width=True)
    st.caption(f"One-step-ahead fit: RMSE {twin_metrics['rmse']:.2f}°C, "
               f"Willmott's d {twin_metrics['willmott_d']:.2f} (n={twin_metrics['n']}).")

    # -- Auto schedule from the lecture calendar -----------------------------
    section("Auto preheat schedule (from the lecture calendar)",
            "For each upcoming lecture, the recommended switch-on time so the room is at the "
            "setpoint exactly when it starts. Switch-on = lecture start − preheat lead time.")
    sc = st.columns(3)
    sched_units = sc[0].number_input("Units to run", 1, 6, len(src.devices), 1,
                                     key="sched_units",
                                     help="Heat-pump units assumed running for the preheat. "
                                          "Answers 'would N units be enough?'")
    sched_target = sc[1].number_input("Comfort setpoint °C", 10.0, 30.0,
                                      float(config.EVENT_TEMP_C), 0.5, key="sched_target",
                                      help="Temperature the room should reach by lecture start.")
    sched_people = sc[2].number_input("Expected people", 0, 300, 0, 10, key="sched_people",
                                      help="Expected occupants — their body heat helps warm the room.")

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
                              else "need more units"),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        first = schedule[0]
        if first["reachable"]:
            st.success(f"Next lecture {first['starts_at']:%H:%M}: switch on at "
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
        section("Proof: the room reaches the setpoint exactly at lecture start",
                "Simulated room temperature from switch-on. The red curve crosses the green "
                "setpoint line precisely at the lecture-start marker.")
        ev = reachable[0]
        q_heat_w = sched_units * config.HEAT_PUMP_DELIVERED_KW_PER_UNIT * 1000
        q_people_w = sched_people * config.SENSIBLE_GAIN_PER_PERSON_W
        lead = ev["lead_min"]
        mins, temps = twin.trajectory(ev["t_now"], ev["t_out"], q_heat_w, q_people_w,
                                      minutes=lead + 45)
        times = [ev["switch_on_at"] + pd.Timedelta(minutes=float(m)) for m in mins]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=times, y=temps, name="Predicted room °C",
                                 line=dict(color="#ef4444", width=3)))
        fig.add_hline(y=sched_target, line=dict(color="#22c55e", dash="dash"),
                      annotation_text=f"Setpoint {sched_target:.0f}°C",
                      annotation_position="top left")
        fig.add_vline(x=ev["switch_on_at"], line=dict(color="#94a3b8", dash="dot"))
        fig.add_vline(x=ev["starts_at"], line=dict(color="#3b82f6", dash="dot"))
        fig.add_trace(go.Scatter(
            x=[ev["switch_on_at"], ev["starts_at"]],
            y=[ev["t_now"], sched_target], mode="markers+text",
            text=[f" switch on {ev['switch_on_at']:%H:%M}",
                  f" lecture {ev['starts_at']:%H:%M}"],
            textposition=["bottom right", "top left"],
            marker=dict(size=11, color=["#94a3b8", "#3b82f6"]), showlegend=False))
        fig.update_layout(yaxis_title="Room °C", showlegend=False)
        st.plotly_chart(style_fig(fig, 340), use_container_width=True)
        st.caption(f"Starting at {ev['t_now']:.1f}°C, {sched_units} unit(s) bring the "
                   f"room to the {sched_target:.0f}°C setpoint in {lead:.0f} min — "
                   f"arriving right as the {ev['starts_at']:%H:%M} lecture begins.")

    # -- Interactive physics simulator ---------------------------------------
    section("Thermal physics playground",
            "Sliders seeded with the fitted values. Drag any of them to see how the room "
            "responds — the same lumped-capacitance equation, live.")
    pc = st.columns(2)
    with pc[0]:
        sim_C = st.slider("Thermal mass C (MJ/°C)", 1.0, 60.0,
                          float(round(twin.params.C_J_per_C / 1e6, 1)), 0.5,
                          help="Bigger = slower to heat or cool (more inertia).")
        sim_UA = st.slider("Heat loss UA (W/°C)", 50, 2000,
                           int(twin.params.UA_W_per_C), 10,
                           help="Bigger = leakier envelope (loses heat faster).")
        sim_q_kw = st.slider("HVAC power Q (kW, − = cooling)", -60.0, 60.0,
                             float(sched_units * config.HEAT_PUMP_DELIVERED_KW_PER_UNIT), 1.0,
                             help="Heat delivered into the room; negative cools.")
    with pc[1]:
        sim_tout = st.slider("Outside temp (°C)", -15.0, 40.0, 5.0, 0.5,
                             help="Outdoor temperature the room exchanges heat with.")
        sim_people = st.slider("People in room", 0, 300, 0, 5,
                               help="Occupant body heat (~100 W each).")
        sim_tstart = st.slider("Starting room temp (°C)", 0.0, 35.0, 16.0, 0.5,
                               help="Where the room temperature begins.")
        sim_hours = st.slider("Simulate hours", 1, 24, 8, 1,
                              help="How long to run the simulation.")

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
                             line=dict(color="#ef4444", width=3)))
    fig.add_hline(y=t_ss, line=dict(color="#22c55e", dash="dash"),
                  annotation_text=f"Settles at {t_ss:.1f}°C", annotation_position="top left")
    fig.update_layout(xaxis_title="Hours", yaxis_title="Room °C", showlegend=False)
    st.plotly_chart(style_fig(fig, 320), use_container_width=True)
    mc = st.columns(3)
    mc[0].metric("Settles at (T_ss)", f"{t_ss:.1f} °C",
                 help="Steady-state temperature this power can hold: T_out + Q/UA.")
    mc[1].metric("Time constant τ", f"{sim_twin.params.tau_hours:.1f} h",
                 help="C/UA — how slowly this configuration responds.")
    mc[2].metric("After this run", f"{stemps[-1]:.1f} °C",
                 help="Room temperature at the end of the simulated window.")

    # -- Manual what-if calculator -------------------------------------------
    section("What-if preheat calculator",
            "Manual version of the planner: pick a starting state and power, get the minutes "
            "of preheat needed to reach the target.")
    cc = st.columns(5)
    t_start = cc[0].number_input("Current room °C", 5.0, 30.0, 16.0, 0.5,
                                 help="Room temperature right now.")
    t_target = cc[1].number_input("Target °C", 10.0, 30.0, 21.0, 0.5,
                                  help="Temperature to reach on arrival.")
    t_out = cc[2].number_input("Outside °C", -10.0, 35.0, 5.0, 0.5,
                               help="Use the forecast outside temperature for the lecture slot.")
    units = cc[3].number_input("Units running", 1, 6, len(src.devices), 1,
                               help="How many heat-pump units are heating.")
    people = cc[4].number_input("People in hall", 0, 300, 0, 10,
                                help="Body heat adds to the room (≈100 W/person).")
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
        st.success(f"Start heating **{mins:.0f} minutes** before occupancy to hit "
                   f"{t_target:.0f}°C on arrival — no more cold rooms, no panic electric heating.")
