"""
TrafficShield Standalone User Management Script
==============================================
Enables secure administrative account inspection, user creation, and password resets.
Never logs, stores, or prints plaintext passwords, hashes, or secret keys.

Usage:
    python scripts/manage_users.py list
    python scripts/manage_users.py reset analyst
    python scripts/manage_users.py reset analyst --password <secret>
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.database.models import User
from app.extensions import db


def main() -> None:
    parser = argparse.ArgumentParser(description="TrafficShield User Administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: list
    subparsers.add_parser("list", help="List registered users (redacted, no secrets)")

    # Subcommand: reset
    reset_parser = subparsers.add_parser("reset", help="Reset password for an existing or new user")
    reset_parser.add_argument("username", help="Username to reset or create")
    reset_parser.add_argument("--password", "-p", default=None, help="New password (prompted securely if omitted)")
    reset_parser.add_argument("--role", default=None, choices=["admin", "analyst"], help="Role if creating new user")

    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.command == "list":
            users = User.query.order_by(User.username).all()
            if not users:
                print("No user accounts found in database.")
                return
            print(f"Registered user accounts ({len(users)}):")
            for u in users:
                status = "ACTIVE" if u.is_active else "INACTIVE"
                print(f"  - Username: {u.username:<16} Role: {u.role:<10} Status: {status}")

        elif args.command == "reset":
            username = args.username.strip()
            password = args.password
            if not password:
                # Read securely from env var if set, otherwise prompt without echo
                env_pwd = os.getenv("NEW_PASSWORD")
                if env_pwd:
                    password = env_pwd
                else:
                    password = getpass.getpass(f"Enter new password for '{username}': ")
                    confirm = getpass.getpass("Confirm new password: ")
                    if password != confirm:
                        print("Error: Passwords do not match.", file=sys.stderr)
                        sys.exit(1)

            if not password or len(password) < 8:
                print("Error: Password must be at least 8 characters.", file=sys.stderr)
                sys.exit(1)

            user = User.query.filter_by(username=username).first()
            if user is None:
                role = args.role or ("admin" if username == "admin" else "analyst")
                print(f"User '{username}' does not exist. Creating new account with role '{role}'...")
                user = User(username=username, role=role, is_active=True)
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                print(f"Successfully created user '{username}' with role '{role}'.")
            else:
                user.set_password(password)
                user.is_active = True
                db.session.commit()
                print(f"Successfully reset password for user '{username}'.")


if __name__ == "__main__":
    main()
