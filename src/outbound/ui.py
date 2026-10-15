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
from outbound.steps import clay, export, source, suppress

ROOT_ENV = "OUTBOUND_ROOT"  # set by `outbound ui`; the project folder
ALL_SEGMENTS = "All segments"
DECISIONS = ("ready", "maybe", "hold", "drop")
NONE = "(none)"


def _apollo_cap(settings: Settings) -> int | None:
    return settings.caps.get("apollo", {}).get("credits")


def overview_tab(
    conn: sqlite3.Connection, settings: Settings, segments: dict[str, Segment]
) -> None:
    cap = _apollo_cap(settings)
    used = db.usage_this_month(conn, source.PROVIDER, source.UNIT)
    saved = db.count_companies(conn)

    credits, companies, ready, blocked = st.columns(4)
    credits.metric(
        f"Apollo credits used ({db.current_month()})",
        f"{used} / {cap}" if cap is not None else f"{used} (no cap set)",
    )
    companies.metric("Companies saved", sum(saved.values()))
    ready.metric("Contacts ready", db.count_contacts(conn).get("ready", 0))
    blocked.metric("Do-not-contact entries", db.count_suppression(conn))

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


def clay_tab(conn: sqlite3.Connection, settings: Settings, segments: dict[str, Segment]) -> None:
    st.subheader("1. Send companies to Clay")
    choice = st.selectbox("Segment", [ALL_SEGMENTS, *sorted(segments)], key="clay_segment")
    segment = None if choice == ALL_SEGMENTS else choice
    rows = int(
        st.number_input(
            "Companies per file (200 on Clay Free, 50 on a Clay trial)",
            min_value=1,
            max_value=1000,
            value=clay.DEFAULT_ROWS,
            key="clay_rows",
        )
    )
    waiting = db.count_waiting_for_clay(conn, segment)
    st.caption(f"{waiting} companies waiting for Clay. Each company is only ever sent once.")
    if st.button("Create the Clay file", disabled=waiting == 0, key="clay_export"):
        result = clay.export_batch(conn, settings.root, segment, rows)
        st.session_state["clay_file"] = str(result.path) if result else None
        st.rerun()
    path = Path(st.session_state.get("clay_file") or "")
    if path.is_file():
        st.success(
            f"{path.name} is ready. Upload it to a Clay table (steps in docs/clay-table.md)."
        )
        st.download_button(
            "Download the Clay file",
            data=path.read_bytes(),
            file_name=path.name,
            mime="text/csv",
            key="clay_download",
        )

    st.subheader("2. Bring Clay's results back")
    upload = st.file_uploader("The CSV you downloaded from Clay", type="csv", key="clay_upload")
    if upload is not None:
        headers, people = clay.read_csv(upload.getvalue().decode("utf-8-sig", errors="replace"))
        detected = clay.detect_columns(headers)
        st.caption(f"{len(people)} rows. Check which Clay column holds what:")
        options = [NONE, *headers]
        mapping: dict[str, str | None] = {}
        columns = st.columns(2)
        for i, (name, (label, _)) in enumerate(clay.FIELDS.items()):
            found = detected.get(name)
            pick = columns[i % 2].selectbox(
                label, options, index=options.index(found) if found else 0, key=f"map_{name}"
            )
            mapping[name] = None if pick == NONE else pick
        missing = clay.missing_fields(mapping)
        if missing:
            st.warning("Still needed: " + ", ".join(missing))
        account = st.text_input("Which Clay account ran it (optional)", key="clay_account")
        used_credits = st.number_input(
            "Clay credits this batch used (optional)", min_value=0.0, value=0.0, key="clay_credits"
        )
        if st.button("Import", type="primary", disabled=bool(missing), key="clay_import"):
            credits = used_credits or None
            result = clay.import_rows(
                conn, people, mapping, account=account.strip() or None, credits=credits
            )
            st.session_state["last_import"] = clay.describe_import(conn, result, credits)
            st.rerun()
    if "last_import" in st.session_state:
        st.success("Import finished. Importing the same file again is safe: repeats are skipped.")
        st.code(st.session_state["last_import"], language=None)

    st.subheader("Batches")
    batches = [
        {key: row[key] for key in row.keys() if key != "file"} for row in db.list_batches(conn)
    ]
    st.dataframe(batches, hide_index=True, width="stretch")


def contacts_tab(conn: sqlite3.Connection) -> None:
    counts = db.count_contacts(conn)
    for column, decision in zip(st.columns(4), DECISIONS, strict=True):
        column.metric(decision, counts.get(decision, 0))
    st.caption(
        "ready: Clay says valid. maybe: re-checked with Instantly at the next step. "
        "hold: waiting on a decision. drop: never sent."
    )
    choice = st.selectbox("Show", ["All", *DECISIONS], key="contacts_decision")
    rows = export.contact_rows(conn, None if choice == "All" else choice)
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={"linkedin_url": st.column_config.LinkColumn("LinkedIn")},
    )
    st.download_button(
        "Download CSV",
        data=export.csv_text(rows, export.CONTACT_COLUMNS).encode("utf-8-sig"),
        file_name="contacts.csv",
        mime="text/csv",
        key="contacts_download",
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
        overview, find, companies, clay_page, contacts, do_not_contact = st.tabs(
            ["Overview", "Find companies", "Companies", "Clay", "Contacts", "Do-not-contact"]
        )
        with overview:
            overview_tab(conn, settings, segments)
        with find:
            find_tab(conn, settings, segments)
        with companies:
            companies_tab(conn, segments)
        with clay_page:
            clay_tab(conn, settings, segments)
        with contacts:
            contacts_tab(conn)
        with do_not_contact:
            do_not_contact_tab(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
