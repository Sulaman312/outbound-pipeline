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
  { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
  { key: "created_at", label: "Found", render: (r) => shortDate(r.created_at) },
];

export default function Companies() {
  const icps = useLoad(api.icps);
  const [icp, setIcp] = useState("");
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const companies = useLoad(() => api.companies({ icp, search }), [icp, search]);

  function submit(e) {
    e.preventDefault();
    setSearch(typed.trim());
  }

  const data = companies.data;
  return (
    <>
      <PageHeader title="Companies">
        Companies Apollo found. Status shows where each one is: new, exported (sent to Clay),
        enriched (Clay found an email) or no_contact.
      </PageHeader>

      <Card
        aside={
          <a className="button secondary" href={api.companiesCsvUrl({ icp, search })}>
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
              search || icp
                ? "No companies match. Clear the search or pick another ICP."
                : "No companies yet. Find some on the Find companies page."
            }
          />
        </Card>
      )}
    </>
  );
}
