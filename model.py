
from pathlib import Path
import sqlite3

import joblib
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "hotel_guests.db"
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

# 1. Load imported historical sales from SQLite.
with sqlite3.connect(DB_PATH) as connection:
    df = pd.read_sql_query(
        """
        SELECT sale_date, time_of_sale, item_name, item_type, quantity
        FROM imported_sales
        """,
        connection,
    )

if df.empty:
    raise ValueError("No imported sales found. Import a sales CSV first.")

# 2. Clean the data.
df["sale_date"] = pd.to_datetime(df["sale_date"], errors="coerce")
df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
df = df.dropna(
    subset=["sale_date", "quantity", "item_name", "time_of_sale"]
)
df = df[df["quantity"] >= 0].copy()

for column in ["item_name", "item_type", "time_of_sale"]:
    df[column] = df[column].fillna("Unknown").astype(str).str.strip()

# Normalize timestamps into hour slots, e.g. 19:30 -> 19.
parsed_time = pd.to_datetime(
    df["time_of_sale"], format="%H:%M", errors="coerce"
)
df["hour"] = parsed_time.dt.hour
df = df.dropna(subset=["hour"])
df["hour"] = df["hour"].astype(int)

df["date"] = df["sale_date"].dt.normalize()
df["weekday"] = df["date"].dt.dayofweek
df["month"] = df["date"].dt.month
df["day"] = df["date"].dt.day
df["is_weekend"] = (df["weekday"] >= 5).astype(int)

# 3. Aggregate duplicate bill lines for the same item/date/hour.
daily_items = (
    df.groupby(
        [
            "date", "item_name", "item_type", "hour",
            "weekday", "month", "day", "is_weekend",
        ],
        as_index=False,
    )["quantity"]
    .sum()
    .sort_values("date")
)

if daily_items["date"].nunique() < 10:
    raise ValueError(
        "Need at least 10 distinct sales dates to make a basic train/test split. "
        "Import more historical sales first."
    )

# 4. Split chronologically: older dates train, newer dates test.
dates = sorted(daily_items["date"].unique())
split_index = max(1, int(len(dates) * 0.8))
split_index = min(split_index, len(dates) - 1)
test_start = dates[split_index]

train = daily_items[daily_items["date"] < test_start].copy()
test = daily_items[daily_items["date"] >= test_start].copy()

categorical_features = ["item_name", "item_type"]
numeric_features = [
    "hour", "weekday", "month", "day", "is_weekend"
]
features = categorical_features + numeric_features

preprocessor = ColumnTransformer(
    transformers=[
        (
            "categorical",
            OneHotEncoder(handle_unknown="ignore"),
            categorical_features,
        ),
        ("numeric", SimpleImputer(strategy="median"), numeric_features),
    ]
)

# 5. Train the Random Forest model.
model = Pipeline(
    steps=[
        ("preprocessor", preprocessor),
        (
            "regressor",
            RandomForestRegressor(
                n_estimators=200,
                max_depth=12,
                min_samples_leaf=2,
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ]
)

X_train = train[features]
y_train = train["quantity"]
X_test = test[features]
y_test = test["quantity"]

model.fit(X_train, y_train)
predictions = model.predict(X_test)

# 6. Evaluate on dates excluded from training.
mae = mean_absolute_error(y_test, predictions)
r2 = r2_score(y_test, predictions) if len(y_test) >= 2 else float("nan")

print("Training rows:", len(train))
print("Testing rows:", len(test))
print("Test period starts:", pd.Timestamp(test_start).date())
print("MAE:", round(mae, 3), "units")
print("R²:", round(r2, 3) if pd.notna(r2) else "Not available")

# 7. Save model and known menu items.
joblib.dump(
    {
        "model": model,
        "features": features,
        "items": (
            daily_items[["item_name", "item_type"]]
            .drop_duplicates()
            .to_dict(orient="records")
        ),
        "hours": sorted(daily_items["hour"].unique().tolist()),
    },
    MODEL_DIR / "item_demand_model.joblib",
)

test_results = test[["date", "item_name", "hour", "quantity"]].copy()
test_results["predicted_quantity"] = predictions.clip(min=0).round(2)
test_results.to_csv(MODEL_DIR / "item_test_predictions.csv", index=False)

print("Saved model:", MODEL_DIR / "item_demand_model.joblib")
print("Saved test results:", MODEL_DIR / "item_test_predictions.csv")


import numpy as np
from sklearn.dummy import DummyRegressor

baseline = DummyRegressor(strategy="mean")
baseline.fit(X_train, y_train)
baseline_predictions = baseline.predict(X_test)

print("\n--- MODEL DIAGNOSTICS ---")
print("Training target mean:", round(y_train.mean(), 2))
print("Training target std:", round(y_train.std(), 2))
print("Test target mean:", round(y_test.mean(), 2))
print("Test target std:", round(y_test.std(), 2))
print("Baseline MAE:", round(
    mean_absolute_error(y_test, baseline_predictions), 3
))
print("Random Forest MAE:", round(
    mean_absolute_error(y_test, predictions), 3
))
print("Actual test quantity range:",
      y_test.min(), "to", y_test.max())
print("Unique items in train:", train["item_name"].nunique())
print("Unique items in test:", test["item_name"].nunique())
print("Test dates:", test["date"].nunique())
print("Negative predictions:", int((predictions < 0).sum()))
