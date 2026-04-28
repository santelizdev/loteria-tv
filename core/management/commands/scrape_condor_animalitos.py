from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Provider
from core.models.animalito_result import AnimalitoResult
from core.services.device_redis_service import DeviceRedisService
from core.services.results_refresh_service import ResultsRefreshService
from core.services.result_window_service import (
    delete_future_rows_for_provider,
    get_business_cutoff_time,
)


SOURCE_URL = "https://resultados365.com/resultados/Condor%20Gana"
BASE_URL = "https://resultados365.com"
CONDOR_IMAGE_URL_TEMPLATE = "/CondorGana/{number}.webp"

TIME_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*$", re.IGNORECASE)
LINE_RE = re.compile(r"^\s*(\d{1,2})\s+(.+?)\s*$")
PLACEHOLDER_VALUES = {"", "-", "pendiente", "proximo", "próximo"}


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _normalize_space(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _is_placeholder_value(value: str) -> bool:
    return _normalize_space(value).lower() in PLACEHOLDER_VALUES


def _build_condor_image_url(number: str) -> str:
    raw_number = str(number).strip()
    normalized_number = raw_number.zfill(2) if raw_number.isdigit() else raw_number
    return urljoin(BASE_URL, CONDOR_IMAGE_URL_TEMPLATE.format(number=normalized_number))


def _parse_time_12h(text: str):
    normalized = _normalize_space(text).lower()
    match = TIME_RE.match(normalized)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or "00")
    meridiem = match.group(3).lower()

    if hour == 12:
        hour = 0
    if meridiem == "pm":
        hour += 12

    return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()


def _get_or_create_provider() -> Provider:
    provider, _ = Provider.objects.get_or_create(
        name="Condor Gana",
        defaults={"source_url": SOURCE_URL, "is_active": True},
    )
    updates: list[str] = []
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
    help = "Scrapea Condor Gana (animalitos) desde Resultados365 y guarda en AnimalitoResult."

    HTML_CACHE_TTL_SECONDS = _int_env("CONDOR_ANIMALITOS_HTML_CACHE_TTL_SECONDS", 150)
    GLOBAL_COOLDOWN_SECONDS = _int_env("CONDOR_ANIMALITOS_COOLDOWN_SECONDS", 150)
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=20)
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="YYYY-MM-DD. Solo soporta HOY o AYER.",
        )
        parser.add_argument("--dry-run", action="store_true", help="No guarda en BD.")
        parser.add_argument("--force", action="store_true", help="Ignora cooldown y cache.")
        parser.add_argument("--debug", action="store_true", help="Imprime métricas de parseo.")

    def handle(self, *args, **opts):
        timeout: int = opts["timeout"]
        dry_run: bool = bool(opts["dry_run"])
        force: bool = bool(opts["force"])
        debug: bool = bool(opts["debug"])
        target_date = self._parse_date(opts.get("date"))

        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        if target_date not in (today, yesterday):
            raise CommandError(
                "Este scraper soporta solo HOY o AYER. "
                f"Hoy={today.isoformat()} Ayer={yesterday.isoformat()}."
            )

        if not force and self._is_in_global_cooldown(target_date):
            secs = self._seconds_since_last_run(target_date)
            self.stdout.write(
                self.style.WARNING(
                    f"Saltando Condor Gana: último scrape hace {secs}s "
                    f"(< {self.GLOBAL_COOLDOWN_SECONDS}s)."
                )
            )
            return

        final_url = self._source_url_for_date(target_date)
        html = self._fetch_html(target_date=target_date, timeout=timeout, force=force)
        rows = self._parse_html(html, target_date=target_date, debug=debug)

        if not rows:
            raise CommandError(
                f"No se detectaron resultados Condor Gana en HTML público para {target_date.isoformat()}"
            )

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: parsed={len(rows)}"))
            for row in rows:
                self.stdout.write(
                    f"{row['time']} -> {row['number']} {row['animal']} ({row['image']})"
                )
            return

        provider = _get_or_create_provider()
        future_purged = 0
        if target_date == today:
            cutoff_time = get_business_cutoff_time()
            rows = [row for row in rows if row["draw_time_obj"] <= cutoff_time]
            future_purged = delete_future_rows_for_provider(
                model=AnimalitoResult,
                provider=provider,
                draw_date=target_date,
                cutoff_time=cutoff_time,
            )

        created = 0
        updated = 0
        has_changes = False

        for row in rows:
            _, was_created, was_changed = ResultsRefreshService.upsert_animalito_result(
                provider=provider,
                draw_date=target_date,
                draw_time=row["draw_time_obj"],
                defaults={
                    "animal_number": row["number"],
                    "animal_name": row["animal"],
                    "animal_image_url": row["image"],
                    "provider_logo_url": provider.logo_url or "",
                    "result_origin": AnimalitoResult.ResultOrigin.AUTOMATIC_VALID,
                    "source_incident": None,
                },
            )
            if was_created:
                created += 1
            elif was_changed:
                updated += 1
            has_changes = has_changes or was_changed

        self._set_last_run(target_date)
        DeviceRedisService.delete_pattern("results:animalitos:*")
        ResultsRefreshService.schedule_refresh_results_now_on_commit(
            has_changes=has_changes or bool(future_purged)
        )

        self.stdout.write(
            self.style.SUCCESS(
                "OK Condor Gana (html): "
                f"url={final_url} date={target_date} parsed={len(rows)} "
                f"created={created} updated={updated} future_purged={future_purged}"
            )
        )

    def _source_url_for_date(self, target_date) -> str:
        return f"{SOURCE_URL}/{target_date.isoformat()}"

    def _last_run_key(self, target_date) -> str:
        return f"scrape:condor_animalitos:last_run:{target_date.isoformat()}"

    def _set_last_run(self, target_date):
        cache.set(self._last_run_key(target_date), timezone.now().timestamp(), timeout=24 * 3600)

    def _seconds_since_last_run(self, target_date) -> int:
        ts = cache.get(self._last_run_key(target_date))
        if not ts:
            return 10**9
        return int(timezone.now().timestamp() - float(ts))

    def _is_in_global_cooldown(self, target_date) -> bool:
        return self._seconds_since_last_run(target_date) < self.GLOBAL_COOLDOWN_SECONDS

    def _html_cache_key(self, target_date) -> str:
        return f"scrape:condor_animalitos:html:{target_date.isoformat()}"

    def _fetch_html(self, *, target_date, timeout: int, force: bool) -> str:
        cache_key = self._html_cache_key(target_date)
        if not force:
            cached = cache.get(cache_key)
            if cached:
                return cached

        time.sleep(0.8)
        resp = requests.get(
            self._source_url_for_date(target_date),
            timeout=timeout,
            headers={"User-Agent": self.USER_AGENT},
        )
        resp.raise_for_status()

        html = resp.text
        cache.set(cache_key, html, timeout=self.HTML_CACHE_TTL_SECONDS)
        return html

    def _parse_html(self, html: str, *, target_date, debug: bool) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        today = timezone.localdate()
        daily_block = self._select_daily_block(soup, target_date=target_date, today=today)

        rows_by_parser = {
            "resultado_items": self._parse_resultado_items(soup),
            "weekly_table": self._parse_weekly_table(soup, target_date=target_date),
            "daily_block": self._parse_daily_block(soup, target_date=target_date, today=today),
            "step_list": self._parse_step_list(daily_block) if daily_block else [],
        }

        selected_parser = ""
        rows: list[dict] = []
        for parser_name in ("resultado_items", "weekly_table", "daily_block", "step_list"):
            parser_rows = rows_by_parser[parser_name]
            if parser_rows:
                selected_parser = parser_name
                rows = parser_rows
                break

        if debug:
            self.stdout.write(f"[debug] final_url={self._source_url_for_date(target_date)}")
            self.stdout.write(
                f"[debug] resultado_items_found={len(soup.select('div.resultado-item'))}"
            )
            self.stdout.write(f"[debug] tables_found={len(soup.select('table'))}")
            self.stdout.write(
                f"[debug] step_items_found={len(soup.select('ul.step li.step-item'))}"
            )
            for parser_name in ("resultado_items", "weekly_table", "daily_block", "step_list"):
                self.stdout.write(
                    f"[debug] parsed_{parser_name}={len(rows_by_parser[parser_name])}"
                )
            self.stdout.write(f"[debug] selected_parser={selected_parser or 'none'}")
            for row in rows[:5]:
                self.stdout.write(
                    f"[debug] row {row['time']} -> {row['number']} {row['animal']}"
                )

        return rows

    def _parse_resultado_items(self, soup) -> list[dict]:
        out: list[dict] = []

        article = soup.select_one("article#article_CondorGana")
        containers = article.select("div.resultado-item") if article else soup.select("div.resultado-item")

        for item in containers:
            time_label = _normalize_space(
                item.get("data-hora") or self._safe_text(item.select_one("p.text-gray-500"))
            )
            number = _normalize_space(item.get("data-ganador") or "")
            animal = _normalize_space(item.get("data-descripcion") or "")

            if _is_placeholder_value(number) or _is_placeholder_value(animal):
                continue

            draw_time = _parse_time_12h(time_label)
            if not draw_time:
                continue

            img = item.select_one("img")
            image_url = self._extract_media_url(img) or _build_condor_image_url(number)

            out.append(
                {
                    "time": time_label,
                    "draw_time_obj": draw_time,
                    "number": number,
                    "animal": animal,
                    "image": image_url,
                }
            )

        return out

    def _parse_weekly_table(self, soup, *, target_date) -> list[dict]:
        target_label = target_date.strftime("%d/%m/%y")

        for table in soup.select("table.table, table"):
            header_cells = table.select("thead tr th")
            if len(header_cells) < 2:
                continue

            target_index = None
            for index, cell in enumerate(header_cells[1:], start=1):
                small = cell.select_one("small")
                date_label = _normalize_space(small.get_text(" ", strip=True) if small else "")
                if date_label == target_label:
                    target_index = index
                    break

            if target_index is None:
                continue

            out: list[dict] = []
            for row in table.select("tbody tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                if len(cells) <= target_index:
                    continue

                time_label = _normalize_space(cells[0].get_text(" ", strip=True))
                draw_time = _parse_time_12h(time_label)
                if not draw_time:
                    continue

                raw_parts = [
                    _normalize_space(part)
                    for part in cells[target_index].stripped_strings
                    if _normalize_space(part)
                ]
                if not raw_parts:
                    continue

                joined_value = " ".join(raw_parts)
                if _is_placeholder_value(joined_value):
                    continue

                match = LINE_RE.match(joined_value)
                if not match:
                    continue

                number = match.group(1)
                animal = match.group(2).strip()
                img = cells[target_index].select_one("img")
                image_url = self._extract_media_url(img) or _build_condor_image_url(number)
                out.append(
                    {
                        "time": time_label,
                        "draw_time_obj": draw_time,
                        "number": number,
                        "animal": animal,
                        "image": image_url,
                    }
                )

            if out:
                return out

        return []

    def _select_daily_block(self, soup, *, target_date, today):
        if target_date == today:
            block = soup.select_one("#resultado-de-condor-gana-de-hoy")
            if block:
                return block
        else:
            block = soup.select_one("#resultado-de-condor-gana-de-ayer")
            if block:
                return block

        cols = soup.select(".row > .col-sm-6")
        if target_date == today and cols:
            return cols[0]
        if len(cols) >= 2:
            return cols[1]
        return None

    def _parse_daily_block(self, soup, *, target_date, today) -> list[dict]:
        block = self._select_daily_block(soup, target_date=target_date, today=today)
        return self._parse_step_list(block) if block else []

    def _parse_step_list(self, container) -> list[dict]:
        out: list[dict] = []
        if not container:
            return out

        items = container.select("ul.step li.step-item")
        for item in items:
            time_label = self._safe_text(item.select_one("h4"))
            line_value = self._safe_text(item.select_one("p.step-text"))

            if _is_placeholder_value(line_value):
                continue

            draw_time = _parse_time_12h(time_label)
            if not draw_time:
                continue

            match = LINE_RE.match(line_value)
            if not match:
                continue

            number = match.group(1)
            animal = match.group(2).strip()
            image_url = self._extract_media_url(item.select_one("img")) or _build_condor_image_url(number)

            out.append(
                {
                    "time": time_label,
                    "draw_time_obj": draw_time,
                    "number": number,
                    "animal": animal,
                    "image": image_url,
                }
            )

        return out

    def _safe_text(self, el) -> str:
        if not el:
            return ""
        return el.get_text(" ", strip=True)

    def _extract_media_url(self, el) -> str:
        if not el:
            return ""

        candidates = (
            el.get("data-src"),
            el.get("data-lazy-src"),
            el.get("data-original"),
            el.get("data-srcset"),
            el.get("srcset"),
            el.get("src"),
        )

        for raw_value in candidates:
            value = str(raw_value or "").strip()
            if not value:
                continue
            if "," in value:
                value = value.split(",", 1)[0].strip()
            if " " in value:
                value = value.split(" ", 1)[0].strip()
            if not value or value.startswith("data:"):
                continue
            return urljoin(BASE_URL, value)

        return ""

    def _parse_date(self, raw: Optional[str]):
        if not raw:
            return timezone.localdate()
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Formato date inválido. Usa YYYY-MM-DD.") from exc
