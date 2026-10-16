// The Clay round trip in three numbered steps, then every batch so far.
// Step 3 (upload and import) is in ClayImport.jsx.
import { useState } from "react";
import { api } from "../api.js";
import { Card, DataTable, Notice, PageHeader, SegmentSelect, shortDate } from "../components.jsx";
import { useLoad } from "../useLoad.js";
import ClayImport from "./ClayImport.jsx";

const BATCH_COLUMNS = [
  { key: "id", label: "Batch", numeric: true },
  { key: "segment", label: "Segment", render: (b) => b.segment || "all" },
  { key: "rows", label: "Companies", numeric: true },
  { key: "exported_at", label: "File made", render: (b) => shortDate(b.exported_at) },
  { key: "imported_at", label: "Back from Clay", render: (b) => shortDate(b.imported_at) || "not yet" },
  { key: "people", label: "People", numeric: true },
  { key: "verified", label: "Verified", numeric: true },
  { key: "needs_check", label: "Needs check", numeric: true },
  { key: "hold", label: "Hold", numeric: true },
  { key: "dropped", label: "Dropped", numeric: true },
  { key: "clay_credits", label: "Credits", numeric: true },
  {
    key: "file",
    label: "",
    render: (b) => <a href={api.clayFileUrl(b.id)}>Download</a>,
  },
];

function ExportStep({ segments, waiting, onDone }) {
  const [segment, setSegment] = useState("");
  const [rows, setRows] = useState(200);
  const [busy, setBusy] = useState(false);
  const [batch, setBatch] = useState(null);
  const [error, setError] = useState(null);
  const chosen = segments.find((s) => s.key === segment);
  const count = chosen ? chosen.waiting_for_clay : waiting;

  async function create() {
    setBusy(true);
    setError(null);
    setBatch(null);
    try {
      setBatch(await api.clayExport(segment, Number(rows)));
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card step="1" title="Download the file for Clay">
      <p className="muted">
        {count} {count === 1 ? "company is" : "companies are"} waiting for Clay. Each company goes into
        one file only, even if two people do this at the same time.
      </p>
      <div className="form-row">
        <label>
          Segment
          <SegmentSelect segments={segments} value={segment} onChange={setSegment} allLabel="All segments" />
        </label>
        <label>
          Rows
          <select value={rows} onChange={(e) => setRows(e.target.value)}>
            <option value={200}>200 (Clay Free)</option>
            <option value={50}>50 (Clay trial)</option>
          </select>
        </label>
        <button type="button" onClick={create} disabled={busy || count === 0}>
          {busy ? "Creating…" : "Create the file"}
        </button>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {batch && (
        <Notice kind="success" title={`Batch ${batch.batch_id}: ${batch.rows} companies`}>
          <a className="button" href={api.clayFileUrl(batch.batch_id)}>
            Download {batch.file}
          </a>
        </Notice>
      )}
    </Card>
  );
}

function ClaySteps() {
  return (
    <Card step="2" title="What to do in Clay">
      <ol className="checklist">
        <li>In Clay: <b>Home → Import data → CSV</b>. Pick the file and create a <b>new table</b>.</li>
        <li>Switch <b>Auto-run off</b> (top left of the table) while you set it up.</li>
        <li>
          <b>Add column → Find people</b>. Company: the <code>domain</code> column. Job titles: Founder,
          Co-Founder, Owner, CEO, President. Limit: 1 person per company.
        </li>
        <li>In the people table: <b>Add column → Find work email</b>.</li>
        <li>
          <b>Add column → Validate email</b> on the work email column. With ZeroBounce or LeadMagic, turn on
          “only mark safe to send”.
        </li>
        <li>Write down your Clay credits. Run <b>5 rows</b> first, check them, then run the rest. Write down the credits again: the difference is this batch’s cost.</li>
        <li><b>Actions → Export → Download CSV</b>. You don’t need to rename columns. Then go to step 3.</li>
      </ol>
      <p className="muted">More detail: docs/clay-table.md.</p>
    </Card>
  );
}

export default function Clay() {
  const segments = useLoad(api.segments);
  const batches = useLoad(api.clayBatches);

  function refresh() {
    segments.reload();
    batches.reload();
  }

  return (
    <>
      <PageHeader title="Enrich with Clay">
        Clay finds the right person at each company and their work email. Clay Free has no API, so the
        file goes in and out by hand. Follow the three steps.
      </PageHeader>
      {segments.error && <Notice kind="error">{segments.error}</Notice>}
      <ExportStep segments={segments.data || []} waiting={batches.data ? batches.data.waiting : 0} onDone={refresh} />
      <ClaySteps />
      <ClayImport onDone={refresh} />
      <Card title="Batches">
        {batches.error && <Notice kind="error">{batches.error}</Notice>}
        {batches.data && (
          <DataTable
            columns={BATCH_COLUMNS}
            rows={batches.data.batches}
            rowKey={(b) => b.id}
            empty="No batches yet. Step 1 makes the first one."
          />
        )}
      </Card>
    </>
  );
}
