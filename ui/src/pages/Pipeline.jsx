// The board: every stage from backend/pipeline.py, built or not, with how many leads are in
// each state it writes. Plus credits against the cap, and which keys are set.
import { api } from "../api.js";
import { Badge, Card, Loading, Notice, PageHeader, Stat } from "../components.jsx";
import { useLoad } from "../useLoad.js";

export default function Pipeline() {
  const { data, error, loading } = useLoad(api.overview);
  if (error) return <Notice kind="error" title="Couldn't load the pipeline">{error}</Notice>;
  if (loading && !data) return <Loading />;

  const { apollo, companies, states } = data;

  return (
    <>
      <PageHeader title="Pipeline">
        Every step from finding a company to a reply. The numbers are leads in each state right now.
        Grey steps aren&apos;t built yet.
      </PageHeader>

      <div className="stats">
        <Stat label="Companies found" value={companies.total} />
        <Stat label="Waiting for Clay" value={companies.waiting_for_clay} />
        <Stat label="Verified leads" value={states.verified} hint={`${states.needs_check} need a check`} />
        <Stat label="Do-not-contact" value={data.do_not_contact} />
        {data.usage.map((u) => (
          <div className="stat" key={u.source}>
            <div className="stat-value">{u.used}</div>
            <div className="stat-label">
              {u.label} {u.unit} used
            </div>
            <div className="meter" aria-hidden="true">
              <div style={{ width: `${u.cap ? Math.min(100, (100 * u.used) / u.cap) : 0}%` }} />
            </div>
            <div className="stat-hint">{u.cap === null ? "no cap set" : `of ${u.cap} in ${apollo.month}`}</div>
          </div>
        ))}
      </div>

      <div className="board">
        {data.stages.map((stage, i) => (
          <div key={stage.key} className={`stage ${stage.built ? "" : "stage-off"}`}>
            <div className="stage-top">
              <span className="stage-number">{i + 1}</span>
              <Badge value={stage.built ? "built" : "not built"} tone={stage.built ? "good" : "plain"} />
            </div>
            <h3>{stage.label}</h3>
            <ul>
              {stage.writes.map((w) => (
                <li key={w.state}>
                  <span>{w.state}</span>
                  <strong>{stage.built ? w.count : "—"}</strong>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <Card title="Setup">
        <dl className="facts">
          <div className="fact-row">
            <dt>Database</dt>
            <dd>{data.database}</dd>
          </div>
          {Object.entries(data.keys).map(([name, isSet]) => (
            <div key={name} className="fact-row">
              <dt>{name}</dt>
              <dd>{isSet ? <Badge value="set" tone="good" /> : <Badge value="not set" tone="bad" />}</dd>
            </div>
          ))}
          <div className="fact-row">
            <dt>ICPs</dt>
            <dd>
              {data.icps.active} active of {data.icps.total} (<a href="#/icps">ICPs page</a>)
            </dd>
          </div>
        </dl>
      </Card>
    </>
  );
}
