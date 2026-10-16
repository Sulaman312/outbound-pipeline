// People Clay found, filtered by lead state, with a CSV download.
import { useState } from "react";
import { api } from "../api.js";
import { Badge, Card, DataTable, Loading, Notice, PageHeader, shortDate } from "../components.jsx";
import { useLoad } from "../useLoad.js";

const MEANING = {
  verified: "Clay says the email is valid. Ready for the next steps.",
  needs_check: "Catch-all or unknown. Re-checked with Instantly's verifier before sending (M3).",
  hold: "Role addresses like info@. Waiting on decision D5.",
  dropped: "No email, invalid, or do-not-contact. Never sent.",
};

const COLUMNS = [
  { key: "email", label: "Email" },
  { key: "name", label: "Name", render: (r) => `${r.first_name} ${r.last_name}`.trim() },
  { key: "title", label: "Title" },
  { key: "company_name", label: "Company", render: (r) => r.company_name || r.company_domain },
  { key: "icp", label: "ICP" },
  { key: "state", label: "State", render: (r) => <Badge value={r.state} /> },
  { key: "state_reason", label: "Why", wrap: true },
  { key: "created_at", label: "Added", render: (r) => shortDate(r.created_at) },
];

export default function Leads() {
  const [state, setState] = useState("");
  const leads = useLoad(() => api.leads(state), [state]);
  const data = leads.data;
  const counts = data ? data.counts : {};
  const shownStates = data ? data.states.filter((s) => counts[s] || MEANING[s]) : [];

  return (
    <>
      <PageHeader title="Leads">People Clay found, and what happens to each one next.</PageHeader>

      <Card
        title="Filter by state"
        aside={
          <a className="button secondary" href={api.leadsCsvUrl(state)}>
            Download CSV
          </a>
        }
      >
        <div className="chips">
          <button type="button" className={state === "" ? "chip active" : "chip"} onClick={() => setState("")}>
            All <span>{Object.values(counts).reduce((a, b) => a + b, 0)}</span>
          </button>
          {shownStates.map((s) => (
            <button key={s} type="button" className={state === s ? "chip active" : "chip"} onClick={() => setState(s)}>
              {s} <span>{counts[s] || 0}</span>
            </button>
          ))}
        </div>
        {MEANING[state] && <p className="muted">{MEANING[state]}</p>}
      </Card>

      {leads.error && <Notice kind="error">{leads.error}</Notice>}
      {!data && !leads.error && <Loading />}
      {data && (
        <Card>
          {data.total !== data.shown && (
            <p className="muted">Showing the first {data.shown} of {data.total}. The CSV has all of them.</p>
          )}
          <DataTable
            columns={COLUMNS}
            rows={data.rows}
            rowKey={(r) => r.email || `${r.company_domain}-${r.created_at}-${r.first_name}`}
            empty={state ? `No leads are ${state}.` : "No leads yet. Import Clay's results on the Enrich with Clay page."}
          />
        </Card>
      )}
    </>
  );
}
