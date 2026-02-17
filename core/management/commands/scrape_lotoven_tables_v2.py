import re
import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Provider, CurrentResult

URL = "https://lotoven.com/loterias/"

TIME_RE = re.compile(r"\b(?:[01]\d|2[0-3]):[0-5]\d\b")
NUM_RE = re.compile(r"\b\d{3}\b")  # triples típicamente 3 dígitos

# Ajusta esta lista según lo que veas en la web
PROVIDERS = [
  "Trio Activo",
  "Triple Chance",
  "Triple Zulia",
  "Triple Tachira",
  "Triple Caracas",
  "Triple Caliente",
  "Triple Zamorano",
  "Triple Uneloton",
  "Terminal Trio",
  "Terminal La Granjita",
  "La Granjita",
  "La Ricachona",
  "La Ruca",
]

class Command(BaseCommand):
  help = "Scrape lotoven loterias/triples (V2 parser heurístico)"

  def handle(self, *args, **kwargs):
    resp = requests.get(URL, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text("\n", strip=True)

    today = timezone.localdate()
    created = updated = 0
    found_any = False

    for name in PROVIDERS:
      idx = text.find(name)
      if idx == -1:
        continue

      chunk = text[idx: idx + 8000]
      times = TIME_RE.findall(chunk)
      nums = NUM_RE.findall(chunk)

      n = min(len(times), len(nums))
      if n == 0:
        continue

      found_any = True
      provider, _ = Provider.objects.get_or_create(name=name)

      for i in range(n):
        hhmm = times[i]
        num = nums[i]

        hh, mm = hhmm.split(":")
        draw_time = timezone.datetime(2000, 1, 1, int(hh), int(mm)).time()

        obj, was_created = CurrentResult.objects.update_or_create(
          provider=provider,
          draw_date=today,
          draw_time=draw_time,
          defaults={"winning_number": num},
        )
        if was_created:
          created += 1
        else:
          updated += 1

    if not found_any:
      self.stdout.write(self.style.WARNING("No se detectaron secciones/pares hora+número. Lotoven cambió o lista PROVIDERS no coincide."))
    self.stdout.write(self.style.SUCCESS(f"OK tables_v2 created={created} updated={updated}"))
