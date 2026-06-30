import os
import socket
from urllib.parse import urlparse

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
# Use DATABASE_URL from the environment, or replace the placeholder with your connection string.
database_url = os.getenv("DATABASE_URL", "postgresql://user:password@host:port/database")
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


def resolve_host_from_url(url):
    parsed = urlparse(url)
    return parsed.hostname


def check_dns(hostname):
    try:
        ip = socket.gethostbyname(hostname)
        print(f"✅ DNS resolution succeeded: {hostname} -> {ip}")
        return True
    except Exception as exc:
        print(f"❌ DNS resolution failed for {hostname}: {exc}")
        return False


if __name__ == "__main__":
    host = resolve_host_from_url(database_url)
    if not host:
        print("❌ Could not parse hostname from DATABASE_URL.")
        raise SystemExit(1)

    print(f"Testing database host: {host}")
    if not check_dns(host):
        print("Please verify your network, DNS settings, or the Supabase host name.")
    else:
        with app.app_context():
            try:
                result = db.session.execute(text("SELECT version();")).fetchone()
                print("\n🎉 SUCCESS! Connected to Supabase.")
                print(f"Database Version: {result}\n")
            except Exception as e:
                print("\n❌ CONNECTION FAILED!")
                print(f"Error details: {e}\n")





 

