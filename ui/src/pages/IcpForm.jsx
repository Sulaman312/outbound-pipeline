// Create or edit one ICP. Lists are typed one per line. The source sections come from
// /api/sources, so a new source shows up here without changing this file.
import { useState } from "react";
import { api } from "../api.js";
import { Badge, Card, Notice, PageHeader } from "../components.jsx";

const lines = (text) => text.split("\n").map((t) => t.trim()).filter(Boolean);
const asText = (list) => (list || []).join("\n");

function toForm(icp, sources) {
  const form = {
    key: icp?.key || "",
    name: icp?.name || "",
    description: icp?.description || "",
    offer: icp?.offer || "",
    country: icp?.country || "US",
    target_leads: String(icp?.target_leads ?? 0),
    active: icp ? icp.active : true,
    person_titles: asText(icp?.person_titles),
    person_locations: asText(icp?.person_locations),
    exclude_notes: icp?.exclude_notes || "",
    sources: {},
  };
  for (const source of sources) {
    const saved = icp?.sources?.[source.key] || {};
    form.sources[source.key] = Object.fromEntries(
      source.fields.map((f) => {
        const value = saved[f.key] ?? f.default;
        if (f.kind === "bool") return [f.key, value ?? false];
        if (f.kind === "int" || f.kind === "text") return [f.key, value == null ? "" : String(value)];
        return [f.key, asText(value)];
      }),
    );
  }
  return form;
}

function toIcp(form, sources) {
  const out = {
    ...form,
    target_leads: form.target_leads === "" ? 0 : Number(form.target_leads),
    person_titles: lines(form.person_titles),
    person_locations: lines(form.person_locations),
    sources: {},
  };
  for (const source of sources) {
    out.sources[source.key] = Object.fromEntries(
      source.fields.map((f) => {
        const value = form.sources[source.key][f.key];
        if (f.kind === "bool") return [f.key, value];
        if (f.kind === "text") return [f.key, value.trim() || null];
        if (f.kind === "int") return [f.key, value === "" ? null : Number(value)];
        return [f.key, lines(value)];
      }),
    );
  }
  return out;
}

function Field({ label, help, children }) {
  return (
    <label className="grow">
      {label}
      {children}
      {help && <span className="help">{help}</span>}
    </label>
  );
}

function SourceInput({ field, value, onChange }) {
  if (field.kind === "bool") {
    return (
      <span className="check">
        <input type="checkbox" checked={value} onChange={onChange} /> {value ? "Yes" : "No"}
      </span>
    );
  }
  if (field.kind === "int") {
    return <input type="number" min={field.low ?? 0} max={field.high ?? undefined} value={value} onChange={onChange} />;
  }
  if (field.kind === "text") return <input value={value} onChange={onChange} />;
  return <textarea rows="3" value={value} onChange={onChange} />;
}

export default function IcpForm({ icp, sources, onSaved, onCancel }) {
  const [form, setForm] = useState(() => toForm(icp, sources));
  const [original] = useState(() => JSON.stringify(toIcp(toForm(icp, sources), sources).sources));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (name) => (e) => setForm({ ...form, [name]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setSource = (source, name) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm({ ...form, sources: { ...form.sources, [source]: { ...form.sources[source], [name]: value } } });
  };

  const changedSources = icp && JSON.stringify(toIcp(form, sources).sources) !== original;

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = toIcp(form, sources);
      onSaved(icp ? await api.updateIcp(icp.key, body) : await api.createIcp(body));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save}>
      <PageHeader title={icp ? `Edit ${icp.key}` : "New ICP"}>
        One line per item in the lists. Leave a source empty if this ICP doesn&apos;t use it.
      </PageHeader>

      <Card title="Who">
        <div className="form-row">
          <Field label="Key" help={icp ? "Can't change: companies point at it" : 'Lowercase, like "vets_us_small"'}>
            <input value={form.key} onChange={set("key")} disabled={Boolean(icp)} required />
          </Field>
          <Field label="Name"><input value={form.name} onChange={set("name")} required /></Field>
        </div>
        <div className="form-row">
          <Field label="Offer"><input value={form.offer} onChange={set("offer")} /></Field>
          <Field label="Country"><input value={form.country} onChange={set("country")} /></Field>
          <label className="narrow">Target leads<input type="number" min="0" value={form.target_leads} onChange={set("target_leads")} /></label>
        </div>
        <Field label="Description"><textarea rows="2" value={form.description} onChange={set("description")} /></Field>
        <label className="check"><input type="checkbox" checked={form.active} onChange={set("active")} /> Active (can find companies)</label>
      </Card>

      <Card title="People to find in Clay">
        <div className="form-row">
          <Field label="Job titles" help="Typed into Clay's Find people step"><textarea rows="5" value={form.person_titles} onChange={set("person_titles")} /></Field>
          <Field label="Person locations"><textarea rows="5" value={form.person_locations} onChange={set("person_locations")} /></Field>
          <Field label="Exclude" help="Checked by hand in Clay"><textarea rows="5" value={form.exclude_notes} onChange={set("exclude_notes")} /></Field>
        </div>
      </Card>

      {sources.map((source) => (
        <Card
          key={source.key}
          title={`Where to find companies: ${source.label}`}
          aside={<Badge value={source.built ? source.cost : "not built yet (M1b)"} tone={source.built ? "info" : "plain"} />}
        >
          <div className="source-fields">
            {source.fields.map((f) => (
              <Field key={f.key} label={f.label + (f.required ? " *" : "")} help={f.help}>
                <SourceInput field={f} value={form.sources[source.key][f.key]} onChange={setSource(source.key, f.key)} />
              </Field>
            ))}
          </div>
        </Card>
      ))}

      {changedSources && (
        <Notice kind="warn" title="Saving starts this ICP's search again at page 1">
          You changed where to find companies. The next run fetches from page 1 with the new settings,
          and each page costs credits again. Companies already saved are kept and skipped.
        </Notice>
      )}
      {error && <Notice kind="error">{error}</Notice>}
      <div className="confirm">
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save ICP"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
