
from flask import Flask, render_template, request, jsonify
import sqlite3
import pandas as pd
import joblib
from datetime import date

from pathlib import Path
from datetime import date
import csv
import io
import sqlite3
import math
from flask import request, jsonify
import pandas as pd
import joblib
from datetime import date
app = Flask(__name__)

DATABASE = Path(__file__).resolve().parent / "hotel_guests.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn



def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS guests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                room_number TEXT NOT NULL,
                phone_number TEXT,
                booking_source TEXT CHECK (booking_source IN (
                    'Direct booking',
                    'Walk-in',
                    'Online booking',
                    'Travel agent'
                )),
                check_in_date TEXT NOT NULL,
                check_out_date TEXT NOT NULL,
                num_adults INTEGER NOT NULL CHECK (num_adults >= 1),
                num_children INTEGER DEFAULT 0 CHECK (num_children >= 0),
                includes_breakfast INTEGER DEFAULT 0 CHECK (includes_breakfast IN (0, 1)),
                includes_lunch INTEGER DEFAULT 0 CHECK (includes_lunch IN (0, 1)),
                includes_dinner INTEGER DEFAULT 0 CHECK (includes_dinner IN (0, 1)),
                guest_status TEXT NOT NULL CHECK (guest_status IN (
                    'Expected — not arrived',
                    'Checked in — arrived',
                    'Checked out — departed'
                )),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS menu_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Other',
                price_paise INTEGER NOT NULL
                    CHECK (price_paise >= 0),
                active INTEGER NOT NULL DEFAULT 1
                    CHECK (active IN (0, 1)),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)



def guest_to_dict(row):
    return {
        "id": row["id"],
        "name": row["full_name"],
        "room": row["room_number"],
        "phone": row["phone_number"] or "",
        "bookingSource": row["booking_source"],
        "checkin": row["check_in_date"],
        "checkout": row["check_out_date"],
        "adults": row["num_adults"],
        "children": row["num_children"],
        "meals": {
            "breakfast": bool(row["includes_breakfast"]),
            "lunch": bool(row["includes_lunch"]),
            "dinner": bool(row["includes_dinner"])
        },
        "status": row["guest_status"],
        "createdAt": row["created_at"]
    }


def validate_guest(data):
    if not isinstance(data, dict):
        return "Invalid JSON body."

    required = [
        "name", "room", "checkin", "checkout",
        "adults", "children", "meals", "status"
    ]

    for key in required:
        if key not in data:
            return f"Missing field: {key}"

    if not isinstance(data["name"], str) or not data["name"].strip():
        return "Guest name is required."

    if not isinstance(data["room"], str) or not data["room"].strip():
        return "Room number is required."

    try:
        checkin = date.fromisoformat(data["checkin"])
        checkout = date.fromisoformat(data["checkout"])
    except (ValueError, TypeError):
        return "Dates must use YYYY-MM-DD format."

    if checkout <= checkin:
        return "Check-out must be after check-in."

    for field, minimum, maximum in [
        ("adults", 1, 50),
        ("children", 0, 50)
    ]:
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{field} must be a whole number."
        if not minimum <= value <= maximum:
            return f"{field} must be between {minimum} and {maximum}."

    meals = data["meals"]
    if not isinstance(meals, dict):
        return "Meals must be an object."

    for meal in ["breakfast", "lunch", "dinner"]:
        if not isinstance(meals.get(meal), bool):
            return f"{meal} must be true or false."

    if data.get("bookingSource", "Direct booking") not in [
        "Direct booking", "Walk-in", "Online booking", "Travel agent"
    ]:
        return "Invalid booking source."

    if data["status"] not in [
        "Expected — not arrived",
        "Checked in — arrived",
        "Checked out — departed"
    ]:
        return "Invalid guest status."

    phone = data.get("phone", "")
    if not isinstance(phone, str) or len(phone) > 20:
        return "Invalid phone number."

    return None


def room_conflict(conn, data, exclude_id=None):
    query = """
        SELECT id FROM guests
        WHERE LOWER(room_number) = LOWER(?)
          AND guest_status != 'Checked out — departed'
          AND check_in_date < ?
          AND check_out_date > ?
    """
    params = [data["room"].strip(), data["checkout"], data["checkin"]]

    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)

    return conn.execute(query, params).fetchone() is not None


@app.route("/")
def home():
    return render_template(
        "hotel.html",
        title="KitchenSathi | Guest Check-in",
        user="Developer"
    )

@app.route("/menu")
def menu():
    return render_template(
        "menu.html",
        title="KitchenSathi | Menu",
        user="Developer"
    )


@app.route("/api/guests", methods=["GET"])
def get_guests():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM guests ORDER BY id DESC
        """).fetchall()

    return jsonify([guest_to_dict(row) for row in rows])


@app.route("/api/guests", methods=["POST"])
def create_guest():
    data = request.get_json(silent=True)
    error = validate_guest(data)

    if error:
        return jsonify(error=error), 400

    try:
        with get_db() as conn:
            if room_conflict(conn, data):
                return jsonify(
                    error="This room has an overlapping active booking."
                ), 409

            cursor = conn.execute("""
                INSERT INTO guests (
                    full_name, room_number, phone_number, booking_source,
                    check_in_date, check_out_date, num_adults, num_children,
                    includes_breakfast, includes_lunch, includes_dinner,
                    guest_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["name"].strip(),
                data["room"].strip(),
                data.get("phone", "").strip(),
                data.get("bookingSource", "Direct booking"),
                data["checkin"],
                data["checkout"],
                data["adults"],
                data["children"],
                int(data["meals"]["breakfast"]),
                int(data["meals"]["lunch"]),
                int(data["meals"]["dinner"]),
                data["status"]
            ))

            row = conn.execute(
                "SELECT * FROM guests WHERE id = ?",
                (cursor.lastrowid,)
            ).fetchone()

        return jsonify(guest_to_dict(row)), 201

    except sqlite3.Error:
        app.logger.exception("Failed to create guest")
        return jsonify(error="Database error."), 500


@app.route("/api/guests/<int:guest_id>", methods=["PUT"])
def update_guest(guest_id):
    data = request.get_json(silent=True)
    error = validate_guest(data)

    if error:
        return jsonify(error=error), 400

    try:
        with get_db() as conn:
            exists = conn.execute(
                "SELECT id FROM guests WHERE id = ?", (guest_id,)
            ).fetchone()

            if not exists:
                return jsonify(error="Guest not found."), 404

            if room_conflict(conn, data, exclude_id=guest_id):
                return jsonify(
                    error="This room has an overlapping active booking."
                ), 409

            conn.execute("""
                UPDATE guests SET
                    full_name = ?, room_number = ?, phone_number = ?,
                    booking_source = ?, check_in_date = ?,
                    check_out_date = ?, num_adults = ?, num_children = ?,
                    includes_breakfast = ?, includes_lunch = ?,
                    includes_dinner = ?, guest_status = ?
                WHERE id = ?
            """, (
                data["name"].strip(),
                data["room"].strip(),
                data.get("phone", "").strip(),
                data.get("bookingSource", "Direct booking"),
                data["checkin"],
                data["checkout"],
                data["adults"],
                data["children"],
                int(data["meals"]["breakfast"]),
                int(data["meals"]["lunch"]),
                int(data["meals"]["dinner"]),
                data["status"],
                guest_id
            ))

            row = conn.execute(
                "SELECT * FROM guests WHERE id = ?", (guest_id,)
            ).fetchone()

        return jsonify(guest_to_dict(row))

    except sqlite3.Error:
        app.logger.exception("Failed to update guest")
        return jsonify(error="Database error."), 500


@app.route("/api/guests/<int:guest_id>", methods=["DELETE"])
def delete_guest(guest_id):
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "DELETE FROM guests WHERE id = ?", (guest_id,)
            )

            if cursor.rowcount == 0:
                return jsonify(error="Guest not found."), 404

        return jsonify(message="Guest deleted.")

    except sqlite3.Error:
        app.logger.exception("Failed to delete guest")
        return jsonify(error="Database error."), 500



# MENUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUuu

from decimal import Decimal, InvalidOperation


MENU_CATEGORIES = {
    "Breakfast",
    "Main Course",
    "Beverages",
    "Snacks",
    "Desserts",
    "Other"
}


def menu_item_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "price": row["price_paise"] / 100,
        "active": bool(row["active"]),
        "createdAt": row["created_at"]
    }



# ---------------- DEMAND FORECAST ----------------

MODEL_PATH = Path(__file__).resolve().parent / "models" / "item_demand_model.joblib"
TEST_PREDICTIONS_PATH = (
    Path(__file__).resolve().parent / "models" / "item_test_predictions.csv"
)

# Which sale hours belong to each meal.
MEAL_HOURS = {
    "Breakfast": range(5, 12),
    "Lunch": range(12, 17),
    "Dinner": range(17, 24),
}

_saved_model = None


def load_saved_model():
    """Load the trained model once and reuse it."""
    global _saved_model
    if _saved_model is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Model not found: {MODEL_PATH.name}. Run model.py first."
            )
        _saved_model = joblib.load(MODEL_PATH)
    return _saved_model


@app.route("/api/forecast/dashboard-data")
def forecast_dashboard_data():
    if not TEST_PREDICTIONS_PATH.exists():
        return jsonify({
            "error": "models/item_test_predictions.csv not found. Run model.py first."
        }), 404

    df = pd.read_csv(TEST_PREDICTIONS_PATH)

    required = {"date", "quantity", "predicted_quantity"}
    missing = required - set(df.columns)
    if missing:
        return jsonify({
            "error": f"Prediction file is missing columns: {sorted(missing)}"
        }), 500

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "quantity", "predicted_quantity"])

    if df.empty:
        return jsonify({"error": "No valid test predictions found."}), 500

    # Average error per test record (one record = item + date + hour).
    mae = (df["quantity"] - df["predicted_quantity"]).abs().mean()

    # One bar pair per day: total actual vs total predicted units.
    daily = (
        df.groupby(df["date"].dt.strftime("%Y-%m-%d"))[
            ["quantity", "predicted_quantity"]
        ]
        .sum()
        .sort_index()
        .tail(30)
    )

    return jsonify({
        "total_test_rows": int(len(df)),
        "mae": round(float(mae), 2),
        "actual_total": int(round(df["quantity"].sum())),
        "predicted_total": int(round(df["predicted_quantity"].sum())),
        "meals": list(MEAL_HOURS),
        "weather_options": ["Sunny", "Cloudy", "Rainy"],
        "history": [
            {
                "date": day,
                "actual": float(row.quantity),
                "predicted": float(row.predicted_quantity),
            }
            for day, row in daily.iterrows()
        ],
    })

@app.route("/api/menu", methods=["GET"])
def get_menu():
    try:
        with get_db() as conn:
            rows = conn.execute("""
                SELECT *
                FROM menu_items
                WHERE active = 1
                ORDER BY category, name
            """).fetchall()

        return jsonify([menu_item_to_dict(row) for row in rows])

    except sqlite3.Error:
        app.logger.exception("Failed to load menu")
        return jsonify(error="Could not load menu from database."), 500


@app.route("/api/menu", methods=["POST"])
def create_menu_item():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="Invalid JSON body."), 400

    name = data.get("name")
    category = data.get("category", "Other")
    price = data.get("price")

    if not isinstance(name, str) or not name.strip():
        return jsonify(error="Food item name is required."), 400

    if len(name.strip()) > 100:
        return jsonify(error="Food item name is too long."), 400

    if not isinstance(category, str) or category not in MENU_CATEGORIES:
        return jsonify(error="Invalid food category."), 400

    try:
        if isinstance(price, bool) or price is None:
            raise InvalidOperation

        amount = Decimal(str(price))

        if not amount.is_finite() or amount < 0 or amount > 100000:
            raise InvalidOperation

        if amount.as_tuple().exponent < -2:
            raise InvalidOperation

        price_paise = int(amount * 100)

    except (InvalidOperation, ValueError, TypeError):
        return jsonify(
            error="Enter a valid price between ₹0 and ₹100,000, with up to 2 decimal places."
        ), 400

    try:
        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO menu_items (name, category, price_paise)
                VALUES (?, ?, ?)
            """, (name.strip(), category, price_paise))

            row = conn.execute("""
                SELECT * FROM menu_items WHERE id = ?
            """, (cursor.lastrowid,)).fetchone()

        return jsonify(menu_item_to_dict(row)), 201

    except sqlite3.Error:
        app.logger.exception("Failed to create menu item")
        return jsonify(error="Could not save food item."), 500


@app.route("/api/menu/<int:item_id>", methods=["PUT"])
def update_menu_item(item_id):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="Invalid JSON body."), 400

    name = data.get("name")
    category = data.get("category")
    price = data.get("price")

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        return jsonify(error="Enter a valid food item name."), 400

    if not isinstance(category, str) or category not in MENU_CATEGORIES:
        return jsonify(error="Invalid food category."), 400

    try:
        if isinstance(price, bool) or price is None:
            raise InvalidOperation

        amount = Decimal(str(price))

        if (
            not amount.is_finite()
            or amount < 0
            or amount > 100000
            or amount.as_tuple().exponent < -2
        ):
            raise InvalidOperation

        price_paise = int(amount * 100)

    except (InvalidOperation, ValueError, TypeError):
        return jsonify(error="Invalid price."), 400

    try:
        with get_db() as conn:
            cursor = conn.execute("""
                UPDATE menu_items
                SET name = ?, category = ?, price_paise = ?
                WHERE id = ? AND active = 1
            """, (name.strip(), category, price_paise, item_id))

            if cursor.rowcount == 0:
                return jsonify(error="Active menu item not found."), 404

            row = conn.execute("""
                SELECT * FROM menu_items WHERE id = ?
            """, (item_id,)).fetchone()

        return jsonify(menu_item_to_dict(row))

    except sqlite3.Error:
        app.logger.exception("Failed to update menu item")
        return jsonify(error="Could not update food item."), 500


@app.route("/api/menu/<int:item_id>", methods=["DELETE"])
def deactivate_menu_item(item_id):
    try:
        with get_db() as conn:
            cursor = conn.execute("""
                UPDATE menu_items
                SET active = 0
                WHERE id = ? AND active = 1
            """, (item_id,))

            if cursor.rowcount == 0:
                return jsonify(error="Active menu item not found."), 404

        return jsonify(message="Menu item deactivated.")

    except sqlite3.Error:
        app.logger.exception("Failed to deactivate menu item")
        return jsonify(error="Could not deactivate food item."), 500



# ---------------- BILLING & SALES ----------------

PAYMENT_METHODS = {"cash", "upi", "card", "other"}
MEAL_TYPES = {"breakfast", "lunch", "dinner", "other"}
CUSTOMER_TYPES = {"walk_in", "resident"}


def init_billing_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                customer_type TEXT NOT NULL,
                room_number TEXT,
                meal_type TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                subtotal_paise INTEGER NOT NULL,
                discount_paise INTEGER NOT NULL DEFAULT 0,
                total_paise INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS bill_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER NOT NULL,
                menu_item_id INTEGER,
                item_name TEXT NOT NULL,
                unit_price_paise INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                line_total_paise INTEGER NOT NULL,
                FOREIGN KEY (bill_id) REFERENCES bills(id)
                    ON DELETE CASCADE
            )
        """)


# Create the billing tables when the application starts.
init_billing_db()



@app.route("/forecast")
def forecast_dashboard():
    return render_template("forecast.html")


@app.route("/api/bills", methods=["GET"])
def get_bills():
    try:
        with get_db() as conn:
            bills = conn.execute("""
                SELECT * FROM bills
                ORDER BY id DESC
                LIMIT 500
            """).fetchall()

            result = []

            for bill in bills:
                items = conn.execute("""
                    SELECT menu_item_id AS item_id,
                           item_name AS name,
                           unit_price_paise / 100.0 AS price,
                           quantity,
                           line_total_paise / 100.0 AS line_total
                    FROM bill_items
                    WHERE bill_id = ?
                    ORDER BY id
                """, (bill["id"],)).fetchall()

                result.append({
                    "id": bill["id"],
                    "customer_name": bill["customer_name"],
                    "customer_type": bill["customer_type"],
                    "room_number": bill["room_number"],
                    "meal_type": bill["meal_type"],
                    "payment_method": bill["payment_method"],
                    "subtotal": bill["subtotal_paise"] / 100,
                    "discount": bill["discount_paise"] / 100,
                    "total_amount": bill["total_paise"] / 100,
                    "created_at": bill["created_at"],
                    "items": [dict(item) for item in items]
                })

        return jsonify(result)

    except sqlite3.Error:
        app.logger.exception("Could not retrieve bills")
        return jsonify(error="Could not load sales."), 500


@app.route("/api/bills", methods=["POST"])
def create_bill():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(error="Invalid JSON body."), 400

    customer_name = data.get("customer_name", "Walk-in customer")
    customer_type = data.get("customer_type", "walk_in")
    room_number = data.get("room_number")
    meal_type = data.get("meal_type")
    payment_method = data.get("payment_method")
    items = data.get("items")
    discount = data.get("discount", 0)

    if not isinstance(customer_name, str) or not customer_name.strip():
        return jsonify(error="Customer name is required."), 400

    if customer_type not in CUSTOMER_TYPES:
        return jsonify(error="Invalid customer type."), 400

    if customer_type == "resident" and (
        not isinstance(room_number, str) or not room_number.strip()
    ):
        return jsonify(error="Room number is required for resident guests."), 400

    if meal_type not in MEAL_TYPES:
        return jsonify(error="Invalid meal type."), 400

    if payment_method not in PAYMENT_METHODS:
        return jsonify(error="Invalid payment method."), 400

    if not isinstance(items, list) or not items or len(items) > 100:
        return jsonify(error="Add between 1 and 100 bill items."), 400

    try:
        if isinstance(discount, bool):
            raise InvalidOperation

        discount_amount = Decimal(str(discount))

        if (
            not discount_amount.is_finite()
            or discount_amount < 0
            or discount_amount > Decimal("1000000")
            or discount_amount.as_tuple().exponent < -2
        ):
            raise InvalidOperation

        discount_paise = int(discount_amount * 100)

        # Validate quantities and combine duplicate item IDs.
        quantities = {}

        for item in items:
            if not isinstance(item, dict):
                return jsonify(error="Invalid bill item."), 400

            item_id = item.get("item_id")
            quantity = item.get("quantity")

            if (
                isinstance(item_id, bool)
                or not isinstance(item_id, int)
                or item_id <= 0
            ):
                return jsonify(error="Invalid menu item ID."), 400

            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or not 1 <= quantity <= 10000
            ):
                return jsonify(error="Quantity must be between 1 and 10000."), 400

            quantities[item_id] = quantities.get(item_id, 0) + quantity

        if any(qty > 10000 for qty in quantities.values()):
            return jsonify(error="Total quantity for an item is too high."), 400

    except (InvalidOperation, ValueError, TypeError):
        return jsonify(error="Invalid discount amount."), 400

    try:
        with get_db() as conn:
            # Prices always come from the database, never the browser.
            priced_items = []
            subtotal_paise = 0

            for item_id, quantity in quantities.items():
                menu_item = conn.execute("""
                    SELECT id, name, price_paise
                    FROM menu_items
                    WHERE id = ? AND active = 1
                """, (item_id,)).fetchone()

                if menu_item is None:
                    return jsonify(
                        error=f"Menu item {item_id} is unavailable."
                    ), 400

                unit_price = menu_item["price_paise"]
                line_total = unit_price * quantity
                subtotal_paise += line_total

                priced_items.append({
                    "id": menu_item["id"],
                    "name": menu_item["name"],
                    "unit_price": unit_price,
                    "quantity": quantity,
                    "line_total": line_total
                })

            if discount_paise > subtotal_paise:
                return jsonify(
                    error="Discount cannot exceed the subtotal."
                ), 400

            total_paise = subtotal_paise - discount_paise

            cursor = conn.execute("""
                INSERT INTO bills (
                    customer_name, customer_type, room_number,
                    meal_type, payment_method, subtotal_paise,
                    discount_paise, total_paise
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                customer_name.strip(),
                customer_type,
                room_number.strip() if isinstance(room_number, str) else None,
                meal_type,
                payment_method,
                subtotal_paise,
                discount_paise,
                total_paise
            ))

            bill_id = cursor.lastrowid

            for item in priced_items:
                conn.execute("""
                    INSERT INTO bill_items (
                        bill_id, menu_item_id, item_name,
                        unit_price_paise, quantity, line_total_paise
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    bill_id,
                    item["id"],
                    item["name"],
                    item["unit_price"],
                    item["quantity"],
                    item["line_total"]
                ))

        return jsonify({
            "message": "Bill saved successfully.",
            "bill_id": bill_id,
            "subtotal": subtotal_paise / 100,
            "discount": discount_paise / 100,
            "total_amount": total_paise / 100
        }), 201

    except sqlite3.Error:
        app.logger.exception("Could not save bill")
        return jsonify(error="Could not save bill to the database."), 500

# ---------------- BILLING & SALES ----------------

PAYMENT_METHODS = {"cash", "upi", "card", "other"}
MEAL_TYPES = {"breakfast", "lunch", "dinner", "other"}
CUSTOMER_TYPES = {"walk_in", "resident"}


def init_billing_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                customer_type TEXT NOT NULL,
                room_number TEXT,
                meal_type TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                subtotal_paise INTEGER NOT NULL,
                discount_paise INTEGER NOT NULL DEFAULT 0,
                total_paise INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS bill_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER NOT NULL,
                menu_item_id INTEGER,
                item_name TEXT NOT NULL,
                unit_price_paise INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                line_total_paise INTEGER NOT NULL,
                FOREIGN KEY (bill_id) REFERENCES bills(id)
                    ON DELETE CASCADE
            )
        """)


# Create the billing tables when the application starts.
init_billing_db()


@app.route("/billing")
def billing():
    return render_template(
        "billing.html",
        title="KitchenSathi | Billing & Sales",
        user="Developer"
    )


# ---------- CSV SALES IMPORT ----------

MAX_CSV_SIZE = 10 * 1024 * 1024  # 10 MB


def init_imported_sales_db():
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS imported_sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_filename TEXT NOT NULL,
                order_id TEXT,
                sale_date TEXT,
                item_name TEXT,
                item_type TEXT,
                item_price REAL,
                quantity REAL,
                transaction_amount REAL,
                transaction_type TEXT,
                received_by TEXT,
                time_of_sale TEXT,
                imported_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


# Create the table when the app starts.
init_imported_sales_db()


@app.route("/api/sales/import-csv", methods=["POST"])
def import_sales_csv():
    if "file" not in request.files:
        return jsonify({
            "success": False,
            "error": "No CSV file provided."
        }), 400

    file = request.files["file"]

    if not file.filename:
        return jsonify({
            "success": False,
            "error": "Please select a file."
        }), 400

    if not file.filename.lower().endswith(".csv"):
        return jsonify({
            "success": False,
            "error": "Only CSV files are supported."
        }), 400

    # Read at most 10 MB + 1 byte to enforce the limit.
    content = file.stream.read(MAX_CSV_SIZE + 1)

    if len(content) > MAX_CSV_SIZE:
        return jsonify({
            "success": False,
            "error": "CSV file must be smaller than 10 MB."
        }), 413

    try:
        # Handle common CSV encodings from Excel.
        text_data = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text_data = content.decode("cp1252")
        except UnicodeDecodeError:
            return jsonify({
                "success": False,
                "error": "Could not read the CSV encoding. Save it as UTF-8 CSV."
            }), 400

    try:
        reader = csv.DictReader(io.StringIO(text_data))

        if not reader.fieldnames:
            return jsonify({
                "success": False,
                "error": "The CSV file is empty or has no header row."
            }), 400

        # Normalize header names so Quantity, quantity and " Quantity "
        # are treated alike.
        headers = {
            header.strip().lower(): header
            for header in reader.fieldnames
            if header
        }

        # Maps our database fields to accepted CSV column names.
        aliases = {
            "order_id": ["order_id", "order id", "orderid"],
            "sale_date": ["date", "sale_date", "transaction_date"],
            "item_name": ["item_name", "item name", "item"],
            "item_type": ["item_type", "item type", "category"],
            "item_price": ["item_price", "item price", "price"],
            "quantity": ["quantity", "qty"],
            "transaction_amount": [
                "transaction_amount", "transaction amount",
                "amount", "total_amount"
            ],
            "transaction_type": [
                "transaction_type", "transaction type", "payment_method"
            ],
            "received_by": ["received_by", "received by", "cashier"],
            "time_of_sale": ["time_of_sale", "time of sale", "time"]
        }

        resolved = {}

        for field, possible_names in aliases.items():
            for name in possible_names:
                if name in headers:
                    resolved[field] = headers[name]
                    break

        # These fields are essential for useful sales records.
        required = ["item_name", "quantity"]

        missing = [
            field for field in required
            if field not in resolved
        ]

        if missing:
            return jsonify({
                "success": False,
                "error": (
                    "Missing required CSV columns: "
                    + ", ".join(missing)
                    + ". Required columns: item_name and quantity."
                )
            }), 400

        rows_to_insert = []
        errors = []
        MAX_ROWS = 100_000

        for line_number, row in enumerate(reader, start=2):
            if line_number > MAX_ROWS + 1:
                return jsonify({
                    "success": False,
                    "error": f"CSV exceeds the {MAX_ROWS:,}-row limit."
                }), 400

            # Skip completely blank lines.
            if not any(
                str(value or "").strip()
                for value in row.values()
            ):
                continue

            def get_value(field):
                column = resolved.get(field)
                if not column:
                    return None

                value = row.get(column)
                if value is None:
                    return None

                value = value.strip()
                return value if value else None

            def get_number(field):
                value = get_value(field)
                if value is None:
                    return None

                # Remove common currency formatting.
                cleaned = value.replace(",", "").replace("₹", "").strip()

                try:
                    number = float(cleaned)
                    if not math.isfinite(number):
                        raise ValueError()
                    return number
                except ValueError:
                    raise ValueError(
                        f"Invalid number in {field}: {value}"
                    )

            try:
                item_name = get_value("item_name")
                quantity = get_number("quantity")

                if not item_name:
                    raise ValueError("Item name is empty.")

                if quantity is None or quantity <= 0:
                    raise ValueError("Quantity must be greater than zero.")

                item_price = get_number("item_price")
                amount = get_number("transaction_amount")

                if item_price is not None and item_price < 0:
                    raise ValueError("Item price cannot be negative.")

                if amount is not None and amount < 0:
                    raise ValueError("Transaction amount cannot be negative.")

                rows_to_insert.append((
                    file.filename,
                    get_value("order_id"),
                    get_value("sale_date"),
                    item_name,
                    get_value("item_type"),
                    item_price,
                    quantity,
                    amount,
                    get_value("transaction_type"),
                    get_value("received_by"),
                    get_value("time_of_sale")
                ))

            except ValueError as exc:
                if len(errors) < 10:
                    errors.append({
                        "row": line_number,
                        "error": str(exc)
                    })

        if errors:
            return jsonify({
                "success": False,
                "error": "CSV validation failed. No rows were imported.",
                "details": errors
            }), 400

        if not rows_to_insert:
            return jsonify({
                "success": False,
                "error": "No valid sales rows found in the CSV."
            }), 400

        conn = get_db()

        try:
            conn.executemany("""
                INSERT INTO imported_sales (
                    source_filename,
                    order_id,
                    sale_date,
                    item_name,
                    item_type,
                    item_price,
                    quantity,
                    transaction_amount,
                    transaction_type,
                    received_by,
                    time_of_sale
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows_to_insert)

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

        return jsonify({
            "success": True,
            "message": "Sales CSV imported successfully.",
            "rows_imported": len(rows_to_insert),
            "filename": file.filename
        }), 201

    except csv.Error:
        return jsonify({
            "success": False,
            "error": "The CSV file could not be parsed."
        }), 400

    except Exception:
        app.logger.exception("CSV sales import failed")
        return jsonify({
            "success": False,
            "error": "An internal error occurred while importing the CSV."
        }), 500



@app.route("/api/forecast/predict", methods=["POST"])
def predict_demand():
    data = request.get_json(silent=True) or {}

    try:
        selected_date = date.fromisoformat(str(data.get("date", "")))
    except ValueError:
        return jsonify({"error": "Choose a valid forecast date."}), 400

    meal = data.get("meal")
    if meal not in MEAL_HOURS:
        return jsonify({"error": "Meal must be Breakfast, Lunch or Dinner."}), 400

    try:
        saved = load_saved_model()
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404

    model = saved["model"]
    features = saved["features"]
    item_types = {
        item["item_name"]: item["item_type"] for item in saved["items"]
    }

    # Which (item, hour) combinations really sold, and on what share of days.
    # The model was trained only on hours when something sold, so each
    # prediction is weighted by how often that item sells at that hour.
    with get_db() as conn:
        sales = pd.read_sql_query(
            "SELECT sale_date, time_of_sale, item_name FROM imported_sales",
            conn,
        )

    sales["hour"] = pd.to_datetime(
        sales["time_of_sale"], format="%H:%M", errors="coerce"
    ).dt.hour
    sales = sales.dropna(subset=["sale_date", "hour", "item_name"])
    sales["item_name"] = sales["item_name"].astype(str).str.strip()
    sales["hour"] = sales["hour"].astype(int)

    total_days = sales["sale_date"].nunique()
    sales = sales[sales["hour"].isin(MEAL_HOURS[meal])]
    sales = sales[sales["item_name"].isin(item_types)]

    if total_days == 0 or sales.empty:
        return jsonify({
            "error": f"No past {meal.lower()} sales found. "
                     "Import a sales CSV on the Billing page first."
        }), 404

    combos = (
        sales.groupby(["item_name", "hour"])["sale_date"]
        .nunique()
        .reset_index(name="days_sold")
    )
    combos["share"] = combos["days_sold"] / total_days

    weekday = selected_date.weekday()
    rows = pd.DataFrame({
        "item_name": combos["item_name"],
        "item_type": combos["item_name"].map(item_types),
        "hour": combos["hour"],
        "weekday": weekday,
        "month": selected_date.month,
        "day": selected_date.day,
        "is_weekend": int(weekday >= 5),
    })[features]

    combos["expected"] = (
        pd.Series(model.predict(rows), index=combos.index).clip(lower=0)
        * combos["share"]
    )

    per_item = (
        combos.groupby("item_name")["expected"].sum()
        .sort_values(ascending=False)
    )

    return jsonify({
        "date": selected_date.isoformat(),
        "meal": meal,
        "predicted_covers": int(round(per_item.sum())),
        "items": [
            {"name": name, "quantity": round(float(qty), 1)}
            for name, qty in per_item.items()
            if qty >= 0.05
        ],
        "note": "Estimate from past sales patterns (item, hour, weekday, "
                "date). Weather, occupancy and events are not used yet.",
    })


@app.route("/api/sales/imported", methods=["GET"])
def get_imported_sales():
    try:
        with get_db() as conn:
            rows = conn.execute("""
                SELECT
                    id,
                    source_filename,
                    order_id,
                    sale_date,
                    item_name,
                    item_type,
                    item_price,
                    quantity,
                    transaction_amount,
                    transaction_type,
                    received_by,
                    time_of_sale,
                    imported_at
                FROM imported_sales
                ORDER BY sale_date DESC, id DESC
            """).fetchall()

        return jsonify([dict(row) for row in rows])

    except sqlite3.Error:
        app.logger.exception("Could not load imported sales")
        return jsonify(error="Could not load imported sales."), 500



# Sign up / log in. Every page and API route below requires a logged-in user.
from auth import init_auth
init_auth(app)

# Initialize the database once when the application starts.
init_db()




if __name__ == "__main__":
    app.run(debug=True)
