"""The local web page: the same steps as the commands, with buttons and tables.

Start it with `outbound ui`. It only listens on this computer (http://localhost:8501).
The work is done by the same step functions the commands use; this file only shows them.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import streamlit as st

from outbound import db, http
from outbound.config import (
    ConfigError,
    Segment,
    Settings,
    key_status,
    load_env,
    load_segments,
    load_settings,
)
from outbound.steps import export, source, suppress

ROOT_ENV = "OUTBOUND_ROOT"  # set by `outbound ui`; the project folder
ALL_SEGMENTS = "All segments"


def _apollo_cap(settings: Settings) -> int | None:
    return settings.caps.get("apollo", {}).get("credits")


def overview_tab(
    conn: sqlite3.Connection, settings: Settings, segments: dict[str, Segment]
) -> None:
    cap = _apollo_cap(settings)
    used = db.usage_this_month(conn, source.PROVIDER, source.UNIT)
    saved = db.count_companies(conn)

    left, middle, right = st.columns(3)
    left.metric(
        f"Apollo credits used ({db.current_month()})",
        f"{used} / {cap}" if cap is not None else f"{used} (no cap set)",
    )
    middle.metric("Companies saved", sum(saved.values()))
    right.metric("Do-not-contact entries", db.count_suppression(conn))

    for name, is_set in key_status().items():
        if not is_set:
            st.warning(f"{name} isn't set. Add it to the .env file in the project folder.")

    rows = []
    for key in sorted(segments):
        segment = segments[key]
        next_page, exhausted, total = source.start_point(conn, segment)
        rows.append(
            {
                "segment": key,
                "offer": segment.offer,
                "description": segment.description,
                "saved": saved.get(key, 0),
                "Apollo matches": "" if total is None else f"{total:,}",
                "next page": "no more" if exhausted else str(next_page),
            }
        )
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption(
        "Segments are set in config/segments.yaml. The monthly cap is in config/settings.yaml."
    )


def find_tab(conn: sqlite3.Connection, settings: Settings, segments: dict[str, Segment]) -> None:
    key = st.selectbox(
        "Segment",
        sorted(segments),
        format_func=lambda k: f"{k}  ({segments[k].description})",
        key="find_segment",
    )
    segment = segments[key]
    pages = int(
        st.number_input(
            "Pages to fetch (100 companies and 1 credit each)",
            min_value=1,
            max_value=50,
            value=1,
            key="find_pages",
        )
    )
    cap = _apollo_cap(settings)

    st.markdown("**Preview** (free, nothing is sent to Apollo)")
    st.code(source.describe(conn, segment, pages=pages, cap=cap), language=None)

    api_key = os.environ.get("APOLLO_API_KEY", "").strip()
    blocker = None
    if not api_key:
        blocker = "Add APOLLO_API_KEY to the .env file in the project folder first."
    elif cap is None:
        blocker = "Set caps.apollo.credits in config/settings.yaml first."
    if blocker:
        st.info(blocker)

    if st.session_state.pop("reset_confirm", False):
        st.session_state["find_confirm"] = False  # ask again before the next spend
    confirmed = st.checkbox(f"Spend up to {pages} Apollo credit(s)", key="find_confirm")
    if st.button(
        "Fetch from Apollo", type="primary", disabled=bool(blocker) or not confirmed, key="find_run"
    ):
        with st.spinner("Asking Apollo..."), http.new_client() as client:
            result = source.run_live(
                conn, segment, client=client, api_key=api_key, cap=cap, pages=pages
            )
        used = db.usage_this_month(conn, source.PROVIDER, source.UNIT)
        st.session_state["last_run"] = (
            result.error is None,
            source.summarize(result, used=used, cap=cap),
        )
        st.session_state["reset_confirm"] = True
        st.rerun()

    if "last_run" in st.session_state:
        ok, text = st.session_state["last_run"]
        (st.success if ok else st.error)(
            "Last run finished." if ok else "Last run stopped with an error."
        )
        st.code(text, language=None)


def companies_tab(conn: sqlite3.Connection, segments: dict[str, Segment]) -> None:
    choice = st.selectbox("Segment", [ALL_SEGMENTS, *sorted(segments)], key="companies_segment")
    search = st.text_input("Search name or domain", key="companies_search").strip().lower()
    rows = export.company_rows(conn, None if choice == ALL_SEGMENTS else choice)
    if search:
        rows = [
            r
            for r in rows
            if search in str(r["name"]).lower() or search in str(r["domain"]).lower()
        ]

    st.caption(f"{len(rows)} companies. Do-not-contact domains are left out.")
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={"linkedin_url": st.column_config.LinkColumn("LinkedIn")},
    )
    st.download_button(
        "Download CSV",
        data=export.csv_text(rows).encode("utf-8-sig"),
        file_name="companies.csv",
        mime="text/csv",
        key="companies_download",
    )


def do_not_contact_tab(conn: sqlite3.Connection) -> None:
    with st.form("suppress_form", clear_on_submit=True):
        value = st.text_input("Domain or email", placeholder="acme.com", key="suppress_value")
        reason = st.text_input("Reason", placeholder="existing client", key="suppress_reason")
        submitted = st.form_submit_button("Add to the do-not-contact list")
    if submitted:
        try:
            normalized, kind, added = suppress.suppress(conn, value, reason)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(
                f"Added {kind} {normalized}." if added else f"{normalized} was already on the list."
            )
    st.caption("Entries are never removed.")
    st.dataframe([dict(row) for row in db.list_suppression(conn)], hide_index=True, width="stretch")


def main() -> None:
    st.set_page_config(page_title="Arsuno outbound", layout="wide")
    st.title("Arsuno outbound")
    root = Path(os.environ.get(ROOT_ENV, ".")).resolve()
    load_env(root / ".env")
    try:
        settings = load_settings(root)
        segments = load_segments(root)
    except ConfigError as exc:
        st.error(f"Config error: {exc}")
        return

    conn = db.connect(settings.database)
    try:
        overview, find, companies, do_not_contact = st.tabs(
            ["Overview", "Find companies", "Companies", "Do-not-contact"]
        )
        with overview:
            overview_tab(conn, settings, segments)
        with find:
            find_tab(conn, settings, segments)
        with companies:
            companies_tab(conn, segments)
        with do_not_contact:
            do_not_contact_tab(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
