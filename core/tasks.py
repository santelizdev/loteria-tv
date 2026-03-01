from celery import shared_task
from django.core.management import call_command

@shared_task
def scrape_triples():
    call_command("scrape_lotoven_tables")

@shared_task
def scrape_animalitos():
    call_command("scrape_lotoven_animalitos")
