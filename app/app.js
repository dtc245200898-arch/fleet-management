const views = {
  overview: { title: "Tổng quan", description: "Theo dõi hoạt động và tình trạng đội xe của bạn." },
  vehicles: { title: "Phương tiện", description: "Quản lý danh sách, tình trạng và thông tin phương tiện." },
  trips: { title: "Chuyến đi", description: "Theo dõi lịch trình và hoạt động vận chuyển." },
  maintenance: { title: "Bảo dưỡng", description: "Quản lý lịch bảo dưỡng và chi phí sửa chữa." },
};
const vehicleStatuses = ["Hoạt động", "Bảo trì", "Ngừng hoạt động"];
const tripStatuses = ["Đã lên lịch", "Đang thực hiện", "Hoàn thành", "Đã hủy"];
const maintenanceStatuses = ["Đã lên lịch", "Đang thực hiện", "Hoàn thành"];
const formDefinitions = {
  vehicles: [
    { name: "registration", label: "Biển số xe", required: true, placeholder: "Ví dụ: 51A-123.45" },
    { name: "make", label: "Hãng xe", required: true, placeholder: "Ví dụ: Toyota" },
    { name: "model", label: "Dòng xe", required: true, placeholder: "Ví dụ: Fortuner" },
    { name: "year", label: "Năm sản xuất", type: "number", min: 1950, max: 2100, required: true },
    { name: "mileage", label: "Số kilomet", type: "number", min: 0, required: true },
    { name: "status", label: "Trạng thái", type: "select", options: vehicleStatuses, required: true },
  ],
  trips: [
    { name: "vehicle_id", label: "Phương tiện", type: "select", options: [], required: true },
    { name: "driver", label: "Tài xế", required: true, placeholder: "Tên tài xế" },
    { name: "origin", label: "Điểm đi", required: true, placeholder: "Tỉnh/thành phố" },
    { name: "destination", label: "Điểm đến", required: true, placeholder: "Tỉnh/thành phố" },
    { name: "departure_date", label: "Ngày khởi hành", type: "date", required: true },
    { name: "arrival_date", label: "Ngày đến", type: "date" },
    { name: "distance_km", label: "Quãng đường (km)", type: "number", min: 0, required: true },
    { name: "status", label: "Trạng thái", type: "select", options: tripStatuses, required: true },
  ],
  maintenance: [
    { name: "vehicle_id", label: "Phương tiện", type: "select", options: [], required: true },
    { name: "service_date", label: "Ngày bảo dưỡng", type: "date", required: true },
    { name: "service_type", label: "Hạng mục", required: true, placeholder: "Ví dụ: Thay dầu" },
    { name: "cost", label: "Chi phí (VNĐ)", type: "number", min: 0, required: true },
    { name: "status", label: "Trạng thái", type: "select", options: maintenanceStatuses, required: true },
    { name: "description", label: "Mô tả", type: "textarea", wide: true, required: true, placeholder: "Ghi chú nội dung bảo dưỡng" },
  ],
};
const state = { view: "overview", vehicles: [], trips: [], maintenance: [], editingId: null };
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]);
const formatNumber = (value) => new Intl.NumberFormat("vi-VN").format(Number(value) || 0);
const formatCurrency = (value) => `${formatNumber(value)} ₫`;
const today = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium" }).format(new Date());
$("#today").textContent = today;

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const result = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(result?.error || "Không thể hoàn tất yêu cầu.");
  return result;
}

function showNotice(message, type = "success") {
  const notice = $("#notice");
  notice.textContent = message;
  notice.className = `notice ${type}`;
  notice.hidden = false;
  window.clearTimeout(showNotice.timeout);
  showNotice.timeout = window.setTimeout(() => { notice.hidden = true; }, 4500);
}

function badge(status) {
  let color = "gray";
  if (status === "Hoạt động" || status === "Hoàn thành") color = "green";
  else if (status === "Bảo trì" || status === "Đang thực hiện") color = "orange";
  else if (status === "Đã lên lịch") color = "blue";
  else if (status === "Đã hủy") color = "purple";
  return `<span class="badge badge-${color}">${escapeHtml(status)}</span>`;
}

function vehicleCell(vehicle) {
  return `<div class="vehicle-name">${escapeHtml(vehicle.make)} ${escapeHtml(vehicle.model)}</div><div class="vehicle-sub">Mã xe #${vehicle.id}</div>`;
}

function renderVehicleRow(vehicle, actions = false) {
  return `<tr>
    <td>${vehicleCell(vehicle)}</td><td><span class="plate">${escapeHtml(vehicle.registration)}</span></td>
    <td>${escapeHtml(vehicle.year)}</td><td>${formatNumber(vehicle.mileage)} km</td><td>${badge(vehicle.status)}</td>
    ${actions ? `<td><div class="row-actions"><button class="row-action" data-edit="${vehicle.id}">Sửa</button><button class="row-action delete" data-delete="${vehicle.id}">Xóa</button></div></td>` : "<td></td>"}
  </tr>`;
}

function emptyRow(columns, message) {
  return `<tr><td colspan="${columns}" class="empty-state">${escapeHtml(message)}</td></tr>`;
}

function render() {
  const vehicles = state.vehicles;
  const trips = state.trips;
  const maintenance = state.maintenance;
  $("#stat-total").textContent = formatNumber(vehicles.length);
  $("#stat-active").textContent = formatNumber(vehicles.filter((vehicle) => vehicle.status === "Hoạt động").length);
  $("#stat-maintenance").textContent = formatNumber(vehicles.filter((vehicle) => vehicle.status === "Bảo trì").length);
  $("#stat-trips").textContent = formatNumber(trips.filter((trip) => trip.status === "Đang thực hiện").length);
  $("#overview-vehicles").innerHTML = vehicles.slice(0, 5).map((vehicle) => renderVehicleRow(vehicle)).join("")
    || emptyRow(6, "Chưa có phương tiện. Hãy thêm xe đầu tiên.");
  $("#vehicles-table").innerHTML = filteredVehicles().map((vehicle) => renderVehicleRow(vehicle, true)).join("")
    || emptyRow(6, "Không tìm thấy phương tiện phù hợp.");
  $("#vehicle-count").textContent = `${filteredVehicles().length} / ${vehicles.length} phương tiện`;
  $("#trips-table").innerHTML = trips.map(renderTripRow).join("") || emptyRow(6, "Chưa có chuyến đi nào.");
  $("#overview-trips").innerHTML = trips.slice(0, 5).map(renderTripRow).join("") || emptyRow(5, "Chưa có chuyến đi nào.");
  $("#trip-count").textContent = `${trips.length} chuyến đi`;
  $("#maintenance-table").innerHTML = maintenance.map(renderMaintenanceRow).join("") || emptyRow(6, "Chưa có lịch bảo dưỡng nào.");
  $("#maintenance-count").textContent = `${maintenance.length} lịch bảo dưỡng`;
}

function filteredVehicles() {
  const query = ($("#vehicle-search")?.value || "").trim().toLocaleLowerCase("vi");
  return state.vehicles.filter((vehicle) => [
    vehicle.registration, vehicle.make, vehicle.model, vehicle.status,
  ].some((value) => value.toLocaleLowerCase("vi").includes(query)));
}

function renderTripRow(trip) {
  const route = `${escapeHtml(trip.origin)} <span class="vehicle-sub">→</span> ${escapeHtml(trip.destination)}`;
  return `<tr><td><span class="plate">${escapeHtml(trip.vehicle_registration || "Đã xóa xe")}</span></td>
    <td>${escapeHtml(trip.driver)}</td><td>${route}</td><td>${escapeHtml(trip.departure_date)}</td>
    <td>${formatNumber(trip.distance_km)} km</td><td>${badge(trip.status)}</td></tr>`;
}

function renderMaintenanceRow(item) {
  return `<tr><td><span class="plate">${escapeHtml(item.vehicle_registration || "Đã xóa xe")}</span></td>
    <td>${escapeHtml(item.service_date)}</td><td>${escapeHtml(item.service_type)}</td>
    <td>${escapeHtml(item.description)}</td><td>${formatCurrency(item.cost)}</td><td>${badge(item.status)}</td></tr>`;
}

async function loadData() {
  try {
    [state.vehicles, state.trips, state.maintenance] = await Promise.all([
      request("/api/vehicles"), request("/api/trips"), request("/api/maintenance"),
    ]);
    render();
  } catch (error) {
    showNotice(error.message, "error");
  }
}

function changeView(view) {
  state.view = view;
  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.hidden = panel.id !== `${view}-view`;
  });
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  $("#breadcrumb").textContent = views[view].title;
  $("#page-title").textContent = views[view].title;
  $("#page-description").textContent = views[view].description;
  $("#primary-action").hidden = view === "overview" ? false : !formDefinitions[view];
  $("#primary-action").innerHTML = view === "vehicles"
    ? "<span>＋</span>Thêm phương tiện"
    : view === "trips" ? "<span>＋</span>Thêm chuyến đi"
      : view === "maintenance" ? "<span>＋</span>Lên lịch bảo dưỡng"
        : "<span>＋</span>Thêm phương tiện";
}

function renderFormFields(resource, record = {}) {
  const definitions = formDefinitions[resource];
  $("#form-fields").innerHTML = definitions.map((field) => {
    const required = field.required ? " required" : "";
    const value = record[field.name] ?? "";
    let control;
    if (field.type === "select") {
      const options = field.name === "vehicle_id"
        ? state.vehicles.map((vehicle) => ({ value: vehicle.id, label: `${vehicle.registration} · ${vehicle.make} ${vehicle.model}` }))
        : field.options.map((option) => ({ value: option, label: option }));
      control = `<select name="${field.name}"${required}><option value="">Chọn...</option>${options.map((option) =>
        `<option value="${escapeHtml(option.value)}"${String(option.value) === String(value) ? " selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select>`;
    } else if (field.type === "textarea") {
      control = `<textarea name="${field.name}" placeholder="${escapeHtml(field.placeholder || "")}"${required}>${escapeHtml(value)}</textarea>`;
    } else {
      control = `<input name="${field.name}" type="${field.type || "text"}"${field.min !== undefined ? ` min="${field.min}"` : ""}${field.max !== undefined ? ` max="${field.max}"` : ""} placeholder="${escapeHtml(field.placeholder || "")}" value="${escapeHtml(value)}"${required}>`;
    }
    return `<div class="form-field${field.wide ? " wide" : ""}"><label for="field-${field.name}">${escapeHtml(field.label)}</label>${control}</div>`;
  }).join("");
  definitions.forEach((field) => {
    const input = $(`[name="${field.name}"]`);
    input.id = `field-${field.name}`;
  });
}

function openForm(resource, record = null) {
  state.editingId = record?.id ?? null;
  const titles = { vehicles: "phương tiện", trips: "chuyến đi", maintenance: "bảo dưỡng" };
  $("#dialog-eyebrow").textContent = { vehicles: "ĐỘI XE", trips: "VẬN HÀNH", maintenance: "KỸ THUẬT" }[resource];
  $("#dialog-title").textContent = record ? `Cập nhật ${titles[resource]}` : ({
    vehicles: "Thêm phương tiện", trips: "Thêm chuyến đi", maintenance: "Lên lịch bảo dưỡng",
  })[resource];
  $("#dialog-submit").textContent = record ? "Lưu thay đổi" : "Lưu thông tin";
  renderFormFields(resource, record || {});
  $("#record-dialog").dataset.resource = resource;
  $("#record-dialog").showModal();
}

function readForm(resource) {
  const payload = {};
  for (const field of formDefinitions[resource]) {
    const input = $(`[name="${field.name}"]`);
    const value = input.value.trim();
    if (value === "" && !field.required) continue;
    payload[field.name] = field.type === "number" ? Number(value)
      : field.name === "vehicle_id" ? Number(value) : value;
  }
  return payload;
}

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => changeView(item.dataset.view));
});
document.querySelectorAll("[data-go]").forEach((button) => {
  button.addEventListener("click", () => changeView(button.dataset.go));
});
$("#primary-action").addEventListener("click", () => {
  const resource = state.view === "overview" ? "vehicles" : state.view;
  openForm(resource);
});
$("#vehicle-search").addEventListener("input", render);
$("#dialog-close").addEventListener("click", () => $("#record-dialog").close());
$("#dialog-cancel").addEventListener("click", () => $("#record-dialog").close());
$("#record-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const dialog = $("#record-dialog");
  const resource = dialog.dataset.resource;
  const method = state.editingId ? "PUT" : "POST";
  const path = `/api/${resource}${state.editingId ? `/${state.editingId}` : ""}`;
  try {
    await request(path, { method, body: JSON.stringify(readForm(resource)) });
    dialog.close();
    showNotice(state.editingId ? "Đã cập nhật thông tin." : "Đã lưu thông tin mới.");
    await loadData();
  } catch (error) {
    showNotice(error.message, "error");
  }
});
$("#vehicles-table").addEventListener("click", async (event) => {
  const editButton = event.target.closest("[data-edit]");
  const deleteButton = event.target.closest("[data-delete]");
  if (editButton) {
    const vehicle = state.vehicles.find((item) => item.id === Number(editButton.dataset.edit));
    if (vehicle) openForm("vehicles", vehicle);
  }
  if (deleteButton) {
    const vehicle = state.vehicles.find((item) => item.id === Number(deleteButton.dataset.delete));
    if (!vehicle || !window.confirm(`Xóa phương tiện ${vehicle.registration}? Các chuyến đi và lịch bảo dưỡng gắn với xe cũng sẽ bị xóa.`)) return;
    try {
      await request(`/api/vehicles/${vehicle.id}`, { method: "DELETE" });
      showNotice("Đã xóa phương tiện và dữ liệu liên quan.");
      await loadData();
    } catch (error) {
      showNotice(error.message, "error");
    }
  }
});
loadData();
