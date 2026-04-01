from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

from core.models import AnimalitoResult, Provider, ScraperIncident
from core.services.provider_catalog_service import canonical_animalito_provider_name


@dataclass(frozen=True)
class FallbackAttemptResult:
    scraper_key: str
    provider_name: str
    rows_persisted: int
    success: bool
    detail: str = ""


class TuAzarAnimalitoFallbackService:
    SCRAPER_KEY = "tuazar_animalitos_lottorey"
    SOURCE_URL = "https://www.tuazar.com/loteria/animalitos/resultados/"
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    TARGET_PROVIDER = "Lotto Rey"

    @classmethod
    def run_lottorey(cls, *, target_date, incident: ScraperIncident | None) -> FallbackAttemptResult:
        if target_date != timezone.localdate():
            return FallbackAttemptResult(
                scraper_key=cls.SCRAPER_KEY,
                provider_name=cls.TARGET_PROVIDER,
                rows_persisted=0,
                success=False,
                detail="TuAzar animalitos solo se usa como emergencia para HOY.",
            )

        html = cls._fetch_html()
        rows = cls._parse_lottorey_rows(html)
        if not rows:
            return FallbackAttemptResult(
                scraper_key=cls.SCRAPER_KEY,
                provider_name=cls.TARGET_PROVIDER,
                rows_persisted=0,
                success=False,
                detail="TuAzar no devolvio filas utilizables para Lotto Rey.",
            )

        provider = cls._upsert_provider(rows[0])
        persisted = 0
        for row in rows:
            if cls._persist_row(provider=provider, row=row, target_date=target_date, incident=incident):
                persisted += 1

        return FallbackAttemptResult(
            scraper_key=cls.SCRAPER_KEY,
            provider_name=provider.name,
            rows_persisted=persisted,
            success=persisted > 0,
            detail=f"TuAzar emergencia persiste {persisted} filas para {provider.name}.",
        )

    @classmethod
    def _fetch_html(cls) -> str:
        response = requests.get(
            cls.SOURCE_URL,
            headers={"User-Agent": cls.USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        return response.text

    @classmethod
    def _parse_lottorey_rows(cls, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        sections = soup.select(".lottery-animalitos-grid-container .resultados")
        rows: list[dict] = []

        for section in sections:
            title = section.select_one("h2.lotResTit")
            provider_name = canonical_animalito_provider_name(title.get_text(" ", strip=True) if title else "")
            if provider_name != cls.TARGET_PROVIDER:
                continue

            logo_el = title.select_one("img") if title else None
            provider_logo_url = cls._abs_url(logo_el.get("src") if logo_el else "")

            for card in section.select(".row.resultado .col-xs-6.col-sm-3"):
                image_el = card.select_one("img")
                image_src = cls._abs_url(image_el.get("src") if image_el else "")
                if not image_src or "resultados-espera" in image_src:
                    continue

                horario_text = card.select_one(".horario span")
                draw_time = cls._parse_time_12h(horario_text.get_text(" ", strip=True) if horario_text else "")
                if not draw_time:
                    continue

                text_spans = card.select("div span")
                result_text = text_spans[0].get_text(" ", strip=True) if text_spans else ""
                animal_number, animal_name = cls._parse_number_and_name(result_text)
                if not animal_number or not animal_name:
                    continue

                rows.append(
                    {
                        "provider_name": provider_name,
                        "provider_logo_url": provider_logo_url,
                        "provider_source_url": cls.SOURCE_URL,
                        "animal_image_url": image_src,
                        "animal_number": animal_number,
                        "animal_name": animal_name,
                        "draw_time_obj": draw_time,
                    }
                )
            break

        return rows

    @classmethod
    def _upsert_provider(cls, row: dict) -> Provider:
        provider, _ = Provider.objects.get_or_create(
            name=row["provider_name"],
            defaults={
                "logo_url": row["provider_logo_url"],
                "source_url": row["provider_source_url"],
                "is_active": True,
            },
        )
        changed = False
        if row["provider_logo_url"] and provider.logo_url != row["provider_logo_url"]:
            provider.logo_url = row["provider_logo_url"]
            changed = True
        if row["provider_source_url"] and provider.source_url != row["provider_source_url"]:
            provider.source_url = row["provider_source_url"]
            changed = True
        if not provider.is_active:
            provider.is_active = True
            changed = True
        if changed:
            provider.save(update_fields=["logo_url", "source_url", "is_active"])
        return provider

    @classmethod
    def _persist_row(cls, *, provider: Provider, row: dict, target_date, incident: ScraperIncident | None) -> bool:
        existing = AnimalitoResult.objects.filter(
            provider=provider,
            draw_date=target_date,
            draw_time=row["draw_time_obj"],
        ).first()

        if existing and existing.result_origin in {
            AnimalitoResult.ResultOrigin.AUTOMATIC_VALID,
            AnimalitoResult.ResultOrigin.MANUAL_CONTINGENCY,
        }:
            return False

        defaults = {
            "animal_number": row["animal_number"],
            "animal_name": row["animal_name"],
            "animal_image_url": row["animal_image_url"],
            "provider_logo_url": row["provider_logo_url"],
            "result_origin": AnimalitoResult.ResultOrigin.AUTOMATIC_FALLBACK,
            "source_incident": incident if getattr(incident, "pk", None) else None,
        }

        AnimalitoResult.objects.update_or_create(
            provider=provider,
            draw_date=target_date,
            draw_time=row["draw_time_obj"],
            defaults=defaults,
        )
        return True

    @staticmethod
    def _abs_url(value: str) -> str:
        if not value:
            return ""
        return urljoin(TuAzarAnimalitoFallbackService.SOURCE_URL, value)

    @staticmethod
    def _parse_time_12h(value: str):
        raw = (value or "").strip().upper().replace(".", "")
        if not raw:
            return None
        for fmt in ("%I:%M %p", "%I %p"):
            try:
                return datetime.strptime(raw, fmt).time()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_number_and_name(value: str) -> tuple[str, str]:
        raw = " ".join((value or "").split())
        if not raw or raw == "- -":
            return "", ""
        normalized = raw.replace(" - ", "|").replace("-", "|", 1)
        pieces = [piece.strip() for piece in normalized.split("|") if piece.strip()]
        if len(pieces) < 2:
            return "", ""
        animal_number = pieces[0]
        animal_name = pieces[1].title()
        if animal_number == "-" or animal_name == "-":
            return "", ""
        return animal_number, animal_name
