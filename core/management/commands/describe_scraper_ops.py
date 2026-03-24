from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from core.services.scraper_ops_contract_service import ScraperOpsContractService


class Command(BaseCommand):
    help = "Describe el contrato operativo de Fase 0 para scrapers e imprime la matriz vigente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="Formato de salida. Default: text.",
        )

    def handle(self, *args, **options):
        output_format = options["format"]
        snapshot = ScraperOpsContractService.build_contract_snapshot()

        if output_format == "json":
            self.stdout.write(json.dumps(snapshot, indent=2, ensure_ascii=True, sort_keys=True))
            return

        global_contract = snapshot["global_contract"]
        self.stdout.write("Fase 0 - contrato operativo vigente")
        self.stdout.write(
            f"canal_alerta={global_contract['primary_alert_channel']} "
            f"viewer_groups={','.join(global_contract['viewer_groups']) or '-'} "
            f"resolver_groups={','.join(global_contract['resolver_groups']) or '-'}"
        )
        self.stdout.write(
            f"origen_auto={global_contract['automatic_origin_label']} "
            f"origen_manual={global_contract['manual_origin_label']}"
        )
        self.stdout.write(
            "fuentes_destinatarios="
            + ",".join(global_contract["alert_recipient_sources"])
        )
        self.stdout.write("")

        for scraper in snapshot["scrapers"]:
            self.stdout.write(f"[{scraper['scraper_key']}] {scraper['label']}")
            self.stdout.write(f"  command={scraper['command_name']}")
            self.stdout.write(f"  model={scraper['result_model']}")
            self.stdout.write(f"  group_key={'+'.join(scraper['group_key'])}")
            self.stdout.write(f"  validation_profile={scraper['validation_profile']}")
            self.stdout.write(f"  business_hours={scraper['starts_hour']}:00-{scraper['ends_hour']}:00")
            self.stdout.write(f"  enforcement={scraper['enforcement_status']}")
            self.stdout.write(f"  failure_real={scraper['real_failure_definition']}")
            self.stdout.write(f"  alert_trigger={scraper['alert_trigger_definition']}")
            self.stdout.write(f"  manual_scope={scraper['manual_resolution_scope']}")
            self.stdout.write("  expected_scope:")
            for item in scraper["expected_group_scope"]:
                self.stdout.write(f"    - {item}")
            self.stdout.write("")
