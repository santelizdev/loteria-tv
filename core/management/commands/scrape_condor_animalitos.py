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


SOURCE_URL = "https://www.lottoresultados.com/resultados/animalitos/condor-gana"
BASE_URL = "https://www.lottoresultados.com"


TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)\s*$", re.IGNORECASE)
LINE_RE = re.compile(r"^\s*(\d{1,2})\s+(.+?)\s*$")  # "62 Cachicamo"


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
    # Asegura source_url requerido
    if not provider.source_url:
        provider.source_url = SOURCE_URL
        provider.save(update_fields=["source_url"])
    if provider.is_active is False:
        provider.is_active = True
        provider.save(update_fields=["is_active"])
    return provider


class Command(BaseCommand):
    help = "Scrapea Condor Gana (animalitos) desde lottoresultados.com y guarda en AnimalitoResult."

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
        soup = BeautifulSoup(html, "html.parser")

        # Bloques: hoy / ayer
        block_id = (
            "resultado-de-condor-gana-de-hoy"
            if target_date == today
            else None  # el de ayer no tiene id fijo en tu dump, pero es el siguiente col-sm-6
        )

        rows = []
        if target_date == today:
            block = soup.select_one(f"#{block_id}")
            if not block:
                raise CommandError("No se encontró el bloque de HOY en el HTML.")
            rows = self._parse_step_list(block)
        else:
            # “Resultados de Ayer” está en el segundo .col-sm-6 del mismo row.
            cols = soup.select(".row > .col-sm-6")
            if len(cols) < 2:
                raise CommandError("No se encontró el bloque de AYER en el HTML.")
            rows = self._parse_step_list(cols[1])

        # invalidación cache ANIMALITOS (para TVs)
        DeviceRedisService.delete_pattern("results:animalitos:*")

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: parsed={len(rows)}"))
            for r in rows:
                self.stdout.write(f"{r['time']} -> {r['number']} {r['animal']} ({r['image']})")
            return

        provider = _get_or_create_provider()

        created = 0
        updated = 0

        for r in rows:
            obj, was_created = AnimalitoResult.objects.update_or_create(
                provider=provider,
                draw_date=target_date,
                draw_time=r["draw_time_obj"],
                defaults={
                    "animal_number": r["number"],        # Django coerces si es IntegerField
                    "animal_name": r["animal"],
                    "animal_image_url": r["image"],
                    "provider_logo_url": provider.logo_url or "",
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"OK Condor Gana (lottoresultados): date={target_date} parsed={len(rows)} created={created} updated={updated}"
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

        items = container.select("ul.step li.step-item")
        for it in items:
            time_txt = it.select_one("h4")
            line_txt = it.select_one("p.step-text")
            img = it.select_one("img")

            t_raw = time_txt.get_text(" ", strip=True) if time_txt else ""
            line_raw = line_txt.get_text(" ", strip=True) if line_txt else ""

            # Ignorar "Próximo" o vacíos
            if not line_raw or "próximo" in line_raw.lower() or "proximo" in line_raw.lower():
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
            image_url = urljoin(BASE_URL, src)

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
