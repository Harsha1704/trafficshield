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

    @app.cli.group("monitoring")
    def monitoring_group() -> None:
        """Monitoring telemetry, drift metrics, and retention operations."""
        pass

    @monitoring_group.command("purge-metrics")
    @click.option(
        "--days",
        "-d",
        default=None,
        type=int,
        help="Retention period in days. Records older than this will be purged. Defaults to configured retention.",
    )
    @click.option(
        "--dry-run/--execute",
        default=True,
        help="Dry run mode (default: True). Shows eligible records without deleting them.",
    )
    @click.option(
        "--yes",
        "-y",
        is_flag=True,
        default=False,
        help="Skip interactive confirmation prompt when executing.",
    )
    def purge_metrics(days: int | None, dry_run: bool, yes: bool) -> None:
        """Purge expired MonitoringBatchMetric records according to retention policy."""
        from app.api.v1.monitoring import get_monitoring_service
        service = get_monitoring_service()

        target_days = days if days is not None else service.retention_days
        if target_days <= 0:
            click.echo(f"Error: Retention days must be a positive integer (> 0), got {target_days}.", err=True)
            raise click.Abort()

        try:
            eligible_count = service.purge_stale_metrics(retention_days=target_days, dry_run=True)
            click.echo(f"Retention period: {target_days} days")
            click.echo(f"Records eligible for deletion: {eligible_count} monitoring batch metric(s)")

            if dry_run:
                click.echo("[DRY-RUN] No records were deleted. Run with '--execute' and confirm to delete.")
                return

            if eligible_count == 0:
                click.echo("No expired records to purge.")
                return

            if not yes:
                confirm = click.confirm(
                    f"Are you sure you want to permanently delete {eligible_count} monitoring batch metric(s) older than {target_days} days?",
                    default=False,
                )
                if not confirm:
                    click.echo("Operation cancelled by operator. No records were deleted.")
                    return

            deleted_count = service.purge_stale_metrics(retention_days=target_days, dry_run=False)
            click.echo(f"Successfully purged {deleted_count} monitoring batch metric(s).")
        except click.Abort:
            raise
        except Exception as exc:
            click.echo(f"Error executing retention purge: {exc}", err=True)
            raise click.Abort() from exc
