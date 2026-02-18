# core/management/commands/scrape_lotoven_animalitos.py
"""
SCRAPER: LOTOVEN / ANIMALITOS
============================

Scrapea:
- HOY:  https://lotoven.com/animalitos/
- AYER: https://lotoven.com/animalitos/ayer/

Extrae por cada proveedor y horario:
- provider_name
- provider_logo_url
- provider_source_url
- animal_image_url
- animal_name
- animal_number  (IMPORTANTE: preservar exactamente "0" vs "00")
- draw_time_obj

Guarda en BD:
- Provider (upsert por name)
- AnimalitoResult (upsert por provider + draw_date + draw_time)
"""

import re
import time
from datetime import datetime, date as date_cls, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Provider
from core.models.animalito_result import AnimalitoResult
from core.services.device_redis_service import DeviceRedisService



# -----------------------------------------------------------------------------
# 1) NORMALIZACIÓN DE NOMBRES DE PROVIDER
# -----------------------------------------------------------------------------
PROVIDER_ALIASES = {
    "La-Ricachona": "La Ricachona",
}


def normalize_provider_name(raw: str) -> str:
    if not raw:
        return ""
    name = raw.replace("\u00a0", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return PROVIDER_ALIASES.get(name, name)


# -----------------------------------------------------------------------------
# 2) UPSERT DE PROVIDERS
# -----------------------------------------------------------------------------
def upsert_providers(provider_rows: list[dict]) -> tuple[int, int]:
    created = 0
    updated = 0

    for p in provider_rows:
        name = normalize_provider_name(p.get("provider_name") or "")
        if not name:
            continue

        logo_url = p.get("provider_logo_url") or None
        source_url = p.get("provider_source_url") or None

        existing = Provider.objects.filter(name=name).first()

        if existing:
            changed = False
            if logo_url and existing.logo_url != logo_url:
                existing.logo_url = logo_url
                changed = True
            if source_url and existing.source_url != source_url:
                existing.source_url = source_url
                changed = True
            if existing.is_active is False:
                existing.is_active = True
                changed = True

            if changed:
                existing.save(update_fields=["logo_url", "source_url", "is_active"])
                updated += 1
        else:
            Provider.objects.create(
                name=name,
                logo_url=logo_url,
                source_url=source_url,
                is_active=True,
            )
            created += 1

    return created, updated


# -----------------------------------------------------------------------------
# 3) COMANDO DJANGO
# -----------------------------------------------------------------------------
class Command(BaseCommand):
    help = "Scrapea resultados de animalitos desde lotoven.com"

    BASE_URL = "https://lotoven.com"
    ANIMALITOS_URL = "https://lotoven.com/animalitos/"

    HTML_CACHE_TTL_SECONDS = 10 * 60
    GLOBAL_COOLDOWN_SECONDS = 10 * 60

    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    def _animalitos_url_for_date(self, target_date: date_cls) -> str:
        today = timezone.localdate()
        if target_date == today:
            return self.ANIMALITOS_URL
        if target_date == (today - timedelta(days=1)):
            return f"{self.BASE_URL}/animalitos/ayer/"
        raise CommandError(
            f"Lotoven no soporta histórico para {target_date}. Solo HOY y AYER."
        )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="No guarda en BD.")
        parser.add_argument("--date", type=str, default=None, help="Fecha YYYY-MM-DD.")
        parser.add_argument("--force", action="store_true", help="Ignora cooldown.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]
        verbosity = int(options.get("verbosity") or 1)

        target_date = self._parse_date(options.get("date"))
        if not target_date:
            self.stderr.write("Fecha inválida. Usa YYYY-MM-DD")
            return

        if not force and self._is_in_global_cooldown(target_date):
            secs = self._seconds_since_last_run(target_date)
            self.stdout.write(
                self.style.WARNING(
                    f"Saltando: último scrape animalitos hace {secs}s "
                    f"(< {self.GLOBAL_COOLDOWN_SECONDS}s)."
                )
            )
            return
        
        DeviceRedisService.delete_pattern("results:animalitos:*")

        html = self._fetch_html(target_date=target_date, force=force)
        rows = self._parse_html(html, target_date=target_date, verbosity=verbosity)

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: {len(rows)} resultados detectados."))
            for r in rows[:200]:
                # IMPORTANTE: NO :02d, NO int(), NO zfill() — preservar "0" vs "00"
                self.stdout.write(
                    f"{r['provider_name']} {r['draw_time_obj']} -> {r['animal_number']} {r['animal_name']}"
                )
            return

        provider_rows = self._providers_from_rows(rows)
        prov_created, prov_updated = upsert_providers(provider_rows)
        self.stdout.write(self.style.SUCCESS(f"Providers upsert: created={prov_created} updated={prov_updated}"))

        created, updated = self._upsert_results(rows, target_date)
        self._set_last_run(target_date)

        self.stdout.write(
            self.style.SUCCESS(
                f"OK animalitos: {len(rows)} parseados | results created={created} updated={updated}"
            )
        )

    # -------------------------------------------------------------------------
    # Helpers: providers únicos
    # -------------------------------------------------------------------------
    def _providers_from_rows(self, rows: list[dict]) -> list[dict]:
        by_name: dict[str, dict] = {}
        for r in rows:
            name = normalize_provider_name(r.get("provider_name") or "")
            if not name:
                continue
            by_name[name] = {
                "provider_name": name,
                "provider_logo_url": r.get("provider_logo_url"),
                "provider_source_url": r.get("provider_source_url"),
            }
        return list(by_name.values())

    # -------------------------------------------------------------------------
    # COOLDOWN
    # -------------------------------------------------------------------------
    def _last_run_key(self, target_date: date_cls) -> str:
        return f"scrape:animalitos:last_run:{target_date.isoformat()}"

    def _set_last_run(self, target_date: date_cls):
        cache.set(self._last_run_key(target_date), timezone.now().timestamp(), timeout=24 * 3600)

    def _seconds_since_last_run(self, target_date: date_cls) -> int:
        ts = cache.get(self._last_run_key(target_date))
        if not ts:
            return 10**9
        return int(timezone.now().timestamp() - float(ts))

    def _is_in_global_cooldown(self, target_date: date_cls) -> bool:
        return self._seconds_since_last_run(target_date) < self.GLOBAL_COOLDOWN_SECONDS

    # -------------------------------------------------------------------------
    # FECHA
    # -------------------------------------------------------------------------
    def _parse_date(self, raw: str | None) -> date_cls | None:
        if not raw:
            return timezone.localdate()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None

    # -------------------------------------------------------------------------
    # FETCH HTML CON CACHE
    # -------------------------------------------------------------------------
    def _html_cache_key(self, target_date: date_cls) -> str:
        return f"scrape:animalitos:html:{target_date.isoformat()}"

    def _fetch_html(self, *, target_date: date_cls, force: bool) -> str:
        cache_key = self._html_cache_key(target_date)

        if not force:
            cached = cache.get(cache_key)
            if cached:
                return cached

        time.sleep(0.8)
        headers = {"User-Agent": self.USER_AGENT}

        url = self._animalitos_url_for_date(target_date)
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()

        html = resp.text
        cache.set(cache_key, html, timeout=self.HTML_CACHE_TTL_SECONDS)
        return html

    # -------------------------------------------------------------------------
    # PARSER HTML
    # -------------------------------------------------------------------------
    def _parse_html(self, html: str, *, target_date: date_cls, verbosity: int = 1) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        source_url = self._animalitos_url_for_date(target_date)

        rows: list[dict] = []

        # 1) Camino “normal”: contenedores con header + cards
        section = soup.select_one("section#ani-res")
        containers = section.select("div.container") if section else soup.select("div.container")

        for container in containers:
            header = container.select_one(".section-header.title-ani")
            if not header:
                continue

            provider_name = normalize_provider_name(self._safe_text(header.select_one("p.title.one")))

            logo_img = header.select_one("img.logo-result")
            provider_logo_url = self._abs_url(logo_img.get("src") if logo_img else "")

            provider_link = header.select_one("a.logo-ani-header")
            provider_source_url = self._abs_url(provider_link.get("href") if provider_link else "") or source_url

            for card in container.select(".counter-wrapper"):
                animal_img = card.select_one(".counter-item img")
                animal_image_url = self._abs_url(animal_img.get("src") if animal_img else "")

                info = self._safe_text(card.select_one("span.info"))
                animal_number, animal_name = self._parse_number_and_name(info)

                horario = self._safe_text(card.select_one("span.horario, span.info2.horario"))
                draw_time_obj = self._parse_time_12h(horario)

                if not provider_name or not draw_time_obj or not animal_name:
                    continue

                rows.append(
                    {
                        "provider_name": provider_name,
                        "provider_logo_url": provider_logo_url,
                        "provider_source_url": provider_source_url,
                        "animal_image_url": animal_image_url,
                        "animal_number": animal_number,  # string exacto
                        "animal_name": animal_name,
                        "draw_time_obj": draw_time_obj,
                    }
                )

        # 2) Fallback: layout tipo /animalitos/ayer/ que viene como invest-table-area
        if not rows:
            fallback_cards = soup.select(".invest-table-area .counter-wrapper")
            if verbosity >= 2:
                self.stdout.write(f"[debug] section#ani-res={'OK' if section else 'NO'} containers={len(containers)} fallback_cards={len(fallback_cards)}")

            provider_name = "Lotoven Animalitos"
            provider_logo_url = ""
            provider_source_url = source_url

            for card in fallback_cards:
                animal_img = card.select_one(".counter-item img")
                animal_image_url = self._abs_url(animal_img.get("src") if animal_img else "")

                info = self._safe_text(card.select_one("span.info"))
                animal_number, animal_name = self._parse_number_and_name(info)

                horario = self._safe_text(card.select_one("span.horario, span.info2.horario"))
                draw_time_obj = self._parse_time_12h(horario)

                if not draw_time_obj or not animal_name:
                    continue

                rows.append(
                    {
                        "provider_name": provider_name,
                        "provider_logo_url": provider_logo_url,
                        "provider_source_url": provider_source_url,
                        "animal_image_url": animal_image_url,
                        "animal_number": animal_number,
                        "animal_name": animal_name,
                        "draw_time_obj": draw_time_obj,
                    }
                )

        return rows

    def _safe_text(self, el) -> str:
        if not el:
            return ""
        return el.get_text(" ", strip=True)

    def _abs_url(self, maybe_relative: str) -> str:
        if not maybe_relative:
            return ""
        return urljoin(self.BASE_URL, maybe_relative.strip())

    def _parse_number_and_name(self, info_text: str) -> tuple[str, str]:
        """
        Convierte "00 Ballena" -> ("00", "Ballena")
                 "0 Delfin"   -> ("0",  "Delfin")
        IMPORTANTE: NO convertir a int. NO zfill. Preservar literal.
        """
        info_text = re.sub(r"\s+", " ", (info_text or "").strip())
        if not info_text:
            return ("", "")

        parts = info_text.split(" ", 1)
        raw_num = parts[0].strip()
        raw_name = (parts[1] if len(parts) > 1 else "").strip()

        # Limpieza mínima: solo quedarnos con dígitos al inicio, pero sin alterar "0" vs "00"
        m = re.match(r"^(\d+)", raw_num)
        num = m.group(1) if m else raw_num

        raw_name = re.sub(r"\s+", " ", raw_name)
        return (num, raw_name)

    def _parse_time_12h(self, text: str):
        text = re.sub(r"\s+", " ", (text or "").strip().upper())
        if not text:
            return None

        text = text.replace("AM", " AM").replace("PM", " PM")
        text = re.sub(r"\s+", " ", text).strip()

        try:
            return datetime.strptime(text, "%I:%M %p").time()
        except ValueError:
            try:
                return datetime.strptime(text, "%H:%M").time()
            except ValueError:
                return None

    # -------------------------------------------------------------------------
    # UPSERT RESULTS
    # -------------------------------------------------------------------------
    def _upsert_results(self, rows: list[dict], target_date: date_cls) -> tuple[int, int]:
        created = 0
        updated = 0

        for r in rows:
            provider_name = normalize_provider_name(r["provider_name"])

            provider = Provider.objects.filter(name=provider_name).first()
            if not provider:
                provider = Provider.objects.create(
                    name=provider_name,
                    logo_url=r.get("provider_logo_url") or None,
                    source_url=r.get("provider_source_url") or self.ANIMALITOS_URL,
                    is_active=True,
                )

            _, was_created = AnimalitoResult.objects.update_or_create(
                provider=provider,
                draw_date=target_date,
                draw_time=r["draw_time_obj"],
                defaults={
                    "animal_number": r["animal_number"],  # string exacto "0"/"00"
                    "animal_name": r["animal_name"],
                    "animal_image_url": r["animal_image_url"],
                    "provider_logo_url": r.get("provider_logo_url") or "",
                },
            )

            if was_created:
                created += 1
            else:
                updated += 1

        return created, updated
