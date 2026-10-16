// Every saved company (do-not-contact ones are left out), with search and a CSV download.
import { useState } from "react";
import { api } from "../api.js";
import { Badge, Card, DataTable, Loading, Notice, PageHeader, IcpSelect, shortDate } from "../components.jsx";
import { useLoad } from "../useLoad.js";

const COLUMNS = [
  { key: "name", label: "Company" },
  {
    key: "domain",
    label: "Website",
    render: (r) => (
      <a href={`https://${r.domain}`} target="_blank" rel="noreferrer">
        {r.domain}
      </a>
    ),
  },
  { key: "icp", label: "ICP" },
  { key: "source", label: "Source", render: (r) => <Badge value={r.source === "google_places" ? "Google Maps" : "Apollo"} tone="info" /> },
  { key: "city", label: "City", render: (r) => [r.city, r.state].filter(Boolean).join(", ") },
  {
    key: "status",
    label: "Status",
    render: (r) => (
      <>
        <Badge value={r.status} />
        {Number(r.likely_chain) === 1 && <Badge value="likely chain" tone="warn" />}
      </>
    ),
  },
  { key: "created_at", label: "Found", render: (r) => shortDate(r.created_at) },
];

export default function Companies() {
  const icps = useLoad(api.icps);
  const [icp, setIcp] = useState("");
  const [source, setSource] = useState("");
  const sources = useLoad(api.sources);
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const companies = useLoad(() => api.companies({ icp, search, source }), [icp, search, source]);

  function submit(e) {
    e.preventDefault();
    setSearch(typed.trim());
  }

  const data = companies.data;
  return (
    <>
      <PageHeader title="Companies">
        Companies found by Apollo or Google Maps. Status shows where each one is: new, exported (sent
        to Clay), enriched (Clay found an email), no_contact, or chain (a likely chain kept out of Clay).
      </PageHeader>

      <Card
        aside={
          <a className="button secondary" href={api.companiesCsvUrl({ icp, search, source })}>
            Download CSV
          </a>
        }
        title="Search"
      >
        <form className="form-row" onSubmit={submit}>
          <label>
            ICP
            <IcpSelect icps={icps.data || []} value={icp} onChange={setIcp} allLabel="All ICPs" />
          </label>
          <label>
            Source
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">All sources</option>
              {(sources.data || []).filter((s) => s.built).map((s) => (
                <option key={s.provider} value={s.provider}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grow">
            Name or website contains
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="e.g. accounting" />
          </label>
          <button type="submit">Search</button>
        </form>
      </Card>

      {companies.error && <Notice kind="error">{companies.error}</Notice>}
      {!data && !companies.error && <Loading />}
      {data && (
        <Card>
          <p className="muted">
            {data.total === data.shown
              ? `${data.total} companies`
              : `Showing the first ${data.shown} of ${data.total}. The CSV has all of them.`}
          </p>
          <DataTable
            columns={COLUMNS}
            rows={data.rows}
            rowKey={(r) => r.domain}
            empty={
              search || icp || source
                ? "No companies match. Clear the search or pick another ICP or source."
                : "No companies yet. Find some on the Find companies page."
            }
          />
        </Card>
      )}
    </>
  );
}
