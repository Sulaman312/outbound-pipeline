// Small building blocks every page uses: header, notices, tables, badges, numbers.

export function PageHeader({ title, children }) {
  return (
    <header className="page-header">
      <h1>{title}</h1>
      {children && <p className="lead">{children}</p>}
    </header>
  );
}

export function Notice({ kind = "info", title, children }) {
  return (
    <div className={`notice notice-${kind}`} role={kind === "error" ? "alert" : "status"}>
      {title && <strong>{title}</strong>}
      <div>{children}</div>
    </div>
  );
}

export function Loading() {
  return <p className="muted">Loading…</p>;
}

export function Card({ title, step, children, aside }) {
  return (
    <section className="card">
      {(title || aside) && (
        <div className="card-head">
          <h2>
            {step && <span className="step">{step}</span>}
            {title}
          </h2>
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

const STATE_TONES = {
  verified: "good",
  enriched: "good",
  needs_check: "warn",
  hold: "warn",
  exported: "info",
  dropped: "bad",
  no_contact: "bad",
};

export function Badge({ value, tone }) {
  return <span className={`badge badge-${tone || STATE_TONES[value] || "plain"}`}>{value}</span>;
}

// Cells stay on one line (the table scrolls sideways); columns marked `wrap` hold longer text.
function cellClass(column) {
  return [column.numeric && "num", column.wrap && "wrap"].filter(Boolean).join(" ") || undefined;
}

export function DataTable({ columns, rows, empty, rowKey }) {
  if (!rows.length) return <p className="empty">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={cellClass(c)}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={rowKey ? rowKey(row) : i}>
              {columns.map((c) => (
                <td key={c.key} className={cellClass(c)}>
                  {c.render ? c.render(row) : (row[c.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function shortDate(text) {
  return text ? text.replace("T", " ").replace(/:\d\dZ$/, " UTC") : "";
}

export function SegmentSelect({ segments, value, onChange, allLabel }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {allLabel && <option value="">{allLabel}</option>}
      {segments.map((s) => (
        <option key={s.key} value={s.key}>
          {s.key} ({s.offer})
        </option>
      ))}
    </select>
  );
}
