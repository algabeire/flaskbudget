import os
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

# --------------------------------------------------
# Load environment variables
# --------------------------------------------------

basedir = Path(__file__).resolve().parent
load_dotenv(basedir / ".env")

# --------------------------------------------------
# Flask configuration
# --------------------------------------------------

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", os.urandom(32))

database_url = (
    os.getenv("DATABASE_URL")
    or os.getenv("SQLALCHEMY_DATABASE_URI")
)

# Fix PostgreSQL URL used by Render/Heroku
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql://",
        1,
    )

app.config["SQLALCHEMY_DATABASE_URI"] = (
    database_url
    or f"sqlite:///{basedir / 'budget.db'}"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    date = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text, nullable=True)

    user = db.relationship(
        "User",
        backref=db.backref("transactions", lazy=True)
    )


with app.app_context():
    print("\n--- DATABASE CONNECTED SUCCESSFULLY ---\n")
    db.create_all()


CATEGORIES = [
    "Groceries",
    "Rent",
    "Transport",
    "Entertainment",
    "Savings",
    "Income",
    "Other",
    "Utilities",
    "Shopping",
    "Telecom",
    "Gift",
    "Eating Out",
]


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def format_currency(value):
    return f"£{value:,.2f}"


@app.context_processor
def inject_helpers():
    return {
        "format_currency": format_currency,
        "categories": CATEGORIES,
    }


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

        user = User(
            username=username,
            password=generate_password_hash(password)
        )

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
    transactions = (
        Transaction.query
        .filter_by(user_id=session["user_id"])
        .order_by(Transaction.date.desc())
        .all()
    )

    summary = (
        db.session.query(
            Transaction.type,
            func.sum(Transaction.amount).label("total")
        )
        .filter_by(user_id=session["user_id"])
        .group_by(Transaction.type)
        .all()
    )

    category_rows = (
        db.session.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total")
        )
        .filter_by(
            user_id=session["user_id"],
            type="expense"
        )
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount).desc())
        .all()
    )

    income = 0.0
    expense = 0.0

    for tx_type, total in summary:
        if tx_type == "income":
            income = total or 0.0
        elif tx_type == "expense":
            expense = total or 0.0

    balance = income - expense

    monthly = {}

    for tx in transactions:
        month = tx.date.strftime("%b %Y")
        monthly.setdefault(month, 0.0)

        if tx.type == "income":
            monthly[month] += tx.amount
        else:
            monthly[month] -= tx.amount

    category_labels = [row[0] for row in category_rows]
    category_values = [float(row[1] or 0) for row in category_rows]

    return render_template(
        "dashboard.html",
        transactions=transactions,
        income=format_currency(income),
        expense=format_currency(expense),
        balance=format_currency(balance),
        monthly=monthly,
        category_labels=category_labels,
        category_values=category_values,
    )


@app.route("/edit/<int:transaction_id>", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id):
    transaction = Transaction.query.filter_by(
        id=transaction_id,
        user_id=session["user_id"]
    ).first()

    if transaction is None:
        flash("Transaction not found.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        title = request.form["title"].strip()
        amount = request.form["amount"].strip()
        category = request.form["category"]
        tx_type = request.form["type"].lower()
        description = request.form.get("description", "").strip()

        if not title or not amount:
            flash("Please add a title and amount.", "warning")
            return redirect(url_for("edit_transaction", transaction_id=transaction_id))

        if category not in CATEGORIES:
            flash("Invalid category.", "danger")
            return redirect(url_for("edit_transaction", transaction_id=transaction_id))

        if tx_type not in ("income", "expense"):
            flash("Invalid transaction type.", "danger")
            return redirect(url_for("edit_transaction", transaction_id=transaction_id))

        try:
            amount_value = float(amount)
            if amount_value <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be greater than zero.", "danger")
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
    )


@app.route("/add", methods=["POST"])
@login_required
def add_transaction_view():
    title = request.form.get("title", "").strip()
    amount = request.form.get("amount", "").strip()
    category = request.form.get("category")
    tx_type = request.form.get("type", "").lower()
    description = request.form.get("description", "").strip()

    if not title or not amount:
        flash("Please enter a title and amount.", "warning")
        return redirect(url_for("dashboard"))

    if category not in CATEGORIES:
        flash("Invalid category.", "danger")
        return redirect(url_for("dashboard"))

    if tx_type not in ("income", "expense"):
        flash("Invalid transaction type.", "danger")
        return redirect(url_for("dashboard"))

    try:
        amount_value = float(amount)
        if amount_value <= 0:
            raise ValueError
    except ValueError:
        flash("Please enter a valid amount greater than zero.", "danger")
        return redirect(url_for("dashboard"))

    transaction = Transaction(
        user_id=session["user_id"],
        title=title,
        amount=amount_value,
        category=category,
        type=tx_type,
        description=description,
    )

    db.session.add(transaction)
    db.session.commit()

    flash("Transaction added successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/delete/<int:transaction_id>", methods=["POST"])
@login_required
def delete_transaction(transaction_id):
    transaction = Transaction.query.filter_by(
        id=transaction_id,
        user_id=session["user_id"]
    ).first()

    if transaction is None:
        flash("Transaction not found.", "danger")
        return redirect(url_for("dashboard"))

    db.session.delete(transaction)
    db.session.commit()

    flash("Transaction deleted successfully.", "success")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)