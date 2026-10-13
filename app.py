
from flask import Flask, render_template, request, jsonify
import sqlite3
from pathlib import Path
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

# Initialize the database once when the application starts.
init_db()




if __name__ == "__main__":
    app.run(debug=True)
