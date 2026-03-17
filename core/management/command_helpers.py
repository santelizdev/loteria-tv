from __future__ import annotations

import os
from urllib.parse import urlparse

from django.core.management.base import CommandError


def raise_database_connection_help(*, command_name: str, exc: Exception) -> None:
    database_url = os.getenv("DATABASE_URL", "")
    host = urlparse(database_url).hostname or "<unset>"

    lines = [
        f"Database connection failed while running `python manage.py {command_name}`.",
        f"Configured DATABASE_URL host: {host}",
        f"Original error: {exc}",
    ]

    if host == "postgres":
        lines.extend(
            [
                "`postgres` is the Docker Compose service hostname and only resolves inside the Compose network.",
                "If you are running `manage.py` from your host shell, use `127.0.0.1` or `localhost` instead.",
            ]
        )
    else:
        lines.append("Verify the database service is running and the configured host is reachable.")

    lines.extend(
        [
            "Example for host-shell execution:",
            f"DATABASE_URL=postgresql://loteria:loteria@127.0.0.1:5432/loteria python manage.py {command_name}",
            "If you want to keep using `postgres` as hostname, run the command inside the `api` container instead.",
        ]
    )

    raise CommandError("\n".join(lines)) from exc
