// Every call to the backend lives here. Pages never call fetch() themselves.
// Errors come back from the API as {detail}; they're thrown as Error(detail) for the page to show.

const NOT_RUNNING = "Can't reach the app. Is `outbound serve` still running in the terminal?";

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new Error(NOT_RUNNING);
  }
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) throw new Error(errorText(data, response));
  return data;
}

function errorText(data, response) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join("; ");
  }
  if (response.status === 502 || response.status === 504) return NOT_RUNNING;
  return `The app answered ${response.status} ${response.statusText}.`;
}

function postJson(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function query(params = {}) {
  const kept = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return kept.length ? `?${new URLSearchParams(kept)}` : "";
}

function fileForm(file, fields = {}) {
  const form = new FormData();
  form.append("file", file);
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null && value !== "") form.append(key, value);
  }
  return form;
}

export const api = {
  overview: () => request("/overview"),

  segments: () => request("/segments"),
  previewSource: (segment, pages) => postJson("/source/preview", { segment, pages }),
  runSource: (segment, pages, confirmCredits) =>
    postJson("/source/run", { segment, pages, confirm_credits: confirmCredits }),

  companies: (params) => request(`/companies${query(params)}`),
  companiesCsvUrl: (params) => `/api/companies.csv${query(params)}`,

  clayBatches: () => request("/clay/batches"),
  clayExport: (segment, rows) => postJson("/clay/export", { segment: segment || null, rows }),
  clayFileUrl: (batchId) => `/api/clay/batches/${batchId}/file`,
  clayColumns: (file) => request("/clay/columns", { method: "POST", body: fileForm(file) }),
  clayImport: (file, mapping, account, credits) =>
    request("/clay/import", {
      method: "POST",
      body: fileForm(file, { mapping: JSON.stringify(mapping), account, credits }),
    }),

  leads: (state) => request(`/leads${query({ state })}`),
  leadsCsvUrl: (state) => `/api/leads.csv${query({ state })}`,

  suppression: () => request("/suppression"),
  suppress: (value, reason) => postJson("/suppression", { value, reason }),
};
