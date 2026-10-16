// Find companies for an ICP from one or more sources. Preview is free and never calls a source.
// Fetch spends credits, and only after you tick "Spend up to N credits"; the tick clears itself
// after every run.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Card, IcpSelect, Loading, Notice, PageHeader } from "../components.jsx";
import { useLoad } from "../useLoad.js";

export default function FindCompanies() {
  const icps = useLoad(api.icps);
  const sources = useLoad(api.sources);
  const [icp, setIcp] = useState("");
  const [chosen, setChosen] = useState(["apollo"]);
  const [pages, setPages] = useState(1);
  const [preview, setPreview] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [runs, setRuns] = useState(null);

  const active = (icps.data || []).filter((i) => i.active);
  const picked = active.find((i) => i.key === icp);

  useEffect(() => {
    if (!icp && active.length) setIcp(active[0].key);
  }, [active, icp]);

  useEffect(() => {
    // A changed choice needs a new preview and a new tick.
    setPreview(null);
    setConfirmed(false);
  }, [icp, chosen, pages]);

  function toggleSource(key) {
    setChosen(chosen.includes(key) ? chosen.filter((k) => k !== key) : [...chosen, key]);
  }

  async function doPreview() {
    setError(null);
    try {
      setPreview(await api.previewSource(icp, chosen, Number(pages)));
    } catch (e) {
      setError(e.message);
    }
  }

  async function doRun() {
    setBusy(true);
    setError(null);
    try {
      setRuns((await api.runSource(icp, chosen, Number(pages), preview.credits)).runs);
      icps.reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setConfirmed(false);
      setBusy(false);
      setPreview(await api.previewSource(icp, chosen, Number(pages)).catch(() => null));
    }
  }

  if (icps.error || sources.error) return <Notice kind="error">{icps.error || sources.error}</Notice>;
  if (!icps.data || !sources.data) return <Loading />;

  const blocked = preview && preview.previews.some((p) => p.problem);

  return (
    <>
      <PageHeader title="Find companies">
        Pick an ICP and where to look. Every company goes into the same list, once: if another ICP
        already saved it, it&apos;s skipped. So run an ICP with a hiring signal before its twin without.
      </PageHeader>

      <Card title="What to search for">
        <div className="form-row">
          <label>
            ICP
            <IcpSelect icps={icps.data} value={icp} onChange={setIcp} activeOnly />
          </label>
          <label className="narrow">
            Pages per source
            <input type="number" min="1" max="50" value={pages} onChange={(e) => setPages(e.target.value)} />
          </label>
        </div>
        <div className="sources">
          {sources.data.map((s) => (
            <label key={s.key} className="check">
              <input type="checkbox" checked={chosen.includes(s.key)} disabled={!s.built} onChange={() => toggleSource(s.key)} />
              {s.label} <span className="muted small">{s.built ? s.cost : "not built yet (M1b)"}</span>
            </label>
          ))}
        </div>
        {picked && (
          <p className="muted">
            {(picked.description || picked.name).replace(/\.$/, "")}. {picked.saved} companies saved so far,{" "}
            {picked.waiting_for_clay} waiting for Clay.
          </p>
        )}
        <button type="button" className="secondary" onClick={doPreview} disabled={!icp || !chosen.length}>
          Preview (free)
        </button>
      </Card>

      {error && <Notice kind="error">{error}</Notice>}

      {preview && (
        <Card title="Preview">
          {preview.previews.map((p) => (
            <div key={p.source}>
              <h3 className="sub">{p.label}</h3>
              <pre className="output">{p.text}</pre>
              {p.problem && <Notice kind="warn" title={`${p.label} can't run yet`}>{p.problem}</Notice>}
            </div>
          ))}
          {!blocked && (
            <div className="confirm">
              <label className="check">
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                Spend up to {preview.credits} credit{preview.credits === 1 ? "" : "s"}
              </label>
              <button type="button" onClick={doRun} disabled={!confirmed || busy}>
                {busy ? "Fetching…" : "Fetch companies"}
              </button>
            </div>
          )}
        </Card>
      )}

      {runs && (
        <Card title="Last run">
          {runs.map((r) => (
            <div key={r.source}>
              <Notice kind={r.result.error ? "error" : "success"} title={r.label}>
                {r.result.error
                  ? "Returned an error. What was fetched before it is saved."
                  : `Saved ${r.result.saved} new companies.`}
                {r.result.total_entries != null &&
                  ` ${r.label} reports about ${r.result.total_entries.toLocaleString()} matching companies.`}
              </Notice>
              <pre className="output">{r.summary}</pre>
            </div>
          ))}
        </Card>
      )}
    </>
  );
}
