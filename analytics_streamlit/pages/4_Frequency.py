# analytics_streamlit/pages/3_Frequency.py
import pandas as pd
import requests
import streamlit as st
import altair as alt
from datetime import datetime, date, timedelta, timezone

st.set_page_config(page_title="Frequency", layout="wide")
st.title("⏱️ Frequency")

# --- Use separate secrets so we don't touch your incidents API ---
API_URL  = st.secrets["freq_api"]["url"]
API_TOKEN = st.secrets["freq_api"]["token"]

# Catalog used for buttons
BEHAVIORS = [
    ("INGEST_NONFOOD", "Attempts to ingest an inedible object"),
    ("TRANSITION_ASSIST", "Transition Assistance within the classroom"),
    ("OUT_OF_SEAT", "Gets out of seat w/o permission"),
    ("AGGRESSION_PHYS", "Touches/Hits/Bites scratches others"),
    ("THROW_DESTROY", "Throws/Destroys objects"),
    ("VERBAL_AGGR", "Shouts out/Verbal Aggression"),
    ("OTHER", "Other"),
]

# ---------------- API helpers ----------------
@st.cache_data(ttl=60)
def load_students():
    r = requests.get(API_URL, params={"mode":"json","resource":"students","token":API_TOKEN}, timeout=15)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload: raise RuntimeError(payload)
    df = pd.DataFrame(payload.get("data", []))
    if not df.empty:
        df["label"] = df.apply(lambda x: f"{x.get('last_name','')}, {x.get('first_name','')} (Gr {x.get('grade','')})", axis=1)
    return df

@st.cache_data(ttl=60)
def load_events(student_key=None, start=None, end=None):
    params = {"mode":"json","resource":"events","token":API_TOKEN}
    if student_key: params["student_key"] = student_key
    if start: params["from"] = start.isoformat()
    if end: params["to"] = (end + timedelta(days=1) - timedelta(seconds=1)).isoformat()
    r = requests.get(API_URL, params=params, timeout=15)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload: raise RuntimeError(payload)
    df = pd.DataFrame(payload.get("data", []))
    if not df.empty:
        df["ts_utc"] = pd.to_datetime(df["ts_utc"], errors="coerce", utc=True)
        try:
            df["ts_ct"] = df["ts_utc"].dt.tz_convert("America/Chicago")
        except Exception:
            df["ts_ct"] = df["ts_utc"]
        df["date"] = df["ts_ct"].dt.date
        df["hour"] = df["ts_ct"].dt.hour
    return df

def post_json(action: str, body: dict):
    r = requests.post(API_URL, params={"action":action,"token":API_TOKEN}, json=body, timeout=15)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload: raise RuntimeError(payload)
    return payload

# ---------------- UI ----------------
tab_collect, tab_reports = st.tabs(["🧮 Frequency data collection", "📈 Frequency reports"])

# ===== Tab 1: Collection =====
with tab_collect:
    st.subheader("Students (for frequency tracking)")
    try:
        students_df = load_students()
    except Exception as e:
        st.error(f"Could not load students.\n\n{e}")
        students_df = pd.DataFrame()

    c1, c2 = st.columns([2,1])
    with c1:
        if not students_df.empty:
            st.dataframe(
                students_df[["student_key","last_name","first_name","grade","active"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "student_key": "Key", "last_name": "Last", "first_name": "First",
                    "grade": "Grade", "active": "Active"
                }
            )
        else:
            st.info("No students yet. Add one on the right.")

    with c2:
        st.markdown("**Add student**")
        ln = st.text_input("Last name")
        fn = st.text_input("First name")
        gr = st.text_input("Grade")
        if st.button("➕ Add"):
            if not ln or not fn or not gr:
                st.warning("Please fill Last, First, and Grade.")
            else:
                try:
                    res = post_json("add_student", {"last_name": ln, "first_name": fn, "grade": gr})
                    load_students.clear()
                    st.success(f"Added: {ln}, {fn} (key={res.get('student_key')})" + (" — already existed" if res.get("duplicate") else ""))
                    st.rerun()
                except Exception as e:
                    st.error(f"Add failed: {e}")

    st.divider()
    st.subheader("Observe & record")

    if students_df.empty:
        st.info("Add at least one student to start recording.")
        st.stop()

    key_by_label = {row["label"]: row["student_key"] for _, row in students_df.iterrows()}
    selected_label = st.selectbox("Select student to observe", list(key_by_label.keys()))
    selected_key = key_by_label[selected_label]

    other_note = st.text_input("If 'Other', briefly describe", placeholder="e.g., taps desk repeatedly")

    if "freq_log" not in st.session_state:
        st.session_state.freq_log = []

    st.markdown("<style>div.stButton > button {padding:1rem 1.2rem;font-size:1.05rem;border-radius:12px;}</style>", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, (code, label) in enumerate(BEHAVIORS):
        with cols[i % 3]:
            if st.button(label, use_container_width=True, key=f"btn_{code}"):
                payload = {
                    "student_key": selected_key,
                    "behavior_code": code,
                    "behavior_label": label,
                    "notes": (other_note if code == "OTHER" else "")
                }
                try:
                    res = post_json("add_event", payload)
                    st.session_state.freq_log.append({
                        "ts": datetime.now(timezone.utc).astimezone(),
                        "student_key": selected_key,
                        "behavior": label,
                        "event_id": res.get("event_id")
                    })
                    st.toast(f"Recorded: {label}", icon="✅")
                except Exception as e:
                    st.error(f"Save failed: {e}")

    if st.session_state.freq_log:
        st.subheader("This session")
        log_df = pd.DataFrame([{
            "Time (local)": x["ts"].strftime("%Y-%m-%d %H:%M:%S"),
            "Student key": x["student_key"],
            "Behavior": x["behavior"],
            "Event ID": x["event_id"]
        } for x in reversed(st.session_state.freq_log)])
        st.dataframe(log_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No events recorded in this session yet.")

# ===== Tab 2: Reports =====
with tab_reports:
    st.subheader("Filters")
    try:
        students_df = load_students()
    except Exception as e:
        st.error(f"Could not load students.\n\n{e}")
        students_df = pd.DataFrame()

    opts = ["All"]
    label_to_key = {}
    if not students_df.empty:
        for _, r in students_df.iterrows():
            opts.append(r["label"])
            label_to_key[r["label"]] = r["student_key"]

    c1, c2, c3 = st.columns(3)
    pick = c1.selectbox("Student", opts)
    start = c2.date_input("From", value=date.today().replace(day=1))
    end = c3.date_input("To", value=date.today())
    key = None if pick == "All" else label_to_key[pick]

    try:
        ev = load_events(key, start, end)
    except Exception as e:
        st.error(f"Failed to load events.\n\n{e}")
        st.stop()

    k1, k2 = st.columns(2)
    k1.metric("Events", f"{len(ev):,}")
    k2.metric("Days observed", f"{ev['date'].nunique():,}" if not ev.empty else "—")

    st.divider()
    if ev.empty:
        st.info("No events for the selected range.")
        st.stop()

    daily = ev.groupby("date").size().reset_index(name="count")
    st.altair_chart(
        alt.Chart(daily).mark_line(point=True).encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("count:Q", title="Events"),
            tooltip=["date:T","count:Q"]
        ).properties(height=280),
        use_container_width=True
    )

    st.subheader("By behavior")
    beh = ev.groupby("behavior_label").size().reset_index(name="count").sort_values("count", ascending=False)
    st.altair_chart(
        alt.Chart(beh).mark_bar().encode(
            x=alt.X("count:Q", title="Events"),
            y=alt.Y("behavior_label:N", sort='-x', title="Behavior"),
            tooltip=["behavior_label","count"]
        ).properties(height=280),
        use_container_width=True
    )

    st.subheader("Time of day × Day of week")
    ev["dow"] = ev["ts_ct"].dt.day_name()
    st.altair_chart(
        alt.Chart(ev).mark_rect().encode(
            x=alt.X("hour:O", title="Hour"),
            y=alt.Y("dow:N", title="Day", sort=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]),
            color=alt.Color("count()", title="Events"),
            tooltip=["dow","hour","count()"]
        ).properties(height=260),
        use_container_width=True
    )

    st.subheader("Events (filtered)")
    show = ev[["ts_ct","student_key","behavior_label","notes","event_id"]].sort_values("ts_ct", ascending=False)
    st.dataframe(show, use_container_width=True, hide_index=True, column_config={
        "ts_ct": st.column_config.DatetimeColumn("Time (CT)", format="YYYY-MM-DD HH:mm"),
        "student_key": "Student",
        "behavior_label": "Behavior",
        "notes": "Notes",
        "event_id": "Event ID"
    })
    st.download_button("⬇️ Download CSV", data=show.to_csv(index=False), file_name="frequency_events.csv", mime="text/csv")
