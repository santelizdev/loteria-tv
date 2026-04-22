from __future__ import annotations

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import CurrentResult, Provider
from core.services.device_redis_service import DeviceRedisService
from core.services.results_refresh_service import ResultsRefreshService
from core.services.result_window_service import (
    delete_future_rows_for_provider,
    get_business_cutoff_time,
)


SOURCE_URL = "https://tripletachira.com/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
HEADER_RE = re.compile(r"^(TACHIRA A|TACHIRA B|ZODIACAL)\s+(\d{1,2}:\d{2})\s*([AP]M)$", re.IGNORECASE)
NUMBER_RE = re.compile(r"^\d{3}$")
SIGNO_RE = re.compile(r"^[A-Z]{3,4}$")


def _clean(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_time_12h(value: str):
    text = _clean(value).upper()
    return datetime.strptime(text, "%I:%M%p").time()


def _get_or_create_provider(name: str) -> Provider:
    provider, _ = Provider.objects.get_or_create(
        name=name,
        defaults={"source_url": SOURCE_URL, "is_active": True, "logo_url": ""},
    )
    updates = []
    if provider.source_url != SOURCE_URL:
        provider.source_url = SOURCE_URL
        updates.append("source_url")
    if provider.is_active is False:
        provider.is_active = True
        updates.append("is_active")
    if updates:
        provider.save(update_fields=updates)
    return provider


class Command(BaseCommand):
    help = "Scrapea Triple Tachira desde su pagina oficial y persiste A/B/C con la estructura actual."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=20)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--date", type=str, default=None, help="Solo soporta HOY (YYYY-MM-DD).")

    def handle(self, *args, **opts):
        timeout = int(opts["timeout"])
        dry_run = bool(opts["dry_run"])
        target_date = self._parse_date(opts.get("date"))
        today = timezone.localdate()
        if target_date != today:
            raise CommandError(f"scrape_triple_tachira solo soporta HOY ({today.isoformat()}).")

        html = self._fetch_html(timeout=timeout)
        rows = self._parse_rows(html)
        cutoff_time = get_business_cutoff_time()
        rows = [row for row in rows if row["draw_time"] <= cutoff_time]

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: parsed={len(rows)}"))
            for row in rows:
                self.stdout.write(
                    f"{row['provider_name']} {row['draw_time'].strftime('%H:%M')} -> "
                    f"{row['winning_number']} {row.get('signo', '')}".strip()
                )
            return

        total_created = 0
        total_updated = 0
        total_future_purged = 0
        has_changes = False

        providers = {
            "A": _get_or_create_provider("Triple Tachira A"),
            "B": _get_or_create_provider("Triple Tachira B"),
            "C": _get_or_create_provider("Triple Tachira C"),
        }

        with transaction.atomic():
            for row in rows:
                provider = providers[row["group"]]
                defaults = {
                    "winning_number": row["winning_number"],
                    "image_url": "",
                    "extra": row["extra"],
                    "result_origin": CurrentResult.ResultOrigin.AUTOMATIC_VALID,
                    "source_incident": None,
                }
                _, was_created, was_changed = ResultsRefreshService.upsert_current_result(
                    provider=provider,
                    draw_date=today,
                    draw_time=row["draw_time"],
                    defaults=defaults,
                )
                if was_created:
                    total_created += 1
                elif was_changed:
                    total_updated += 1
                has_changes = has_changes or was_changed

            for provider in providers.values():
                purged = delete_future_rows_for_provider(
                    model=CurrentResult,
                    provider=provider,
                    draw_date=today,
                    cutoff_time=cutoff_time,
                )
                total_future_purged += purged
                has_changes = has_changes or bool(purged)

            DeviceRedisService.delete_pattern("results:triples:*")
            DeviceRedisService.delete_pattern("results:current:*")
            DeviceRedisService.delete_cache("results:current:all")
            ResultsRefreshService.schedule_refresh_results_now_on_commit(has_changes=has_changes)

        self.stdout.write(
            self.style.SUCCESS(
                "OK Triple Tachira (oficial): "
                f"parsed={len(rows)} created={total_created} updated={total_updated} "
                f"future_purged={total_future_purged}"
            )
        )

    def _parse_date(self, raw_value):
        if not raw_value:
            return timezone.localdate()
        try:
            return datetime.strptime(str(raw_value), "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Fecha invalida. Usa YYYY-MM-DD.") from exc

    def _fetch_html(self, *, timeout: int) -> str:
        response = requests.get(
            SOURCE_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return response.text

    def _parse_rows(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        tokens = [_clean(token) for token in soup.stripped_strings if _clean(token)]

        try:
            start_index = tokens.index("Resultados de Hoy") + 1
        except ValueError as exc:
            raise CommandError("No se encontro el bloque 'Resultados de Hoy' en tripletachira.com.") from exc

        end_index = len(tokens)
        for index in range(start_index, len(tokens)):
            if tokens[index] == "Marcas Asociadas":
                end_index = index
                break

        tokens = tokens[start_index:end_index]
        rows = []
        index = 0
        while index < len(tokens):
            header_match = HEADER_RE.match(tokens[index])
            if not header_match:
                index += 1
                continue

            label = header_match.group(1).upper()
            draw_time = _parse_time_12h(f"{header_match.group(2)}{header_match.group(3)}")
            group = "C" if label == "ZODIACAL" else label[-1]

            number = ""
            signo = ""
            scan_index = index + 1
            while scan_index < len(tokens):
                candidate = tokens[scan_index]
                if HEADER_RE.match(candidate):
                    break
                if not number and NUMBER_RE.match(candidate):
                    number = candidate
                elif group == "C" and number and not signo and SIGNO_RE.match(candidate.upper()):
                    signo = candidate.upper()
                scan_index += 1

            if number:
                extra = {"grupo": group}
                if signo:
                    extra["signo"] = signo
                rows.append(
                    {
                        "provider_name": f"Triple Tachira {group}",
                        "group": group,
                        "draw_time": draw_time,
                        "winning_number": number,
                        "extra": extra,
                    }
                )

            index = scan_index

        return rows
