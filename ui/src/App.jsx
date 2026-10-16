// The frame: a sidebar with one link per page. The address is #/page, so refresh keeps your place.
import { useEffect, useState } from "react";
import Pipeline from "./pages/Pipeline.jsx";
import Icps from "./pages/Icps.jsx";
import FindCompanies from "./pages/FindCompanies.jsx";
import Companies from "./pages/Companies.jsx";
import Clay from "./pages/Clay.jsx";
import Leads from "./pages/Leads.jsx";
import DoNotContact from "./pages/DoNotContact.jsx";

const PAGES = [
  { path: "pipeline", label: "Pipeline", Page: Pipeline },
  { path: "icps", label: "ICPs", Page: Icps },
  { path: "find", label: "Find companies", Page: FindCompanies },
  { path: "companies", label: "Companies", Page: Companies },
  { path: "clay", label: "Enrich with Clay", Page: Clay },
  { path: "leads", label: "Leads", Page: Leads },
  { path: "do-not-contact", label: "Do-not-contact", Page: DoNotContact },
];

function currentPath() {
  const path = window.location.hash.replace(/^#\/?/, "");
  return PAGES.some((p) => p.path === path) ? path : "pipeline";
}

export default function App() {
  const [path, setPath] = useState(currentPath);

  useEffect(() => {
    const onHash = () => setPath(currentPath());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const { Page } = PAGES.find((p) => p.path === path);
  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand">
          Arsuno <span>outbound</span>
        </div>
        {PAGES.map((p) => (
          <a key={p.path} href={`#/${p.path}`} className={p.path === path ? "active" : undefined}>
            {p.label}
          </a>
        ))}
        <div className="sidebar-foot">Runs on this computer only</div>
      </nav>
      <main className="content">
        <Page />
      </main>
    </div>
  );
}
