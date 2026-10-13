
const menuForm = document.getElementById("menuForm");
const menuGrid = document.getElementById("menuGrid");
const emptyState = document.getElementById("emptyState");
const loading = document.getElementById("loading");
const formMessage = document.getElementById("formMessage");
const saveButton = document.getElementById("saveButton");

let menuItems = [];

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers
    }
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }

  return data;
}

function showMessage(message, type) {
  formMessage.textContent = message;
  formMessage.className = `message ${type}`;
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

function categoryIcon(category) {
  const icons = {
    Breakfast: "☕",
    "Main Course": "🍛",
    Beverages: "🥤",
    Snacks: "🥪",
    Desserts: "🍮",
    Other: "🍽️"
  };

  return icons[category] || "🍽️";
}

async function loadMenu() {
  loading.classList.remove("hidden");
  emptyState.classList.add("hidden");

  try {
    menuItems = await apiRequest("/api/menu");
    renderMenu();
  } catch (error) {
    showMessage("Could not load menu: " + error.message, "error");
    menuGrid.innerHTML = "";
    menuItems = [];
  } finally {
    loading.classList.add("hidden");
  }
}

menuForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  formMessage.textContent = "";

  const name = document.getElementById("foodName").value.trim();
  const category = document.getElementById("category").value;
  const price = Number(document.getElementById("price").value);

  if (!name) {
    showMessage("Please enter the food item name.", "error");
    return;
  }

  if (!Number.isFinite(price) || price < 0 || price > 100000) {
    showMessage("Enter a valid price between ₹0 and ₹100,000.", "error");
    return;
  }

  saveButton.disabled = true;

  try {
    await apiRequest("/api/menu", {
      method: "POST",
      body: JSON.stringify({ name, category, price })
    });

    menuForm.reset();
    document.getElementById("category").value = "Breakfast";

    await loadMenu();
    showMessage(`${name} added to the menu!`, "success");
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    saveButton.disabled = false;
  }
});

function renderMenu() {
  const search = document.getElementById("searchInput")
    .value.trim().toLowerCase();

  const filtered = menuItems.filter((item) =>
    item.name.toLowerCase().includes(search) ||
    item.category.toLowerCase().includes(search)
  );

  document.getElementById("itemCount").textContent = menuItems.length;

  document.getElementById("categoryCount").textContent =
    new Set(menuItems.map((item) => item.category)).size;

  menuGrid.innerHTML = "";
  emptyState.classList.toggle("hidden", filtered.length > 0);

  if (filtered.length === 0) {
    emptyState.querySelector("h3").textContent =
      menuItems.length === 0
        ? "No food items yet"
        : "No matching items found";

    emptyState.querySelector("p").textContent =
      menuItems.length === 0
        ? "Add your first dish using the form above."
        : "Try another food name or category.";

    return;
  }

  filtered.forEach((item) => {
    const card = document.createElement("article");
    card.className = "menu-item";

    card.innerHTML = `
      <div class="item-top">
        <div>
          <div class="item-icon">${categoryIcon(item.category)}</div>
          <div class="item-name">${escapeHTML(item.name)}</div>
          <span class="item-category">
            ${escapeHTML(item.category)}
          </span>
        </div>
      </div>

      <div class="item-price">
        ₹${Number(item.price).toFixed(2)}
        <small>/ item</small>
      </div>

      <button
        type="button"
        class="button delete-menu-button"
        aria-label="Delete ${escapeHTML(item.name)}"
      >
        Delete item
      </button>
    `;

    card.querySelector(".delete-menu-button")
      .addEventListener("click", async (event) => {
        if (!confirm(`Remove "${item.name}" from your menu?`)) {
          return;
        }

        const deleteButton = event.currentTarget;
        deleteButton.disabled = true;
        deleteButton.textContent = "Removing...";

        try {
          await apiRequest(`/api/menu/${item.id}`, {
            method: "DELETE"
          });

          await loadMenu();
          showMessage(`${item.name} removed from the menu.`, "success");
        } catch (error) {
          deleteButton.disabled = false;
          deleteButton.textContent = "Delete item";
          showMessage(error.message, "error");
        }
      });

    menuGrid.appendChild(card);
  });
}

document.getElementById("searchInput")
  .addEventListener("input", renderMenu);

menuForm.addEventListener("reset", () => {
  formMessage.textContent = "";
  formMessage.className = "message";
});

loadMenu();
