from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from core.services.scraper_health_service import ScraperHealthService
from core.services.scraper_ops_contract_service import ScraperOpsContractService


class ScraperPhaseZeroContractServiceTestCase(SimpleTestCase):
    @override_settings(
        SCRAPER_ALERT_PRIMARY_CHANNEL="telegram",
        SCRAPER_INCIDENT_VIEWER_GROUPS=["OpsViewers"],
        SCRAPER_INCIDENT_RESOLVER_GROUPS=["OpsResolvers"],
        SCRAPER_RESULT_AUTOMATIC_ORIGIN_LABEL="automatic_valid",
        SCRAPER_RESULT_MANUAL_ORIGIN_LABEL="manual_contingency",
    )
    def test_build_contract_snapshot_includes_global_phase_zero_rules(self):
        snapshot = ScraperOpsContractService.build_contract_snapshot()

        self.assertEqual(snapshot["global_contract"]["primary_alert_channel"], "telegram")
        self.assertEqual(snapshot["global_contract"]["viewer_groups"], ("OpsViewers",))
        self.assertEqual(snapshot["global_contract"]["resolver_groups"], ("OpsResolvers",))
        self.assertEqual(snapshot["global_contract"]["automatic_origin_label"], "automatic_valid")
        self.assertEqual(snapshot["global_contract"]["manual_origin_label"], "manual_contingency")

    def test_contract_registry_matches_scraper_registry(self):
        ScraperOpsContractService.validate_registry_alignment()

        matrix = ScraperOpsContractService.build_operational_matrix()
        self.assertEqual(len(matrix), len(ScraperHealthService.REGISTRY))
        self.assertEqual(
            {row["scraper_key"] for row in matrix},
            set(ScraperHealthService.REGISTRY.keys()),
        )

    def test_lotoven_triples_contract_marks_mixed_validation(self):
        contract = ScraperOpsContractService.get_contract("lotoven_triples")

        self.assertEqual(contract.result_model, "CurrentResult")
        self.assertEqual(contract.validation_profile, "mixed")
        self.assertTrue(
            any("Triple Chance estricto" in item for item in contract.expected_group_scope)
        )


class DescribeScraperOpsCommandTestCase(SimpleTestCase):
    def test_command_renders_phase_zero_matrix(self):
        stdout = StringIO()

        call_command("describe_scraper_ops", stdout=stdout)
        output = stdout.getvalue()

        self.assertIn("Fase 0 - contrato operativo vigente", output)
        self.assertIn("[lotoven_triples] Triples Lotoven", output)
        self.assertIn("validation_profile=mixed", output)
        self.assertIn("[condor_animalitos] Animalitos Condor Gana", output)
