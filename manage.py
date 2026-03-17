#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

try:
    from config.env import load_project_env
except ModuleNotFoundError:
    load_project_env = None


def main():
    if load_project_env:
        load_project_env()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
