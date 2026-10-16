// Find companies through Apollo. Preview is free and never calls Apollo. Fetch spends credits,
// and only after you tick "Spend up to N credits"; the tick clears itself after every run.
import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Card, Loading, Notice, PageHeader, SegmentSelect } from "../components.jsx";
import { useLoad } from "../useLoad.js";

export default function FindCompanies() {
  const segments = useLoad(api.segments);
  const [segment, setSegment] = useState("");
  const [pages, setPages] = useState(1);
  const [preview, setPreview] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [run, setRun] = useState(null);

  const list = segments.data || [];
  const chosen = list.find((s) => s.key === segment);

  useEffect(() => {
    if (!segment && list.length) setSegment(list[0].key);
  }, [list, segment]);

  useEffect(() => {
    // A changed choice needs a new preview and a new tick.
    setPreview(null);
    setConfirmed(false);
  }, [segment, pages]);

  async function doPreview() {
    setError(null);
    try {
      setPreview(await api.previewSource(segment, Number(pages)));
    } catch (e) {
      setError(e.message);
    }
  }

  async function doRun() {
    setBusy(true);
    setError(null);
    try {
      setRun(await api.runSource(segment, Number(pages), preview.credits));
      segments.reload();
    } catch (e) {
      setError(e.message);
    } finally {
      setConfirmed(false);
      setBusy(false);
      setPreview(await api.previewSource(segment, Number(pages)).catch(() => null));
    }
  }

  if (segments.error) return <Notice kind="error">{segments.error}</Notice>;
  if (!segments.data) return <Loading />;

  return (
    <>
      <PageHeader title="Find companies">
        Ask Apollo for companies that match a segment. 1 credit per page of up to 100 companies.
      </PageHeader>

      <Card title="What to search for">
        <div className="form-row">
          <label>
            Segment
            <SegmentSelect segments={list} value={segment} onChange={setSegment} />
          </label>
          <label className="narrow">
            Pages
            <input type="number" min="1" max="50" value={pages} onChange={(e) => setPages(e.target.value)} />
          </label>
          <button type="button" className="secondary" onClick={doPreview} disabled={!segment}>
            Preview (free)
          </button>
        </div>
        {chosen && (
          <p className="muted">
            {chosen.description}. {chosen.saved} saved so far, {chosen.waiting_for_clay} waiting for Clay.
          </p>
        )}
      </Card>

      {error && <Notice kind="error">{error}</Notice>}

      {preview && (
        <Card title="Preview">
          <pre className="output">{preview.text}</pre>
          {preview.problem ? (
            <Notice kind="warn" title="Can't fetch yet">{preview.problem}</Notice>
          ) : (
            <div className="confirm">
              <label className="check">
                <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                Spend up to {preview.credits} Apollo credit{preview.credits === 1 ? "" : "s"}
              </label>
              <button type="button" onClick={doRun} disabled={!confirmed || busy}>
                {busy ? "Fetching…" : "Fetch companies"}
              </button>
            </div>
          )}
        </Card>
      )}

      {run && (
        <Card title="Last run">
          <Notice kind={run.result.error ? "error" : "success"}>
            {run.result.error
              ? "Apollo returned an error. What was fetched before it is saved."
              : `Saved ${run.result.saved} new companies.`}
          </Notice>
          <pre className="output">{run.summary}</pre>
        </Card>
      )}
    </>
  );
}
