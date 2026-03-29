from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import CruzDailyContent

SOURCE_URL = "https://cruzdelasuerte.com/"
EXPECTED_CARDS = (
    ("Cruceta de Hoy", CruzDailyContent.CardType.CRUCETA, 0),
    ("Guía y Probables", CruzDailyContent.CardType.GUIA, 1),
    ("Pirámide de la Suerte", CruzDailyContent.CardType.PIRAMIDE, 2),
)


class Command(BaseCommand):
    help = "Scrapea las 3 cards diarias de Cruz de la Suerte y deja solo el set vigente."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=20, help="Timeout HTTP en segundos.")
        parser.add_argument("--html-file", type=str, default="", help="HTML local para pruebas offline.")

    def handle(self, *args, **options):
        html = self._load_html(timeout=int(options["timeout"]), html_file=(options["html_file"] or "").strip())
        soup = BeautifulSoup(html, "html.parser")
        parsed_cards = self._parse_cards(soup)
        if len(parsed_cards) != len(EXPECTED_CARDS):
            raise CommandError(
                f"Expected {len(EXPECTED_CARDS)} cards from Cruz de la Suerte, got {len(parsed_cards)}."
            )

        draw_date = self._resolve_draw_date(parsed_cards)
        with transaction.atomic():
            for card in parsed_cards:
                CruzDailyContent.objects.update_or_create(
                    draw_date=draw_date,
                    card_type=card["card_type"],
                    defaults={
                        "title": card["title"],
                        "image_url": card["image_url"],
                        "image_alt": card["image_alt"],
                        "display_order": card["display_order"],
                    },
                )

            CruzDailyContent.objects.exclude(draw_date=draw_date).delete()

        self.stdout.write(self.style.SUCCESS(f"Cruz diaria actualizada para {draw_date}: {len(parsed_cards)} cards."))

    @staticmethod
    def _load_html(*, timeout: int, html_file: str) -> str:
        if html_file:
            return Path(html_file).read_text(encoding="utf-8")

        response = requests.get(
            SOURCE_URL,
            timeout=timeout,
            headers={"User-Agent": "loteria-tv-bot/1.0 (+contact: admin@local)"},
        )
        response.raise_for_status()
        return response.text

    def _parse_cards(self, soup: BeautifulSoup) -> list[dict]:
        parsed_cards: list[dict] = []
        cards = soup.select("div.card")
        expected_by_title = {title: (card_type, display_order) for title, card_type, display_order in EXPECTED_CARDS}

        for card in cards:
            title_el = card.select_one("h2.card-title")
            img_el = card.select_one("img")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if title not in expected_by_title or not img_el:
                continue

            card_type, display_order = expected_by_title[title]
            image_src = (img_el.get("src") or "").strip()
            if not image_src:
                continue

            parsed_cards.append(
                {
                    "card_type": card_type,
                    "title": title,
                    "image_url": urljoin(SOURCE_URL, image_src),
                    "image_alt": (img_el.get("alt") or "").strip(),
                    "display_order": display_order,
                }
            )

        parsed_cards.sort(key=lambda item: item["display_order"])
        return parsed_cards

    @classmethod
    def _resolve_draw_date(cls, parsed_cards: list[dict]) -> date:
        for card in parsed_cards:
            parsed_date = cls._extract_date(card.get("image_url") or "") or cls._extract_date(card.get("image_alt") or "")
            if parsed_date:
                return parsed_date
        return timezone.localdate()

    @staticmethod
    def _extract_date(raw_value: str) -> date | None:
        value = str(raw_value or "").strip()
        if not value:
            return None

        match = re.search(r"(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?!\d)", value)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                return None

        match = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", value)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            try:
                return date(year, month, day)
            except ValueError:
                return None

        return None
