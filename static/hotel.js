
const form = document.getElementById("guestForm");
const tableBody = document.getElementById("guestTableBody");
const emptyState = document.getElementById("emptyState");
const guestCount = document.getElementById("guestCount");
const formMessage = document.getElementById("formMessage");

let guests = [];
let editingId = null;

// ---------------- API CONNECTION ----------------

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
    throw new Error(data.error || "Something went wrong.");
  }

  return data;
}

async function loadGuests() {
  try {
    guests = await apiRequest("/api/guests");
    renderGuests();
  } catch (error) {
    showMessage("Could not load guests: " + error.message, "error");
  }
}

// ---------------- DATE HELPERS ----------------

function localDateString(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

// ---------------- MESSAGES ----------------

function showMessage(message, type) {
  formMessage.textContent = message;
  formMessage.className = `message ${type}`;
}

function clearMessage() {
  formMessage.textContent = "";
  formMessage.className = "message";
}

// ---------------- FORM DATA ----------------

function getFormData() {
  return {
    name: document.getElementById("guestName").value.trim(),
    room: document.getElementById("roomNumber").value.trim(),
    phone: document.getElementById("phone").value.trim(),

    bookingSource: document.getElementById("bookingSource").value,

    checkin: document.getElementById("checkinDate").value,
    checkout: document.getElementById("checkoutDate").value,

    adults: Number(document.getElementById("adults").value),
    children: Number(document.getElementById("children").value),

    meals: {
      breakfast: document.getElementById("breakfast").checked,
      lunch: document.getElementById("lunch").checked,
      dinner: document.getElementById("dinner").checked
    },

    status: document.getElementById("status").value
  };
}

function validateGuest(guest) {
  if (!guest.name || !guest.room) {
    return "Please enter the guest name and room number.";
  }

  if (!guest.checkin || !guest.checkout) {
    return "Please select both check-in and check-out dates.";
  }

  if (guest.checkout <= guest.checkin) {
    return "Check-out must be after check-in.";
  }

  if (
    !Number.isInteger(guest.adults) ||
    guest.adults < 1 ||
    guest.adults > 50
  ) {
    return "Adults must be between 1 and 50.";
  }

  if (
    !Number.isInteger(guest.children) ||
    guest.children < 0 ||
    guest.children > 50
  ) {
    return "Children must be between 0 and 50.";
  }

  if (guest.phone && guest.phone.length > 20) {
    return "Phone number must not exceed 20 characters.";
  }

  return "";
}

// ---------------- ADD / UPDATE GUEST ----------------

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearMessage();

  const guest = getFormData();
  const error = validateGuest(guest);

  if (error) {
    showMessage(error, "error");
    return;
  }

  const wasEditing = editingId !== null;
  const url = wasEditing
    ? `/api/guests/${editingId}`
    : "/api/guests";

  const method = wasEditing ? "PUT" : "POST";
  const saveButton = document.getElementById("saveButton");

  saveButton.disabled = true;

  try {
    await apiRequest(url, {
      method,
      body: JSON.stringify(guest)
    });

    resetForm();
    await loadGuests();

    showMessage(
      wasEditing
        ? "Guest details updated successfully."
        : "Guest registered successfully!",
      "success"
    );
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    saveButton.disabled = false;
  }
});

// ---------------- RESET FORM ----------------

function resetForm() {
  form.reset();
  editingId = null;

  document.getElementById("checkinDate").value =
    localDateString();

  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);

  document.getElementById("checkoutDate").value =
    localDateString(tomorrow);

  document.getElementById("formTitle").textContent =
    "Register a new guest";

  document.getElementById("saveButtonText").textContent =
    "＋ Add Guest";

  document.getElementById("cancelEdit").classList.add("hidden");
}

document.getElementById("resetForm").addEventListener("click", () => {
  setTimeout(() => {
    resetForm();
    clearMessage();
  }, 0);
});

document.getElementById("cancelEdit").addEventListener("click", () => {
  resetForm();
  clearMessage();
});

// ---------------- EDIT GUEST ----------------

function editGuest(id) {
  const guest = guests.find((item) => item.id === id);
  if (!guest) return;

  editingId = id;

  document.getElementById("guestName").value = guest.name;
  document.getElementById("roomNumber").value = guest.room;
  document.getElementById("phone").value = guest.phone || "";

  document.getElementById("bookingSource").value =
    guest.bookingSource || "Direct booking";

  document.getElementById("checkinDate").value = guest.checkin;
  document.getElementById("checkoutDate").value = guest.checkout;

  document.getElementById("adults").value = guest.adults;
  document.getElementById("children").value = guest.children;

  document.getElementById("breakfast").checked =
    Boolean(guest.meals?.breakfast);

  document.getElementById("lunch").checked =
    Boolean(guest.meals?.lunch);

  document.getElementById("dinner").checked =
    Boolean(guest.meals?.dinner);

  document.getElementById("status").value = guest.status;

  document.getElementById("formTitle").textContent =
    "Edit guest details";

  document.getElementById("saveButtonText").textContent =
    "Save Changes";

  document.getElementById("cancelEdit").classList.remove("hidden");

  clearMessage();

  document.getElementById("guestForm").scrollIntoView({
    behavior: "smooth",
    block: "start"
  });
}

// ---------------- DELETE GUEST ----------------

async function deleteGuest(id) {
  const guest = guests.find((item) => item.id === id);
  if (!guest) return;

  if (!confirm(`Delete the record for ${guest.name}, room ${guest.room}?`)) {
    return;
  }

  try {
    await apiRequest(`/api/guests/${id}`, {
      method: "DELETE"
    });

    if (editingId === id) {
      resetForm();
    }

    await loadGuests();
    showMessage("Guest record deleted.", "success");
  } catch (error) {
    showMessage(error.message, "error");
  }
}

// ---------------- DISPLAY HELPERS ----------------

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

function formatDate(value) {
  if (!value) return "—";

  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function mealTag(label, included) {
  const state = included ? "Included" : "Not included";
  const className = included ? "meal-tag" : "meal-tag off";

  return `<span class="${className}">${label}: ${state}</span>`;
}

function statusClassName(status) {
  if (status.startsWith("Expected")) return "status-Expected";
  if (status.startsWith("Checked in")) return "status-Checked-in";
  if (status.startsWith("Checked out")) return "status-Checked-out";

  return "";
}

// ---------------- RENDER GUEST REGISTER ----------------

function renderGuests() {
  const search = document.getElementById("searchInput")
    .value.trim().toLowerCase();

  const statusFilter = document.getElementById("statusFilter").value;

  const filteredGuests = guests.filter((guest) => {
    const matchesSearch =
      guest.name.toLowerCase().includes(search) ||
      guest.room.toLowerCase().includes(search) ||
      (guest.phone || "").toLowerCase().includes(search);

    const matchesStatus =
      statusFilter === "All" || guest.status === statusFilter;

    return matchesSearch && matchesStatus;
  });

  guestCount.textContent = guests.length;

  emptyState.classList.toggle("hidden", filteredGuests.length > 0);
  tableBody.innerHTML = "";

  if (filteredGuests.length === 0) {
    emptyState.querySelector("h3").textContent =
      guests.length === 0
        ? "No guests registered yet"
        : "No matching guests found";

    emptyState.querySelector("p").textContent =
      guests.length === 0
        ? "Add your first guest using the form above."
        : "Try changing your search or status filter.";

    return;
  }

  emptyState.querySelector("h3").textContent =
    "No guests registered yet";

  emptyState.querySelector("p").textContent =
    "Add your first guest using the form above.";

  filteredGuests.forEach((guest) => {
    const meals = guest.meals || {};
    const row = document.createElement("tr");

    row.innerHTML = `
      <td>
        <span class="guest-name">${escapeHTML(guest.name)}</span>
        <span class="subtext">Room ${escapeHTML(guest.room)}</span>
        <span class="subtext">${escapeHTML(guest.phone || "No phone")}</span>
      </td>

      <td>
        <span>${escapeHTML(formatDate(guest.checkin))}</span>
        <span class="subtext">to ${escapeHTML(formatDate(guest.checkout))}</span>
        <span class="subtext">${escapeHTML(guest.bookingSource || "Direct booking")}</span>
      </td>

      <td>
        ${escapeHTML(guest.adults)} adult(s)
        <span class="subtext">${escapeHTML(guest.children)} child(ren)</span>
      </td>

      <td>
        <div class="meal-tags">
          ${mealTag("Breakfast", meals.breakfast)}
          ${mealTag("Lunch", meals.lunch)}
          ${mealTag("Dinner", meals.dinner)}
        </div>
      </td>

      <td>
        <span class="status-pill ${statusClassName(guest.status)}">
          ${escapeHTML(guest.status)}
        </span>
      </td>

      <td>
        <div class="actions">
          <button type="button" class="action-button edit-button">
            Edit
          </button>
          <button type="button" class="action-button delete delete-button">
            Delete
          </button>
        </div>
      </td>
    `;

    row.querySelector(".edit-button").addEventListener("click", () => {
      editGuest(guest.id);
    });

    row.querySelector(".delete-button").addEventListener("click", () => {
      deleteGuest(guest.id);
    });

    tableBody.appendChild(row);
  });
}

// ---------------- SEARCH AND FILTER ----------------

document.getElementById("searchInput")
  .addEventListener("input", renderGuests);

document.getElementById("statusFilter")
  .addEventListener("change", renderGuests);

// ---------------- START APP ----------------

resetForm();
loadGuests();
