// Find companies for an ICP from Apollo, Google Maps, or both. Preview is free and never calls a
// source. Each source has its own "Spend up to N" tick box; Fetch needs every one ticked, and the
// ticks clear after every run. Both run in order: Apollo, then Google Maps.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Card, DataTable, IcpSelect, Loading, Notice, PageHeader } from "../components.jsx";
import { useLoad } from "../useLoad.js";

const COUNTS = [
  { key: "label", label: "Source" },
  { key: "seen", label: "Found", numeric: true },
  { key: "saved", label: "Saved", numeric: true },
  { key: "no_domain", label: "No website", numeric: true },
  { key: "closed", label: "Closed", numeric: true },
  { key: "duplicate", label: "Already saved", numeric: true },
  { key: "chains", label: "Chains", numeric: true },
  { key: "suppressed", label: "Do-not-contact", numeric: true },
  { key: "credits", label: "Spent", numeric: true },
];

export default function FindCompanies() {
  const icps = useLoad(api.icps);
  const sources = useLoad(api.sources);
  const [icp, setIcp] = useState("");
  const [chosen, setChosen] = useState(["apollo"]);
  const [pages, setPages] = useState(1);
  const [preview, setPreview] = useState(null);
  const [ticks, setTicks] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [runs, setRuns] = useState(null);

  const active = (icps.data || []).filter((i) => i.active);
  const picked = active.find((i) => i.key === icp);

  useEffect(() => {
    if (!icp && active.length) setIcp(active[0].key);
  }, [active, icp]);

  useEffect(() => {
    // A changed choice needs a new preview and new ticks.
    setPreview(null);
    setTicks({});
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
    const confirm = Object.fromEntries(preview.previews.map((p) => [p.source, p.credits]));
    try {
      setRuns((await api.runSource(icp, chosen, Number(pages), confirm)).runs);
      icps.reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setTicks({});
      setBusy(false);
      setPreview(await api.previewSource(icp, chosen, Number(pages)).catch(() => null));
    }
  }

  if (icps.error || sources.error) return <Notice kind="error">{icps.error || sources.error}</Notice>;
  if (!icps.data || !sources.data) return <Loading />;

  const blocked = preview && preview.previews.some((p) => p.problem);
  const spending = preview ? preview.previews.filter((p) => p.credits > 0) : [];
  const allTicked = spending.length > 0 && spending.every((p) => ticks[p.source]);

  return (
    <>
      <PageHeader title="Find companies">
        Pick an ICP and where to look. Every company goes into the same list, once: if another ICP or
        source already saved it, it&apos;s skipped. So run an ICP with a hiring signal before its twin without.
      </PageHeader>

      <Card title="What to search for">
        <div className="form-row">
          <label>
            ICP
            <IcpSelect icps={icps.data} value={icp} onChange={setIcp} activeOnly />
          </label>
          {chosen.includes("apollo") && (
            <label className="narrow">
              Apollo pages
              <input type="number" min="1" max="50" value={pages} onChange={(e) => setPages(e.target.value)} />
            </label>
          )}
        </div>
        <div className="sources">
          {sources.data.map((s) => (
            <label key={s.key} className="check">
              <input type="checkbox" checked={chosen.includes(s.key)} disabled={!s.built} onChange={() => toggleSource(s.key)} />
              {s.label} <span className="muted small">{s.built ? s.cost : "not built yet"}</span>
            </label>
          ))}
        </div>
        {picked && (
          <p className="muted">
            {(picked.description || picked.name).replace(/\.$/, "")}. {picked.saved} companies saved so far,{" "}
            {picked.waiting_for_clay} waiting for Clay. Google Maps uses the ICP&apos;s pages per search.
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
              {!blocked && p.credits > 0 && (
                <label className="check confirm-line">
                  <input
                    type="checkbox"
                    checked={Boolean(ticks[p.source])}
                    onChange={(e) => setTicks({ ...ticks, [p.source]: e.target.checked })}
                  />
                  {p.confirm_label}
                </label>
              )}
              {!p.problem && p.credits === 0 && <Notice kind="info">Nothing left to fetch from {p.label} for this ICP.</Notice>}
            </div>
          ))}
          {!blocked && spending.length > 0 && (
            <div className="confirm">
              <button type="button" onClick={doRun} disabled={!allTicked || busy}>
                {busy ? "Fetching…" : "Fetch companies"}
              </button>
              {!allTicked && <span className="muted">Tick {spending.length > 1 ? "each box" : "the box"} above first.</span>}
            </div>
          )}
        </Card>
      )}

      {runs && (
        <Card title="Last run">
          <DataTable
            columns={COUNTS}
            rows={runs.map((r) => ({ ...r.result, label: r.label }))}
            rowKey={(r) => r.label}
            empty="Nothing ran."
          />
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
