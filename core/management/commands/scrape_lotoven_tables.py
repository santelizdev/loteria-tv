"""
core/management/commands/scrape_lotoven_tables.py

Scraper para https://lotoven.com/loterias/

Soporta:
- Proveedores con tabla simple (fila horas + fila números).
- Triple Chance (tabla con 4 filas: horas, triple, serie, extra_num+signo).
- Triple Zulia / Triple Caracas / Triple Tachira (estructura "plan-item" con Triple A/B/C),
  donde en Triple C el signo puede venir pegado o separado del número.

Guarda:
- CurrentResult (provider, draw_date, draw_time) con winning_number.
- Campo extra (JSONField) con claves como:
    {"signo": "Ari"} o {"signo": "Tau", "serie": "512"} según aplique.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from typing import Iterable, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import CurrentResult, Provider
from core.services.device_redis_service import DeviceRedisService

URL = "https://lotoven.com/loterias/"


@dataclass(frozen=True)
class ProviderSpec:
    dom_id: str
    name: str
    kind: str  # "table_simple" | "triple_chance" | "triple_abc"


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(dom_id="trioactivo", name="Trio Activo", kind="table_simple"),
    ProviderSpec(dom_id="laricachona", name="La Ricachona", kind="table_simple"),
    ProviderSpec(dom_id="triplecentena", name="Triple Centena", kind="table_simple"),
    ProviderSpec(dom_id="tripledorado", name="Triple Dorado", kind="table_simple"),
    ProviderSpec(dom_id="triplefacil", name="Triple Facil", kind="table_simple"),
    ProviderSpec(dom_id="terminaltrio", name="Terminal Trio", kind="table_simple"),
    ProviderSpec(dom_id="terminallagranjita", name="Terminal La Granjita", kind="table_simple"),
    ProviderSpec(dom_id="laruca", name="La Ruca", kind="table_simple"),
    ProviderSpec(dom_id="triplechance", name="Triple Chance", kind="triple_chance"),
    ProviderSpec(dom_id="triplezulia", name="Triple Zulia", kind="triple_abc"),
    ProviderSpec(dom_id="triplecaracas", name="Triple Caracas", kind="triple_abc"),
    ProviderSpec(dom_id="tripletachira", name="Triple Tachira", kind="triple_abc"),
)


_RE_HHMM = re.compile(r"^\s*(\d{1,2})\s*:\s*(\d{2})\s*$")
_RE_NUM_SIGNO = re.compile(r"^\s*(\d+)\s*([A-Za-z]{2,})\s*$")  # 721Ari / 780Tau
_RE_NUM_SIGNO_WS = re.compile(r"^\s*(\d+)\s+([A-Za-z]{2,})\s*$")  # 780 Tau


def _clean(text: str) -> str:
    return (text or "").strip()


def _parse_time_hhmm(value: str) -> Optional[time]:
    m = _RE_HHMM.match(value or "")
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return time(hh, mm)


def _split_number_and_signo(text: str) -> tuple[str, str]:
    """
    Soporta:
      "780 Tau"   -> ("780", "Tau")
      "721Ari"    -> ("721", "Ari")
      "918  Vir"  -> ("918", "Vir")
      "104"       -> ("104", "")
      "980"       -> ("980", "")
    """
    raw = " ".join(_clean(text).split())
    if not raw:
        return "", ""

    m = _RE_NUM_SIGNO_WS.match(raw)
    if m:
        return m.group(1), m.group(2)

    m = _RE_NUM_SIGNO.match(raw.replace(" ", ""))
    if m:
        return m.group(1), m.group(2)

    parts = raw.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    num = parts[0]
    signo = parts[-1]
    if num.isdigit() and not signo.isdigit():
        return num, signo
    return raw, ""


def _extract_table_rows_as_cells(block) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in block.select("tr"):
        cells = [_clean(c.get_text(" ", strip=True)) for c in tr.select("th,td")]
        if cells:
            rows.append(cells)
    return rows


def _iter_pairs(xs: list[str], ys: list[str]) -> Iterable[tuple[int, str, str]]:
    for idx in range(min(len(xs), len(ys))):
        yield idx, xs[idx], ys[idx]


def _save_result(*, provider: Provider, draw_date, draw_time: time, winning_number: str, extra: Optional[dict]) -> None:
    CurrentResult.objects.update_or_create(
        provider=provider,
        draw_date=draw_date,
        draw_time=draw_time,
        defaults={"winning_number": winning_number, "extra": extra},
    )


def _parse_table_simple(block) -> list[Tuple[time, str, Optional[dict]]]:
    rows = _extract_table_rows_as_cells(block)
    if len(rows) < 2:
        return []
    times = rows[0]
    numbers = rows[1]

    out: list[Tuple[time, str, Optional[dict]]] = []
    for _, t_raw, n_raw in _iter_pairs(times, numbers):
        t = _parse_time_hhmm(t_raw)
        if not t:
            continue
        num = _clean(n_raw)
        if not num:
            continue
        out.append((t, num, None))
    return out


def _parse_triple_chance(block) -> list[Tuple[time, str, Optional[dict]]]:
    table = block.select_one("table#resultados") or block.select_one("table")
    if not table:
        return []

    rows = _extract_table_rows_as_cells(table)
    if len(rows) < 2:
        return []

    times = rows[0]
    triples = rows[1]
    series = rows[2] if len(rows) >= 3 else []
    extra2 = rows[3] if len(rows) >= 4 else []

    out: list[Tuple[time, str, Optional[dict]]] = []

    for idx, t_raw, triple_raw in _iter_pairs(times, triples):
        t = _parse_time_hhmm(t_raw)
        if not t:
            continue

        triple = _clean(triple_raw)
        if not triple:
            continue

        extra: dict = {}

        if idx < len(series):
            v = _clean(series[idx])
            if v:
                extra["serie"] = v

        if idx < len(extra2):
            cell_text = _clean(extra2[idx])
            num2, signo = _split_number_and_signo(cell_text)
            if num2 and num2.isdigit():
                extra["extra_num"] = num2
            if signo:
                extra["signo"] = signo

        out.append((t, triple, extra or None))

    return out


def _parse_triple_abc(block) -> list[Tuple[time, str, Optional[dict]]]:
    out: list[Tuple[time, str, Optional[dict]]] = []

    uls = block.select("ul.plan-invest-limit")
    if not uls:
        return []

    for ul in uls:
        title_li = ul.select_one("li.pb-2")
        title = _clean(title_li.get_text(" ", strip=True)) if title_li else ""
        triple_group = title.replace("Triple", "").strip().upper()  # A/B/C

        for li in ul.select("li"):
            lot2 = li.select_one(".lot2")
            lot3 = li.select_one(".lot3")
            if not lot2 or not lot3:
                continue

            t = _parse_time_hhmm(lot2.get_text(" ", strip=True))
            if not t:
                continue

            raw_lot3 = lot3.get_text(" ", strip=True)
            num, signo = _split_number_and_signo(raw_lot3)
            num = _clean(num)
            if not num:
                continue

            extra: dict = {}
            if triple_group:
                extra["grupo"] = triple_group
            if signo:
                extra["signo"] = signo

            out.append((t, num, extra or None))

    return out


class Command(BaseCommand):
    help = "Scrape lotoven tablas (incluye signo en extra para Triple Chance/Zulia/Caracas/Tachira)"

    def add_arguments(self, parser):
        parser.add_argument("--only", help="Procesa solo un dom_id (ej: tripletachira).")
        parser.add_argument("--debug", action="store_true", help="Imprime detalles de parsing (conteos y preview).")

    def handle(self, *args, **opts):
        only = _clean(opts.get("only") or "")
        debug = bool(opts.get("debug"))

        resp = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        draw_date = timezone.localdate()
        total_saved = 0
        total_with_signo = 0

        specs = PROVIDERS
        if only:
            specs = tuple(s for s in PROVIDERS if s.dom_id == only)

        with transaction.atomic():
            for spec in specs:
                block = soup.select_one(f"div#{spec.dom_id}")
                if not block:
                    if debug:
                        self.stdout.write(f"[debug] missing div#{spec.dom_id}")
                    continue

                provider, _ = Provider.objects.get_or_create(name=spec.name)

                if spec.kind == "table_simple":
                    parsed = _parse_table_simple(block)
                elif spec.kind == "triple_chance":
                    parsed = _parse_triple_chance(block)
                elif spec.kind == "triple_abc":
                    parsed = _parse_triple_abc(block)
                else:
                    parsed = []

                for t, winning_number, extra in parsed:
                    _save_result(
                        provider=provider,
                        draw_date=draw_date,
                        draw_time=t,
                        winning_number=winning_number,
                        extra=extra,
                    )
                    total_saved += 1
                    if extra and extra.get("signo"):
                        total_with_signo += 1

                if debug:
                    uls = len(block.select("ul.plan-invest-limit"))
                    self.stdout.write(
                        f"[debug] {spec.dom_id} kind={spec.kind} saved={len(parsed)} "
                        f"uls={uls} has_signo={sum(1 for _, _, e in parsed if e and e.get('signo'))}"
                    )
                    if parsed[:2]:
                        self.stdout.write(f"[debug] sample={parsed[:2]}")

        DeviceRedisService.delete_cache("results:current:all")

        self.stdout.write(
            self.style.SUCCESS(
                f"Guardados {total_saved} resultados (con signo={total_with_signo})"
            )
        )
