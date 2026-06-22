import os
import re
import sys
from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()


def normalize_database_url(url: str) -> str:
    """Remove an empty port segment like host:/path from a Postgres URL."""
    if not url:
        return url
    return re.sub(r"(@[^:/]+):(?=/)", r"\1", url)


def get_database_url() -> str:
    raw_url = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URI")
    if not raw_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Set Render environment variable DATABASE_URL to your Postgres URI."
        )
    return normalize_database_url(raw_url.strip())


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretbudgetkey")
app.config["SQLALCHEMY_DATABASE_URI"] = get_database_url()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    user = db.relationship("User", backref="transactions")

with app.app_context():
    db.create_all()

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

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash("That username is already taken.", "danger")
            return redirect(url_for("register"))

        user = User(username=username, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        user = User.query.filter_by(username=username).first()

        if user is None or not check_password_hash(user.password, password):
            flash("Invalid username or password.", "danger")
            return redirect(url_for("login"))

        session.clear()
        session["user_id"] = user.id
        session["username"] = user.username
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
    transactions = Transaction.query.filter_by(user_id=session["user_id"]).order_by(Transaction.date.desc()).all()

    summary = (
        db.session.query(Transaction.type, func.sum(Transaction.amount).label("total"))
        .filter_by(user_id=session["user_id"])
        .group_by(Transaction.type)
        .all()
    )

    category_rows = (
        db.session.query(Transaction.category, func.sum(Transaction.amount).label("total"))
        .filter_by(user_id=session["user_id"], type="expense")
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount).desc())
        .all()
    )

    income = 0.0
    expense = 0.0
    for type_, total in summary:
        if type_ == "income":
            income = total or 0.0
        else:
            expense = total or 0.0

    balance = income - expense

    monthly = {}
    for tx in transactions:
        tx_date = tx.date
        if isinstance(tx_date, str):
            tx_date = datetime.fromisoformat(tx_date)
        month = tx_date.strftime("%b %Y")
        monthly.setdefault(month, 0.0)
        monthly[month] += tx.amount if tx.type == "income" else -tx.amount

    category_labels = [row[0] for row in category_rows]
    category_values = [row[1] or 0.0 for row in category_rows]

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
    transaction = Transaction.query.filter_by(id=transaction_id, user_id=session["user_id"]).first()

    if transaction is None:
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
            return redirect(url_for("edit_transaction", transaction_id=transaction_id))

        try:
            amount_value = abs(float(amount))
        except ValueError:
            flash("Please enter a valid number for amount.", "danger")
            return redirect(url_for("edit_transaction", transaction_id=transaction_id))

        transaction.title = title
        transaction.amount = amount_value
        transaction.category = category
        transaction.type = tx_type
        transaction.description = description
        db.session.commit()

        flash("Transaction updated successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "edit_expense.html",
        transaction=transaction,
        categories=CATEGORIES,
    )


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_transaction():
    if request.method == "POST":
        try:
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

            transaction = Transaction(
                user_id=session.get("user_id"),
                title=title,
                amount=amount_value,
                category=category,
                date=datetime.now(timezone.utc),
                type=tx_type,
                description=description,
            )
            db.session.add(transaction)
            db.session.commit()

            flash("Transaction added successfully.", "success")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            # Roll back and log the exception so the deploy doesn't return a generic 500 without details
            try:
                db.session.rollback()
            except Exception:
                pass
            print("Error saving transaction:", exc, file=sys.stderr)
            flash(f"Could not save transaction: {exc}", "danger")
            return redirect(url_for("add_transaction"))

    return render_template("add_expense.html", categories=CATEGORIES)


@app.route("/delete/<int:transaction_id>")
@login_required
def delete_transaction(transaction_id):
    transaction = Transaction.query.filter_by(id=transaction_id, user_id=session["user_id"]).first()
    if transaction:
        db.session.delete(transaction)
        db.session.commit()
    flash("Transaction removed.", "info")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
