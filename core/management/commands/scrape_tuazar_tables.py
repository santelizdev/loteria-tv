# core/management/commands/scrape_tuazar_tables.py

"""
Scraper para https://www.tuazar.com/loteria/resultados/

Objetivo:
- Poblar CurrentResult para (fecha = hoy) de los providers:
  1) Chance Astral (con signo)
  2) Triple Gana (con signo)
  3) Super Gana (con signo)

Restricciones del sistema:
- No romper frontend legacy: el API no debe cambiar su estructura JSON.
- Para providers con signo: guardar extra={"signo": "TAU"} en DB; el API luego concatena al string number.
- Invalidar cache Redis por patrón al finalizar.

Notas de robustez:
- TuAzar no usa tablas; usa bloques con:
  - <h2 class="lotResTit ...">NOMBRE</h2>
  - <div class="resultado"> ... <span>hora</span> ... <span>numero</span> ... <abbr title="TAU">TAU</abbr>
  - A/B: columnas "Triple A" y "Triple B" en el header, y luego 2 spans de número por fila.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache

from core.models import Provider, CurrentResult
TUAZAR_URL = "https://www.tuazar.com/loteria/resultados/"


# -----------------------------
# Normalización
# -----------------------------

TIME_12H_RE = re.compile(r"^\s*(\d{1,2}:\d{2}\s*(AM|PM))\s*$", re.IGNORECASE)
DIGITS_RE = re.compile(r"\d+")


def _parse_time_12h(text: str) -> Optional[time]:
    """
    Convierte "1:00 PM" -> datetime.time(13, 0).
    Devuelve None si no parsea.
    """
    if not text:
        return None
    t = " ".join(text.strip().split())  # normaliza whitespace
    if not TIME_12H_RE.match(t):
        return None
    try:
        return datetime.strptime(t.upper(), "%I:%M %p").time()
    except ValueError:
        return None


def _normalize_number(text: str) -> str:
    """
    Extrae solo dígitos, preservando ceros a la izquierda si vienen en el HTML.
    Si el HTML trae "-", devuelve "".
    """
    if not text:
        return ""
    raw = text.strip()
    if raw == "-":
        return ""
    # Aquí NO convertimos a int para no perder leading zeros (ej: "013").
    digits = "".join(DIGITS_RE.findall(raw))
    return digits.strip()


def _normalize_signo(text: str) -> str:
    """
    Normaliza el signo a formato compacto (TAU, LIB, etc).
    Si es "-", devuelve "".
    """
    if not text:
        return ""
    s = text.strip().upper()
    if s == "-":
        return ""
    # Mantenerlo corto y seguro para concatenación: letras/números/guión bajo.
    s = re.sub(r"[^A-Z0-9_]", "", s)
    return s


def _safe_text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


# -----------------------------
# Parsing de bloques
# -----------------------------

@dataclass(frozen=True)
class ParsedRow:
    draw_time: time
    number: str
    signo: str = ""  # opcional


def _iter_result_rows(block: BeautifulSoup) -> Iterable[BeautifulSoup]:
    """
    Itera filas "div.resultado" dentro de un bloque de resultados.
    La primera fila suele ser el header (contiene textos tipo "Horario", "Triple", "Signo").
    """
    for row in block.select("div.resultado"):
        yield row


def _is_header_row(row: BeautifulSoup) -> bool:
    txt = _safe_text(row).lower()
    # Heurística: header contiene "horario" y "triple"/"número"/"signo".
    return ("horario" in txt) and (("triple" in txt) or ("número" in txt) or ("numero" in txt) or ("signo" in txt))


def _parse_block_simple_triple(block: BeautifulSoup) -> List[ParsedRow]:
    """
    Caso: 2 columnas por fila (Horario + Triple).
    Importante: NO buscar el primer span numérico porque el de la hora
    ("1:00 PM") también contiene dígitos y se convertiría en "100".
    """
    out: List[ParsedRow] = []
    for row in _iter_result_rows(block):
        if _is_header_row(row):
            continue

        time_span = row.select_one(".horario span")
        draw_time = _parse_time_12h(_safe_text(time_span))
        if not draw_time:
            continue

        # En TuAzar, el número está en la 2da columna del grid.
        cols = row.select("div[class*='col-xs-']")
        if len(cols) < 2:
            continue

        num_span = cols[1].select_one("span")
        number = _normalize_number(_safe_text(num_span))
        if not number:
            continue

        out.append(ParsedRow(draw_time=draw_time, number=number))
    return out

def _parse_block_triple_and_signo(block: BeautifulSoup) -> List[ParsedRow]:
    """
    Caso: 3 columnas (Horario + Triple/Número + Signo).
    El signo viene como <abbr title="TAU">TAU</abbr> (ver dump). :contentReference[oaicite:3]{index=3}
    """
    out: List[ParsedRow] = []
    for row in _iter_result_rows(block):
        if _is_header_row(row):
            continue

        time_span = row.select_one(".horario span")
        draw_time = _parse_time_12h(_safe_text(time_span))
        if not draw_time:
            continue

        # Número: suele ser el span simple en la columna central.
        # Signo: abbr title="TAU"
        num_span = None
        # columna central normalmente es ".col-xs-4" (segunda columna)
        cols = row.select("div[class*='col-xs-']")
        if len(cols) >= 2:
            num_span = cols[1].select_one("span")

        number = _normalize_number(_safe_text(num_span))
        if not number:
            continue

        abbr = row.select_one("abbr[title]")
        signo = _normalize_signo(abbr.get("title", "")) if abbr else ""
        if not signo:
            # fallback: texto visible del abbr si title viene vacío
            signo = _normalize_signo(_safe_text(abbr))

        # Si no hay signo válido, igual guardamos el número (pero sin extra).
        out.append(ParsedRow(draw_time=draw_time, number=number, signo=signo))
    return out


def _parse_block_triple_a_b(block: BeautifulSoup) -> Tuple[List[ParsedRow], List[ParsedRow]]:
    """
    Caso: 3 columnas (Horario + Triple A + Triple B).
    Patrón visible en tu dump (EL ARREJUNTAO): :contentReference[oaicite:4]{index=4}

    Devuelve (rows_a, rows_b).
    """
    out_a: List[ParsedRow] = []
    out_b: List[ParsedRow] = []

    for row in _iter_result_rows(block):
        if _is_header_row(row):
            continue

        time_span = row.select_one(".horario span")
        draw_time = _parse_time_12h(_safe_text(time_span))
        if not draw_time:
            continue

        cols = row.select("div[class*='col-xs-']")
        if len(cols) < 3:
            continue

        num_a = _normalize_number(_safe_text(cols[1].select_one("span")))
        num_b = _normalize_number(_safe_text(cols[2].select_one("span")))

        if num_a:
            out_a.append(ParsedRow(draw_time=draw_time, number=num_a))
        if num_b:
            out_b.append(ParsedRow(draw_time=draw_time, number=num_b))

    return out_a, out_b


def _find_block_by_title(soup: BeautifulSoup, title_contains: str) -> Optional[BeautifulSoup]:
    """
    Encuentra el contenedor de resultados más cercano que contenga un <h2> cuyo texto
    contenga title_contains (case-insensitive).

    Tu HTML tiene:
      <div class="resultados"> ... <h2 class="lotResTit ...">NOMBRE</h2> ... </div>
    o, para loterías compuestas, sub-secciones:
      <div class="sub-lottery-section"> <h2 ...>NOMBRE</h2> ... </div>
    """
    needle = title_contains.strip().lower()
    for h2 in soup.select("h2"):
        if needle in _safe_text(h2).strip().lower():
            # Elegimos el contenedor más útil: sub-lottery-section si existe, si no resultados.
            parent = h2.find_parent("div", class_="sub-lottery-section")
            if parent:
                return parent
            parent = h2.find_parent("div", class_="resultados")
            if parent:
                return parent
            return h2.parent
    return None


# -----------------------------
# Persistencia
# -----------------------------

def _get_or_create_provider(name: str) -> Provider:
    provider, _ = Provider.objects.get_or_create(
        name=name,
        defaults={"source_url": TUAZAR_URL, "is_active": True},
    )
    return provider


def _save_row(*, provider: Provider, draw_date, row: ParsedRow) -> bool:
    """
    Upsert de CurrentResult por (provider, draw_date, draw_time).
    Devuelve True si guardó algo.
    """
    if not row.number:
        return False

    # extra con signo cuando aplique.
    defaults = {"winning_number": row.number, "image_url": ""}

    # IMPORTANTE: tu modelo real tiene extra JSONField según tu resumen.
    # Si en algún entorno no existe, esto fallará y debes alinear el modelo.
    if row.signo:
        defaults["extra"] = {"signo": row.signo}

    CurrentResult.objects.update_or_create(
        provider=provider,
        draw_date=draw_date,
        draw_time=row.draw_time,
        defaults=defaults,
    )
    return True


def _invalidate_results_cache() -> None:
    """
    Invalida cache de resultados por patrón.
    El backend suele ser django-redis, que expone cache.delete_pattern(pattern).
    Si no existe, degradamos de forma segura sin reventar el comando.
    """
    patterns = [
        "results:triples:*",
        "results:current:*",
    ]

    delete_pattern = getattr(cache, "delete_pattern", None)
    if callable(delete_pattern):
        for p in patterns:
            delete_pattern(p)
        return

    # Fallback: si no hay soporte de pattern delete, al menos limpiamos la clave global si existe.
    for k in ["results:current:all"]:
        cache.delete(k)


# -----------------------------
# Command
# -----------------------------

class Command(BaseCommand):
    help = "Scrapea TuAzar y upsertea CurrentResult para providers no cubiertos por Lotoven."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=20, help="Timeout HTTP (seg).")
        parser.add_argument(
            "--html-file",
            type=str,
            default="",
            help="Ruta a un archivo HTML local para pruebas offline (si se define, no hace HTTP).",
        )

    def handle(self, *args, **opts):
        timeout: int = opts["timeout"]
        html_file: str = (opts["html_file"] or "").strip()

        if html_file:
            with open(html_file, "r", encoding="utf-8", errors="ignore") as f:
                html = f.read()
        else:
            resp = requests.get(
                TUAZAR_URL,
                timeout=timeout,
                headers={"User-Agent": "loteria-tv-bot/1.0 (+contact: admin@local)"},
            )
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")
        today = timezone.localdate()

        # Mapeo de targets (títulos tal como suelen aparecer en la web).
        # Si TuAzar cambia acentos/mayúsculas, _find_block_by_title lo tolera.
        targets = {
            "Chance Astral": {"type": "triple_signo", "title": "CHANCE ASTRAL"},
            "Triple Gana": {"type": "triple_signo", "title": "TRIPLE GANA"},
            "Super Gana": {"type": "triple_signo", "title": "SUPER GANA"},
        }

        saved = 0
        saved_with_signo = 0
        missing_blocks: List[str] = []

        with transaction.atomic():
            # 1) Chance Astral (con signo)
            b = _find_block_by_title(soup, targets["Chance Astral"]["title"])
            if not b:
                missing_blocks.append("Chance Astral")
            else:
                provider = _get_or_create_provider("Chance Astral")
                rows = _parse_block_triple_and_signo(b)
                for r in rows:
                    if _save_row(provider=provider, draw_date=today, row=r):
                        saved += 1
                        if r.signo:
                            saved_with_signo += 1

            # 2) Triple Gana (con signo)
            b = _find_block_by_title(soup, targets["Triple Gana"]["title"])
            if not b:
                missing_blocks.append("Triple Gana")
            else:
                provider = _get_or_create_provider("Triple Gana")
                rows = _parse_block_triple_and_signo(b)
                for r in rows:
                    if _save_row(provider=provider, draw_date=today, row=r):
                        saved += 1
                        if r.signo:
                            saved_with_signo += 1

            # 3) Super Gana (con signo)
            b = _find_block_by_title(soup, targets["Super Gana"]["title"])
            if not b:
                missing_blocks.append("Super Gana")
            else:
                provider = _get_or_create_provider("Super Gana")
                rows = _parse_block_triple_and_signo(b)
                for r in rows:
                    if _save_row(provider=provider, draw_date=today, row=r):
                        saved += 1
                        if r.signo:
                            saved_with_signo += 1

        # Cache invalidation al final (crítico por tu keyspace results:triples:v4:...:{YYYY-MM-DD})
        _invalidate_results_cache()

        # Resumen
        self.stdout.write(self.style.SUCCESS("TuAzar scrape finalizado."))
        self.stdout.write(f"- Guardados/upsert: {saved}")
        self.stdout.write(f"- Guardados con signo: {saved_with_signo}")
        if missing_blocks:
            self.stdout.write(self.style.WARNING(f"- Bloques no encontrados en HTML: {', '.join(missing_blocks)}"))
