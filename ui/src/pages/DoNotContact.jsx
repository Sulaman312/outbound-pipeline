// The do-not-contact list. Adding is permanent: there is no way to remove an entry.
import { useState } from "react";
import { api } from "../api.js";
import { Card, DataTable, Loading, Notice, PageHeader, shortDate } from "../components.jsx";
import { useLoad } from "../useLoad.js";

const COLUMNS = [
  { key: "value", label: "Domain or email" },
  { key: "kind", label: "Kind" },
  { key: "reason", label: "Reason", wrap: true },
  { key: "added_at", label: "Added", render: (r) => shortDate(r.added_at) },
];

export default function DoNotContact() {
  const list = useLoad(api.suppression);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState(null);

  async function add(e) {
    e.preventDefault();
    try {
      const result = await api.suppress(value, reason);
      setMessage({
        kind: "success",
        text: result.added ? `Added ${result.kind} ${result.value}.` : `${result.value} was already on the list.`,
      });
      setValue("");
      setReason("");
      list.reload();
    } catch (err) {
      setMessage({ kind: "error", text: err.message });
    }
  }

  return (
    <>
      <PageHeader title="Do-not-contact">
        Domains and emails we never contact. They&apos;re skipped when finding companies, left out of
        the Clay file, and dropped on import. Entries are never removed.
      </PageHeader>

      <Card title="Add to the list">
        <form className="form-row" onSubmit={add}>
          <label className="grow">
            Domain or email
            <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="acme.com or jane@acme.com" required />
          </label>
          <label className="grow">
            Reason
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="existing client" required />
          </label>
          <button type="submit">Add</button>
        </form>
        {message && <Notice kind={message.kind}>{message.text}</Notice>}
      </Card>

      {list.error && <Notice kind="error">{list.error}</Notice>}
      {!list.data && !list.error && <Loading />}
      {list.data && (
        <Card title={`On the list (${list.data.length})`}>
          <DataTable columns={COLUMNS} rows={list.data} rowKey={(r) => r.value} empty="Nobody on the list yet." />
        </Card>
      )}
    </>
  );
}
