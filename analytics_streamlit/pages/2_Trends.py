# analytics_streamlit/pages/2_Trends.py
import pandas as pd
import numpy as np
import requests
import streamlit as st
import altair as alt

st.set_page_config(page_title="Trends & Insights", layout="wide")
st.title("📈 Trends & Insights")

# Optional: one-click to open your Apps Script form
form_url = st.secrets.get("form_url")
if form_url:
    st.link_button("📝 Open ABC Incident Form", form_url, type="primary", use_container_width=True)

# ---------- Data loader ----------
@st.cache_data(ttl=60)
def load_incidents():
    base = st.secrets["api"]["url"]
    token = st.secrets["api"]["token"]
    r = requests.get(base, params={"mode": "json", "token": token}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"API {r.status_code}. Snippet: {r.text[:300]}")
    payload = r.json()
    if "error" in payload:
        raise RuntimeError(f"API error: {payload}")
    df = pd.DataFrame(payload.get("data", []))

    # Types & helpers
    if "timestamp_utc" in df:
        ts = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
        try:
            df["timestamp_ct"] = ts.dt.tz_convert("America/Chicago")
        except Exception:
            df["timestamp_ct"] = ts
        df["date"] = df["timestamp_ct"].dt.date
        df["hour"] = df["timestamp_ct"].dt.hour
        df["dow_idx"] = df["timestamp_ct"].dt.weekday  # 0=Mon
    else:
        if "date" in df:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        if "time" in df:
            # parse "HH:MM" to hour
            hh = pd.to_datetime(df["time"], errors="coerce", format="%H:%M")
            df["hour"] = hh.dt.hour
        # dow from date
        if "date" in df:
            dt = pd.to_datetime(df["date"], errors="coerce")
            df["dow_idx"] = dt.dt.weekday

    for c in ["duration_sec", "intensity"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Labels
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    df["dow"] = df.get("dow_idx", pd.Series([np.nan]*len(df))).map({i: d for i, d in enumerate(dow_labels)})

    return df

# Load with friendly error
try:
    df = load_incidents()
except Exception as e:
    st.error(f"Failed to load incidents.\n\n{e}")
    st.stop()

if df.empty:
    st.info("No incidents yet. Submit one via the form above.")
    st.stop()

# ---------- Filters ----------
with st.container(border=True):
    st.markdown("**Filters**")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1.3])

    student = c1.selectbox("Student", ["All"] + sorted(df["student_id"].dropna().unique().tolist())) if "student_id" in df else "All"
    behavior = c2.selectbox("Behavior", ["All"] + sorted(df["behavior"].dropna().unique().tolist())) if "behavior" in df else "All"
    antecedent = c3.selectbox("Antecedent", ["All"] + sorted(df["antecedent"].dropna().unique().tolist())) if "antecedent" in df else "All"
    date_range = c4.date_input("Date range", value=())

    c5, c6, c7 = st.columns([1, 1, 2])
    location = c5.selectbox("Location", ["All"] + sorted(df["location"].dropna().unique().tolist())) if "location" in df else "All"
    intensity_min = c6.slider("Min intensity", 1, 5, 1) if "intensity" in df else 1
    if c7.button("Refresh data"):
        load_incidents.clear()
        st.rerun()

mask = pd.Series(True, index=df.index)
if "student_id" in df and student != "All":
    mask &= df["student_id"].eq(student)
if "behavior" in df and behavior != "All":
    mask &= df["behavior"].eq(behavior)
if "antecedent" in df and antecedent != "All":
    mask &= df["antecedent"].eq(antecedent)
if "location" in df and location != "All":
    mask &= df["location"].eq(location)
if "date" in df and len(date_range) == 2:
    start, end = date_range
    mask &= (pd.to_datetime(df["date"]) >= pd.to_datetime(start)) & (pd.to_datetime(df["date"]) <= pd.to_datetime(end))
if "intensity" in df and intensity_min:
    mask &= df["intensity"].fillna(0) >= intensity_min

fdf = df.loc[mask].copy()

# ---------- KPIs ----------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Incidents", f"{len(fdf):,}")
if "student_id" in fdf:
    k2.metric("Students", f"{fdf['student_id'].nunique():,}")
else:
    k2.metric("Students", "—")
if "duration_sec" in fdf and len(fdf):
    k3.metric("Avg duration (s)", f"{fdf['duration_sec'].mean():.0f}")
else:
    k3.metric("Avg duration (s)", "—")
if "intensity" in fdf and len(fdf):
    k4.metric("Median intensity", f"{fdf['intensity'].median():.0f}")
else:
    k4.metric("Median intensity", "—")

st.divider()

# ---------- Helpers for charts ----------
def line_trend(df_in: pd.DataFrame, freq_label: str):
    """Incidents over time with a rolling average."""
    # pick a date-like index
    date_col = None
    if "timestamp_ct" in df_in:
        date_col = "timestamp_ct"
    elif "date" in df_in:
        date_col = "date"
    if date_col is None or df_in[date_col].isna().all():
        return None

    s = df_in.copy()
    s[date_col] = pd.to_datetime(s[date_col])
    s = s.set_index(date_col)

    freq_map = {"Daily": "D", "Weekly": "W", "Monthly": "MS"}
    rule = freq_map.get(freq_label, "D")
    counts = s.resample(rule).size().rename("Incidents").to_frame()
    # rolling window by frequency
    window = 7 if rule == "D" else (4 if rule == "W" else 3)
    counts["Rolling"] = counts["Incidents"].rolling(window=window, min_periods=1).mean()

    source = counts.reset_index().rename(columns={counts.index.name: "period"})
    base = alt.Chart(source).encode(
        x=alt.X("period:T", title="Date")
    )
    lines = base.mark_line().encode(
        y=alt.Y("Incidents:Q", title="Incidents"),
        tooltip=["period:T", "Incidents:Q"]
    )
    roll = base.mark_line(strokeDash=[4,2]).encode(
        y=alt.Y("Rolling:Q", title="Rolling avg"),
        tooltip=["period:T", "Rolling:Q"]
    )
    return (lines + roll).properties(height=280).interactive()

def bar_count(df_in: pd.DataFrame, col: str, title: str):
    data = df_in[col].dropna().value_counts().reset_index()
    if data.empty:
        return None
    data.columns = [col, "count"]
    return alt.Chart(data).mark_bar().encode(
        x=alt.X("count:Q", title="Incidents"),
        y=alt.Y(f"{col}:N", sort='-x', title=title),
        tooltip=[col, "count"]
    ).properties(height=280)

def heatmap_hour_dow(df_in: pd.DataFrame):
    if "hour" not in df_in or "dow" not in df_in:
        return None
    pivot = df_in[["hour","dow"]].dropna()
    if pivot.empty:
        return None
    agg = pivot.groupby(["dow","hour"]).size().reset_index(name="count")
    # order days Mon..Sun
    day_order = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    return alt.Chart(agg).mark_rect().encode(
        x=alt.X("hour:O", title="Hour of day (local)"),
        y=alt.Y("dow:O", title="Day of week", sort=day_order),
        color=alt.Color("count:Q", title="Incidents"),
        tooltip=["dow","hour","count"]
    ).properties(height=260)

def stacked_antecedent_behavior(df_in: pd.DataFrame):
    need = {"antecedent","behavior"}
    if not need.issubset(df_in.columns):
        return None
    ab = df_in.groupby(["antecedent","behavior"]).size().reset_index(name="count")
    if ab.empty:
        return None
    return alt.Chart(ab).mark_bar().encode(
        x=alt.X("antecedent:N", title="Antecedent"),
        y=alt.Y("count:Q", title="Incidents"),
        color=alt.Color("behavior:N", title="Behavior"),
        tooltip=["antecedent","behavior","count"]
    ).properties(height=280)

def box_duration_by_behavior(df_in: pd.DataFrame):
    if "duration_sec" not in df_in or "behavior" not in df_in:
        return None
    sub = df_in.dropna(subset=["duration_sec","behavior"])
    if sub.empty:
        return None
    return alt.Chart(sub).mark_boxplot().encode(
        y=alt.Y("behavior:N", title="Behavior", sort="-x"),
        x=alt.X("duration_sec:Q", title="Duration (sec)"),
        tooltip=["behavior","duration_sec"]
    ).properties(height=300)

# ---------- Controls for trend frequency ----------
freq = st.radio("Trend frequency", ["Daily", "Weekly", "Monthly"], horizontal=True)
st.caption("Rolling average shown as dashed line.")

# ---------- Layout ----------
row1 = st.columns((2,1))
with row1[0]:
    chart = line_trend(fdf, freq)
    if chart is not None:
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("Not enough date/time data to plot trend.")
with row1[1]:
    c = bar_count(fdf, "dow", "Day of week") if "dow" in fdf else None
    if c is not None:
        st.altair_chart(c, use_container_width=True)
    else:
        st.info("Day-of-week data unavailable.")

row2 = st.columns(2)
with row2[0]:
    c = heatmap_hour_dow(fdf)
    st.subheader("Time-of-day × Day-of-week")
    if c is not None:
        st.altair_chart(c, use_container_width=True)
    else:
        st.info("Need timestamp or time to show heatmap.")
with row2[1]:
    st.subheader("Locations")
    if "location" in fdf:
        c = bar_count(fdf, "location", "Location")
        if c is not None:
            st.altair_chart(c, use_container_width=True)
        else:
            st.info("No location data.")
    else:
        st.info("No location column.")

row3 = st.columns(2)
with row3[0]:
    st.subheader("Behaviors")
    if "behavior" in fdf:
        c = bar_count(fdf, "behavior", "Behavior")
        if c is not None:
            st.altair_chart(c, use_container_width=True)
        else:
            st.info("No behavior data.")
    else:
        st.info("No behavior column.")
with row3[1]:
    st.subheader("Antecedent × Behavior")
    c = stacked_antecedent_behavior(fdf)
    if c is not None:
        st.altair_chart(c, use_container_width=True)
    else:
        st.info("Need antecedent and behavior columns.")

row4 = st.columns(2)
with row4[0]:
    st.subheader("Duration by Behavior")
    c = box_duration_by_behavior(fdf)
    if c is not None:
        st.altair_chart(c, use_container_width=True)
    else:
        st.info("Need duration_sec and behavior to show boxplots.")
with row4[1]:
    st.subheader("Intensity & Top Students")
    if "intensity" in fdf:
        # Intensity histogram
        hist = alt.Chart(fdf.dropna(subset=["intensity"])).mark_bar().encode(
            x=alt.X("intensity:Q", bin=alt.Bin(step=1), title="Intensity (1–5)"),
            y=alt.Y("count():Q", title="Incidents"),
            tooltip=["count()"]
        ).properties(height=140)
        st.altair_chart(hist, use_container_width=True)
    else:
        st.info("No intensity column.")

    st.markdown("**Top 10 Students by Incidents**")
    if "student_id" in fdf:
        top = fdf["student_id"].value_counts().reset_index()
        if not top.empty:
            top.columns = ["student_id", "count"]
            chart_top = alt.Chart(top.head(10)).mark_bar().encode(
                x=alt.X("count:Q", title="Incidents"),
                y=alt.Y("student_id:N", sort='-x', title="Student ID"),
                tooltip=["student_id","count"]
            ).properties(height=200)
            st.altair_chart(chart_top, use_container_width=True)
        else:
            st.info("No student data.")
    else:
        st.info("No student_id column.")


# === PDF Monthly Summary (per student) ===
import io
from datetime import date
from calendar import monthrange
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

def _counts_table(title: str, s):
    """Return a (title, Table) pair for a value_counts Series."""
    s = s.dropna().astype(str).value_counts()
    if s.empty:
        return Paragraph(f"<b>{title}</b>: No data", getSampleStyleSheet()["Normal"]), Spacer(1, 6)
    data = [["Value", "Count"]] + [[k, int(v)] for k, v in s.items()]
    tbl = Table(data, hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.black),
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN", (1,1), (1,-1), "RIGHT"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
    ]))
    return Paragraph(f"<b>{title}</b>", getSampleStyleSheet()["Normal"]), tbl

def build_monthly_pdf(student_id: str, year: int, month: int, df_all: pd.DataFrame) -> bytes:
    # Build month window
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    # Filter for student + month
    dfm = df_all.copy()
    if "student_id" in dfm:
        dfm = dfm[dfm["student_id"] == student_id]
    if "date" in dfm:
        dfm = dfm[(pd.to_datetime(dfm["date"]) >= pd.to_datetime(start)) &
                  (pd.to_datetime(dfm["date"]) <= pd.to_datetime(end))]

    # Prepare metrics
    n = len(dfm)
    avg_dur = f"{dfm['duration_sec'].mean():.0f}s" if "duration_sec" in dfm and n else "—"
    med_int = f"{dfm['intensity'].median():.0f}" if "intensity" in dfm and n else "—"
    days = dfm["date"].nunique() if "date" in dfm and n else 0

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    H1, H2, P = styles["Title"], styles["Heading2"], styles["BodyText"]

    story = []
    story.append(Paragraph(f"ABC Incident Summary — {student_id}", H1))
    story.append(Paragraph(f"{start.strftime('%B %Y')}", H2))
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>Total incidents:</b> {n}", P))
    story.append(Paragraph(f"<b>Avg duration:</b> {avg_dur}", P))
    story.append(Paragraph(f"<b>Median intensity:</b> {med_int}", P))
    story.append(Paragraph(f"<b>Days with incidents:</b> {days}", P))
    story.append(Spacer(1, 10))

    # Tables
    if "behavior" in dfm:
        story.extend(_counts_table("Behaviors", dfm["behavior"]))
        story.append(Spacer(1, 8))
    if "antecedent" in dfm:
        story.extend(_counts_table("Antecedents", dfm["antecedent"]))
        story.append(Spacer(1, 8))
    if "location" in dfm:
        story.extend(_counts_table("Locations", dfm["location"]))
        story.append(Spacer(1, 8))
    if "consequence" in dfm:
        story.extend(_counts_table("Consequences", dfm["consequence"]))
        story.append(Spacer(1, 8))

    # Recent incidents (top 10)
    if n:
        cols = [c for c in ["date","time","behavior","location","intensity","duration_sec","notes","staff"] if c in dfm.columns]
        recent = dfm.sort_values(dfm.columns[0], ascending=False)[cols].head(10) if cols else pd.DataFrame()
        if not recent.empty:
            story.append(Spacer(1, 4))
            story.append(Paragraph("<b>Recent incidents (up to 10)</b>", P))
            data = [ [c.replace("_"," ").title() for c in recent.columns] ] + recent.fillna("").astype(str).values.tolist()
            tbl = Table(data, hAlign="LEFT", colWidths=[None]*len(recent.columns))
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f0f0f0")),
                ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
                ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ]))
            story.append(tbl)

    doc.build(story)
    return buf.getvalue()

# === UI: Export monthly PDF ===
st.divider()
with st.container(border=True):
    st.subheader("📄 Export Monthly PDF Summary (per student)")
    # Student picker
    students = sorted(df["student_id"].dropna().unique().tolist()) if "student_id" in df else []
    c1, c2, c3 = st.columns([2, 1, 1])
    student_pick = c1.selectbox("Student", options=students if students else ["(none)"])
    year_pick = c2.number_input("Year", value=pd.Timestamp.today().year, min_value=2000, max_value=2100, step=1)
    month_pick = c3.selectbox("Month", options=list(range(1,13)), format_func=lambda m: pd.Timestamp(2000,m,1).strftime("%B"))

    if st.button("Generate PDF"):
        if not students:
            st.warning("No students available.")
        else:
            pdf_bytes = build_monthly_pdf(student_pick, int(year_pick), int(month_pick), df)
            fname = f"ABC_{student_pick}_{int(year_pick)}-{int(month_pick):02d}.pdf"
            st.download_button("⬇️ Download PDF", data=pdf_bytes, file_name=fname, mime="application/pdf")

