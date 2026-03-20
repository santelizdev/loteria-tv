"""
Scraper de loterías de Lotoven.

Fuentes:
- https://lotoven.com/loterias/ (tablas simples)
- https://lotoven.com/loteria/<provider>/resultados/ (Triple Chance y triples A/B/C)

Notas:
- Triple Caracas/Táchira/Zulia/Caliente/Zamorano publican resultados A/B/C.
- Se guardan como providers distintos: "<Proveedor> A", "<Proveedor> B", "<Proveedor> C"
  para evitar sobreescritura por (provider, draw_date, draw_time).
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
from core.services.result_window_service import (
    delete_future_rows_for_provider,
    get_business_cutoff_time,
)

LOTERIAS_URL = "https://lotoven.com/loterias/"
TRIPLE_CHANCE_URL = "https://lotoven.com/loteria/triplechance/resultados/"
TRIPLE_ZULIA_URL = "https://lotoven.com/loteria/triplezulia/resultados/"
TRIPLE_CARACAS_URL = "https://lotoven.com/loteria/triplecaracas/resultados/"
TRIPLE_TACHIRA_URL = "https://lotoven.com/loteria/tripletachira/resultados/"
TRIPLE_CALIENTE_URL = "https://lotoven.com/loteria/triplecaliente/resultados/"
TRIPLE_ZAMORANO_URL = "https://lotoven.com/loteria/triplezamorano/resultados/"

EXPECTED_TRIPLE_ABC_TIMES = {
    "Triple Caracas": {(13, 0), (16, 30), (19, 10)},
    "Triple Caliente": {(13, 0), (16, 30), (19, 10)},
    "Triple Tachira": {(13, 15), (16, 45), (22, 0)},
    "Triple Zamorano": {(10, 0), (12, 0), (14, 0)},
}
EXPECTED_TRIPLE_CHANCE_TIMES = {(13, 0), (16, 0), (19, 0)}


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    kind: str  # "table_simple" | "triple_chance" | "triple_abc"
    dom_id: str = ""
    source_url: str = LOTERIAS_URL


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(name="Trio Activo", kind="table_simple", dom_id="trioactivo"),
    ProviderSpec(name="La Ricachona", kind="table_simple", dom_id="laricachona"),
    ProviderSpec(name="Triple Centena", kind="table_simple", dom_id="triplecentena"),
    ProviderSpec(name="Triple Dorado", kind="table_simple", dom_id="tripledorado"),
    ProviderSpec(name="Triple Facil", kind="table_simple", dom_id="triplefacil"),
    ProviderSpec(name="Terminal Trio", kind="table_simple", dom_id="terminaltrio"),
    ProviderSpec(name="Terminal La Granjita", kind="table_simple", dom_id="terminallagranjita"),
    ProviderSpec(name="La Ruca", kind="table_simple", dom_id="laruca"),
    ProviderSpec(
        name="Triple Chance",
        kind="triple_chance",
        dom_id="triplechance",
        source_url=TRIPLE_CHANCE_URL,
    ),
    ProviderSpec(name="Triple Zulia", kind="triple_abc", dom_id="triplezulia", source_url=TRIPLE_ZULIA_URL),
    ProviderSpec(name="Triple Caracas", kind="triple_abc", dom_id="triplecaracas", source_url=TRIPLE_CARACAS_URL),
    ProviderSpec(name="Triple Tachira", kind="triple_abc", dom_id="tripletachira", source_url=TRIPLE_TACHIRA_URL),
    ProviderSpec(name="Triple Caliente", kind="triple_abc", dom_id="triplecaliente", source_url=TRIPLE_CALIENTE_URL),
    ProviderSpec(name="Triple Zamorano", kind="triple_abc", dom_id="triplezamorano", source_url=TRIPLE_ZAMORANO_URL),
)


_RE_HHMM = re.compile(r"(\d{1,2})\s*:\s*(\d{2})")
_RE_NUM_SIGNO = re.compile(r"^\s*(\d+)\s*([A-Za-z]{2,})\s*$")  # 721Ari / 780Tau
_RE_NUM_SIGNO_WS = re.compile(r"^\s*(\d+)\s+([A-Za-z]{2,})\s*$")  # 780 Tau


def _clean(text: str) -> str:
    return (text or "").strip()


def _parse_time_hhmm(value: str) -> Optional[time]:
    m = _RE_HHMM.search(value or "")
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


def _cleanup_unexpected_times(provider: Provider, draw_date, expected_hhmm: set[tuple[int, int]]) -> None:
    if not expected_hhmm:
        return
    allowed = [time(h, m) for h, m in sorted(expected_hhmm)]
    CurrentResult.objects.filter(
        provider=provider,
        draw_date=draw_date,
    ).exclude(draw_time__in=allowed).delete()


def _filter_due_current_rows(rows, cutoff_time: time):
    filtered = []
    for row in rows:
        draw_time = row[0] if isinstance(row[0], time) else row[1]
        if draw_time <= cutoff_time:
            filtered.append(row)
    return filtered


def _get_or_create_provider(name: str, source_url: str) -> Provider:
    provider, _ = Provider.objects.get_or_create(
        name=name,
        defaults={"source_url": source_url, "is_active": True, "logo_url": ""},
    )
    updates = []
    if not provider.source_url:
        provider.source_url = source_url
        updates.append("source_url")
    if provider.is_active is False:
        provider.is_active = True
        updates.append("is_active")
    if updates:
        provider.save(update_fields=updates)
    return provider


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


def _parse_triple_chance(block) -> list[Tuple[str, time, str, Optional[dict]]]:
    table = block.select_one("table#resultados") or block.select_one("table")
    if not table:
        return []

    rows = _extract_table_rows_as_cells(table)
    if len(rows) < 2:
        return []

    times = rows[0]
    row_a = rows[1] if len(rows) >= 2 else []
    row_b = rows[2] if len(rows) >= 3 else []
    row_c = rows[3] if len(rows) >= 4 else []

    out: list[Tuple[str, time, str, Optional[dict]]] = []

    for idx, t_raw, a_raw in _iter_pairs(times, row_a):
        t = _parse_time_hhmm(t_raw)
        if not t:
            continue
        a = _clean(a_raw)
        if a:
            out.append(("A", t, a, {"grupo": "A"}))

        if idx < len(row_b):
            b = _clean(row_b[idx])
            if b:
                out.append(("B", t, b, {"grupo": "B"}))

        if idx < len(row_c):
            c_raw = _clean(row_c[idx])
            c_num, c_signo = _split_number_and_signo(c_raw)
            c_num = _clean(c_num)
            if c_num:
                c_extra = {"grupo": "C"}
                if c_signo:
                    c_extra["signo"] = c_signo
                out.append(("C", t, c_num, c_extra))

    return out


def _find_triple_abc_block(soup: BeautifulSoup, provider_name: str):
    needle = provider_name.strip().lower()
    for h2 in soup.select("h2.plan-interest-percent, h2.title"):
        if needle in _clean(h2.get_text(" ", strip=True)).lower():
            parent = h2.find_parent("div", class_="plan-item")
            if parent:
                return parent
    return soup.select_one("div.plan-item") or soup


def _parse_triple_abc(block) -> list[Tuple[str, time, str, Optional[dict]]]:
    out: list[Tuple[str, time, str, Optional[dict]]] = []

    uls = block.select("ul.plan-invest-limit")
    if not uls:
        return []

    for ul in uls:
        title_li = ul.select_one("li.pb-2")
        title = _clean(title_li.get_text(" ", strip=True)) if title_li else ""
        triple_group = title.replace("Triple", "").strip().upper()  # A/B/C
        if triple_group not in {"A", "B", "C"}:
            continue

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
            extra["grupo"] = triple_group
            if signo:
                extra["signo"] = signo

            out.append((triple_group, t, num, extra or None))

    return out


def _filter_expected_triple_abc_times(
    provider_name: str,
    rows: list[Tuple[str, time, str, Optional[dict]]],
) -> list[Tuple[str, time, str, Optional[dict]]]:
    expected = EXPECTED_TRIPLE_ABC_TIMES.get(provider_name)
    if not expected:
        return rows
    filtered: list[Tuple[str, time, str, Optional[dict]]] = []
    for grp, t, num, extra in rows:
        if (t.hour, t.minute) in expected:
            filtered.append((grp, t, num, extra))
    return filtered


def _filter_expected_triple_chance_times(
    rows: list[Tuple[str, time, str, Optional[dict]]],
) -> list[Tuple[str, time, str, Optional[dict]]]:
    filtered: list[Tuple[str, time, str, Optional[dict]]] = []
    for grp, t, num, extra in rows:
        if (t.hour, t.minute) in EXPECTED_TRIPLE_CHANCE_TIMES:
            filtered.append((grp, t, num, extra))
    return filtered


class Command(BaseCommand):
    help = "Scrape Lotoven tablas y triples A/B/C (incluye Triple Caliente y Triple Zamorano)"

    def add_arguments(self, parser):
        parser.add_argument("--only", help="Procesa solo un dom_id (ej: tripletachira).")
        parser.add_argument("--debug", action="store_true", help="Imprime detalles de parsing (conteos y preview).")

    def handle(self, *args, **opts):
        only = _clean(opts.get("only") or "")
        debug = bool(opts.get("debug"))

        soup_cache: dict[str, BeautifulSoup] = {}

        def load_soup(url: str) -> BeautifulSoup:
            s = soup_cache.get(url)
            if s is not None:
                return s
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
            resp.raise_for_status()
            s = BeautifulSoup(resp.text, "html.parser")
            soup_cache[url] = s
            return s

        draw_date = timezone.localdate()
        cutoff_time = get_business_cutoff_time()
        total_saved = 0
        total_with_signo = 0
        total_future_purged = 0

        specs = PROVIDERS
        if only:
            needle = only.lower()
            specs = tuple(
                s for s in PROVIDERS
                if needle in {s.dom_id.lower(), s.name.lower().replace(" ", ""), s.name.lower()}
            )

        with transaction.atomic():
            for spec in specs:
                soup = load_soup(spec.source_url)
                if spec.kind == "triple_abc":
                    block = _find_triple_abc_block(soup, spec.name)
                else:
                    block = soup.select_one(f"div#{spec.dom_id}") if spec.dom_id else soup
                if not block:
                    if debug:
                        self.stdout.write(f"[debug] missing block for {spec.name} ({spec.source_url})")
                    continue

                if spec.kind == "table_simple":
                    parsed = _filter_due_current_rows(_parse_table_simple(block), cutoff_time)
                    provider = _get_or_create_provider(spec.name, spec.source_url)
                    for t, winning_number, extra in parsed:
                        _save_result(
                            provider=provider,
                            draw_date=draw_date,
                            draw_time=t,
                            winning_number=winning_number,
                            extra=extra,
                        )
                        total_saved += 1
                    total_future_purged += delete_future_rows_for_provider(
                        model=CurrentResult,
                        provider=provider,
                        draw_date=draw_date,
                        cutoff_time=cutoff_time,
                    )
                elif spec.kind == "triple_chance":
                    parsed = _filter_due_current_rows(
                        _filter_expected_triple_chance_times(_parse_triple_chance(block)),
                        cutoff_time,
                    )
                    chance_providers = {
                        group: _get_or_create_provider(f"{spec.name} {group}", spec.source_url)
                        for group in ("A", "B", "C")
                    }
                    for group, t, winning_number, extra in parsed:
                        provider = chance_providers[group]
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
                    for _, p in chance_providers.items():
                        _cleanup_unexpected_times(p, draw_date, EXPECTED_TRIPLE_CHANCE_TIMES)
                        total_future_purged += delete_future_rows_for_provider(
                            model=CurrentResult,
                            provider=p,
                            draw_date=draw_date,
                            cutoff_time=cutoff_time,
                        )
                elif spec.kind == "triple_abc":
                    parsed = _filter_due_current_rows(
                        _filter_expected_triple_abc_times(spec.name, _parse_triple_abc(block)),
                        cutoff_time,
                    )
                    expected_abc = EXPECTED_TRIPLE_ABC_TIMES.get(spec.name)
                    expected_groups = ("A", "C") if spec.name == "Triple Zamorano" else ("A", "B", "C")
                    abc_providers = {
                        group: _get_or_create_provider(f"{spec.name} {group}", spec.source_url)
                        for group in expected_groups
                    }
                    for group, t, winning_number, extra in parsed:
                        provider = abc_providers[group]
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
                    if expected_abc:
                        for _, p in abc_providers.items():
                            _cleanup_unexpected_times(p, draw_date, expected_abc)
                            total_future_purged += delete_future_rows_for_provider(
                                model=CurrentResult,
                                provider=p,
                                draw_date=draw_date,
                                cutoff_time=cutoff_time,
                            )
                else:
                    parsed = []

                if debug:
                    uls = len(block.select("ul.plan-invest-limit"))
                    signo_count = 0
                    if spec.kind == "triple_abc":
                        signo_count = sum(1 for _, _, _, e in parsed if e and e.get("signo"))
                    elif spec.kind == "triple_chance":
                        signo_count = sum(1 for _, _, _, e in parsed if e and e.get("signo"))
                    else:
                        signo_count = sum(1 for _, _, e in parsed if e and e.get("signo"))
                    self.stdout.write(
                        f"[debug] {spec.name} kind={spec.kind} saved={len(parsed)} "
                        f"uls={uls} has_signo={signo_count}"
                    )
                    if parsed[:2]:
                        self.stdout.write(f"[debug] sample={parsed[:2]}")

        DeviceRedisService.delete_cache("results:current:all")

        self.stdout.write(
            self.style.SUCCESS(
                f"Guardados {total_saved} resultados (con signo={total_with_signo}, futuras_limpiadas={total_future_purged})"
            )
        )
