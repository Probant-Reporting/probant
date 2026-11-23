#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    espace = (os.environ.get("SPACE", "") or os.environ.get("ESPACE", "")).strip()
    if espace and espace != "principal":  # ESPACE=achats python3 manage.py <commande> : la commande dans cet espace
        import django

        django.setup()
        from espaces import contexte as E
        from espaces.models import Espace

        if not E.CODE.match(espace) or not Espace.objects.filter(code=espace).exists():
            sys.exit(f"Espace « {espace} » inconnu (python3 manage.py spaces --list).")
        with E.activer(espace):
            execute_from_command_line(sys.argv)
        return
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
