
const $ = (id) => document.getElementById(id);

const formatNumber = (value) =>
  Number(value).toLocaleString("en-IN", {
    maximumFractionDigits: 1
  });

$("today").textContent = new Date().toLocaleDateString("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric"
});

$("forecastDate").value = new Date().toLocaleDateString("en-CA");

let dashboardData = null;

// -------------------------------
// LOAD DASHBOARD METRICS & RESULTS
// -------------------------------
async function loadDashboard() {
  try {
    const response = await fetch("/api/forecast/dashboard-data");
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Could not load dashboard.");
    }

    dashboardData = data;

    $("testRows").textContent = formatNumber(data.total_test_rows);
    $("mae").textContent = formatNumber(data.mae);
    $("actualTotal").textContent = formatNumber(data.actual_total);
    $("predictedTotal").textContent = formatNumber(data.predicted_total);

    // Populate meal options if the API provides them.
    const mealSelect = $("meal");

if (mealSelect) {
  mealSelect.replaceChildren();

  ["Breakfast", "Lunch", "Dinner"].forEach((meal) => {
    mealSelect.add(new Option(meal, meal));
  });
}

    // Populate weather options if the API provides them.
    const weatherSelect = $("weather");
    if (weatherSelect && Array.isArray(data.weather_options)) {
      weatherSelect.replaceChildren();
      data.weather_options.forEach((weather) => {
        weatherSelect.add(new Option(weather, weather));
      });
    }

    // Render actual vs predicted table.
    const body = $("resultsBody");
    body.replaceChildren();

    (data.history || []).slice().reverse().forEach((row) => {
      const tr = document.createElement("tr");
      const error = Math.abs(row.actual - row.predicted);

      [
        row.date,
        formatNumber(row.actual),
        formatNumber(row.predicted),
        formatNumber(error)
      ].forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });

      body.appendChild(tr);
    });

    if (!data.history || data.history.length === 0) {
      body.innerHTML =
        '<tr><td colspan="4">No test results available.</td></tr>';
    }

    drawChart(data.history || []);
  } catch (error) {
    console.error("Dashboard loading error:", error);

    $("resultsBody").innerHTML =
      `<tr><td colspan="4">${escapeHtml(error.message)}</td></tr>`;
  }
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

// -------------------------------
// DRAW ACTUAL VS PREDICTED CHART
// -------------------------------
function drawChart(rows) {
  const canvas = $("demandChart");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;

  canvas.width = Math.max(1, rect.width * ratio);
  canvas.height = Math.max(1, rect.height * ratio);

  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

  const width = rect.width;
  const height = rect.height;

  ctx.clearRect(0, 0, width, height);

  if (!rows.length) {
    ctx.fillStyle = "#77827b";
    ctx.font = "13px sans-serif";
    ctx.fillText("No predictions available yet.", 15, 30);
    return;
  }

  const left = 38;
  const right = 12;
  const top = 12;
  const bottom = 42;

  const plotWidth = Math.max(1, width - left - right);
  const plotHeight = Math.max(1, height - top - bottom);

  const maxValue =
    Math.max(
      1,
      ...rows.map((row) =>
        Math.max(Number(row.actual), Number(row.predicted))
      )
    ) * 1.15;

  ctx.font = "10px sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= 4; i++) {
    const y = top + (plotHeight * i) / 4;
    const value = maxValue * (1 - i / 4);

    ctx.strokeStyle = "#e8ede9";
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();

    ctx.fillStyle = "#77827b";
    ctx.fillText(String(Math.round(value)), left - 7, y);
  }

  const groupWidth = plotWidth / rows.length;
  const barWidth = Math.max(1, Math.min(12, groupWidth * 0.32));

  rows.forEach((row, index) => {
    const center = left + groupWidth * (index + 0.5);

    const actualHeight =
      (Number(row.actual) / maxValue) * plotHeight;

    const predictedHeight =
      (Number(row.predicted) / maxValue) * plotHeight;

    ctx.fillStyle = "#18794e";
    ctx.fillRect(
      center - barWidth - 1,
      top + plotHeight - actualHeight,
      barWidth,
      actualHeight
    );

    ctx.fillStyle = "#e5a33d";
    ctx.fillRect(
      center + 1,
      top + plotHeight - predictedHeight,
      barWidth,
      predictedHeight
    );

    if (
      rows.length <= 15 ||
      index % Math.ceil(rows.length / 8) === 0
    ) {
      ctx.fillStyle = "#77827b";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(
        String(row.date).slice(5),
        center,
        top + plotHeight + 9
      );
    }
  });
}

// -------------------------------
// GENERATE RESORT DEMAND FORECAST
// -------------------------------
async function generateResortForecast() {
  const button = $("forecastButton");
  const result = $("forecastResult");

  button.disabled = true;
  button.textContent = "Predicting…";

  result.classList.remove("hidden");
  result.textContent = "Generating forecast…";

  try {
    const payload = {
      date: $("forecastDate").value,
      meal: $("meal").value,
      occupancy_pct: Number($("occupancy").value),
      event: Number($("event").value),
      weather: $("weather").value
    };

    if (!payload.date) {
      throw new Error("Please select a forecast date.");
    }

    if (
      !Number.isFinite(payload.occupancy_pct) ||
      payload.occupancy_pct < 0 ||
      payload.occupancy_pct > 100
    ) {
      throw new Error("Occupancy must be between 0 and 100.");
    }

    if (![0, 1].includes(payload.event)) {
      throw new Error("Event must be 0 or 1.");
    }

    const response = await fetch("/api/forecast/predict", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Forecast failed.");
    }

    // Update the large blue prediction number.
    $("expectedOrders").textContent =
      formatNumber(data.predicted_covers);

    // Update its description.
    $("demandFootnote").textContent =
      `Forecast for ${data.date} · ${data.meal}. ` +
      "Estimate based on the trained historical demand model.";

    // Show the forecast result below the form.
    result.replaceChildren();

    const heading = document.createElement("div");
    heading.textContent = `${data.meal} · ${data.date}`;

    const number = document.createElement("strong");
    number.textContent =
      `${formatNumber(data.predicted_covers)} expected diners`;

    const note = document.createElement("p");
    note.textContent =
      "This is a demand estimate, not a guaranteed number of diners.";

    result.append(heading, number, note);
  } catch (error) {
    console.error("Forecast error:", error);
    result.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Generate forecast";
  }
}

// -------------------------------
// FORM EVENTS
// -------------------------------
$("forecastForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await generateResortForecast();
});

window.addEventListener("resize", () => {
  if (dashboardData) {
    drawChart(dashboardData.history || []);
  }
});

// Initial page load.
loadDashboard();
