const state = {
  page: 1,
  limit: 10,
  sort: "check_in",
  order: "desc",
  search: "",
};

async function api(url, options = {}) {
  const resp = await fetch(url, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await resp.json().catch(() => ({}));
  return { ok: resp.ok, status: resp.status, data };
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso + "Z");
  return d.toLocaleString();
}

async function requireAuth() {
  const { ok, data } = await api("/api/status");
  if (!ok) {
    window.location.href = "/login";
    return null;
  }
  document.getElementById("user-name").textContent = data.name;
  return data;
}

async function loadStats() {
  const { ok, data } = await api("/api/dashboard-stats");
  if (!ok) return;
  document.getElementById("stat-total").textContent = data.total_spots;
  document.getElementById("stat-available").textContent = data.available_spots;
  document.getElementById("stat-occupied").textContent = data.occupied_spots;
  document.getElementById("stat-ev-total").textContent = data.total_ev_spots;
  document.getElementById("stat-ev-available").textContent = data.available_ev_spots;
}

function renderHistoryRow(row) {
  const tr = document.createElement("tr");
  tr.className = "border-b border-slate-100";
  tr.innerHTML = `
    <td class="py-2 pr-4 font-medium">${row.plate_number}</td>
    <td class="py-2 pr-4 capitalize">${row.vehicle_type}</td>
    <td class="py-2 pr-4">${row.spot_number ?? "—"} (Floor ${row.floor ?? "—"})</td>
    <td class="py-2 pr-4">${fmtDate(row.check_in)}</td>
    <td class="py-2 pr-4">${fmtDate(row.check_out)}</td>
    <td class="py-2 pr-4">${row.fee !== null ? "₹" + row.fee : "—"}</td>
    <td class="py-2 pr-4">
      <span class="px-2 py-0.5 rounded-full text-xs ${row.status === "active" ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-600"}">
        ${row.status}
      </span>
    </td>
  `;
  return tr;
}

async function loadHistory() {
  const params = new URLSearchParams({
    page: state.page,
    limit: state.limit,
    sort: state.sort,
    order: state.order,
  });
  if (state.search) params.set("search", state.search);

  const { ok, data } = await api(`/api/parking?${params.toString()}`);
  const tbody = document.getElementById("history-body");
  tbody.innerHTML = "";

  if (!ok) return;

  if (data.data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="py-4 text-center text-slate-400">No parking records found.</td></tr>`;
  } else {
    data.data.forEach((row) => tbody.appendChild(renderHistoryRow(row)));
  }

  document.getElementById("history-summary").textContent =
    data.total === 0 ? "No results" : `Showing page ${data.page} of ${data.pages} (${data.total} total)`;
  document.getElementById("history-page").textContent = `${data.page} / ${Math.max(data.pages, 1)}`;

  document.getElementById("history-prev").disabled = data.page <= 1;
  document.getElementById("history-next").disabled = data.page >= data.pages;
}

function setCheckinMessage(text, isError) {
  const el = document.getElementById("checkin-message");
  el.textContent = text;
  el.classList.remove("hidden", "text-red-600", "text-green-600");
  el.classList.add(isError ? "text-red-600" : "text-green-600");
}

function renderVehicleResult(plate, payload, notice) {
  const el = document.getElementById("vehicle-result");
  if (!payload) {
    el.innerHTML = `<p class="text-slate-500">No records found for plate <strong>${plate}</strong>.</p>`;
    return;
  }

  const { active, history } = payload;
  let html = "";
  if (notice) {
    html += `<p class="mb-3 text-sm font-medium ${notice.isError ? "text-red-600" : "text-green-600"}">${notice.text}</p>`;
  }
  if (active) {
    html += `
      <div class="p-3 bg-green-50 border border-green-200 rounded-lg mb-3">
        <p class="font-semibold">${active.plate_number} — currently parked</p>
        <p class="text-slate-600">Spot ${active.spot_number} (Floor ${active.floor}) · ${active.vehicle_type}</p>
        <p class="text-slate-600">Checked in: ${fmtDate(active.check_in)}</p>
        <button id="checkout-btn" data-plate="${active.plate_number}"
                class="mt-2 bg-red-600 text-white px-3 py-1.5 rounded-lg text-sm hover:bg-red-700">
          Check Out
        </button>
      </div>
    `;
  } else {
    html += `<p class="text-slate-500 mb-3">No active session for <strong>${plate}</strong>.</p>`;
  }

  html += `<p class="text-xs text-slate-400">${history.length} historical record(s)</p>`;
  el.innerHTML = html;

  const btn = document.getElementById("checkout-btn");
  if (btn) {
    btn.addEventListener("click", async () => {
      const plate = btn.dataset.plate;
      const { ok, data } = await api("/api/parking/check-out", {
        method: "POST",
        body: JSON.stringify({ plate_number: plate }),
      });
      await loadStats();
      await loadHistory();
      if (!ok) {
        await searchPlate(plate, { text: data.error || "Check-out failed", isError: true });
        return;
      }
      await searchPlate(plate, { text: `Checked out. Fee charged: ₹${data.fee}`, isError: false });
    });
  }
}

async function searchPlate(plate, notice) {
  const { ok, data } = await api(`/api/parking/${encodeURIComponent(plate)}`);
  renderVehicleResult(plate, ok ? data : null, notice);
}

function init() {
  document.getElementById("checkin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const plate = document.getElementById("checkin-plate").value.trim();
    const vehicleType = document.getElementById("checkin-type").value;

    const { ok, data } = await api("/api/parking/check-in", {
      method: "POST",
      body: JSON.stringify({ plate_number: plate, vehicle_type: vehicleType }),
    });

    if (!ok) {
      setCheckinMessage(data.error || "Check-in failed", true);
      return;
    }
    setCheckinMessage(`Checked in to spot ${data.spot_number} (Floor ${data.floor})`, false);
    document.getElementById("checkin-plate").value = "";
    await Promise.all([loadStats(), loadHistory()]);
  });

  document.getElementById("search-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const plate = document.getElementById("search-plate").value.trim();
    if (plate) await searchPlate(plate);
  });

  document.getElementById("history-search").addEventListener("input", (e) => {
    state.search = e.target.value.trim();
    state.page = 1;
    loadHistory();
  });
  document.getElementById("history-sort").addEventListener("change", (e) => {
    state.sort = e.target.value;
    loadHistory();
  });
  document.getElementById("history-order").addEventListener("change", (e) => {
    state.order = e.target.value;
    loadHistory();
  });
  document.getElementById("history-limit").addEventListener("change", (e) => {
    state.limit = parseInt(e.target.value, 10);
    state.page = 1;
    loadHistory();
  });
  document.getElementById("history-prev").addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      loadHistory();
    }
  });
  document.getElementById("history-next").addEventListener("click", () => {
    state.page += 1;
    loadHistory();
  });

  document.getElementById("logout-btn").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" });
    window.location.href = "/login";
  });
}

(async function main() {
  const user = await requireAuth();
  if (!user) return;
  init();
  await Promise.all([loadStats(), loadHistory()]);
})();
