
const API = {
  menu: "/api/menu",
  bills: "/api/bills"
};

const $ = (id) => document.getElementById(id);

const state = {
  menu: [],
  cart: [],
  sales: [],
  saving: false
};

const money = (value) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR"
  }).format(Number(value) || 0);

const escapeHTML = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[char]);

function localDate(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateOf(value) {
  if (!value) return "";
  const text = String(value);
  const match = text.match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : "";
}

function showMessage(text, type = "success") {
  const el = $("billMessage");
  el.textContent = text;
  el.className = `message show ${type}`;
}

function clearMessage() {
  $("billMessage").textContent = "";
  $("billMessage").className = "message";
}

async function requestJSON(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers
    }
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.error || data.message || `Request failed (${response.status})`);
  }

  return data;
}

// Support common response formats from a Flask menu API.
function normaliseMenu(data) {
  const list = Array.isArray(data)
    ? data
    : data.menu || data.items || data.products || [];

  return list.map((item) => ({
    id: item.id ?? item.item_id,
    name: item.name ?? item.item_name ?? item.dish_name ?? item.title,
    price: Number(item.price ?? item.item_price ?? item.selling_price ?? 0)
  })).filter((item) =>
    item.id !== undefined &&
    item.name &&
    Number.isFinite(item.price) &&
    item.price >= 0
  );
}

function normaliseSale(sale) {
  return {
    id: sale.id ?? sale.bill_id ?? sale.invoice_id ?? "—",
    customer: sale.customer_name ?? sale.customer ?? "Walk-in customer",
    amount: Number(sale.total_amount ?? sale.total ?? sale.grand_total ?? 0),
    payment: sale.payment_method ?? sale.payment ?? "other",
    date: dateOf(sale.created_at ?? sale.bill_date ?? sale.date),
    items: Array.isArray(sale.items) ? sale.items : [],
    customerType: sale.customer_type ?? "walk_in"
  };
}

async function loadMenu() {
  const select = $("menuItem");

  try {
    const data = await requestJSON(API.menu);
    state.menu = normaliseMenu(data);

    select.innerHTML = "";

    if (!state.menu.length) {
      select.add(new Option("No menu items available", ""));
      return;
    }

    select.add(new Option("Select a menu item", ""));

    state.menu.forEach((item) => {
      select.add(new Option(
        `${item.name} — ${money(item.price)}`,
        String(item.id)
      ));
    });
  } catch (error) {
    select.innerHTML = "";
    select.add(new Option("Could not load menu", ""));
    showMessage(
      "Menu could not be loaded. Check that GET /api/menu is working.",
      "error"
    );
  }
}

function cartTotals() {
  const subtotal = state.cart.reduce(
    (sum, item) => sum + item.price * item.quantity,
    0
  );

  const requestedDiscount = Number($("discount").value) || 0;
  const discount = Math.min(Math.max(requestedDiscount, 0), subtotal);

  return {
    subtotal,
    discount,
    total: Math.max(0, subtotal - discount)
  };
}

function renderCart() {
  const body = $("cartBody");

  if (!state.cart.length) {
    body.innerHTML = `
      <tr class="empty-row">
        <td colspan="5">No items added yet.</td>
      </tr>`;
  } else {
    body.innerHTML = state.cart.map((item, index) => `
      <tr>
        <td>${escapeHTML(item.name)}</td>
        <td>${money(item.price)}</td>
        <td>${item.quantity}</td>
        <td><strong>${money(item.price * item.quantity)}</strong></td>
        <td>
          <button class="remove-item" type="button"
            data-remove="${index}" aria-label="Remove ${escapeHTML(item.name)}">
            ×
          </button>
        </td>
      </tr>
    `).join("");
  }

  const totals = cartTotals();
  $("subtotal").textContent = money(totals.subtotal);
  $("discountTotal").textContent = `−${money(totals.discount)}`;
  $("grandTotal").textContent = money(totals.total);
}

function addItem() {
  clearMessage();

  const id = $("menuItem").value;
  const quantity = Number($("itemQuantity").value);
  const item = state.menu.find((entry) => String(entry.id) === id);

  if (!item) {
    showMessage("Please select a menu item first.", "error");
    return;
  }

  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 10000) {
    showMessage("Enter a valid quantity.", "error");
    return;
  }

  const existing = state.cart.find(
    (entry) => String(entry.id) === String(item.id)
  );

  if (existing) {
    existing.quantity += quantity;
  } else {
    state.cart.push({ ...item, quantity });
  }

  $("itemQuantity").value = "1";
  renderCart();
}

function renderStats() {
  const today = localDate();

  const todaysSales = state.sales.filter((sale) => sale.date === today);
  const revenue = todaysSales.reduce((sum, sale) => sum + sale.amount, 0);

  const bills = todaysSales.length;
  const items = todaysSales.reduce((sum, sale) => {
    return sum + sale.items.reduce(
      (itemSum, item) => itemSum + Number(item.quantity ?? item.qty ?? 0),
      0
    );
  }, 0);

  $("revenueStat").textContent = money(revenue);
  $("billsStat").textContent = String(bills);
  $("itemsStat").textContent = String(items);
  $("averageStat").textContent = money(bills ? revenue / bills : 0);
}

function renderSales() {
  const query = $("searchSales").value.trim().toLowerCase();
  const filterDate = $("salesDate").value;

  const filtered = state.sales.filter((sale) => {
    const matchesQuery =
      String(sale.id).toLowerCase().includes(query) ||
      sale.customer.toLowerCase().includes(query);

    const matchesDate = !filterDate || sale.date === filterDate;

    return matchesQuery && matchesDate;
  });

  const body = $("salesBody");

  if (!filtered.length) {
    body.innerHTML = `
      <tr>
        <td colspan="4" class="table-message">No matching sales found.</td>
      </tr>`;
    return;
  }

  body.innerHTML = filtered.map((sale) => `
    <tr>
      <td class="bill-id">#${escapeHTML(sale.id)}</td>
      <td>${escapeHTML(sale.customer)}</td>
      <td><strong>${money(sale.amount)}</strong></td>
      <td><span class="payment-badge">${escapeHTML(sale.payment)}</span></td>
    </tr>
  `).join("");
}

async function loadSales() {
  $("salesBody").innerHTML = `
    <tr><td colspan="4" class="table-message">Loading sales...</td></tr>`;

  try {
    const data = await requestJSON(API.bills);
    const list = Array.isArray(data)
      ? data
      : data.bills || data.sales || [];

    state.sales = list.map(normaliseSale);

    renderStats();
    renderSales();
  } catch (error) {
    $("salesBody").innerHTML = `
      <tr>
        <td colspan="4" class="table-message">
          Could not load sales. Check GET /api/bills.
        </td>
      </tr>`;
  }
}

async function saveBill(event) {
  event.preventDefault();
  clearMessage();

  if (state.saving) return;

  if (!state.cart.length) {
    showMessage("Add at least one item before saving the bill.", "error");
    return;
  }

  const totals = cartTotals();
  const customerType = $("customerType").value;
  const customerName = $("customerName").value.trim();
  const roomNumber = $("roomNumber").value.trim();

  if (customerType === "resident" && !roomNumber) {
    showMessage("Enter the room number for a resident guest.", "error");
    return;
  }

  if (totals.total < 0) {
    showMessage("The bill total cannot be negative.", "error");
    return;
  }

  const payload = {
    customer_name: customerName || "Walk-in customer",
    customer_type: customerType,
    room_number: roomNumber || null,
    meal_type: $("mealType").value,
    payment_method: $("paymentMethod").value,
    discount: Number(totals.discount.toFixed(2)),
    items: state.cart.map((item) => ({
      item_id: item.id,
      quantity: item.quantity
    }))
  };

  state.saving = true;
  $("saveBillBtn").disabled = true;
  $("saveBillBtn").textContent = "Saving...";

  try {
    await requestJSON(API.bills, {
      method: "POST",
      body: JSON.stringify(payload)
    });

    showMessage("Bill saved successfully.", "success");

    state.cart = [];
    $("billForm").reset();
    $("itemQuantity").value = "1";
    renderCart();

    // Refresh from the database; don't assume the response is a saved bill.
    await loadSales();
  } catch (error) {
    showMessage(
      `${error.message}. Ensure POST /api/bills is implemented in Flask.`,
      "error"
    );
  } finally {
    state.saving = false;
    $("saveBillBtn").disabled = false;
    $("saveBillBtn").textContent = "Save bill →";
  }
}

function clearBill() {
  state.cart = [];
  $("billForm").reset();
  $("itemQuantity").value = "1";
  clearMessage();
  renderCart();
}

function initBilling() {
  $("todayLabel").textContent = new Date().toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric"
  });

  $("salesDate").value = localDate();

  $("addItemBtn").addEventListener("click", addItem);

  $("cartBody").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove]");
    if (!button) return;

    state.cart.splice(Number(button.dataset.remove), 1);
    renderCart();
  });

  $("discount").addEventListener("input", renderCart);
  $("billForm").addEventListener("submit", saveBill);
  $("clearBillBtn").addEventListener("click", clearBill);
  $("refreshBtn").addEventListener("click", loadSales);
  $("searchSales").addEventListener("input", renderSales);
  $("salesDate").addEventListener("change", renderSales);

  renderCart();
  loadMenu();
  loadSales();
}

document.addEventListener("DOMContentLoaded", initBilling);

const csvForm = document.getElementById("csvForm");

if (csvForm) {
  csvForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const fileInput = document.getElementById("csvFile");
    const message = document.getElementById("csvMessage");
    const file = fileInput.files[0];

    if (!file) {
      message.textContent = "Please select a CSV file.";
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    message.textContent = "Importing CSV...";

    try {
      const response = await fetch("/api/sales/import-csv", {
        method: "POST",
        body: formData
      });

      const result = await response.json();

      if (!response.ok) {
        const details = result.details
          ? " " + result.details.map(
              item => `Row ${item.row}: ${item.error}`
            ).join("; ")
          : "";

        throw new Error((result.error || "Import failed.") + details);
      }

      message.textContent =
        `${result.message} ${result.rows_imported} rows imported.`;

      csvForm.reset();
    } catch (error) {
      message.textContent = error.message;
    }
  });
}