from celery import shared_task
from django.core.management import call_command

from core.services.scraper_notification_service import ScraperNotificationService
from core.services.scraper_health_service import ScraperHealthService

@shared_task
def scrape_triples():
    return ScraperHealthService.run_registered("lotoven_triples")


@shared_task
def scrape_tuazar_triples():
    return ScraperHealthService.run_registered("tuazar_triples")

@shared_task
def scrape_animalitos():
    return ScraperHealthService.run_registered("lotoven_animalitos")


@shared_task
def scrape_condor_animalitos():
    return ScraperHealthService.run_registered("condor_animalitos")


@shared_task
def archive_daily():
    call_command("archive_daily_triples")
    call_command("archive_daily_animalitos")


@shared_task
def notify_scraper_alerts():
    return ScraperNotificationService.notify_active_alerts()
