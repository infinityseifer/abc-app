# analytics_streamlit/pages/1_Incidents.py
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Incidents Table", layout="wide")
st.title("📋 Incidents Table")

# Optional: big button to open your Apps Script form
form_url = st.secrets.get("form_url")
if form_url:
    st.link_button("📝 Open ABC Incident Form", form_url, type="primary", use_container_width=True)

# --- Make toolbar buttons bigger ---
st.markdown("""
<style>
div.stButton > button {padding: 0.9rem 1.2rem; font-size: 1.05rem; border-radius: 12px;}
</style>
""", unsafe_allow_html=True)

# ---------- Data loader ----------
@st.cache_data(ttl=60)
def load_incidents():
    """Fetch incidents as JSON from Apps Script and return a typed DataFrame."""
    base = st.secrets["api"]["url"]
    token = st.secrets["api"]["token"]
    r = requests.get(base, params={"mode": "json", "token": token}, timeout=15)

    if r.status_code != 200:
        raise RuntimeError(f"API {r.status_code}. Snippet: {r.text[:300]}")

    payload = r.json()  # Our Apps Script returns JSON even for errors
    if "error" in payload:
        raise RuntimeError(f"API error: {payload}")

    df = pd.DataFrame(payload.get("data", []))

    # Normalize columns if present
    if "timestamp_utc" in df:
        ts = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
        try:
            df["timestamp_ct"] = ts.dt.tz_convert("America/Chicago")
        except Exception:
            df["timestamp_ct"] = ts
    if "date" in df:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in ["duration_sec", "intensity"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Preferred column order
    preferred = [
        "timestamp_ct", "date", "time", "student_id", "location",
        "antecedent", "behavior", "consequence", "duration_sec",
        "intensity", "notes", "staff", "incident_id"
    ]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    df = df.loc[:, cols] if len(df) else df
    return df

# Load with friendly error
try:
    df = load_incidents()
except Exception as e:
    st.error(f"Failed to load incidents.\n\n{e}")
    st.stop()

if df.empty:
    st.info("No incidents yet. Submit via the form above.")
    st.stop()

# ---------- Session state defaults ----------
if "show_filters" not in st.session_state:
    st.session_state.show_filters = True
if "show_sort" not in st.session_state:
    st.session_state.show_sort = False
if "sort_by" not in st.session_state:
    st.session_state.sort_by = "timestamp_ct" if "timestamp_ct" in df.columns else ( "timestamp_utc" if "timestamp_utc" in df.columns else None )
if "sort_dir" not in st.session_state:
    st.session_state.sort_dir = "desc"  # 'asc' or 'desc'

# ---------- Toolbar: Filter / Sort buttons ----------
tb1, tb2, tb3 = st.columns([1, 1, 4])
with tb1:
    if st.button("🔎 Filters", use_container_width=True):
        st.session_state.show_filters = not st.session_state.show_filters
with tb2:
    if st.button("↕️ Sort", use_container_width=True):
        st.session_state.show_sort = not st.session_state.show_sort

# ---------- Filter Panel ----------
def render_filters(df_in: pd.DataFrame):
    with st.container(border=True):
        st.markdown("**Filters**")
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1.2])

        student = c1.selectbox("Student", ["All"] + sorted(df_in["student_id"].dropna().unique().tolist())) if "student_id" in df_in else "All"
        behavior = c2.selectbox("Behavior", ["All"] + sorted(df_in["behavior"].dropna().unique().tolist())) if "behavior" in df_in else "All"
        location = c3.selectbox("Location", ["All"] + sorted(df_in["location"].dropna().unique().tolist())) if "location" in df_in else "All"
        date_range = c4.date_input("Date range", value=())

        c5, c6 = st.columns([1, 2])
        intensity_min = c5.slider("Min intensity", 1, 5, 1) if "intensity" in df_in else 1
        search = c6.text_input("Search notes/staff", placeholder="type to filter…")

        # Build mask
        mask = pd.Series(True, index=df_in.index)
        if "student_id" in df_in and student != "All":
            mask &= df_in["student_id"].eq(student)
        if "behavior" in df_in and behavior != "All":
            mask &= df_in["behavior"].eq(behavior)
        if "location" in df_in and location != "All":
            mask &= df_in["location"].eq(location)
        if "date" in df_in and len(date_range) == 2:
            start, end = date_range
            mask &= (df_in["date"] >= start) & (df_in["date"] <= end)
        if "intensity" in df_in and intensity_min:
            mask &= df_in["intensity"].fillna(0) >= intensity_min
        if search:
            s = search.lower()
            fields = [c for c in ["notes", "staff"] if c in df_in]
            if fields:
                m = pd.Series(False, index=df_in.index)
                for c in fields:
                    m |= df_in[c].astype(str).str.lower().str.contains(s, na=False)
                mask &= m

        # Controls row
        bc1, bc2, bc3 = st.columns([1, 1, 6])
        if bc1.button("Clear filters"):
            st.rerun()
        if bc2.button("Refresh data"):
            load_incidents.clear()
            st.rerun()

    return df_in.loc[mask].copy()

# ---------- Sort Panel ----------
def render_sort_controls(df_in: pd.DataFrame):
    with st.container(border=True):
        st.markdown("**Sort**")
        # Choose sortable columns from DataFrame
        sortable_candidates = [
            "timestamp_ct", "timestamp_utc", "date", "time",
            "student_id", "location", "antecedent", "behavior",
            "consequence", "duration_sec", "intensity", "staff"
        ]
        sortable_cols = [c for c in sortable_candidates if c in df_in.columns]
        default_col = st.session_state.sort_by or (sortable_cols[0] if sortable_cols else None)

        col1, col2, col3 = st.columns([2, 1, 1])
        sel = col1.selectbox("Column", sortable_cols, index=sortable_cols.index(default_col) if default_col in sortable_cols else 0, key="sort_col_sel")
        dir_label = "Ascending" if st.session_state.sort_dir == "asc" else "Descending"
        dir_choice = col2.radio("Direction", ["Descending", "Ascending"], horizontal=True, index=(0 if dir_label=="Descending" else 1), key="sort_dir_radio")

        apply_clicked = col3.button("Apply sort", type="primary")
        if apply_clicked:
            st.session_state.sort_by = sel
            st.session_state.sort_dir = "asc" if dir_choice == "Ascending" else "desc"
            st.rerun()

# Show panels depending on toggles
if st.session_state.show_filters:
    fdf = render_filters(df)
else:
    fdf = df.copy()

if st.session_state.show_sort:
    render_sort_controls(fdf)

# ---------- Apply sorting to filtered data ----------
sort_by = st.session_state.sort_by
ascending = (st.session_state.sort_dir == "asc")
if sort_by and sort_by in fdf.columns:
    try:
        fdf = fdf.sort_values(sort_by, ascending=ascending, kind="mergesort")  # stable sort
    except Exception:
        pass

# ---------- KPIs ----------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Incidents", f"{len(fdf):,}")
if "duration_sec" in fdf and len(fdf):
    k2.metric("Avg duration (s)", f"{fdf['duration_sec'].mean():.0f}")
else:
    k2.metric("Avg duration (s)", "—")
if "intensity" in fdf and len(fdf):
    k3.metric("Median intensity", f"{fdf['intensity'].median():.0f}")
else:
    k3.metric("Median intensity", "—")
if "date" in fdf and len(fdf):
    k4.metric("Days in range", f"{fdf['date'].nunique():,}")
else:
    k4.metric("Days in range", "—")

st.divider()

# ---------- Table ----------
column_config = {}
if "timestamp_ct" in fdf:
    column_config["timestamp_ct"] = st.column_config.DatetimeColumn("Submitted (CT)", format="YYYY-MM-DD HH:mm")
if "duration_sec" in fdf:
    column_config["duration_sec"] = st.column_config.NumberColumn("Duration (sec)", step=1)
if "intensity" in fdf:
    column_config["intensity"] = st.column_config.NumberColumn("Intensity (1–5)", min_value=1, max_value=5, step=1)
if "student_id" in fdf:
    column_config["student_id"] = st.column_config.TextColumn("Student ID")
if "notes" in fdf:
    column_config["notes"] = st.column_config.TextColumn("Notes", width="medium")

# Show active sort (tiny hint)
if sort_by:
    st.caption(f"Sorted by **{sort_by}** ({'ascending' if ascending else 'descending'})")

st.dataframe(
    fdf,
    use_container_width=True,
    hide_index=True,
    column_config=column_config
)

# ---------- Export ----------
csv = fdf.to_csv(index=False)
st.download_button("⬇️ Download filtered CSV", data=csv, file_name="abc_incidents_filtered.csv", mime="text/csv")
