import requests
from bs4 import BeautifulSoup
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import Provider, CurrentResult

URL = "https://lotoven.com/loterias/"

TABLE_BASED = {
    "trioactivo": "Trio Activo",
    "laricachona": "La Ricachona",
    "triplecentena": "Triple Centena",
    "tripledorado": "Triple Dorado",
    "triplefacil": "Triple Facil",
    "terminaltrio": "Terminal Trio",
    "terminallagranjita": "Terminal La Granjita",
    "laruca": "La Ruca",
}

class Command(BaseCommand):
    help = "Scrape lotoven tablas simples"

    def handle(self, *args, **kwargs):
        html = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
        soup = BeautifulSoup(html, "html.parser")

        draw_date = timezone.localdate()
        total_saved = 0

        with transaction.atomic():
            for dom_id, provider_name in TABLE_BASED.items():
                block = soup.select_one(f"div#{dom_id}")
                if not block:
                    continue

                rows = block.select("tr")
                if len(rows) < 2:
                    continue

                times = [c.get_text(strip=True) for c in rows[0].select("th,td")]
                numbers = [c.get_text(strip=True) for c in rows[1].select("th,td")]

                provider, _ = Provider.objects.get_or_create(name=provider_name)

                for t, n in zip(times, numbers):
                    if ":" not in t:
                        continue

                    hh, mm = t.split(":")
                    draw_time = datetime(2000, 1, 1, int(hh), int(mm)).time()

                    CurrentResult.objects.update_or_create(
                        provider=provider,
                        draw_date=draw_date,
                        draw_time=draw_time,
                        defaults={"winning_number": n.strip()},
                    )

                    total_saved += 1

        self.stdout.write(self.style.SUCCESS(f"Guardados {total_saved} resultados"))
