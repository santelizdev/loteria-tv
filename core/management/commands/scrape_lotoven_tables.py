"""
Scraper de lotoven.com/loterias/ (SOLO providers de tabla simple 2 filas).

✅ Reglas del proyecto:
- No agresivo: controla frecuencia (min-interval) + hash HTML (si no cambia, no re-procesa).
- Normaliza datos: HH:MM y números solo dígitos conservando ceros a la izquierda.
- SQLite liviana: upsert por (provider, draw_time) vía UniqueConstraint.
- Prepara cache Redis: payload serializable para que /api/results/ responda rápido.
"""

import hashlib
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from django.core.cache import cache


from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Provider, CurrentResult
from core.services.device_redis_service import DeviceRedisService

from core.models import CurrentResult, ResultArchive

LOTOVEN_URL = "https://lotoven.com/loterias/"

# Providers que en tu HTML están como tablas (horas en fila 1, resultados en fila 2)
# Nota: dejamos fuera Triple Chance / Triple A-B-C por ahora (modelo actual no soporta canales/meta).
TABLE_BASED: Dict[str, str] = {
    "trioactivo": "Trio Activo",
    "laricachona": "La Ricachona",
    "triplecentena": "Triple Centena",
    "tripledorado": "Triple Dorado",
    "triplefacil": "Triple Facil",
    "terminaltrio": "Terminal Trio",
    "terminallagranjita": "Terminal La Granjita",
    "laruca": "La Ruca",
}

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_hhmm(text: str) -> Optional[Tuple[int, int]]:
    """
    Convierte texto tipo '08:05' -> (8, 5). Devuelve None si no es válido.
    """
    t = (text or "").strip()
    m = TIME_RE.match(t)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return hh, mm


def normalize_number(text: str) -> str:
    """
    Normaliza el número ganador:
    - trim
    - elimina espacios internos
    - conserva solo dígitos (mantiene ceros a la izquierda)
    """
    t = (text or "").strip()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[^\d]", "", t)
    return t


class Command(BaseCommand):
    help = "Scrapea lotoven.com/loterias/ (tablas simples) y upsertea CurrentResult."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=15, help="Timeout HTTP en segundos.")
        parser.add_argument(
            "--min-interval",
            type=int,
            default=600,
            help="Mínimo intervalo entre scrapes efectivos (seg). Default 600=10min.",
        )
        parser.add_argument("--force", action="store_true", help="Fuerza scrape aunque hash/interval diga no.")
        parser.add_argument("--dry-run", action="store_true", help="No escribe DB; solo imprime detecciones.")

    def handle(self, *args, **opts):
        timeout: int = opts["timeout"]
        min_interval: int = opts["min_interval"]
        force: bool = opts["force"]
        dry_run: bool = opts["dry_run"]

        now_ts = int(timezone.now().timestamp())

        # -----------------------------
        # 1) Backoff interno por tiempo
        # -----------------------------
        last_run_key = "lotoven:loterias:last_run_ts"
        if not force:
            last_ts = DeviceRedisService.get_cache(last_run_key)
            if last_ts:
                try:
                    last_ts = int(last_ts)
                except (ValueError, TypeError):
                    last_ts = 0

                if last_ts and (now_ts - last_ts) < min_interval:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Saltando: último scrape hace {now_ts - last_ts}s (< {min_interval}s)."
                        )
                    )
                    return

        # -----------------------------
        # 2) GET HTML con UA explícito
        # -----------------------------
        resp = requests.get(
            LOTOVEN_URL,
            timeout=timeout,
            headers={"User-Agent": "loteria-tv-bot/1.0 (+contact: admin@local)"},
        )
        resp.raise_for_status()
        html = resp.text

        # -----------------------------
        # 3) Hash HTML (si no cambia, no tocar DB)
        # -----------------------------
        html_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
        hash_key = "lotoven:loterias:html_hash"

        if not force:
            prev_hash = DeviceRedisService.get_cache(hash_key)
            if prev_hash and prev_hash == html_hash:
                # Guardamos last_run para evitar loop por cron frecuente
                DeviceRedisService.set_cache(last_run_key, str(now_ts), ttl_seconds=24 * 3600)
                self.stdout.write(self.style.SUCCESS("Sin cambios (hash igual). No se toca DB."))
                return

        DeviceRedisService.set_cache(hash_key, html_hash, ttl_seconds=24 * 3600)
        DeviceRedisService.set_cache(last_run_key, str(now_ts), ttl_seconds=24 * 3600)

        # -----------------------------
        # 4) Parseo HTML
        # -----------------------------
        soup = BeautifulSoup(html, "html.parser")
        upserts: List[Tuple[Provider, datetime.time, str]] = []

        for dom_id, provider_name in TABLE_BASED.items():
            block = soup.select_one(f"div#{dom_id}")
            if not block:
                continue

            rows = block.select("table#resultados tbody tr.ingrid")
            if len(rows) < 2:
                continue

            times = [p.get_text(strip=True) for p in rows[0].select("th p.bor-b")]
            vals = [p.get_text(strip=True) for p in rows[1].select("td p.bor-b")]

            provider, _ = Provider.objects.get_or_create(
                name=provider_name,
                defaults={"source_url": LOTOVEN_URL, "is_active": True},
            )

            # zip -> evita IndexError si el HTML viene incompleto
            for t, v in zip(times, vals):
                hhmm = parse_hhmm(t)
                if not hhmm:
                    continue

                number = normalize_number(v)
                if not number:
                    continue

                draw_time = datetime(2000, 1, 1, hhmm[0], hhmm[1]).time()
                upserts.append((provider, draw_time, number))

        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: {len(upserts)} resultados detectados."))
            for p, t, n in upserts[:100]:
                self.stdout.write(f"{p.name} {t.strftime('%H:%M')} -> {n}")
            return

        # -----------------------------
        # 5) Upsert DB (SQLite liviana)
        # -----------------------------
        with transaction.atomic():
            for provider, draw_time, number in upserts:
                today = timezone.localdate()

                draw_date = timezone.localdate()
                CurrentResult.objects.update_or_create(
                    provider=provider,
                    draw_date=draw_date,
                    draw_time=draw_time,
                    defaults={"winning_number": number, "image_url": ""},
                )

        # -----------------------------
        # 6) Cache para lectura rápida
        # -----------------------------
class Command(BaseCommand):
    help = "Scrapea lotoven.com/loterias/ (tablas simples) y upsertea CurrentResult."

    def handle(self, *args, **opts):
        ...
        payload = self._build_cache_payload()
        DeviceRedisService.set_cache("results:current:all", payload, ttl_seconds=120)
        ...

    @staticmethod
    def _build_cache_payload():
        """
        Payload serializable para Redis, consistente con tu API/PWA:
        [{provider, time, number, image}]
        """
        data = []
        qs = CurrentResult.objects.select_related("provider").order_by("provider__name", "draw_time")
        for r in qs:
            data.append(
                {
                    "provider": r.provider.name,
                    "time": r.draw_time.strftime("%H:%M"),
                    "number": r.winning_number,
                    "image": r.image_url or "",
                }
            )
        return data

    # -----------------------------
    # CACHE GENÉRICO (para resultados)
    # -----------------------------

    @staticmethod
    def get_cache(key: str):
        """Lee cualquier clave desde Redis (cache backend)."""
        return cache.get(key)

    @staticmethod
    def set_cache(key: str, value, ttl_seconds: int = 120):
        """
        Guarda cualquier clave en Redis.
        value debe ser serializable (dict/list/str/int).
        """
        cache.set(key, value, timeout=ttl_seconds)

