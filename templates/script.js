
const form = document.getElementById("kitchenForm");
const occupancyInput = document.getElementById("occupancy");
const occupancyValue = document.getElementById("occupancyValue");
const result = document.getElementById("result");

const selections = {
  meal: "Breakfast",
  weather: "Pleasant",
  event: "No"
};

// Handle all selection buttons.
document.querySelectorAll("[data-group]").forEach((button) => {
  button.addEventListener("click", () => {
    const group = button.dataset.group;
    const value = button.dataset.value;

    selections[group] = value;

    // Highlight the selected button in this group.
    document.querySelectorAll(`[data-group="${group}"]`).forEach((item) => {
      item.classList.toggle("selected", item === button);
    });

    result.classList.add("hidden");
  });
});

// Update the occupancy percentage as the slider moves.
occupancyInput.addEventListener("input", () => {
  occupancyValue.textContent = occupancyInput.value;
  result.classList.add("hidden");
});

// Make the demo kitchen plan.
form.addEventListener("submit", (event) => {
  event.preventDefault();

  const occupancy = Number(occupancyInput.value);

  // Temporary demo formula, not an ML prediction.
  let estimatedGuests = Math.round(40 * occupancy / 100 * 0.8);

  // Illustrative adjustment for a special event.
  if (selections.event === "Yes") {
    estimatedGuests = Math.round(estimatedGuests * 1.2);
  }

  document.getElementById("resultTitle").textContent =
    `${selections.meal} plan is ready!`;

  document.getElementById("guestCount").textContent =
    estimatedGuests;

  document.getElementById("resultMessage").textContent =
    `Your property is ${occupancy}% occupied. ` +
    `Weather: ${selections.weather}. ` +
    `Prepare for approximately ${estimatedGuests} diners, ` +
    `then check your bookings before cooking.`;

  result.classList.remove("hidden");

  result.scrollIntoView({
    behavior: "smooth",
    block: "nearest"
  });
});
