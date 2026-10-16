// ICPs: who we target. A list (active first) with companies saved and waiting for Clay, and a
// form to create or edit one. ICPs are never deleted, only turned off: companies point at them.
import { useState } from "react";
import { api } from "../api.js";
import { Badge, Card, DataTable, Loading, Notice, PageHeader } from "../components.jsx";
import { useLoad } from "../useLoad.js";
import IcpForm from "./IcpForm.jsx";

export default function Icps() {
  const icps = useLoad(api.icps);
  const sources = useLoad(api.sources);
  const [editing, setEditing] = useState(null); // null, "new", or an ICP
  const [message, setMessage] = useState(null);

  async function toggle(icp) {
    setMessage(null);
    try {
      await api.setIcpActive(icp.key, !icp.active);
      setMessage({ kind: "success", text: `${icp.key} is now ${icp.active ? "inactive" : "active"}.` });
      icps.reload();
    } catch (e) {
      setMessage({ kind: "error", text: e.message });
    }
  }

  function saved(icp) {
    setEditing(null);
    setMessage({ kind: "success", text: `Saved ${icp.key}.` });
    icps.reload();
  }

  if (icps.error || sources.error) return <Notice kind="error">{icps.error || sources.error}</Notice>;
  if (!icps.data || !sources.data) return <Loading />;

  if (editing) {
    return (
      <IcpForm
        icp={editing === "new" ? null : editing}
        sources={sources.data}
        onSaved={saved}
        onCancel={() => setEditing(null)}
      />
    );
  }

  const columns = [
    {
      key: "name",
      label: "ICP",
      wrap: true,
      render: (i) => (
        <>
          <strong>{i.name}</strong>
          <div className="muted small">{i.key}</div>
          <span className="row-actions">
            <button type="button" className="secondary small" onClick={() => setEditing(i)}>Edit</button>
            <button type="button" className="secondary small" onClick={() => toggle(i)}>
              {i.active ? "Turn off" : "Turn on"}
            </button>
          </span>
        </>
      ),
    },
    { key: "offer", label: "Offer", wrap: true },
    {
      key: "sources",
      label: "Sources",
      render: (i) =>
        Object.keys(i.sources).length
          ? Object.keys(i.sources).map((s) => <Badge key={s} value={s} tone="info" />)
          : <span className="muted">none</span>,
    },
    { key: "saved", label: "Companies", numeric: true },
    { key: "waiting_for_clay", label: "For Clay", numeric: true },
    { key: "target_leads", label: "Target", numeric: true },
    { key: "active", label: "Status", render: (i) => <Badge value={i.active ? "active" : "inactive"} tone={i.active ? "good" : "plain"} /> },
  ];

  return (
    <>
      <PageHeader title="ICPs">
        Who we target. Each ICP has its own settings for each place we find companies (Apollo,
        Google Maps), and the people to look for in Clay. Both laptops see the same list.
      </PageHeader>
      {message && <Notice kind={message.kind}>{message.text}</Notice>}
      <Card title={`${icps.data.length} ICPs`} aside={<button type="button" onClick={() => setEditing("new")}>New ICP</button>}>
        <DataTable columns={columns} rows={icps.data} rowKey={(i) => i.key} empty="No ICPs yet. Make the first one." />
      </Card>
    </>
  );
}
