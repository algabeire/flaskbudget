import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy  # Added for Supabase
from dotenv import load_dotenv           # Added to read your .env file

# Load your verified cloud database link from .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretbudgetkey")

# Configure your new Supabase PostgreSQL connection
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the SQLAlchemy interface tool
db = SQLAlchemy(app)

CATEGORIES = [
    "Groceries",
    "Bills",
    "Rent",
    "Transport",
    "Entertainment",
    "Savings",
    "Income",
    "Other",
]

# Legacy SQLite connection function - we will migrate this next!
def get_db_connection():
    # We will safely remove this once your new database models are set up
    pass



def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            description TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    conn.commit()
    conn.close()


def setup():
    init_db()


def login_required(view):
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(**kwargs)

    wrapped_view.__name__ = view.__name__
    return wrapped_view


def format_currency(value):
    return f"£{value:,.2f}"


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        if not username or not password:
            flash("Please enter a username and password.", "warning")
            return redirect(url_for("register"))

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            conn.commit()
            flash("Registration successful. You can now log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That username is already taken.", "danger")
            return redirect(url_for("register"))
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password"], password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db_connection()
    transactions = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC",
        (session["user_id"],),
    ).fetchall()

    summary = conn.execute(
        "SELECT type, SUM(amount) as total FROM transactions WHERE user_id = ? GROUP BY type",
        (session["user_id"],),
    ).fetchall()
    category_rows = conn.execute(
        "SELECT category, SUM(amount) AS total FROM transactions WHERE user_id = ? AND type = 'expense' GROUP BY category ORDER BY total DESC",
        (session["user_id"],),
    ).fetchall()
    conn.close()

    income = 0.0
    expense = 0.0
    for row in summary:
        if row["type"] == "income":
            income = row["total"] or 0.0
        else:
            expense = row["total"] or 0.0

    balance = income - expense

    monthly = {}
    for tx in transactions:
        month = datetime.fromisoformat(tx["date"]).strftime("%b %Y")
        monthly.setdefault(month, 0.0)
        monthly[month] += tx["amount"] if tx["type"] == "income" else -tx["amount"]

    category_labels = [row["category"] for row in category_rows]
    category_values = [row["total"] or 0.0 for row in category_rows]

    return render_template(
        "dashboard.html",
        transactions=transactions,
        income=format_currency(income),
        expense=format_currency(expense),
        balance=format_currency(balance),
        monthly=monthly,
        format_currency=format_currency,
        categories=CATEGORIES,
        category_labels=category_labels,
        category_values=category_values,
    )


@app.route("/edit/<int:transaction_id>", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id):
    conn = get_db_connection()
    transaction = conn.execute(
        "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, session["user_id"]),
    ).fetchone()

    if transaction is None:
        conn.close()
        flash("Transaction not found.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        title = request.form["title"].strip()
        amount = request.form["amount"].strip()
        category = request.form["category"]
        tx_type = request.form["type"]
        description = request.form.get("description", "").strip()

        if not title or not amount:
            flash("Please add a title and amount.", "warning")
            conn.close()
            return redirect(url_for("edit_transaction", transaction_id=transaction_id))

        try:
            amount_value = abs(float(amount))
        except ValueError:
            flash("Please enter a valid number for amount.", "danger")
            conn.close()
            return redirect(url_for("edit_transaction", transaction_id=transaction_id))

        conn.execute(
            "UPDATE transactions SET title = ?, amount = ?, category = ?, type = ?, description = ? WHERE id = ? AND user_id = ?",
            (
                title,
                amount_value,
                category,
                tx_type,
                description,
                transaction_id,
                session["user_id"],
            ),
        )
        conn.commit()
        conn.close()

        flash("Transaction updated successfully.", "success")
        return redirect(url_for("dashboard"))

    conn.close()
    return render_template(
        "edit_expense.html",
        transaction=transaction,
        categories=CATEGORIES,
    )


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_transaction():
    if request.method == "POST":
        title = request.form["title"].strip()
        amount = request.form["amount"].strip()
        category = request.form["category"]
        tx_type = request.form["type"]
        description = request.form.get("description", "").strip()

        if not title or not amount:
            flash("Please add a title and amount.", "warning")
            return redirect(url_for("add_transaction"))

        try:
            amount_value = abs(float(amount))
        except ValueError:
            flash("Please enter a valid number for amount.", "danger")
            return redirect(url_for("add_transaction"))

        conn = get_db_connection()
        conn.execute(
            "INSERT INTO transactions (user_id, title, amount, category, date, type, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session["user_id"],
                title,
                amount_value,
                category,
                datetime.utcnow().date().isoformat(),
                tx_type,
                description,
            ),
        )
        conn.commit()
        conn.close()

        flash("Transaction added successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_expense.html", categories=CATEGORIES)


@app.route("/delete/<int:transaction_id>")
@login_required
def delete_transaction(transaction_id):
    conn = get_db_connection()
    conn.execute(
        "DELETE FROM transactions WHERE id = ? AND user_id = ?",
        (transaction_id, session["user_id"]),
    )
    conn.commit()
    conn.close()
    flash("Transaction removed.", "info")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    setup()
    app.run(debug=True)
