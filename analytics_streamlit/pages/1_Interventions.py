# analytics_streamlit/pages/1_Interventions.py
import pandas as pd
import requests
import streamlit as st
import altair as alt
from datetime import date, timedelta

st.set_page_config(page_title="Interventions", layout="wide")
st.title("🧰 Interventions")

# ---------------------- Safe secrets helper ----------------------
def get_secret(path: str, default=None):
    """Read 'a.b.c' from st.secrets; return default if absent (no crash)."""
    try:
        node = st.secrets
        for part in path.split("."):
            node = node[part]
        return node
    except Exception:
        return default

# Required Interventions API (Apps Script web app)
INT_API_URL   = get_secret("interv_api.url")
INT_API_TOKEN = get_secret("interv_api.token")

# Optional: Students list from Frequency API (if available)
FREQ_API_URL   = get_secret("freq_api.url")
FREQ_API_TOKEN = get_secret("freq_api.token")

# Optional: Incidents API (not required)
INC_API_URL   = get_secret("api.url")
INC_API_TOKEN = get_secret("api.token")

# Quick dev helper
if st.button("🔄 Refresh data caches"):
    for name, fn in list(globals().items()):
        if callable(fn) and name.startswith("load_"):
            try:
                fn.clear()
            except Exception:
                pass
    st.success("Caches cleared.")
    st.rerun()

# ---------------------- Small helpers ----------------------
def _norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())

def _split_tags(val: str) -> list[str]:
    import re
    if val is None:
        return []
    parts = re.split(r"[;,/]", str(val))
    return [_norm(p) for p in parts if _norm(p)]

DEFAULT_BEHAVIORS = [
    "Attempts to ingest an inedible object",
    "Transition Assistance within the classroom",
    "Gets out of seat w/o permission",
    "Touches/Hits/Bites scratches others",
    "Throws/Destroys objects",
    "Shouts out/Verbal Aggression",
    "Other",
]

# ---------------------- HTTP helpers ----------------------
def _get_json(url, params, label: str, timeout=20):
    r = requests.get(url, params=params, timeout=timeout)
    ct = (r.headers.get("content-type") or "").lower()
    if r.status_code != 200 or "json" not in ct:
        snippet = (r.text or "")[:400].replace("\n", " ")
        raise RuntimeError(f"{label}: HTTP {r.status_code}, CT={ct}. Snippet: {snippet}")
    try:
        return r.json()
    except Exception:
        snippet = (r.text or "")[:400].replace("\n", " ")
        raise RuntimeError(f"{label}: response not JSON. Snippet: {snippet}")

def _post_json(url, params, body, label: str, timeout=20):
    r = requests.post(url, params=params, json=body, timeout=timeout)
    ct = (r.headers.get("content-type") or "").lower()
    if r.status_code != 200 or "json" not in ct:
        snippet = (r.text or "")[:400].replace("\n", " ")
        raise RuntimeError(f"{label}: HTTP {r.status_code}, CT={ct}. Snippet: {snippet}")
    try:
        return r.json()
    except Exception:
        snippet = (r.text or "")[:400].replace("\n", " ")
        raise RuntimeError(f"{label}: response not JSON. Snippet: {snippet}")

# ---------------------- Frequency (for suggestions) ----------------------
@st.cache_data(ttl=60)
def _load_freq_events(freq_url: str, freq_token: str, student_key: str, start: date, end: date) -> pd.DataFrame:
    params = {
        "mode": "json",
        "resource": "events",
        "student_key": student_key,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "token": freq_token,
    }
    payload = _get_json(freq_url, params, "Frequency events")
    df = pd.DataFrame(payload.get("data", []))
    if df.empty:
        return df
    if "ts_utc" in df:
        df["ts_utc"] = pd.to_datetime(df["ts_utc"], errors="coerce", utc=True)
    if "behavior_label" in df:
        df["behavior_label"] = df["behavior_label"].astype(str)
    return df

# ---------------------- Data loaders (cached) ----------------------
@st.cache_data(ttl=60)
def load_students():
    # Prefer Frequency API
    if FREQ_API_URL and FREQ_API_TOKEN:
        try:
            payload = _get_json(
                FREQ_API_URL,
                {"mode": "json", "resource": "students", "token": FREQ_API_TOKEN},
                "Students (frequency)"
            )
            df = pd.DataFrame(payload.get("data", []))
            if not df.empty:
                if "student_id" not in df.columns and "student_key" in df.columns:
                    df = df.rename(columns={"student_key": "student_id"})
                if "label" not in df.columns:
                    df["label"] = df.apply(
                        lambda x: f"{x.get('last_name','')}, {x.get('first_name','')} (Gr {x.get('grade','')})",
                        axis=1
                    )
                return df[["student_id", "label"]].dropna()
        except Exception:
            pass
    # Fallback: Interventions API (if it exposes students)
    if INT_API_URL and INT_API_TOKEN:
        try:
            payload = _get_json(
                INT_API_URL,
                {"mode": "json", "resource": "students", "token": INT_API_TOKEN},
                "Students (interventions)"
            )
            df = pd.DataFrame(payload.get("data", []))
            if not df.empty:
                if "student_id" not in df.columns:
                    for alt in ("student_key", "id"):
                        if alt in df.columns:
                            df = df.rename(columns={alt: "student_id"})
                            break
                if "label" not in df.columns:
                    df["label"] = df["student_id"].astype(str)
                return df[["student_id", "label"]].dropna()
        except Exception:
            pass
    return pd.DataFrame(columns=["student_id", "label"])

@st.cache_data(ttl=60)
def load_catalog():
    payload = _get_json(
        INT_API_URL,
        {"mode": "json", "resource": "catalog", "token": INT_API_TOKEN},
        "Interventions catalog"
    )
    return pd.DataFrame(payload.get("data", []))

@st.cache_data(ttl=60)
def load_assignments(student_id: str | None = None):
    params = {"mode": "json", "resource": "assignments", "token": INT_API_TOKEN}
    if student_id:
        params["student_id"] = student_id
    payload = _get_json(INT_API_URL, params, "Intervention assignments")
    df = pd.DataFrame(payload.get("data", []))
    if df.empty:
        return df
    # normalize backend variants
    if "assignment" in df.columns and "assignment_id" not in df.columns:
        df = df.rename(columns={"assignment": "assignment_id"})
    if "intervention" in df.columns and "intervention_code" not in df.columns:
        df = df.rename(columns={"intervention": "intervention_code"})
    return df

@st.cache_data(ttl=60)
def load_tracking(student_id: str | None = None,
                  assignment_id: str | None = None,
                  start: date | None = None,
                  end: date | None = None) -> pd.DataFrame:
    params = {"mode": "json", "resource": "tracking", "token": INT_API_TOKEN}
    if student_id:
        params["student_id"] = student_id
    if assignment_id:
        params["assignment_id"] = assignment_id
    if start:
        params["from"] = start.isoformat()
    if end:
        params["to"] = end.isoformat()

    payload = _get_json(INT_API_URL, params, "Intervention tracking")
    df = pd.DataFrame(payload.get("data", []))
    if df.empty:
        return df

    # normalize backend variants
    if "assignment" in df.columns and "assignment_id" not in df.columns:
        df = df.rename(columns={"assignment": "assignment_id"})
    if "intervention" in df.columns and "intervention_code" not in df.columns:
        df = df.rename(columns={"intervention": "intervention_code"})

    # build/normalize a date column
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    else:
        candidate_dt_cols = [c for c in ["ts_utc","timestamp","created_at","time","when"] if c in df.columns]
        derived = None
        for c in candidate_dt_cols:
            ts = pd.to_datetime(df[c], errors="coerce", utc=True).tz_convert(None)
            if ts.notna().any():
                derived = ts.dt.date
                break
        if derived is None:
            for c in df.columns:
                s = df[c].astype(str)
                if s.str.match(r"\d{4}-\d{2}-\d{2}").any():
                    derived = pd.to_datetime(s, errors="coerce").dt.date
                    break
        df["date"] = derived

    # normalize types
    if "completed" in df.columns:
        df["completed"] = df["completed"].astype(str).str.lower().isin(["1","true","yes","y"])
    if "fidelity_pct" in df.columns:
        df["fidelity_pct"] = pd.to_numeric(df["fidelity_pct"], errors="coerce")

    # ensure expected display columns exist
    for col in ["assignment_id","intervention_code","notes"]:
        if col not in df.columns:
            df[col] = None
    return df

# ---------------------- Guard: required secrets ----------------------
if not (INT_API_URL and INT_API_TOKEN):
    st.error(
        "Missing [interv_api] settings in `.streamlit/secrets.toml`.\n\n"
        "[interv_api]\n"
        "url = \"https://script.google.com/macros/s/XXXXX/exec\"\n"
        "token = \"YOUR_TOKEN\""
    )
    st.stop()

# ---------------------- UI: Tabs ----------------------
tab_assign, tab_track, tab_reports = st.tabs(["📝 Assign", "🧾 Track", "📊 Reports"])

# ========= Tab: Assign =========
with tab_assign:
    st.subheader("Assign an intervention")

    # Students
    students = load_students()
    c1, c2 = st.columns([2, 1])
    if not students.empty:
        student_label = c1.selectbox("Student", options=students["label"].tolist())
        student_id = students.set_index("label").loc[student_label, "student_id"]
    else:
        st.info("No student list available; enter an ID manually.")
        student_id = c1.text_input("Student ID").strip()

    # Catalog
    try:
        catalog = load_catalog()
    except Exception as e:
        st.error(f"{e}")
        catalog = pd.DataFrame()

    # Suggestions (requires freq creds + catalog + student)
    st.divider()
    st.subheader("💡 Suggested interventions (based on recent frequency)")
    if catalog.empty:
        st.caption("No interventions in the catalog yet—skipping suggestions.")
    else:
        LOOKBACK_DAYS = 14
        TOP_BEHAVIORS = 2
        TIER_BOOST = {"1": 0.0, "2": 0.1, "3": 0.15}

        if not (FREQ_API_URL and FREQ_API_TOKEN and student_id):
            st.caption("Suggestions disabled (missing frequency API creds or student).")
            freq_df = pd.DataFrame()
        else:
            freq_student_key = str(student_id)  # map student_id -> student_key if needed
            start_w = date.today() - timedelta(days=LOOKBACK_DAYS)
            end_w = date.today()
            try:
                freq_df = _load_freq_events(FREQ_API_URL, FREQ_API_TOKEN, freq_student_key, start_w, end_w)
            except Exception as e:
                st.warning(f"Could not load recent frequency events: {e}")
                freq_df = pd.DataFrame()

        if freq_df.empty:
            st.caption("No recent frequency data available for this student.")
        else:
            counts = freq_df["behavior_label"].value_counts().reset_index()
            counts.columns = ["behavior_label", "events"]
            st.caption(f"Window: last {LOOKBACK_DAYS} day(s). Total events: {int(counts['events'].sum())}")

            counts["key"] = counts["behavior_label"].map(_norm)
            top_behaviors = counts.head(TOP_BEHAVIORS).copy()

            cat = catalog.copy()
            beh_col = None
            for candidate in ["behavior", "Behavior", "behaviors", "behavior_tag", "tags"]:
                if candidate in cat.columns:
                    beh_col = candidate
                    break
            cat["_tags"] = [[] for _ in range(len(cat))] if beh_col is None else cat[beh_col].apply(_split_tags)

            def _tier_num(x):
                try:
                    return float(x)
                except Exception:
                    return 0.0
            cat["_tier_num"] = cat.get("tier", pd.Series(dtype=str)).apply(_tier_num)

            suggested = []
            for _, row in top_behaviors.iterrows():
                beh_disp = row["behavior_label"]
                beh_key = row["key"]
                beh_events = int(row["events"])

                if beh_col is not None:
                    cat_match = cat[cat["_tags"].apply(lambda tags: beh_key in tags)].copy()
                    if cat_match.empty:
                        cat_match = cat.copy()
                else:
                    cat_match = cat.copy()

                cat_match["_score"] = beh_events + cat_match["_tier_num"].map(
                    lambda t: TIER_BOOST.get(str(int(t)), 0.0) * beh_events
                )
                for _, r in cat_match.sort_values("_score", ascending=False).head(3).iterrows():
                    suggested.append({
                        "behavior_display": beh_disp,
                        "behavior_key": beh_key,
                        "code": r.get("code") or "",
                        "name": r.get("name") or r.get("intervention") or r.get("code") or "Intervention",
                        "tier": r.get("tier"),
                        "default_goal": r.get("default_goal") or "",
                        "score": r.get("_score", 0),
                    })

            if not suggested:
                st.caption("No matching catalog items for the recent behaviors.")
            else:
                sug_df = pd.DataFrame(suggested)
                for beh in sug_df["behavior_display"].unique():
                    sub = sug_df[sug_df["behavior_display"] == beh].sort_values("score", ascending=False)
                    st.markdown(f"**Behavior:** {beh}")
                    for _, s in sub.iterrows():
                        col1, col2, col3, col4 = st.columns([2.2, 1, 2.2, 1.2])
                        with col1:
                            st.write(f"**{s['name']}** [{s['code']}]")
                            st.caption(f"Tier: {s.get('tier','—')}")
                        with col2:
                            goal = st.text_input(
                                "Goal", key=f"goal_{beh}_{s['code']}",
                                value=s["default_goal"], label_visibility="collapsed",
                                placeholder="Goal/target"
                            )
                        with col3:
                            schedule = st.selectbox(
                                "Schedule", ["Daily", "Weekly", "Other"], key=f"sched_{beh}_{s['code']}",
                                label_visibility="collapsed"
                            )
                        with col4:
                            if st.button("Assign", key=f"assign_{beh}_{s['code']}", use_container_width=True):
                                body = {
                                    "student_id": str(student_id),
                                    "intervention_code": s["code"],  # backend also accepts 'intervention'
                                    "behavior": beh,
                                    "goal": goal or s["default_goal"],
                                    "start": date.today().isoformat(),
                                    "schedule": schedule,
                                    "owner": st.session_state.get("owner_default", ""),
                                }
                                try:
                                    _post_json(
                                        INT_API_URL,
                                        {"action": "add_assignment", "token": INT_API_TOKEN},
                                        body,
                                        "Add assignment (suggested)"
                                    )
                                    load_assignments.clear()
                                    st.success(f"Assigned: {beh} → {s['name']} [{s['code']}]")
                                except Exception as e:
                                    st.error(f"{e}")

    # Manual assignment
    st.divider()
    st.subheader("Manual assignment")

    if 'catalog' in locals() and not catalog.empty:
        beh_col = "behavior" if "behavior" in catalog.columns else None
        behaviors = (
            sorted([b for b in catalog[beh_col].dropna().astype(str).unique() if b.strip()])
            if beh_col else DEFAULT_BEHAVIORS
        )

        behavior_pick = st.selectbox("Behavior", options=behaviors, key="asgn_behavior")

        if beh_col:
            cat_filtered = catalog[
                catalog[beh_col].astype(str).str.strip().str.casefold()
                .eq(str(behavior_pick).strip().casefold())
            ]
            if cat_filtered.empty:
                st.info("No interventions tagged for this behavior; showing all.")
                cat_filtered = catalog.copy()
        else:
            cat_filtered = catalog.copy()

        def _label(row):
            name = row.get("name") or row.get("intervention") or row.get("code") or "Intervention"
            code = row.get("code") or ""
            tier = row.get("tier") or ""
            return f"{name} [{code}] {('(Tier ' + str(tier) + ')') if tier else ''}".strip()

        cat_filtered["_pick"] = cat_filtered.apply(_label, axis=1)
        pick = st.selectbox("Intervention", options=cat_filtered["_pick"].tolist(), key="asgn_interv")
        chosen = cat_filtered.loc[cat_filtered["_pick"] == pick].iloc[0].to_dict()
        default_goal = chosen.get("default_goal") or ""

        c3, c4, c5 = st.columns([2, 1, 1])
        goal = c3.text_input("Goal/Target", value=default_goal)
        start_d = c4.date_input("Start", value=date.today())
        freq = c5.selectbox("Schedule", ["Daily", "Weekly", "Other"])
        owner = st.text_input("Owner/Provider", placeholder="e.g., Ms. Lee (SPED)")

        if st.button("➕ Assign intervention", type="primary", use_container_width=True, disabled=not student_id):
            body = {
                "student_id": str(student_id),
                "intervention_code": chosen.get("code") or chosen.get("id") or "",
                "behavior": behavior_pick,
                "goal": goal,
                "start": start_d.isoformat(),
                "schedule": freq,
                "owner": owner,
            }
            try:
                _post_json(
                    INT_API_URL,
                    {"action": "add_assignment", "token": INT_API_TOKEN},
                    body,
                    "Add assignment"
                )
                load_assignments.clear()
                st.success(f"Assigned: {behavior_pick} → {pick}")
            except Exception as e:
                st.error(f"{e}")
    else:
        st.warning("No interventions in the catalog yet.")

    # Current assignments
    st.divider()
    st.subheader("Current assignments")
    if student_id:
        try:
            assign = load_assignments(str(student_id))
        except Exception as e:
            st.error(f"{e}")
            assign = pd.DataFrame()

        if not assign.empty:
            # Already normalized to have assignment_id / intervention_code if backend used variants
            rename = {
                "assignment_id": "Assignment",
                "intervention_code": "Intervention",
                "behavior": "Behavior",
                "name": "Name",
                "goal": "Goal",
                "start": "Start",
                "status": "Status",
            }
            view = assign.rename(columns=rename)
            st.dataframe(view, use_container_width=True, hide_index=True)
        else:
            st.info("No assignments for this student yet.")
    else:
        st.caption("Select or enter a student to see assignments.")

# ========= Tab: Track =========
with tab_track:
    st.subheader("Log tracking data")

    # 1) Student
    students = load_students()
    c1, c2, c3 = st.columns([2, 1.2, 1.2])
    if not students.empty:
        student_label = c1.selectbox("Student", options=students["label"].tolist(), key="trk_student")
        student_id = students.set_index("label").loc[student_label, "student_id"]
    else:
        student_id = c1.text_input("Student ID", key="trk_student_manual").strip()

    # 2) Assignments for student
    assignments = pd.DataFrame()
    if student_id:
        try:
            assignments = load_assignments(str(student_id))
        except Exception as e:
            st.error(f"{e}")

    if assignments.empty:
        st.info("No assignments found for this student. Add one in the **Assign** tab.")
        st.stop()

    # Optional behavior filter
    beh_col = "behavior" if "behavior" in assignments.columns else None
    if beh_col:
        behaviors = ["All"] + sorted([b for b in assignments[beh_col].dropna().astype(str).unique() if b.strip()])
        beh_pick = c2.selectbox("Filter by behavior", behaviors, index=0, key="trk_behavior")
        if beh_pick != "All":
            assignments = assignments[assignments[beh_col].astype(str).str.strip().eq(beh_pick)]

    if assignments.empty:
        st.info("No assignments match the current filter.")
        st.stop()

    # Normalize alternates so we can always read these later
    if "assignment_id" not in assignments.columns:
        for cand in ("assignment", "id"):
            if cand in assignments.columns:
                assignments = assignments.rename(columns={cand: "assignment_id"})
                break
    if "intervention_code" not in assignments.columns:
        for cand in ("code", "intervention"):
            if cand in assignments.columns:
                assignments = assignments.rename(columns={cand: "intervention_code"})
                break

    def _alabel(row):
        name = row.get("name") or row.get("intervention_code") or row.get("assignment_id") or "Intervention"
        goal = (row.get("goal") or "").strip()
        beh  = (row.get("behavior") or "").strip()
        bits = [name]
        if beh:  bits.append(f"({beh})")
        if goal: bits.append(f"— {goal}")
        return " ".join(bits)

    assignments = assignments.copy()
    assignments["_pick"] = assignments.apply(_alabel, axis=1)
    apick = c3.selectbox("Assignment", options=assignments["_pick"].tolist(), key="trk_assign")
    chosen  = assignments.loc[assignments["_pick"] == apick].iloc[0].to_dict()
    asgn_id = chosen.get("assignment_id") or ""
    asgn_code = chosen.get("intervention_code") or ""

    st.divider()

    # 3) Date
    dcol1, dcol2, dcol3, dcol4 = st.columns([1.3, 1, 1, 2])
    date_mode = dcol1.radio("Date", ["Today", "Yesterday", "Pick date"], horizontal=True, key="trk_date_mode")
    if date_mode == "Today":
        day = date.today()
        dcol4.caption(f"Using **{day.isoformat()}**")
    elif date_mode == "Yesterday":
        day = date.today() - timedelta(days=1)
        dcol4.caption(f"Using **{day.isoformat()}**")
    else:
        day = dcol4.date_input("Choose date", value=date.today(), label_visibility="visible", key="trk_date_pick")

    # 4) Fidelity, completed, notes
    l1, l2 = st.columns([1.2, 2.8])
    p1, p2, p3, _ = l1.columns(4)
    if p1.button("100%", key="fid_100"): st.session_state["trk_fid_default"] = 100
    if p2.button("80%", key="fid_80"):  st.session_state["trk_fid_default"]  = 80
    if p3.button("60%", key="fid_60"):  st.session_state["trk_fid_default"]  = 60
    fid_default = st.session_state.get("trk_fid_default", 100)

    fidelity = l1.slider("Fidelity %", 0, 100, fid_default, key="trk_fidelity")
    completed = l1.checkbox("Completed", value=True, key="trk_completed")
    notes = l2.text_area("Notes (what was delivered & student response)", placeholder="Brief notes…", key="trk_notes")

    # 5) Save
    b1, b2 = st.columns([1, 1])

    def _submit(clear_form: bool):
        body = {
            # backend-preferred keys
            "assignment": str(asgn_id),
            "intervention": str(asgn_code),

            # canonical duplicates (harmless if ignored)
            "assignment_id": str(asgn_id),
            "intervention_code": str(asgn_code),

            "student_id": str(student_id),
            "date": day.isoformat(),
            "fidelity_pct": int(fidelity),
            "completed": bool(completed),
            "notes": notes,
        }
        try:
            _post_json(
                INT_API_URL,
                {"action": "add_tracking", "token": INT_API_TOKEN},
                body,
                "Add tracking"
            )
            load_tracking.clear()
            st.success("Logged ✅")
            if clear_form:
                st.rerun()
        except Exception as e:
            st.error(f"{e}")

    if b1.button("➕ Log entry", type="primary", use_container_width=True, key="btn_log_once"):
        _submit(clear_form=True)
    if b2.button("➕ Log & add another", use_container_width=True, key="btn_log_again"):
        _submit(clear_form=True)

    st.divider()

    # 6) Recent tracking
    st.subheader("Recent tracking")
    try:
        trk = load_tracking(student_id=str(student_id))
    except Exception as e:
        st.error(f"{e}")
        trk = pd.DataFrame()

    if not trk.empty:
        # Already normalized to have assignment_id / intervention_code
        cols_pref = ["date","assignment_id","intervention_code","behavior","fidelity_pct","completed","notes"]
        show_cols = [c for c in cols_pref if c in trk.columns]
        view = trk.sort_values("date", ascending=False)[show_cols].head(25)
        st.dataframe(view, use_container_width=True, hide_index=True)
    else:
        st.caption("No tracking entries yet for this student.")

# ========= Tab: Reports =========
with tab_reports:
    st.subheader("Progress & fidelity — all data")

    # Student
    students = load_students()
    c1 = st.columns([2])[0]
    if not students.empty:
        student_label = c1.selectbox("Student", options=students["label"].tolist(), key="rep_student_all")
        student_id = students.set_index("label").loc[student_label, "student_id"]
    else:
        student_id = c1.text_input("Student ID", key="rep_student_manual_all").strip()

    # All tracking for student
    try:
        trk = load_tracking(student_id=str(student_id) if student_id else None)
    except Exception as e:
        st.error(f"{e}")
        st.stop()

    # Debug span
    with st.expander("Debug (data span)"):
        if not trk.empty and "date" in trk:
            dmin = pd.to_datetime(trk["date"]).min().date()
            dmax = pd.to_datetime(trk["date"]).max().date()
            st.write(f"Available tracking dates: **{dmin} → {dmax}**")
        else:
            st.write("No date column or no rows yet.")

    if trk.empty:
        st.info("No tracking records found for this student yet. Log entries in the **Track** tab.")
        st.stop()

    # KPIs
    k1, k2, k3 = st.columns(3)
    k1.metric("Entries", f"{len(trk):,}")
    if "completed" in trk:
        k2.metric("Completion rate", f"{(100.0 * trk['completed'].mean()):.0f}%")
    else:
        k2.metric("Completion rate", "—")
    if "fidelity_pct" in trk:
        k3.metric("Avg fidelity", f"{trk['fidelity_pct'].mean():.0f}%")
    else:
        k3.metric("Avg fidelity", "—")

    st.divider()

    # Fidelity trend
    if {"date", "fidelity_pct"}.issubset(trk.columns):
        base = alt.Chart(trk).encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("fidelity_pct:Q", title="Fidelity %"),
            color=alt.Color("intervention_code:N", title="Intervention") if "intervention_code" in trk.columns else alt.value("steelblue"),
            tooltip=[c for c in ["date", "intervention_code", "fidelity_pct", "notes"] if c in trk.columns],
        )
        st.altair_chart(base.mark_line(point=True).properties(height=280), use_container_width=True)
    else:
        st.caption("Not enough data to plot fidelity trend (need 'date' and 'fidelity_pct').")

    # Completions/week
    if "date" in trk.columns:
        dfw = trk.copy()
        dfw["week"] = pd.to_datetime(dfw["date"], errors="coerce").dt.to_period("W").apply(lambda x: x.start_time.date())
        agg = dfw.groupby("week", dropna=True).agg(count=("date", "size"), completed=("completed", "sum")).reset_index()
        if not agg.empty:
            bar = alt.Chart(agg).mark_bar().encode(
                x=alt.X("week:T", title="Week"),
                y=alt.Y("count:Q", title="Entries"),
                tooltip=["week:T", "count:Q", "completed:Q"],
            ).properties(height=260)
            st.altair_chart(bar, use_container_width=True)
        else:
            st.caption("No valid dates to aggregate by week.")
    else:
        st.caption("No 'date' column available to aggregate by week.")

    st.divider()
    st.subheader("Calendar heatmap — completions per day")
    if {"date","completed"}.issubset(trk.columns):
        cal = trk.copy()
        cal["date"] = pd.to_datetime(cal["date"], errors="coerce")
        daily = (
            cal.groupby("date")
               .agg(completed_per_day=("completed", "sum"),
                    entries=("date","size"))
               .reset_index()
        )
        st.altair_chart(
            alt.Chart(daily).mark_rect().encode(
                x=alt.X("date(date):O", title="Day of month"),
                y=alt.Y("month(date):O", title="Month"),
                color=alt.Color("completed_per_day:Q", title="Completed"),
                tooltip=["date:T", "completed_per_day:Q", "entries:Q"]
            ).properties(height=260),
            use_container_width=True
        )
    else:
        st.caption("Calendar heatmap: need 'date' and 'completed' columns.")

    st.divider()
    st.subheader("Intervention summary")
    need_cols = {"intervention_code","completed","fidelity_pct"}
    if need_cols.issubset(trk.columns):
        summ = (
            trk.copy()
               .assign(fidelity_pct=pd.to_numeric(trk["fidelity_pct"], errors="coerce"))
               .groupby("intervention_code", dropna=False)
               .agg(
                   entries=("intervention_code","size"),
                   completion_rate=("completed", "mean"),
                   avg_fidelity=("fidelity_pct","mean")
               )
               .reset_index()
        )
        summ["completion_rate"] = (summ["completion_rate"] * 100).round(0)
        summ["avg_fidelity"] = summ["avg_fidelity"].round(0)

        st.dataframe(
            summ.sort_values(["completion_rate","avg_fidelity","entries"], ascending=False),
            use_container_width=True, hide_index=True
        )
        st.altair_chart(
            alt.Chart(summ).mark_bar().encode(
                x=alt.X("completion_rate:Q", title="Completion rate (%)"),
                y=alt.Y("intervention_code:N", sort='-x', title="Intervention"),
                tooltip=["intervention_code","entries","completion_rate","avg_fidelity"]
            ).properties(height=280),
            use_container_width=True
        )
    else:
        st.caption("Intervention summary: need 'intervention_code', 'completed', and 'fidelity_pct'.")

    st.divider()
    st.subheader("Raw data (all-time for selected student)")
    st.dataframe(trk, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Download CSV",
        data=trk.to_csv(index=False),
        file_name=f"intervention_tracking_{student_id or 'student'}.csv",
        mime="text/csv"
    )
