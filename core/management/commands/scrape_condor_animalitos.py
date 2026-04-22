# core/management/commands/scrape_lottoresultados_condorgana.py

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

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
SOURCE_RESULTS_API_TEMPLATE = (
    "https://resultados365.com/api/v2/sorteos/resultados"
    "?id_sorteo=1103&fecha={date}&tabla=true"
)
BASE_URL = "https://www.lottoresultados.com"
CONDOR_IMAGE_URL_TEMPLATE = "/img/animalitos_webp_120x120/CondorGana/{number}.webp"


TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)\s*$", re.IGNORECASE)
LINE_RE = re.compile(r"^\s*(\d{1,2})\s+(.+?)\s*$")  # "62 Cachicamo"
PLACEHOLDER_VALUES = {"", "-", "pendiente", "proximo", "próximo"}


def _normalize_space(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _is_placeholder_value(value: str) -> bool:
    return _normalize_space(value).lower() in PLACEHOLDER_VALUES


def _build_condor_image_url(number: str) -> str:
    raw_number = str(number).strip()
    normalized_number = raw_number.zfill(2) if raw_number.isdigit() else raw_number
    return urljoin(BASE_URL, CONDOR_IMAGE_URL_TEMPLATE.format(number=normalized_number))


def _parse_time_12h(text: str):
    """
    Convierte "9:00 am" -> time(9,0), "12:00 pm" -> time(12,0), "1:00 pm" -> time(13,0).
    """
    text = " ".join((text or "").split()).strip().lower()
    m = TIME_RE.match(text)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    ap = m.group(3).lower()

    if hh == 12:
        hh = 0
    if ap == "pm":
        hh += 12
    return datetime.strptime(f"{hh:02d}:{mm:02d}", "%H:%M").time()


def _get_or_create_provider() -> Provider:
    provider, _ = Provider.objects.get_or_create(
        name="Condor Gana",
        defaults={"source_url": SOURCE_URL, "is_active": True},
    )
    if provider.source_url != SOURCE_URL:
        provider.source_url = SOURCE_URL
        provider.save(update_fields=["source_url"])
    if provider.is_active is False:
        provider.is_active = True
        provider.save(update_fields=["is_active"])
    return provider


class Command(BaseCommand):
    help = "Scrapea Condor Gana (animalitos) desde Resultados365 y guarda en AnimalitoResult."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=20)
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="YYYY-MM-DD. Solo soporta HOY o AYER (porque la página trae ambos bloques).",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        timeout: int = opts["timeout"]
        dry_run: bool = bool(opts["dry_run"])
        target_date = self._parse_date(opts.get("date"))

        today = timezone.localdate()
        yesterday = today - timezone.timedelta(days=1)

        if target_date not in (today, yesterday):
            raise CommandError(
                "Este scraper soporta solo HOY o AYER (la página expone ambos). "
                f"Hoy={today.isoformat()} Ayer={yesterday.isoformat()}."
            )

        html = self._fetch_html(timeout=timeout)
        rows = self._fetch_rows_from_resultados365(html=html, target_date=target_date, timeout=timeout)

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: parsed={len(rows)}"))
            for r in rows:
                self.stdout.write(f"{r['time']} -> {r['number']} {r['animal']} ({r['image']})")
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
        for r in rows:
            _, was_created, was_changed = ResultsRefreshService.upsert_animalito_result(
                provider=provider,
                draw_date=target_date,
                draw_time=r["draw_time_obj"],
                defaults={
                    "animal_number": r["number"],
                    "animal_name": r["animal"],
                    "animal_image_url": r["image"],
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

        DeviceRedisService.delete_pattern("results:animalitos:*")
        ResultsRefreshService.schedule_refresh_results_now_on_commit(
            has_changes=has_changes or bool(future_purged)
        )

        self.stdout.write(self.style.SUCCESS(
            f"OK Condor Gana (resultados365): date={target_date} parsed={len(rows)} created={created} updated={updated} future_purged={future_purged}"
        ))

    def _fetch_html(self, timeout: int) -> str:
        resp = requests.get(
            SOURCE_URL,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                )
            },
        )
        resp.raise_for_status()
        return resp.text

    def _fetch_rows_from_resultados365(self, *, html: str, target_date, timeout: int) -> list[dict]:
        data_url = self._resolve_results_api_url(html=html, target_date=target_date)
        response = requests.get(
            data_url,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        return self._parse_results365_table(response.text)

    def _resolve_results_api_url(self, *, html: str, target_date) -> str:
        soup = BeautifulSoup(html, "html.parser")
        button = soup.select_one(".btn-copiar[data-url]")
        if not button:
            return SOURCE_RESULTS_API_TEMPLATE.format(date=target_date.isoformat())

        data_url = _normalize_space(button.get("data-url") or "")
        if not data_url:
            return SOURCE_RESULTS_API_TEMPLATE.format(date=target_date.isoformat())

        data_url = re.sub(r"fecha=\d{4}-\d{2}-\d{2}", f"fecha={target_date.isoformat()}", data_url)
        return urljoin(SOURCE_URL, data_url)

    def _parse_results365_table(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        rows = []
        for tr in soup.select("table tbody tr"):
            cells = tr.find_all("td")
            if len(cells) < 3:
                continue

            draw_label = _normalize_space(cells[0].get_text(" ", strip=True))
            number = _normalize_space(cells[1].get_text(" ", strip=True))
            animal = _normalize_space(cells[2].get_text(" ", strip=True))

            if _is_placeholder_value(number) or _is_placeholder_value(animal):
                continue

            draw_time = self._parse_results365_time(draw_label)
            if not draw_time:
                continue

            rows.append(
                {
                    "time": draw_label,
                    "draw_time_obj": draw_time,
                    "number": number.zfill(2) if number.isdigit() else number,
                    "animal": animal,
                    "image": _build_condor_image_url(number),
                }
            )
        return rows

    def _parse_results365_time(self, value: str):
        match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*([AP]M)$", _normalize_space(value), re.IGNORECASE)
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

    def _parse_weekly_table(self, soup, *, target_date) -> list[dict]:
        target_label = target_date.strftime("%d/%m/%y")

        for table in soup.select("table.table"):
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
                src = (img.get("src") if img else "") or ""
                out.append(
                    {
                        "time": time_label,
                        "draw_time_obj": draw_time,
                        "number": number,
                        "animal": animal,
                        "image": urljoin(BASE_URL, src) if src else _build_condor_image_url(number),
                    }
                )

            if out:
                return out

        return []

    def _parse_daily_block(self, soup, *, target_date, today) -> list[dict]:
        if target_date == today:
            block = soup.select_one("#resultado-de-condor-gana-de-hoy")
            return self._parse_step_list(block) if block else []

        block = soup.select_one("#resultado-de-condor-gana-de-ayer")
        if block:
            return self._parse_step_list(block)

        cols = soup.select(".row > .col-sm-6")
        if len(cols) >= 2:
            return self._parse_step_list(cols[1])
        return []

    def _parse_step_list(self, container) -> list[dict]:
        """
        Formato observado:
        - <ul class="step">
            <li class="step-item">
              <h4>9:00 am</h4>
              <p class="step-text ...">62 Cachicamo</p>
              <img src="/img/.../CondorGana/62.webp" alt="...">
        La fila final puede ser "Próximo" y se ignora. :contentReference[oaicite:2]{index=2}
        """
        out: list[dict] = []
        if not container:
            return out

        items = container.select("ul.step li.step-item")
        for it in items:
            time_txt = it.select_one("h4")
            line_txt = it.select_one("p.step-text")
            img = it.select_one("img")

            t_raw = time_txt.get_text(" ", strip=True) if time_txt else ""
            line_raw = line_txt.get_text(" ", strip=True) if line_txt else ""

            # Ignorar "Próximo" o vacíos
            if _is_placeholder_value(line_raw):
                continue

            draw_time = _parse_time_12h(t_raw)
            if not draw_time:
                continue

            m = LINE_RE.match(line_raw)
            if not m:
                continue

            number = m.group(1)  # "62" / "5"
            animal = m.group(2).strip()  # "Cachicamo" / "León"

            src = (img.get("src") if img else "") or ""
            image_url = urljoin(BASE_URL, src) if src else _build_condor_image_url(number)

            out.append(
                {
                    "time": t_raw,
                    "draw_time_obj": draw_time,
                    "number": number,
                    "animal": animal,
                    "image": image_url,
                }
            )

        return out

    def _parse_date(self, raw: Optional[str]):
        if not raw:
            return timezone.localdate()
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise CommandError("Formato date inválido. Usa YYYY-MM-DD.")
