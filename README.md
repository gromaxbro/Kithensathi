# KitchenSathi 🍽️

**AI-powered food demand forecasting and kitchen planning for hotels and resorts.**

KitchenSathi helps hospitality businesses estimate how many guests will dine during breakfast, lunch, and dinner so they can plan food preparation, reduce overproduction, and make better kitchen decisions.

## 🎯 Problem Statement

Hotels and resorts often struggle to estimate meal demand accurately. Preparing too much food can lead to wastage, while preparing too little can affect guest satisfaction.

KitchenSathi aims to make kitchen planning more data-driven by combining guest information, occupancy, and contextual factors to forecast expected meal covers.

## ✨ Features

- **Guest Management:** Manage guest details, room numbers, check-in/check-out dates, and meal plans.
- **Menu Management:** Maintain menu items, categories, prices, and availability.
- **Billing & Sales:** Create bills, record transactions, and track sales.
- **Sales CSV Import:** Import historical restaurant sales data for analysis.
- **AI Demand Forecasting:** Predict expected meal covers using occupancy, meal type, weather, events, weekday, and month.
- **Forecast Evaluation:** Compare predictions against actual covers using Mean Absolute Error (MAE).
- **Kitchen Planning:** Use demand forecasts to support food preparation and reduce overproduction.

## 🧠 Machine Learning

KitchenSathi uses a Random Forest Regression model to estimate the number of expected meal covers.

**Input features**
- Meal type: Breakfast, Lunch, or Dinner
- Hotel occupancy percentage
- Event indicator
- Weather
- Day of the week
- Month

**Prediction output:** Expected meal covers for the selected meal period.

The model is trained using historical cover data from `datasets/overs.csv`.

Model evaluation includes:
- Mean Absolute Error (MAE)
- Comparison against a mean-based baseline model

> **Note:** Forecast quality depends on the amount, quality, and representativeness of the training data. Results from synthetic or demonstration datasets do not establish real-world accuracy.

## 🛠️ Technology Stack

- **Backend:** Python, Flask
- **Frontend:** HTML, CSS, JavaScript
- **Database:** SQLite
- **Machine Learning:** scikit-learn, pandas, NumPy
- **Model Persistence:** joblib
- **Version Control:** Git and GitHub

## 📁 Project Structure

```text
kitchensathi/
└── webiste/
    ├── app.py
    ├── model.py
    ├── hotel_guests.db
    ├── templates/
    │   └── hotel.html
    ├── static/
    │   ├── css/
    │   ├── js/
    │   └── ...
    ├── datasets/
    │   └── overs.csv
    └── models/
        ├── kitchensathi_model.joblib
        └── test_predictions.csv
```

*The structure above is indicative; adjust it to match the files actually present in your repository.*

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/gromaxbro/Kithensathi.git
cd Kithensathi/webiste
```

### 2. Create and activate a virtual environment

**Linux**

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install flask pandas numpy scikit-learn joblib
```

If your project has a `requirements.txt`, use:

```bash
pip install -r requirements.txt
```

### 4. Prepare the dataset

Place the training dataset at:

```text
datasets/overs.csv
```

It should contain the following columns:

```text
date, meal, occupancy_pct, event, weather, weekday, month, actual_covers
```

Ensure that the data uses consistent formats and that `actual_covers` contains the actual number of diners for each meal period.

### 5. Train the forecasting model

From the directory containing `model.py`, run:

```bash
python model.py
```

The script should train and evaluate the model and save the model artifact and test predictions in the configured output directory.

### 6. Run the Flask application

```bash
python app.py
```

Open the local address printed by Flask in your browser, commonly:

```text
http://127.0.0.1:5000
```

## 📊 How It Works

1. Enter or import available hotel, guest, and sales information.
2. Provide the expected occupancy and meal-period details.
3. Generate a forecast of expected meal covers.
4. Use the forecast to support kitchen preparation decisions.
5. Record actual demand and compare it with the forecast to evaluate performance.

## 🔮 Future Improvements

- Ingredient-level quantity estimation from forecasted covers.
- Food waste and leftover tracking.
- Weather and local-event data integration.
- Historical demand trends and seasonal analysis.
- Forecast accuracy dashboards.
- Recommendations for kitchen preparation and inventory planning.
- Support for multiple hotels and resorts.

## ⚠️ Data & Privacy

Use authorized datasets and protect guest information. Do not commit production databases, personal guest records, API keys, passwords, access tokens, or other secrets to a public repository.

## 👥 Project

KitchenSathi is a hospitality technology project focused on smarter food demand forecasting and kitchen operations.

**Goal:** Help hotels prepare the right amount of food for the expected demand.
