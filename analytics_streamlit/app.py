import os
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="ABC Home", layout="wide")

st.title("🏫 ABC Behavior App")

# Top red form button target URL
form_url = st.secrets.get(
    "form_url",
    "https://script.google.com/macros/s/AKfycbzrpVfKjdAHfemCXltaeB3a6oRn4lvmr3AJYPn466x8kxhytbFyRr1wk08OTBmNw32YRA/exec",
)

# --- styles: red CTA (form) + blue nav buttons, same size ---
st.markdown("""
<style>
:root{
  --red:#dc2626; --red-h:#b91c1c; --red-a:#991b1b;        /* form CTA */
  --blue:#1f6feb; --blue-h:#1a5bd6; --blue-a:#1549ad;     /* navigate */
}

/* same sizing for both types */
div.stButton > button,
a[data-testid="stLinkButton"]{
  padding:1.1rem 1.4rem !important;
  font-size:1.1rem !important;
  border-radius:12px !important;
  width:100% !important;
  display:block !important;
  text-align:center !important;
}

/* top form link button = RED */
a[data-testid="stLinkButton"]{
  background:var(--red) !important; border:1px solid var(--red) !important; color:#fff !important;
}
a[data-testid="stLinkButton"]:hover{  background:var(--red-h) !important; border-color:var(--red-h) !important; }
a[data-testid="stLinkButton"]:active{ background:var(--red-a) !important; border-color:var(--red-a) !important; }

/* navigate buttons = BLUE */
div.stButton > button{
  background:var(--blue) !important; border:1px solid var(--blue) !important; color:#fff !important;
}
div.stButton > button:hover{  background:var(--blue-h) !important; border-color:var(--blue-h) !important; }
div.stButton > button:active{ background:var(--blue-a) !important; border-color:var(--blue-a) !important; }
</style>
""", unsafe_allow_html=True)

# -------- navigation helper (buttons -> pages) --------
from pathlib import Path
import traceback

def goto(script_basename: str):
    """
    Navigate to a multipage script inside ./pages by filename, e.g. '1_Incidents.py'.
    If navigation fails, show helpful diagnostics (does the file exist?).
    """
    target_rel = f"pages/{script_basename}"
    try:
        st.switch_page(target_rel)
    except Exception:
        # Diagnostics: does the file exist on disk? what pages are present?
        here = Path(__file__).resolve().parent
        pages_dir = here / "pages"
        expected_path = pages_dir / script_basename
        exists = expected_path.exists()

        available = []
        if pages_dir.exists():
            available = sorted(p.name for p in pages_dir.glob("*.py"))

        st.error(
            "Couldn't navigate to page.\n\n"
            f"Target: `{target_rel}`\n"
            f"Exists on disk: **{exists}** (looked for `{expected_path}`)\n\n"
            "Make sure the filename matches **exactly** (case-sensitive on Streamlit Cloud) "
            "and lives under the `pages/` folder. If you just added/renamed a page, "
            "push to GitHub and redeploy, or restart the app.\n\n"
            f"Pages I can see: {', '.join(available) if available else '(none found)'}"
        )
        # Optional: log the traceback to the app for quick debugging
        st.caption("Debug:\n" + "".join(traceback.format_exc()))


# -------- top red form button --------
st.link_button("📝 Open ABC Incident Form", form_url, type="primary", use_container_width=True)

st.divider()
st.subheader("Navigate")

# 2×2 grid of BLUE nav buttons
r1c1, r1c2 = st.columns(2)
with r1c1:
    if st.button("📋 Incidents Table", use_container_width=True):
        goto(script_basename="3_Incidents.py")
with r1c2:
    if st.button("📈 Trends & Insights", use_container_width=True):
        goto(script_basename="2_Trends.py")

r2c1, r2c2 = st.columns(2)
with r2c1:
    if st.button("⚙️ Admin", use_container_width=True):
        goto(script_basename="1_Admin.py")
with r2c2:
    if st.button("⏱️ Frequency", use_container_width=True):
        goto(script_basename="4_Frequency.py")

# ------------------ (optional) incidents preload ------------------
@st.cache_data(ttl=60)
def load_incidents():
    base = st.secrets["api"]["url"]
    params = {"mode": "json", "token": st.secrets["api"]["token"]}
    r = requests.get(base, params=params, timeout=15)
    if r.status_code != 200:
        snippet = r.text[:300].replace("\n", " ")
        raise RuntimeError(f"API {r.status_code}. Snippet: {snippet}")
    try:
        payload = r.json()
    except Exception:
        snippet = r.text[:300].replace("\n", " ")
        raise RuntimeError(f"API did not return JSON. Snippet: {snippet}")

    df = pd.DataFrame(payload.get("data", []))
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

# End of file

