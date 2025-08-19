import pandas as pd, requests, streamlit as st
import streamlit as st

st.set_page_config(page_title="ABC Home", layout="wide")

# --- make buttons BIG ---
st.markdown("""
<style>
/* Bigger standard buttons */
div.stButton > button {padding: 1.1rem 1.4rem; font-size: 1.1rem; border-radius: 12px;}
/* Bigger link buttons */
a[data-testid="stLinkButton"] {padding: 1rem 1.25rem !important; font-size: 1.1rem; border-radius: 12px !important; display:block; text-align:center;}
</style>
""", unsafe_allow_html=True)

st.title("🏫 ABC Behavior App")

# === 1) HUGE button to open your form (Apps Script web app) ===
# Put your deployed /exec URL in secrets.toml as: form_url = "https://script.google.com/macros/s/AK.../exec"
form_url = st.secrets.get("form_url", "https://script.google.com/macros/s/AKfycbzrpVfKjdAHfemCXltaeB3a6oRn4lvmr3AJYPn466x8kxhytbFyRr1wk08OTBmNw32YRA/exec")
st.link_button("📝 Open ABC Incident Form", form_url, type="primary", use_container_width=True)

st.divider()
st.subheader("Navigate")

# === 2) Large navigation buttons to your pages ===
# Make sure these files exist in analytics_streamlit/pages/
#   - pages/1_Incidents.py
#   - pages/2_Trends.py
#   - pages/3_Admin.py  (optional)
c1, c2, c3 = st.columns(3)

with c1:
    if st.button("📋 Incidents Table", use_container_width=True):
        st.switch_page("pages/3_Incidents.py")

with c2:
    if st.button("📈 Trends & Insights", use_container_width=True):
        st.switch_page("pages/2_Trends.py")

with c3:
    if st.button("⚙️ Admin", use_container_width=True):
        st.switch_page("pages/1_Admin.py")




@st.cache_data(ttl=60)
def load_incidents():
    # Build URL with mode=json
    base = st.secrets["api"]["url"]
    params = {"mode": "json", "token": st.secrets["api"]["token"]}
    r = requests.get(base, params=params, timeout=15)

    # Helpful debug on non-200
    if r.status_code != 200:
        snippet = r.text[:300].replace("\n", " ")
        raise RuntimeError(f"API {r.status_code}. Snippet: {snippet}")

    # Parse JSON safely
    try:
        payload = r.json()
    except Exception:
        snippet = r.text[:300].replace("\n", " ")
        raise RuntimeError(f"API did not return JSON. Snippet: {snippet}")

    df = pd.DataFrame(payload.get("data", []))
    # basic typing
    if "timestamp_utc" in df: df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
    if "date" in df: df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    for c in ["duration_sec","intensity"]:
        if c in df: df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

try:
    df = load_incidents()
except Exception as e:
    st.error(f"Failed to load incidents.\n\n{e}")
    st.stop()

if df.empty:
    st.info("No incidents yet.")
    st.stop()

# … your filters, KPIs, charts, table …
