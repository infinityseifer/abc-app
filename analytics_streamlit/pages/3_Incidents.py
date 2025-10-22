# analytics_streamlit/pages/1_Incidents.py
import pandas as pd
import requests
import streamlit as st
from io import BytesIO
from pathlib import Path
import html

# ---------- ASCII sanitizer for core (non-Unicode) PDF fonts ----------
_SANITIZE_MAP = {
    "—": "-", "–": "-", "•": "*", "·": "-",
    "“": '"', "”": '"', "‘": "'", "’": "'",
    "≥": ">=", "≤": "<=", "…": "...",
    "\u00a0": " ",  # non-breaking space
}
def sanitize(s: str) -> str:
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    for k, v in _SANITIZE_MAP.items():
        s = s.replace(k, v)
    # ensure Latin-1 in case fpdf core fonts are used
    return s.encode("latin-1", "replace").decode("latin-1")


def _find_ttf_font() -> str | None:
    """Try to find a Unicode TTF on Windows (or add your bundled font path)."""
    candidates = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\verdana.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        # Example if you ship a font with the app:
        # str(Path(__file__).with_name("DejaVuSans.ttf")),
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


# ================= PDF backend (fpdf2 preferred, reportlab fallback) =================
_PDF_BACKEND = None
_PDF_ERR = ""

try:
    from fpdf import FPDF  # pure-Python, very compatible
    _PDF_BACKEND = "fpdf2"
except Exception as e:
    _PDF_ERR = f"fpdf2 not available ({e})"
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        import textwrap
        _PDF_BACKEND = "reportlab"
    except Exception as e2:
        _PDF_ERR += f"; reportlab not available ({e2})"
        _PDF_BACKEND = None


def make_narratives_pdf(df: pd.DataFrame, student_label: str) -> bytes:
    """
    df should include 'date', optional 'time', and 'notes'.
    Returns PDF bytes of bordered, no-fill narrative cards (wrapped).
    """
    use = df.copy()
    for c in ("date", "time", "notes"):
        if c not in use.columns:
            use[c] = None

    if _PDF_BACKEND == "fpdf2":
        pdf = FPDF(orientation="P", unit="pt", format="Letter")
        pdf.set_margins(left=36, top=36, right=36)
        pdf.set_auto_page_break(auto=True, margin=36)
        pdf.add_page()

        # Font selection
        font_path = _find_ttf_font()
        if font_path:
            pdf.add_font("UFont", "", font_path, uni=True)
            pdf.add_font("UFont", "B", font_path, uni=True)
            body_family, body_style = "UFont", ""
            bold_family, bold_style = "UFont", "B"
            def sanitize_text(s: str) -> str:  # no-op when Unicode font
                return "" if s is None else str(s)
        else:
            body_family, body_style = "Helvetica", ""
            bold_family, bold_style = "Helvetica", "B"
            def sanitize_text(s: str) -> str:
                return sanitize(s)

        # Measurements
        pad_x, pad_y = 10, 10
        title_h, line_h, spacer = 14, 14, 6
        max_w = pdf.w - pdf.l_margin - pdf.r_margin
        inner_w = max_w - 2 * pad_x

        # Word wrap w/ fallback for very long tokens
        def _hard_wrap_line(s: str, set_font=True) -> list[str]:
            if set_font:
                pdf.set_font(body_family, body_style, 11)
            s = s or ""
            out, cur = [], ""
            for ch in s:
                trial = cur + ch
                if pdf.get_string_width(trial) <= inner_w or not cur:
                    cur = trial
                else:
                    out.append(cur)
                    cur = ch
            out.append(cur)
            return out

        def _wrap_paragraph(text: str, is_title=False) -> list[str]:
            family, style, size = (bold_family, bold_style, 11) if is_title else (body_family, body_style, 11)
            pdf.set_font(family, style, size)
            text = text or " "
            out = []
            for raw_line in text.splitlines() or [" "]:
                words, cur = raw_line.split(" "), ""
                for w in words:
                    trial = (cur + " " + w).strip()
                    if cur and pdf.get_string_width(trial) > inner_w:
                        if pdf.get_string_width(w) > inner_w:
                            out.extend(_hard_wrap_line(w, set_font=False))
                            cur = ""
                        else:
                            out.append(cur)
                            cur = w
                    else:
                        cur = trial
                if cur:
                    if pdf.get_string_width(cur) > inner_w:
                        out.extend(_hard_wrap_line(cur, set_font=False))
                    else:
                        out.append(cur)
            return out

        # Header
        pdf.set_font(bold_family, bold_style, 14)
        for ln in _wrap_paragraph(sanitize_text(f"Narratives — {student_label}"), is_title=True):
            pdf.cell(0, 18, ln, ln=1)

        pdf.set_font(body_family, body_style, 10)
        pdf.cell(0, 14, "Exported from ABC App", ln=1)
        y = pdf.get_y()
        pdf.set_draw_color(220, 220, 220)
        pdf.line(pdf.l_margin, y + 4, pdf.w - pdf.r_margin, y + 4)
        pdf.ln(10)

        # Card renderer
        pdf.set_draw_color(220, 220, 220)
        pdf.set_line_width(0.8)

        for _, r in use.iterrows():
            d = str(r.get("date") or "").strip()
            t = str(r.get("time") or "").strip()
            title_txt = sanitize_text((f"{d} {t}".strip() or "—"))
            body_txt  = sanitize_text((str(r.get("notes") or "").strip() or " "))

            # Wrap text to measure height
            t_lines = _wrap_paragraph(title_txt, is_title=True)
            b_lines = _wrap_paragraph(body_txt, is_title=False)
            content_h = (len(t_lines) or 1) * title_h + spacer + (len(b_lines) or 1) * line_h
            card_h = pad_y*2 + content_h

            # Page break if needed
            if pdf.get_y() + card_h > (pdf.h - pdf.b_margin):
                pdf.add_page()

            # Draw border
            x0, y0 = pdf.l_margin, pdf.get_y()
            pdf.rect(x0, y0, max_w, card_h)

            # Title inside card
            pdf.set_xy(x0 + pad_x, y0 + pad_y)
            pdf.set_font(bold_family, bold_style, 11)
            for ln in t_lines:
                pdf.multi_cell(inner_w, title_h, ln)
                pdf.set_x(x0 + pad_x)  # keep inside border

            # Spacer
            pdf.ln(spacer)
            pdf.set_x(x0 + pad_x)

            # Body inside card
            pdf.set_font(body_family, body_style, 11)
            for ln in b_lines:
                pdf.multi_cell(inner_w, line_h, ln)
                pdf.set_x(x0 + pad_x)  # keep inside border

            # Move below card
            pdf.set_y(y0 + card_h + 8)

        out = pdf.output(dest="S")
        return out.encode("latin-1", "replace") if isinstance(out, str) else bytes(out)

    elif _PDF_BACKEND == "reportlab":
        from reportlab.lib.pagesizes import letter  # type: ignore
        from reportlab.pdfgen import canvas        # type: ignore
        import textwrap                             # type: ignore

        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        width, height = letter
        left, right, top, bottom = 36, 36, height - 36, 36
        y = top
        inner_w = width - left - right
        pad_x, pad_y = 8, 8
        title_h, line_h, spacer = 14, 14, 6

        def draw_paragraph(text: str, size=11):
            nonlocal y
            text = text or " "
            for line in text.splitlines() or [" "]:
                wrapped = textwrap.wrap(line, width=max(int(inner_w/6.5), 20)) or [" "]
                for ln in wrapped:
                    if y - line_h < bottom:
                        c.showPage(); y = top
                        c.setFont("Helvetica", size)
                    c.drawString(left + pad_x, y, ln)
                    y -= line_h

        # Header
        c.setFont("Helvetica-Bold", 14)
        c.drawString(left, y, f"Narratives - {student_label}")
        y -= 18
        c.setFont("Helvetica", 10)
        c.drawString(left, y, "Exported from ABC App")
        y -= 10
        c.line(left, y, width - right, y)
        y -= 10

        # Cards
        for _, r in use.iterrows():
            d = str(r.get("date") or "").strip()
            t = str(r.get("time") or "").strip()
            title_txt = (f"{d} {t}".strip() or "-")
            body_txt  = (str(r.get("notes") or "").strip() or " ")

            # Rough height estimate
            t_wrapped = textwrap.wrap(title_txt, width=max(int(inner_w/7.0), 20)) or [" "]
            b_wrapped = textwrap.wrap(body_txt,  width=max(int(inner_w/7.0), 20)) or [" "]
            content_h = len(t_wrapped)*title_h + spacer + len(b_wrapped)*line_h
            card_h = pad_y*2 + content_h

            if y - card_h < bottom:
                c.showPage(); y = top

            # Border
            c.roundRect(left, y - card_h, inner_w + 2*pad_x, card_h, 6, stroke=1, fill=0)

            # Title
            c.setFont("Helvetica-Bold", 11)
            ty = y - pad_y - title_h
            c.drawString(left + pad_x, y - pad_y - title_h + (title_h - 11), "")  # ensure font set
            y_cursor = y - pad_y
            c.setFont("Helvetica-Bold", 11)
            y_line = y_cursor - title_h
            for ln in t_wrapped:
                c.drawString(left + pad_x, y_line, ln)
                y_line -= title_h
            y_line -= spacer

            # Body
            c.setFont("Helvetica", 11)
            for ln in b_wrapped:
                c.drawString(left + pad_x, y_line, ln)
                y_line -= line_h

            y = y - card_h - 8  # gap below

        c.showPage()
        c.save()
        return buf.getvalue()

    else:
        raise RuntimeError(
            "PDF export unavailable. Install `fpdf2` (recommended) or `reportlab`) and restart the app.\n"
            f"Details: {_PDF_ERR}"
        )


# =========================== Page setup ===========================
st.set_page_config(page_title="Incidents Table", layout="wide")
st.title("📋 Incidents Table")

# Optional: big button to open your Apps Script form
form_url = st.secrets.get("form_url")
if form_url:
    st.link_button("📝 Open ABC Incident Form", form_url, type="primary", use_container_width=True)

# Make toolbar buttons bigger
st.markdown("""
<style>
div.stButton > button {padding: 0.9rem 1.2rem; font-size: 1.05rem; border-radius: 12px;}
</style>
""", unsafe_allow_html=True)

# =========================== Data loader ===========================
@st.cache_data(ttl=60)
def load_incidents() -> pd.DataFrame:
    base = st.secrets["api"]["url"]
    token = st.secrets["api"]["token"]
    r = requests.get(base, params={"mode": "json", "token": token}, timeout=15)

    if r.status_code != 200:
        raise RuntimeError(f"API {r.status_code}. Snippet: {r.text[:300]}")

    payload = r.json()
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

    preferred = [
        "timestamp_ct", "date", "time", "student_id", "location",
        "antecedent", "behavior", "consequence", "duration_sec",
        "intensity", "notes", "staff", "incident_id"
    ]
    cols = [c for c in preferred if c in df.columns] + [c for c in df.columns if c not in preferred]
    return df.loc[:, cols] if len(df) else df


# Load incidents
try:
    df = load_incidents()
except Exception as e:
    st.error(f"Failed to load incidents.\n\n{e}")
    st.stop()

if df.empty:
    st.info("No incidents yet. Submit via the form above.")
    st.stop()

# Session defaults
st.session_state.setdefault("show_filters", True)
st.session_state.setdefault("show_sort", False)
st.session_state.setdefault(
    "sort_by",
    "timestamp_ct" if "timestamp_ct" in df.columns else ("timestamp_utc" if "timestamp_utc" in df.columns else None)
)
st.session_state.setdefault("sort_dir", "desc")  # 'asc' or 'desc'

# ================================ Tabs ================================
tab_table, tab_notes = st.tabs(["📑 Table", "📝 Narratives / Notes"])

# =============================== Table Tab ===============================
with tab_table:
    # Toolbar
    tb1, tb2, _ = st.columns([1, 1, 4])
    with tb1:
        if st.button("🔎 Filters", use_container_width=True):
            st.session_state.show_filters = not st.session_state.show_filters
    with tb2:
        if st.button("↕️ Sort", use_container_width=True):
            st.session_state.show_sort = not st.session_state.show_sort

    def render_filters(df_in: pd.DataFrame) -> pd.DataFrame:
        with st.container(border=True):
            st.markdown("**Filters**")
            c1, c2, c3, c4 = st.columns([1, 1, 1, 1.2])

            student = c1.selectbox("Student", ["All"] + sorted(df_in["student_id"].dropna().astype(str).unique().tolist())) if "student_id" in df_in else "All"
            behavior = c2.selectbox("Behavior", ["All"] + sorted(df_in["behavior"].dropna().astype(str).unique().tolist())) if "behavior" in df_in else "All"
            location = c3.selectbox("Location", ["All"] + sorted(df_in["location"].dropna().astype(str).unique().tolist())) if "location" in df_in else "All"
            date_range = c4.date_input("Date range", value=())

            c5, c6 = st.columns([1, 2])
            intensity_min = c5.slider("Min intensity", 1, 5, 1) if "intensity" in df_in else 1
            search = c6.text_input("Search notes/staff", placeholder="type to filter…")

            mask = pd.Series(True, index=df_in.index)
            if "student_id" in df_in and student != "All":
                mask &= df_in["student_id"].astype(str).eq(student)
            if "behavior" in df_in and behavior != "All":
                mask &= df_in["behavior"].astype(str).eq(behavior)
            if "location" in df_in and location != "All":
                mask &= df_in["location"].astype(str).eq(location)
            if "date" in df_in and isinstance(date_range, (list, tuple)) and len(date_range) == 2:
                start, end = date_range
                if pd.notna(start) and pd.notna(end):
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

            bc1, bc2, _ = st.columns([1, 1, 6])
            if bc1.button("Clear filters"):
                st.rerun()
            if bc2.button("Refresh data"):
                load_incidents.clear()
                st.rerun()

        return df_in.loc[mask].copy()

    def render_sort_controls(df_in: pd.DataFrame):
        with st.container(border=True):
            st.markdown("**Sort**")
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
            dir_choice = col2.radio("Direction", ["Descending", "Ascending"], horizontal=True, index=(0 if dir_label == "Descending" else 1), key="sort_dir_radio")

            if col3.button("Apply sort", type="primary"):
                st.session_state.sort_by = sel
                st.session_state.sort_dir = "asc" if dir_choice == "Ascending" else "desc"
                st.rerun()

    fdf = render_filters(df) if st.session_state.show_filters else df.copy()
    if st.session_state.show_sort:
        render_sort_controls(fdf)

    sort_by = st.session_state.sort_by
    ascending = (st.session_state.sort_dir == "asc")
    if sort_by and sort_by in fdf.columns:
        try:
            fdf = fdf.sort_values(sort_by, ascending=ascending, kind="mergesort")
        except Exception:
            pass

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Incidents", f"{len(fdf):,}")
    k2.metric("Avg duration (s)", f"{fdf['duration_sec'].mean():.0f}" if "duration_sec" in fdf and len(fdf) else "—")
    k3.metric("Median intensity", f"{fdf['intensity'].median():.0f}" if "intensity" in fdf and len(fdf) else "—")
    k4.metric("Days in range", f"{fdf['date'].nunique():,}" if "date" in fdf and len(fdf) else "—")

    st.divider()

    # Table
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

    if sort_by:
        st.caption(f"Sorted by **{sort_by}** ({'ascending' if ascending else 'descending'})")

    st.dataframe(fdf, use_container_width=True, hide_index=True, column_config=column_config)

    csv = fdf.to_csv(index=False)
    st.download_button("⬇️ Download filtered CSV", data=csv, file_name="abc_incidents_filtered.csv", mime="text/csv")


# =========================== Narratives / Notes Tab ===========================
# Lightweight card styles for the on-screen feed (border only, no fill)
st.markdown("""
<style>
.note-card{
  border:1px solid #e5e7eb;        /* light gray border */
  border-radius:12px;               /* rounded corners */
  padding:14px 16px;                /* inner padding */
  margin:10px 0;                    /* gap between cards */
  background:transparent;           /* no fill */
  box-shadow:none;                  /* no shadow bubble */
}
.note-head{ display:flex; gap:.5rem; align-items:center; margin-bottom:.3rem; font-weight:600; color:#333; }
.note-badge{ font-size:.80rem; padding:.15rem .5rem; border-radius:999px; background:transparent; color:#FFFFE0; border:1px solid #e5e7eb; } /* outline badge, dark text */
.note-meta{ color:#666; font-size:.86rem; }
.note-body{ margin-top:.4rem; line-height:1.45; white-space:pre-wrap; }
</style>
""", unsafe_allow_html=True)

with tab_notes:
    st.subheader("Narratives / Notes by student")

    if "notes" not in df.columns:
        st.info("No **notes** column found in the dataset.")
        st.stop()

    # Student picker
    stu_options = sorted(df["student_id"].dropna().astype(str).unique().tolist()) if "student_id" in df else []
    if not stu_options:
        st.info("No student IDs available to filter.")
        st.stop()

    c1, c2, c3 = st.columns([2, 1.5, 1.5])
    student_pick = c1.selectbox("Student", stu_options)

    # Optional date window
    if "date" in df and not df["date"].dropna().empty:
        sub_dates = df.loc[df["student_id"].astype(str).eq(student_pick), "date"].dropna()
        if not sub_dates.empty:
            dmin, dmax = sub_dates.min(), sub_dates.max()
        else:
            dmin, dmax = df["date"].min(), df["date"].max()
        date_range = c2.date_input("Date range (optional)", value=(dmin, dmax))
    else:
        date_range = ()

    search = c3.text_input("Search text", placeholder="filter notes…")

    # Filtered subset
    ndx = df["student_id"].astype(str).eq(str(student_pick))
    if "date" in df and isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start, end = date_range
        if pd.notna(start) and pd.notna(end):
            ndx &= df["date"].between(start, end)

    ndf = df.loc[ndx].copy()

    if search:
        s = search.lower()
        ndf = ndf[ndf["notes"].astype(str).str.lower().str.contains(s, na=False)]

    # Sort newest first for display
    if "timestamp_ct" in ndf.columns:
        ndf = ndf.sort_values("timestamp_ct", ascending=False)
    elif "timestamp_utc" in ndf.columns:
        ndf = ndf.sort_values("timestamp_utc", ascending=False)
    elif "date" in ndf.columns:
        ndf = ndf.sort_values("date", ascending=False)

    st.markdown("---")

    if ndf.empty:
        st.info("No narrative notes match your filters.")
    else:
        # Top KPIs for this student
        k1, k2 = st.columns(2)
        k1.metric("Entries", f"{len(ndf):,}")
        k2.metric("Median intensity", f"{ndf['intensity'].median():.0f}" if "intensity" in ndf else "—")

        # PDF download for narratives
        pdf_cols = [c for c in ["date", "time", "notes"] if c in ndf.columns]
        try:
            if _PDF_BACKEND and not ndf.empty and pdf_cols:
                pdf_bytes = make_narratives_pdf(ndf[pdf_cols], student_pick)
                st.download_button(
                    "📄 Save Narratives as PDF",
                    data=pdf_bytes,
                    file_name=f"narratives_{student_pick}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            elif not _PDF_BACKEND:
                st.info(
                    "PDF export unavailable. Install `fpdf2` (recommended) or `reportlab` and restart the app.\n\n"
                    f"Details: {_PDF_ERR}"
                )
        except Exception as e:
            st.warning(f"PDF export failed: {e}")

        st.markdown("---")

        # Render a compact feed (cap to 200 rows)
        for _, row in ndf.head(200).iterrows():
            ts = row["timestamp_ct"] if "timestamp_ct" in row and pd.notna(row["timestamp_ct"]) else row.get("date")
            ts_str = pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M") if pd.notna(ts) else "—"
            beh   = (row.get("behavior") or "")
            loc   = (row.get("location") or "")
            staff = (row.get("staff") or "")
            notes_raw = (row.get("notes") or "").strip()

            # Escape for safe HTML, keep line breaks
            notes_safe = html.escape(notes_raw).replace("\n", "<br>")
            badge = html.escape(beh or "Narrative")
            loc_safe = html.escape(loc)
            staff_safe = html.escape(staff)

            st.markdown(
                f"""
                <div class="note-card">
                  <div class="note-head">
                    <span class="note-badge">{badge}</span>
                    <span class="note-meta">· {ts_str}{(' · ' + loc_safe) if loc else ''}{(' · ' + staff_safe) if staff else ''}</span>
                  </div>
                  <div class="note-body">{notes_safe if notes_raw else '<i>No notes</i>'}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        # Tabular view + export
        st.subheader("Narratives table")
        view_cols = [c for c in ["timestamp_ct","date","time","behavior","location","intensity","notes","staff","incident_id"] if c in ndf.columns]
        st.dataframe(ndf[view_cols], use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download narratives CSV",
            data=ndf[view_cols].to_csv(index=False),
            file_name=f"narratives_{student_pick}.csv",
            mime="text/csv"
        )
