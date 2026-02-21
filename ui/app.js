const formatBytes = (bytes) => {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  return `${size.toFixed(1)} ${units[idx]}`;
};

const daysAgoLabel = (iso) => {
  if (!iso) return "never";
  const dt = new Date(iso.replace(" ", "T"));
  if (Number.isNaN(dt.getTime())) return "unknown";
  const diffDays = Math.floor((Date.now() - dt.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return "today";
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  return `${Math.floor(diffDays / 30)}mo ago`;
};

const renderRegistry = (data) => {
  const table = document.querySelector(".table");
  const rows = data.records || [];

  const header = `
    <div class="row header">
      <span>Name</span>
      <span>Status</span>
      <span>Python</span>
      <span>Packages</span>
      <span>Size</span>
      <span>Last Used</span>
      <span>Project</span>
    </div>
  `;

  const body = rows
    .map((r) => {
      const status = r.missing ? "missing" : "healthy";
      const sizeBytes = r.size_mb ? r.size_mb * 1024 * 1024 : 0;
      return `
        <div class="row">
          <span class="pill">${r.name}</span>
          <span class="status ${r.missing ? "warn" : "ok"}">${status}</span>
          <span>${r.python_version || "?"}</span>
          <span>${r.package_count ?? "?"}</span>
          <span>${formatBytes(sizeBytes)}</span>
          <span>${daysAgoLabel(r.last_used_at)}</span>
          <span>${r.project_path || "?"}</span>
        </div>
      `;
    })
    .join("");

  table.innerHTML = header + body;

  const stats = data.stats || {};
  document.querySelector("#metric-total").textContent = stats.total_venvs ?? 0;
  const sizeText = `${stats.total_size_mb?.toFixed(1) ?? "0.0"} MB`;
  document.querySelector("#metric-size").textContent = sizeText;
  document.querySelector("#metric-size-compact").textContent = sizeText;
  document.querySelector("#metric-missing").textContent = stats.missing_venvs ?? 0;
  document.querySelector("#metric-packages").textContent = stats.total_packages ?? 0;
  document.querySelector("#metric-unused").textContent = stats.unused_90_days ?? 0;

  renderHealth(rows);
  renderStorage(rows);
};

const renderSuggestions = (data) => {
  const list = document.querySelector("#suggestions");
  const items = (data.suggestions || []).slice(0, 3);
  if (items.length === 0) {
    list.innerHTML = "<div class=\"muted\">No suggestions yet.</div>";
    return;
  }

  list.innerHTML = items
    .map((s) => {
      const pct = Math.round(s.confidence * 100);
      const riskClass = s.risk_level === "low" ? "danger" : "caution";
      const riskLabel = s.risk_level === "low" ? "low risk" : "medium risk";
      return `
        <div class="suggestion">
          <div class="score">${pct}%</div>
          <div>
            <strong>${s.name}</strong>
            <div class="muted">${s.reason}</div>
          </div>
          <div class="tag ${riskClass}">${riskLabel}</div>
        </div>
      `;
    })
    .join("");
};

const renderHealth = (records) => {
  const health = { healthy: 0, warning: 0, broken: 0, unknown: 0 };
  records.forEach((r) => {
    let status = "healthy";
    if (r.missing) {
      status = "broken";
    } else if (r.health_status && r.health_status !== "healthy") {
      status = "warning";
    }
    health[status] = (health[status] || 0) + 1;
  });
  const total = Math.max(1, records.length);
  const toPct = (v) => `${Math.round((v / total) * 100)}%`;

  const container = document.querySelector("#health-bars");
  container.innerHTML = `
    <div class="bar">
      <span>Healthy</span>
      <span>${health.healthy}</span>
      <div class="track"><div class="fill good" style="width: ${toPct(health.healthy)}"></div></div>
    </div>
    <div class="bar">
      <span>Warning</span>
      <span>${health.warning}</span>
      <div class="track"><div class="fill warn" style="width: ${toPct(health.warning)}"></div></div>
    </div>
    <div class="bar">
      <span>Broken</span>
      <span>${health.broken}</span>
      <div class="track"><div class="fill bad" style="width: ${toPct(health.broken)}"></div></div>
    </div>
  `;
};

const renderStorage = (records) => {
  const list = document.querySelector("#storage-list");
  const sorted = [...records]
    .filter((r) => r.size_mb)
    .sort((a, b) => (b.size_mb || 0) - (a.size_mb || 0));

  const top = sorted.slice(0, 3);
  const rest = sorted.slice(3);
  const restSize = rest.reduce((acc, r) => acc + (r.size_mb || 0), 0);

  const dots = ["a", "b", "c", "d"];
  const items = top.map((r, idx) => ({
    name: r.name,
    size: `${r.size_mb.toFixed(1)} MB`,
    dot: dots[idx] || "d",
  }));
  if (restSize > 0) {
    items.push({ name: "other", size: `${restSize.toFixed(1)} MB`, dot: "d" });
  }

  if (items.length === 0) {
    list.innerHTML = "<div class=\"muted\">No size data yet. Run venvy refresh.</div>";
    return;
  }

  list.innerHTML = items
    .map(
      (i) => `
        <div class="storage-item">
          <span class="dot ${i.dot}"></span>
          <span>${i.name}</span>
          <span>${i.size}</span>
        </div>
      `
    )
    .join("");
};

const load = async () => {
  const registry = await fetch("/api/registry").then((r) => r.json());
  renderRegistry(registry);

  const suggestions = await fetch("/api/suggestions").then((r) => r.json());
  renderSuggestions(suggestions);
};

load().catch(() => {
  document.querySelector("#metric-total").textContent = "0";
});

document.querySelector("#refresh-ui")?.addEventListener("click", () => {
  load();
});
