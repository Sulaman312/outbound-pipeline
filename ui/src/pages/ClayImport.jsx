// Step 3: upload Clay's CSV, check which column is which (pre-filled), import, see the result.
import { useState } from "react";
import { api } from "../api.js";
import { Card, Notice, Stat } from "../components.jsx";

export default function ClayImport({ onDone }) {
  const [file, setFile] = useState(null);
  const [columns, setColumns] = useState(null);
  const [mapping, setMapping] = useState({});
  const [account, setAccount] = useState("");
  const [credits, setCredits] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  async function choose(e) {
    const picked = e.target.files[0];
    setFile(picked || null);
    setColumns(null);
    setResult(null);
    setError(null);
    if (!picked) return;
    try {
      const found = await api.clayColumns(picked);
      setColumns(found);
      setMapping(found.mapping);
    } catch (err) {
      setError(err.message);
    }
  }

  async function doImport() {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.clayImport(file, mapping, account.trim(), credits));
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const missingEmail = columns && !mapping.email;
  const missingCompany = columns && !mapping.company_id && !mapping.domain;

  return (
    <Card step="3" title="Upload Clay's CSV">
      <div className="form-row">
        <label className="grow">
          The CSV you downloaded from Clay
          <input type="file" accept=".csv,text/csv" onChange={choose} />
        </label>
      </div>
      {error && <Notice kind="error">{error}</Notice>}

      {columns && (
        <>
          <p className="muted">
            {columns.rows} rows. We matched the columns below; check them and fix any that are wrong.
          </p>
          <div className="mapping">
            {columns.fields.map((f) => (
              <label key={f.key}>
                {f.label}
                <select value={mapping[f.key] || ""} onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value || null })}>
                  <option value="">(not in the file)</option>
                  {columns.headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <div className="form-row">
            <label>
              Clay account (optional)
              <input value={account} onChange={(e) => setAccount(e.target.value)} placeholder="clay-1" />
            </label>
            <label className="narrow">
              Credits used (optional)
              <input type="number" min="0" step="any" value={credits} onChange={(e) => setCredits(e.target.value)} />
            </label>
            <button type="button" onClick={doImport} disabled={busy || missingEmail || missingCompany}>
              {busy ? "Importing…" : "Import"}
            </button>
          </div>
          {(missingEmail || missingCompany) && (
            <Notice kind="warn">
              Choose a column for {missingEmail ? "Email" : "Our company_id or Company domain"} before importing.
            </Notice>
          )}
        </>
      )}

      {result && <ImportResult result={result.result} summary={result.summary} />}
    </Card>
  );
}

function ImportResult({ result, summary }) {
  const s = result.states;
  return (
    <>
      <Notice kind="success" title="Imported">
        {result.saved} new leads saved from {result.rows} rows.
        {result.unmatched > 0 && ` ${result.unmatched} rows didn't match any of our companies.`}
        {result.duplicate > 0 && ` ${result.duplicate} were already saved.`}
      </Notice>
      <div className="stats">
        <Stat label="verified" value={s.verified || 0} hint="Clay says valid" />
        <Stat label="needs_check" value={s.needs_check || 0} hint="re-checked later" />
        <Stat label="hold" value={s.hold || 0} hint="info@-style" />
        <Stat label="dropped" value={s.dropped || 0} hint="no email or invalid" />
      </div>
      <details>
        <summary>Full report</summary>
        <pre className="output">{summary}</pre>
      </details>
    </>
  );
}
