"""
TrafficShield Administrative CLI Commands
=========================================
Secure administrative commands for user management and operations.
Never logs, stores, or prints plaintext passwords, hashes, or secret keys.
"""
from __future__ import annotations

import click
from flask import Flask

from app.database.models import User
from app.extensions import db


def register_cli_commands(app: Flask) -> None:
    """Register custom Click commands with the Flask application."""

    @app.cli.group("users")
    def users_group() -> None:
        """User account and credential administration."""
        pass

    @users_group.command("list")
    def list_users() -> None:
        """List registered user accounts without exposing hashes."""
        users = User.query.order_by(User.username).all()
        if not users:
            click.echo("No user accounts found in database.")
            return

        click.echo(f"Registered user accounts ({len(users)}):")
        for u in users:
            status = "ACTIVE" if u.is_active else "INACTIVE"
            click.echo(f"  - Username: {u.username:<16} Role: {u.role:<10} Status: {status}")

    @users_group.command("reset-password")
    @click.argument("username")
    @click.option(
        "--password",
        "-p",
        default=None,
        help="New password (if omitted, you will be prompted securely).",
    )
    def reset_password(username: str, password: str | None) -> None:
        """Securely reset the password for a user (or create if missing)."""
        username = username.strip()
        if not password:
            password = click.prompt("Enter new password", hide_input=True, confirmation_prompt=True)

        if not password or len(password) < 8:
            click.echo("Error: Password must be at least 8 characters.", err=True)
            raise click.Abort()

        user = User.query.filter_by(username=username).first()
        if user is None:
            role = "admin" if username == "admin" else "analyst"
            click.echo(f"User '{username}' does not exist. Creating new {role} account...")
            user = User(username=username, role=role, is_active=True)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            click.echo(f"Successfully created user '{username}' (role: {role}).")
        else:
            user.set_password(password)
            user.is_active = True
            db.session.commit()
            click.echo(f"Successfully reset password for user '{username}'.")
