# core/management/commands/scrape_lotoven_animalitos.py
"""
SCRAPER: LOTOVEN / ANIMALITOS
============================

Este comando scrapea:
https://lotoven.com/animalitos/

Extrae por cada proveedor y horario:
1) Logo del proveedor
2) Nombre proveedor
3) Imagen del animalito ganador
4) Nombre del animalito ganador
5) Número del animalito ganador
6) Horario del animalito ganador

Y lo guarda en BD con:
- Provider (normalizado / upsert: name + logo_url + source_url + is_active)
- AnimalitoResult (upsert por provider + draw_date + draw_time)

Reglas fijas (como pediste):
✅ Te indico EXACTAMENTE dónde va cada cosa (aquí ya va todo listo).
✅ Explico qué hace y por qué.
✅ Agrego comentarios en cada bloque importante.
"""

import re
import time
from datetime import datetime, date as date_cls
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Provider
from core.models.animalito_result import AnimalitoResult


# -----------------------------------------------------------------------------
# 1) NORMALIZACIÓN DE NOMBRES DE PROVIDER
# -----------------------------------------------------------------------------
# ✅ Objetivo: evitar duplicados por diferencias mínimas de texto.
# Ej: "La-Ricachona" vs "La Ricachona"
PROVIDER_ALIASES = {
    "La-Ricachona": "La Ricachona",
    # Agrega aquí más alias si detectas duplicados:
    # "Lotto Activo RD  Int": "Lotto Activo RD Int",
}


def normalize_provider_name(raw: str) -> str:
    """
    Normaliza el nombre del provider para evitar duplicados:
    - Limpia espacios múltiples
    - Quita NBSP
    - Aplica aliases
    """
    if not raw:
        return ""

    name = raw.replace("\u00a0", " ")
    name = re.sub(r"\s+", " ", name).strip()
    name = PROVIDER_ALIASES.get(name, name)

    return name


# -----------------------------------------------------------------------------
# 2) UPSERT DE PROVIDERS (TABLA Provider)
# -----------------------------------------------------------------------------
# ✅ Objetivo: poblar logo_url y source_url en Provider en un solo paso.
# ✅ Se llama desde handle() ANTES de guardar los resultados (AnimalitoResult).
def upsert_providers(provider_rows: list[dict]) -> tuple[int, int]:
    """
    Inserta/actualiza providers en la tabla Provider.
    Retorna (created_count, updated_count).

    provider_rows: lista de dicts con:
      - provider_name (obligatorio)
      - provider_logo_url (opcional)
      - provider_source_url (opcional)
    """
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

            # ✅ Actualiza logo_url solo si viene y es distinto (o estaba vacío)
            if logo_url and existing.logo_url != logo_url:
                existing.logo_url = logo_url
                changed = True

            # ✅ Actualiza source_url solo si viene y es distinto (o estaba vacío)
            if source_url and existing.source_url != source_url:
                existing.source_url = source_url
                changed = True

            # ✅ Asegura que esté activo
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
    """
    Scrapea resultados de animalitos desde:
    https://lotoven.com/animalitos/

    Objetivos:
    - Evitar requests agresivos (cache + cooldown)
    - Normalizar datos (Provider FK + parse hora)
    - Mantener sqlite ligera (upsert + unique constraints)
    """

    help = "Scrapea resultados de animalitos desde lotoven.com"

    # Endpoint base
    BASE_URL = "https://lotoven.com"
    ANIMALITOS_URL = "https://lotoven.com/animalitos/"

    # Cache de HTML por fecha (evita pegarle siempre a lotoven)
    HTML_CACHE_TTL_SECONDS = 10 * 60  # 10 min

    # Cooldown extra global (si se ejecuta varias veces seguidas)
    GLOBAL_COOLDOWN_SECONDS = 10 * 60  # 10 min

    # User-Agent para no parecer bot agresivo
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No guarda en BD. Solo imprime lo detectado.",
        )
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Fecha YYYY-MM-DD (si se omite, usa hoy).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Ignora cooldown global y re-scrapea.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        target_date = self._parse_date(options.get("date"))
        if not target_date:
            self.stderr.write("Fecha inválida. Usa YYYY-MM-DD")
            return

        # ---------------------------------------------------------------------
        # (A) Rate-limit global (evita ejecuciones seguidas)
        # ---------------------------------------------------------------------
        if not force and self._is_in_global_cooldown(target_date):
            secs = self._seconds_since_last_run(target_date)
            self.stdout.write(
                self.style.WARNING(
                    f"Saltando: último scrape animalitos hace {secs}s (< {self.GLOBAL_COOLDOWN_SECONDS}s)."
                )
            )
            return

        # ---------------------------------------------------------------------
        # (B) Fetch HTML (con cache para NO hacer requests innecesarias)
        # ---------------------------------------------------------------------
        html = self._fetch_html(target_date=target_date, force=force)

        # ---------------------------------------------------------------------
        # (C) Parse HTML -> rows (resultados planos)
        # ---------------------------------------------------------------------
        rows = self._parse_html(html)

        # ---------------------------------------------------------------------
        # (D) DRY RUN: imprimir y salir sin tocar BD
        # ---------------------------------------------------------------------
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"DRY RUN: {len(rows)} resultados detectados."))
            for r in rows[:200]:
                self.stdout.write(
                    f"{r['provider_name']} {r['draw_time_obj']} -> {r['animal_number']:02d} {r['animal_name']}"
                )
            return

        # ---------------------------------------------------------------------
        # (E) Upsert Providers (1 y 2: nombre + logo + source_url)
        # ✅ Esto es lo que pediste: normalizar y poblar Provider antes del upsert de resultados.
        # ---------------------------------------------------------------------
        provider_rows = self._providers_from_rows(rows)
        prov_created, prov_updated = upsert_providers(provider_rows)
        self.stdout.write(self.style.SUCCESS(f"Providers upsert: created={prov_created} updated={prov_updated}"))

        # ---------------------------------------------------------------------
        # (F) Persistencia resultados (AnimalitoResult upsert)
        # ---------------------------------------------------------------------
        created, updated = self._upsert_results(rows, target_date)

        # ---------------------------------------------------------------------
        # (G) Marca de último run para cooldown
        # ---------------------------------------------------------------------
        self._set_last_run(target_date)

        self.stdout.write(
            self.style.SUCCESS(
                f"OK animalitos: {len(rows)} parseados | results created={created} updated={updated}"
            )
        )

    # -------------------------------------------------------------------------
    # Helpers: construir lista única de providers desde rows
    # -------------------------------------------------------------------------
    def _providers_from_rows(self, rows: list[dict]) -> list[dict]:
        """
        Construye una lista única de providers desde los resultados parseados.
        ✅ Evita duplicar providers (porque rows trae muchos horarios por proveedor).
        """
        by_name: dict[str, dict] = {}

        for r in rows:
            name = r.get("provider_name")
            if not name:
                continue

            name = normalize_provider_name(name)

            # Nos quedamos con el último que encontremos (normalmente todos iguales)
            by_name[name] = {
                "provider_name": name,
                "provider_logo_url": r.get("provider_logo_url"),
                "provider_source_url": r.get("provider_source_url"),
            }

        return list(by_name.values())

    # -------------------------------------------------------------------------
    # COOLDOWN GLOBAL (por fecha)
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
        """
        Convierte YYYY-MM-DD -> date.
        Si no viene, usa hoy (timezone local Django).
        """
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
        """
        Baja el HTML con cache:
        - Si existe en cache y no force => devuelve cache
        - Si no => request con timeout y headers razonables

        Nota:
        - La página tiene form POST por fecha, pero por ahora usamos GET (hoy).
        - Si luego quieres histórico por fecha, hacemos POST con "fecha".
        """
        cache_key = self._html_cache_key(target_date)

        # ✅ Si hay cache y no forzamos, devolvemos sin pegarle al sitio
        if not force:
            cached = cache.get(cache_key)
            if cached:
                return cached

        # ✅ Sleep corto para ser "polite"
        time.sleep(0.8)

        headers = {"User-Agent": self.USER_AGENT}
        resp = requests.get(self.ANIMALITOS_URL, headers=headers, timeout=20)
        resp.raise_for_status()

        html = resp.text
        cache.set(cache_key, html, timeout=self.HTML_CACHE_TTL_SECONDS)
        return html

    # -------------------------------------------------------------------------
    # PARSER HTML
    # -------------------------------------------------------------------------
    def _parse_html(self, html: str) -> list[dict]:
        """
        Devuelve lista plana de resultados:
        [{
          provider_name,
          provider_logo_url,
          provider_source_url,
          animal_image_url,
          animal_number,
          animal_name,
          draw_time_obj (datetime.time)
        }, ...]
        """
        soup = BeautifulSoup(html, "html.parser")

        section = soup.select_one("section#ani-res")
        if not section:
            raise RuntimeError("No se encontró section#ani-res en el HTML")

        rows: list[dict] = []

        # ✅ Cada proveedor tiene un "div.container" que incluye un header .section-header.title-ani
        for container in section.select("div.container"):
            header = container.select_one(".section-header.title-ani")
            if not header:
                continue  # Este container es el del formulario u otro bloque

            # -----------------------------
            # Provider: nombre + logo + link
            # -----------------------------
            provider_name = self._safe_text(header.select_one("p.title.one"))
            provider_name = normalize_provider_name(provider_name)

            logo_img = header.select_one("img.logo-result")
            provider_logo_url = self._abs_url(logo_img.get("src") if logo_img else "")

            # ✅ Link del proveedor (ej: /animalito/lottoactivo/)
            provider_link = header.select_one("a.logo-ani-header")
            provider_source_url = self._abs_url(provider_link.get("href") if provider_link else "")

            # -----------------------------
            # Cada resultado es un .counter-wrapper
            # -----------------------------
            for card in container.select(".counter-wrapper"):
                animal_img = card.select_one(".counter-item img")
                animal_image_url = self._abs_url(animal_img.get("src") if animal_img else "")

                info = self._safe_text(card.select_one("span.info"))
                animal_number, animal_name = self._parse_number_and_name(info)

                horario = self._safe_text(card.select_one("span.horario"))
                draw_time_obj = self._parse_time_12h(horario)

                # ✅ Validación mínima para no romper el comando por un card raro
                if not provider_name or not draw_time_obj or not animal_name:
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
        """Extrae texto de un elemento BeautifulSoup de forma segura."""
        if not el:
            return ""
        return el.get_text(" ", strip=True)

    def _abs_url(self, maybe_relative: str) -> str:
        """
        Normaliza a URL absoluta.
        lotoven suele dar rutas tipo /dist/...
        """
        if not maybe_relative:
            return ""
        return urljoin(self.BASE_URL, maybe_relative)

    def _parse_number_and_name(self, info_text: str) -> tuple[int, str]:
        """
        Convierte "32 Ardilla" -> (32, "Ardilla")
        Soporta:
          - "00 Ballena"
          - "47 Pavo Real" (nombre con espacios)
        """
        info_text = (info_text or "").strip()
        info_text = re.sub(r"\s+", " ", info_text)

        parts = info_text.split(" ", 1)
        if not parts:
            return (0, "")

        raw_num = parts[0]
        raw_name = parts[1] if len(parts) > 1 else ""

        try:
            num = int(raw_num)
        except ValueError:
            m = re.match(r"^(\d+)", raw_num)
            num = int(m.group(1)) if m else 0

        raw_name = re.sub(r"\s+", " ", raw_name.strip())
        return (num, raw_name)

    def _parse_time_12h(self, text: str):
        """
        Convierte "08:05 AM" / "12:10 PM" a datetime.time.
        Si falla, devuelve None.
        """
        text = (text or "").strip().upper()
        text = re.sub(r"\s+", " ", text)

        # Soporta casos "08:05AM" sin espacio
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
    # UPSERT EN BD (sqlite friendly)
    # -------------------------------------------------------------------------
    def _upsert_results(self, rows: list[dict], target_date: date_cls) -> tuple[int, int]:
        """
        Upsert de AnimalitoResult:
        - Provider lo buscamos por name (ya debería existir por el upsert_providers)
        - AnimalitoResult: update_or_create por (provider, draw_date, draw_time)

        ✅ Mantiene SQLite ligera (sin duplicados).
        """
        created = 0
        updated = 0

        for r in rows:
            provider_name = normalize_provider_name(r["provider_name"])

            # ✅ Aquí NO hacemos get_or_create a ciegas sin logo/source,
            # porque ya hicimos upsert de providers arriba.
            provider = Provider.objects.filter(name=provider_name).first()
            if not provider:
                # Fallback de seguridad (por si algo vino raro)
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
                    "animal_number": r["animal_number"],
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
