from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import QuerySet
from django.utils import timezone

from core.models import AnimalitoResult, CurrentResult, ScraperExecution, ScraperIncident
from core.services.scraper_execution_retention_service import ScraperExecutionRetentionService
from core.services.scraper_ops_contract_service import ScraperOpsContractService
from core.services.tuazar_animalito_fallback_service import (
    FallbackAttemptResult,
    TuAzarAnimalitoFallbackService,
)

STRICT_EXPECTED_GROUP_GRACE_MINUTES = 12
STRICT_GROUP_TIME_TOLERANCE_MINUTES = 15
PRIMARY_ATTEMPT_THRESHOLD = 3
FALLBACK_ATTEMPT_THRESHOLD = 3
BASELINE_PROVIDER_START_TIMES = {
    "lotoven_triples": "08:15",
    "tuazar_triples": "09:15",
    "lotoven_animalitos": "08:15",
}
SCRAPER_SCOPE_START_TIMES = {
    "lotoven_animalitos": "08:15",
}

LOTOVEN_TABLE_SIMPLE_PROVIDERS = (
    "Trio Activo",
    "Triple Centena",
    "Triple Facil",
    # "La Ricachona",  # Pausado por alcance comercial actual.
    # "Triple Dorado",  # Pausado por alcance comercial actual.
    # "Terminal Trio",  # Pausado por alcance comercial actual.
    # "Terminal La Granjita",  # Pausado por alcance comercial actual.
    # "La Ruca",  # Pausado por alcance comercial actual.
)

LOTOVEN_STRICT_SCHEDULE = {
    "Triple Caracas A": ("13:00", "16:30"),
    "Triple Caracas B": ("13:00", "16:30"),
    "Triple Caracas C": ("13:00", "16:30"),
    "Triple Caliente A": ("13:00", "16:30", "19:10"),
    "Triple Caliente B": ("13:00", "16:30", "19:10"),
    "Triple Caliente C": ("13:00", "16:30", "19:10"),
    "Triple Tachira A": ("13:15", "16:45"),
    "Triple Tachira B": ("13:15", "16:45"),
    "Triple Tachira C": ("13:15", "16:45"),
    "Triple Zamorano A": ("10:00", "12:00", "14:00"),
    "Triple Zamorano C": ("10:00", "12:00", "14:00"),
    # "Triple Chance A": ("13:00", "16:00", "19:00"),  # Pausado por alcance comercial actual.
    # "Triple Chance B": ("13:00", "16:00", "19:00"),  # Pausado por alcance comercial actual.
    # "Triple Chance C": ("13:00", "16:00", "19:00"),  # Pausado por alcance comercial actual.
}

TUAZAR_BASELINE_PROVIDERS = (
    "Chance Astral",
    "Triple Gana",
    "Super Gana",
)

LOTOVEN_ANIMALITO_BASELINE_PROVIDERS = (
    "Cazaloton",
    "La Granjita",
    "Loto Chaima",
    "Lotto Rey",
    "Mega Animal 40",
)

CONDOR_PROVIDER = ("Condor Gana",)


@dataclass(frozen=True)
class IncidentCandidate:
    fingerprint: str
    provider_name: str
    draw_time_value: object
    detection_scope: str
    result_model: str
    failure_reason_code: str
    summary: str
    evidence_summary: str
    severity: str = "critical"


class ScraperExecutionService:
    @classmethod
    def start_execution(cls, scraper_key: str) -> ScraperExecution:
        from core.services.scraper_health_service import ScraperHealthService

        ScraperExecutionRetentionService.prune_old_executions(keep_days=2)
        definition = ScraperHealthService.get_definition(scraper_key)
        contract = ScraperOpsContractService.get_contract(scraper_key)
        draw_date = timezone.localdate()
        return ScraperExecution.objects.create(
            scraper_key=definition.key,
            label=definition.label,
            command_name=definition.command_name,
            draw_date=draw_date,
            validation_profile=contract.validation_profile,
            status=ScraperExecution.Status.RUNNING,
            started_at=timezone.now(),
            provider_scope=cls._get_provider_scope(scraper_key),
        )

    @classmethod
    def finalize_failure(cls, execution: ScraperExecution, exc: Exception) -> dict:
        now = timezone.now()
        message = str(exc) or exc.__class__.__name__
        evidence = f"technical_failure error={message}"
        incident = cls._open_or_refresh_incident(
            execution=execution,
            candidate=IncidentCandidate(
                fingerprint=cls._build_fingerprint(
                    execution.scraper_key,
                    execution.draw_date,
                    "scraper",
                    provider_name="",
                    draw_time_str="",
                    failure_reason_code="command_failed",
                ),
                provider_name="",
                draw_time_value=None,
                detection_scope="scraper",
                result_model=cls._get_result_model_name(execution.scraper_key),
                failure_reason_code="command_failed",
                summary=f"{execution.label}: la corrida fallo antes de dejar datos utilizables.",
                evidence_summary=evidence,
            ),
        )
        execution.status = ScraperExecution.Status.FAILED
        execution.finished_at = now
        execution.failure_reason_code = "command_failed"
        execution.error_message = message
        execution.evidence_summary = evidence
        execution.incident_detected = True
        execution.incident_count = 1 if incident else 0
        execution.save(
            update_fields=[
                "status",
                "finished_at",
                "failure_reason_code",
                "error_message",
                "evidence_summary",
                "incident_detected",
                "incident_count",
                "updated_at",
            ]
        )
        return {
            "execution": execution,
            "incidents": [incident] if incident else [],
        }

    @classmethod
    def finalize_success(cls, execution: ScraperExecution) -> dict:
        now = timezone.now()
        draw_date = execution.draw_date
        persisted_groups = cls._get_persisted_groups(execution.scraper_key, draw_date)
        expected_groups = cls._get_due_expected_groups(execution.scraper_key, draw_date, now=now)
        missing_groups = cls._get_missing_groups(expected_groups, persisted_groups)
        candidates = cls._build_incident_candidates(
            scraper_key=execution.scraper_key,
            draw_date=draw_date,
            expected_groups=expected_groups,
            persisted_groups=persisted_groups,
            missing_groups=missing_groups,
            now=now,
        )
        opened = [
            cls._open_or_refresh_incident(execution=execution, candidate=candidate)
            for candidate in candidates
        ]
        cls._apply_contingency_policies(
            execution=execution,
            incidents=opened,
            now=now,
        )
        cls._retire_obsolete_open_incidents(
            execution=execution,
            now=now,
        )
        cls._auto_resolve_recovered_incidents(
            execution=execution,
            expected_groups=expected_groups,
            persisted_groups=persisted_groups,
            now=now,
        )

        evidence = cls._build_evidence_summary(
            scraper_key=execution.scraper_key,
            expected_groups=expected_groups,
            persisted_groups=persisted_groups,
            missing_groups=missing_groups,
        )

        has_incident = bool(opened)
        execution.status = (
            ScraperExecution.Status.INCIDENT if has_incident else ScraperExecution.Status.SUCCESS
        )
        execution.finished_at = now
        execution.expected_groups = expected_groups
        execution.persisted_groups = persisted_groups
        execution.missing_groups = missing_groups
        execution.failure_reason_code = candidates[0].failure_reason_code if candidates else ""
        execution.error_message = candidates[0].summary if candidates else ""
        execution.evidence_summary = evidence
        execution.incident_detected = has_incident
        execution.incident_count = len(opened)
        execution.save(
            update_fields=[
                "status",
                "finished_at",
                "expected_groups",
                "persisted_groups",
                "missing_groups",
                "failure_reason_code",
                "error_message",
                "evidence_summary",
                "incident_detected",
                "incident_count",
                "updated_at",
            ]
        )
        return {
            "execution": execution,
            "has_incident": has_incident,
            "has_blocking_incident": any(cls._incident_impacts_frontend(incident) for incident in opened),
            "incident_count": len(opened),
            "incidents": opened,
            "evidence_summary": evidence,
            "health_error_message": candidates[0].summary if candidates else "",
        }

    @classmethod
    def _get_due_expected_groups(cls, scraper_key: str, draw_date, *, now) -> list[dict]:
        local_now = timezone.localtime(now)
        current_time = local_now.time().replace(second=0, microsecond=0)

        groups: list[dict] = []
        for provider_name, time_values in cls._get_strict_schedule(scraper_key).items():
            for time_str in time_values:
                draw_time = cls._parse_time(time_str)
                draw_time_with_grace = cls._add_minutes_to_time(
                    draw_time,
                    cls._get_strict_group_grace_minutes(scraper_key),
                )
                if draw_time_with_grace <= current_time:
                    groups.append(
                        {
                            "provider_name": provider_name,
                            "draw_time": time_str,
                            "scope": "group",
                        }
                    )

        for provider_name in cls._get_baseline_providers(scraper_key):
            if not cls._is_baseline_provider_due(scraper_key, provider_name, current_time=current_time):
                continue
            groups.append(
                {
                    "provider_name": provider_name,
                    "draw_time": "",
                    "scope": "provider",
                }
            )

        if (
            not groups
            and cls._supports_scraper_scope(scraper_key)
            and cls._is_scraper_scope_due(scraper_key, current_time=current_time)
        ):
            groups.append(
                {
                    "provider_name": "",
                    "draw_time": "",
                    "scope": "scraper",
                }
            )

        return groups

    @classmethod
    def _build_incident_candidates(
        cls,
        *,
        scraper_key: str,
        draw_date,
        expected_groups: list[dict],
        persisted_groups: list[dict],
        missing_groups: list[dict],
        now,
    ) -> list[IncidentCandidate]:
        from core.services.scraper_health_service import ScraperHealthService

        definition = ScraperHealthService.get_definition(scraper_key)
        result_model = cls._get_result_model_name(scraper_key)
        contract = ScraperOpsContractService.get_contract(scraper_key)
        local_now = timezone.localtime(now)
        is_business_hours = definition.starts_hour <= local_now.hour <= definition.ends_hour

        if not is_business_hours:
            return []

        candidates: list[IncidentCandidate] = []

        if not persisted_groups and cls._supports_scraper_scope(scraper_key):
            reason = "missing_scraper_rows"
            evidence = cls._build_evidence_summary(
                scraper_key=scraper_key,
                expected_groups=expected_groups,
                persisted_groups=persisted_groups,
                missing_groups=[{"provider_name": "", "draw_time": "", "scope": "scraper"}],
            )
            return [
                IncidentCandidate(
                    fingerprint=cls._build_fingerprint(
                        scraper_key,
                        draw_date,
                        "scraper",
                        provider_name="",
                        draw_time_str="",
                        failure_reason_code=reason,
                    ),
                    provider_name="",
                    draw_time_value=None,
                    detection_scope="scraper",
                    result_model=result_model,
                    failure_reason_code=reason,
                    summary=(
                        f"{definition.label}: no hay grupos persistidos hoy en {result_model}."
                    ),
                    evidence_summary=evidence,
                )
            ]

        for missing in missing_groups:
            provider_name = missing["provider_name"]
            draw_time_str = missing["draw_time"]
            scope = missing["scope"]
            if scope == "group":
                summary = (
                    f"{definition.label}: falta el grupo esperado {provider_name} {draw_time_str}."
                )
                reason = "missing_expected_group"
            elif scope == "provider":
                summary = (
                    f"{definition.label}: el provider {provider_name} no dejo filas utilizables hoy."
                )
                reason = "missing_provider_rows"
            else:
                summary = (
                    f"{definition.label}: la corrida no dejo grupos utilizables hoy."
                )
                reason = "missing_scraper_rows"

            evidence = cls._build_evidence_summary(
                scraper_key=scraper_key,
                expected_groups=expected_groups,
                persisted_groups=persisted_groups,
                missing_groups=missing_groups,
            )
            candidates.append(
                IncidentCandidate(
                    fingerprint=cls._build_fingerprint(
                        scraper_key,
                        draw_date,
                        scope,
                        provider_name=provider_name,
                        draw_time_str=draw_time_str,
                        failure_reason_code=reason,
                    ),
                    provider_name=provider_name,
                    draw_time_value=cls._parse_time(draw_time_str) if draw_time_str else None,
                    detection_scope=scope,
                    result_model=result_model,
                    failure_reason_code=reason,
                    summary=summary,
                    evidence_summary=evidence,
                )
            )

        return candidates

    @classmethod
    def _open_or_refresh_incident(
        cls,
        *,
        execution: ScraperExecution,
        candidate: IncidentCandidate,
    ) -> ScraperIncident:
        now = timezone.now()
        defaults = {
            "scraper_key": execution.scraper_key,
            "label": execution.label,
            "command_name": execution.command_name,
            "draw_date": execution.draw_date,
            "provider_name": candidate.provider_name,
            "draw_time": candidate.draw_time_value,
            "result_model": candidate.result_model,
            "detection_scope": candidate.detection_scope,
            "validation_profile": execution.validation_profile,
            "status": ScraperIncident.Status.OPEN,
            "severity": candidate.severity,
            "failure_reason_code": candidate.failure_reason_code,
            "summary": candidate.summary,
            "evidence_summary": candidate.evidence_summary,
            "contingency_stage": ScraperIncident.ContingencyStage.OBSERVING,
            "primary_attempt_count": 1,
            "fallback_attempt_count": 0,
            "fallback_scraper_key": "",
            "fallback_activated_at": None,
            "manual_enabled_at": None,
            "first_detected_at": now,
            "last_detected_at": now,
            "last_execution": execution,
            "alert_sent": False,
        }
        incident, created = ScraperIncident.objects.get_or_create(
            fingerprint=candidate.fingerprint,
            defaults=defaults,
        )
        if created:
            return incident

        was_resolved = incident.status == ScraperIncident.Status.RESOLVED
        incident.label = execution.label
        incident.command_name = execution.command_name
        incident.status = ScraperIncident.Status.OPEN
        incident.provider_name = candidate.provider_name
        incident.draw_time = candidate.draw_time_value
        incident.result_model = candidate.result_model
        incident.detection_scope = candidate.detection_scope
        incident.validation_profile = execution.validation_profile
        incident.severity = candidate.severity
        incident.failure_reason_code = candidate.failure_reason_code
        incident.summary = candidate.summary
        incident.evidence_summary = candidate.evidence_summary
        incident.last_detected_at = now
        incident.last_execution = execution
        incident.occurrence_count += 1
        if was_resolved:
            incident.contingency_stage = ScraperIncident.ContingencyStage.OBSERVING
            incident.primary_attempt_count = 1
            incident.fallback_attempt_count = 0
            incident.fallback_scraper_key = ""
            incident.fallback_activated_at = None
            incident.manual_enabled_at = None
            incident.alert_sent = False
            incident.alert_sent_at = None
        elif incident.contingency_stage == ScraperIncident.ContingencyStage.OBSERVING:
            incident.primary_attempt_count += 1
        incident.resolved_at = None
        incident.resolved_by = None
        incident.resolution_note = ""
        incident.save(
            update_fields=[
                "label",
                "command_name",
                "status",
                "provider_name",
                "draw_time",
                "result_model",
                "detection_scope",
                "validation_profile",
                "severity",
                "failure_reason_code",
                "summary",
                "evidence_summary",
                "contingency_stage",
                "primary_attempt_count",
                "fallback_attempt_count",
                "fallback_scraper_key",
                "fallback_activated_at",
                "manual_enabled_at",
                "last_detected_at",
                "last_execution",
                "occurrence_count",
                "alert_sent",
                "alert_sent_at",
                "resolved_at",
                "resolved_by",
                "resolution_note",
                "updated_at",
            ]
        )
        return incident

    @classmethod
    def _apply_contingency_policies(
        cls,
        *,
        execution: ScraperExecution,
        incidents: list[ScraperIncident],
        now,
    ) -> None:
        for incident in incidents:
            if incident.status != ScraperIncident.Status.OPEN:
                continue
            if incident.failure_reason_code == "command_failed":
                continue
            cls._advance_incident_contingency_stage(
                incident=incident,
                execution=execution,
                now=now,
            )

    @classmethod
    def _advance_incident_contingency_stage(
        cls,
        *,
        incident: ScraperIncident,
        execution: ScraperExecution,
        now,
    ) -> None:
        stage = incident.contingency_stage or ScraperIncident.ContingencyStage.OBSERVING
        auto_manual_allowed = cls._can_auto_trigger_manual(incident)
        fallback_scraper_key = cls._get_fallback_scraper_key(incident)

        if (
            stage == ScraperIncident.ContingencyStage.MANUAL_REQUIRED
            and not auto_manual_allowed
        ):
            cls._reset_incident_to_observing(incident=incident)
            stage = ScraperIncident.ContingencyStage.OBSERVING

        if stage == ScraperIncident.ContingencyStage.OBSERVING:
            if incident.primary_attempt_count < PRIMARY_ATTEMPT_THRESHOLD:
                return
            if fallback_scraper_key:
                incident.contingency_stage = ScraperIncident.ContingencyStage.FALLBACK_ACTIVE
                incident.fallback_scraper_key = fallback_scraper_key
                incident.fallback_activated_at = now
                cls._reset_alert_state(incident)
                incident.save(
                    update_fields=[
                        "contingency_stage",
                        "fallback_scraper_key",
                        "fallback_activated_at",
                        "alert_sent",
                        "alert_sent_at",
                        "updated_at",
                    ]
                )
                cls._run_fallback_attempt(incident=incident, execution=execution, now=now)
                return
            if not auto_manual_allowed:
                return
            cls._mark_incident_manual_required(incident=incident, now=now)
            return

        if stage == ScraperIncident.ContingencyStage.FALLBACK_ACTIVE:
            cls._run_fallback_attempt(incident=incident, execution=execution, now=now)

    @classmethod
    def _mark_incident_manual_required(cls, *, incident: ScraperIncident, now) -> None:
        incident.contingency_stage = ScraperIncident.ContingencyStage.MANUAL_REQUIRED
        incident.manual_enabled_at = incident.manual_enabled_at or now
        cls._reset_alert_state(incident)
        incident.save(
            update_fields=[
                "contingency_stage",
                "manual_enabled_at",
                "alert_sent",
                "alert_sent_at",
                "updated_at",
            ]
        )

    @classmethod
    def _run_fallback_attempt(
        cls,
        *,
        incident: ScraperIncident,
        execution: ScraperExecution,
        now,
    ) -> None:
        result = cls._execute_fallback(incident=incident, target_date=execution.draw_date)
        incident.last_execution = execution

        if result.success:
            incident.evidence_summary = (
                f"{incident.evidence_summary} | fallback_active={result.scraper_key} persisted={result.rows_persisted}"
            ).strip()
            incident.save(
                update_fields=[
                    "evidence_summary",
                    "last_execution",
                    "updated_at",
                ]
            )
            return

        incident.fallback_attempt_count += 1
        incident.evidence_summary = (
            f"{incident.evidence_summary} | fallback_fail_{incident.fallback_attempt_count}={result.detail or result.scraper_key}"
        ).strip()
        if incident.fallback_attempt_count >= FALLBACK_ATTEMPT_THRESHOLD:
            incident.save(
                update_fields=[
                    "fallback_attempt_count",
                    "evidence_summary",
                    "last_execution",
                    "updated_at",
                ]
            )
            if not cls._can_auto_trigger_manual(incident):
                return
            cls._mark_incident_manual_required(incident=incident, now=now)
            return

        incident.save(
            update_fields=[
                "fallback_attempt_count",
                "evidence_summary",
                "last_execution",
                "updated_at",
            ]
        )

    @classmethod
    def _execute_fallback(cls, *, incident: ScraperIncident, target_date):
        if incident.fallback_scraper_key == TuAzarAnimalitoFallbackService.SCRAPER_KEY:
            return TuAzarAnimalitoFallbackService.run_lottorey(
                target_date=target_date,
                incident=incident,
            )
        return FallbackAttemptResult(
            scraper_key=incident.fallback_scraper_key or "",
            provider_name=incident.provider_name or "",
            rows_persisted=0,
            success=False,
            detail="No fallback scraper configured.",
        )

    @classmethod
    def _get_fallback_scraper_key(cls, incident: ScraperIncident) -> str:
        if incident.scraper_key != "lotoven_animalitos":
            return ""
        if incident.detection_scope != "provider":
            return ""
        if incident.provider_name != "Lotto Rey":
            return ""
        return TuAzarAnimalitoFallbackService.SCRAPER_KEY

    @staticmethod
    def _reset_alert_state(incident: ScraperIncident) -> None:
        incident.alert_sent = False
        incident.alert_sent_at = None

    @classmethod
    def _reset_incident_to_observing(cls, *, incident: ScraperIncident) -> None:
        incident.contingency_stage = ScraperIncident.ContingencyStage.OBSERVING
        incident.manual_enabled_at = None
        cls._reset_alert_state(incident)
        incident.save(
            update_fields=[
                "contingency_stage",
                "manual_enabled_at",
                "alert_sent",
                "alert_sent_at",
                "updated_at",
            ]
        )

    @staticmethod
    def _can_auto_trigger_manual(incident: ScraperIncident) -> bool:
        return incident.detection_scope == "scraper"

    @classmethod
    def _retire_obsolete_open_incidents(
        cls,
        *,
        execution: ScraperExecution,
        now,
    ) -> None:
        open_incidents = ScraperIncident.objects.filter(
            scraper_key=execution.scraper_key,
            status=ScraperIncident.Status.OPEN,
        )
        if not open_incidents.exists():
            return

        active_schedule = cls._get_strict_schedule(execution.scraper_key)
        active_baseline = set(cls._get_baseline_providers(execution.scraper_key))
        scraper_scope_enabled = cls._supports_scraper_scope(execution.scraper_key)

        for incident in open_incidents:
            if not cls._incident_contract_is_obsolete(
                incident,
                active_schedule=active_schedule,
                active_baseline=active_baseline,
                scraper_scope_enabled=scraper_scope_enabled,
            ):
                continue
            incident.status = ScraperIncident.Status.RESOLVED
            incident.resolved_at = now
            incident.resolution_note = (
                "Cerrado automaticamente porque el target ya no forma parte del contrato operativo."
            )
            incident.last_execution = execution
            incident.save(
                update_fields=[
                    "status",
                    "resolved_at",
                    "resolution_note",
                    "last_execution",
                    "updated_at",
                ]
            )

    @classmethod
    def _incident_contract_is_obsolete(
        cls,
        incident: ScraperIncident,
        *,
        active_schedule: dict[str, tuple[str, ...]],
        active_baseline: set[str],
        scraper_scope_enabled: bool,
    ) -> bool:
        scope = incident.detection_scope or ""
        if scope == "group":
            if incident.provider_name not in active_schedule:
                return True
            if not incident.draw_time:
                return True
            return incident.draw_time.strftime("%H:%M") not in active_schedule[incident.provider_name]
        if scope == "provider":
            return incident.provider_name not in active_baseline
        if scope == "scraper":
            return not scraper_scope_enabled
        return False

    @classmethod
    def _auto_resolve_recovered_incidents(
        cls,
        *,
        execution: ScraperExecution,
        expected_groups: list[dict],
        persisted_groups: list[dict],
        now,
    ) -> None:
        open_incidents = ScraperIncident.objects.filter(
            scraper_key=execution.scraper_key,
            draw_date=execution.draw_date,
            status=ScraperIncident.Status.OPEN,
        )
        if not open_incidents.exists():
            return

        active_fingerprints = {
            cls._build_fingerprint(
                execution.scraper_key,
                execution.draw_date,
                group["scope"],
                provider_name=group["provider_name"],
                draw_time_str=group["draw_time"],
                failure_reason_code=cls._scope_reason_code(group["scope"]),
            )
            for group in cls._get_missing_groups(expected_groups, persisted_groups)
        }

        for incident in open_incidents:
            if incident.fingerprint in active_fingerprints:
                continue
            incident.status = ScraperIncident.Status.RESOLVED
            incident.resolved_at = now
            incident.resolution_note = "Recuperado automaticamente por una corrida posterior."
            incident.last_execution = execution
            incident.save(
                update_fields=[
                    "status",
                    "resolved_at",
                    "resolution_note",
                    "last_execution",
                    "updated_at",
                ]
            )

    @classmethod
    def _get_missing_groups(cls, expected_groups: list[dict], persisted_groups: list[dict]) -> list[dict]:
        persisted_group_keys = {
            (group["scope"], group["provider_name"], group["draw_time"])
            for group in persisted_groups
        }
        matched_group_keys: set[tuple[str, str, str]] = set()
        missing = []
        for group in expected_groups:
            key = (group["scope"], group["provider_name"], group["draw_time"])
            if key not in persisted_group_keys:
                if cls._matches_nearby_group_time(group, persisted_groups, matched_group_keys):
                    continue
                missing.append(group)
            else:
                matched_group_keys.add(key)
        return missing

    @classmethod
    def _get_persisted_groups(cls, scraper_key: str, draw_date) -> list[dict]:
        queryset = cls._get_result_queryset(scraper_key, draw_date)
        groups = []
        for row in queryset:
            if not cls._is_usable_result_origin(row["result_origin"]):
                continue
            draw_time_str = row["draw_time"].strftime("%H:%M") if row["draw_time"] else ""
            groups.append(
                {
                    "provider_name": row["provider__name"],
                    "draw_time": draw_time_str,
                    "scope": "group",
                }
            )

        provider_scope = cls._get_baseline_providers(scraper_key)
        if provider_scope:
            provider_presence = {group["provider_name"] for group in groups}
            for provider_name in provider_scope:
                if provider_name in provider_presence:
                    groups.append(
                        {
                            "provider_name": provider_name,
                            "draw_time": "",
                            "scope": "provider",
                        }
                    )

        if groups:
            groups.append(
                {
                    "provider_name": "",
                    "draw_time": "",
                    "scope": "scraper",
                }
            )
        return groups

    @classmethod
    def _get_result_queryset(cls, scraper_key: str, draw_date) -> QuerySet:
        if cls._get_result_model_name(scraper_key) == "CurrentResult":
            queryset = CurrentResult.objects.select_related("provider").filter(draw_date=draw_date)
        else:
            queryset = AnimalitoResult.objects.select_related("provider").filter(draw_date=draw_date)

        provider_scope = cls._get_provider_scope(scraper_key)
        if provider_scope:
            return queryset.filter(provider__name__in=provider_scope).values(
                "provider__name",
                "draw_time",
                "result_origin",
            )

        provider_source_filters = cls._get_provider_source_contains(scraper_key)
        for source_fragment in provider_source_filters:
            queryset = queryset.filter(provider__source_url__icontains=source_fragment)
        return queryset.values("provider__name", "draw_time", "result_origin")

    @classmethod
    def _build_evidence_summary(
        cls,
        *,
        scraper_key: str,
        expected_groups: list[dict],
        persisted_groups: list[dict],
        missing_groups: list[dict],
    ) -> str:
        contract = ScraperOpsContractService.get_contract(scraper_key)
        expected_count = len(expected_groups)
        persisted_count = len(persisted_groups)
        missing_count = len(missing_groups)
        expected_preview = ",".join(
            cls._group_label(item) for item in expected_groups[:6]
        ) or "-"
        missing_preview = ",".join(
            cls._group_label(item) for item in missing_groups[:6]
        ) or "-"
        return (
            f"validation_profile={contract.validation_profile} "
            f"expected={expected_count} persisted={persisted_count} missing={missing_count} "
            f"expected_preview={expected_preview} missing_preview={missing_preview}"
        )

    @staticmethod
    def _group_label(group: dict) -> str:
        provider_name = group.get("provider_name") or "scraper"
        draw_time = group.get("draw_time") or "-"
        scope = group.get("scope") or "group"
        return f"{scope}:{provider_name}@{draw_time}"

    @classmethod
    def _get_result_model_name(cls, scraper_key: str) -> str:
        contract = ScraperOpsContractService.get_contract(scraper_key)
        return contract.result_model

    @classmethod
    def _get_provider_scope(cls, scraper_key: str) -> list[str]:
        if scraper_key == "lotoven_triples":
            return list(LOTOVEN_TABLE_SIMPLE_PROVIDERS) + list(LOTOVEN_STRICT_SCHEDULE.keys())
        if scraper_key == "tuazar_triples":
            return list(TUAZAR_BASELINE_PROVIDERS)
        if scraper_key == "condor_animalitos":
            return list(CONDOR_PROVIDER)
        return []

    @classmethod
    def _get_baseline_providers(cls, scraper_key: str) -> tuple[str, ...]:
        if scraper_key == "lotoven_triples":
            return LOTOVEN_TABLE_SIMPLE_PROVIDERS
        if scraper_key == "tuazar_triples":
            return TUAZAR_BASELINE_PROVIDERS
        if scraper_key == "lotoven_animalitos":
            return LOTOVEN_ANIMALITO_BASELINE_PROVIDERS
        if scraper_key == "condor_animalitos":
            return CONDOR_PROVIDER
        return ()

    @classmethod
    def _get_strict_schedule(cls, scraper_key: str) -> dict[str, tuple[str, ...]]:
        if scraper_key == "lotoven_triples":
            return LOTOVEN_STRICT_SCHEDULE
        return {}

    @classmethod
    def _get_provider_source_contains(cls, scraper_key: str) -> tuple[str, ...]:
        if scraper_key == "lotoven_animalitos":
            return ("lotoven.com",)
        return ()

    @classmethod
    def _supports_scraper_scope(cls, scraper_key: str) -> bool:
        return scraper_key == "lotoven_animalitos"

    @staticmethod
    def _parse_time(value: str):
        return datetime.strptime(value, "%H:%M").time()

    @staticmethod
    def _time_to_minutes(value) -> int:
        return (value.hour * 60) + value.minute

    @classmethod
    def _add_minutes_to_time(cls, value, minutes: int):
        total_minutes = cls._time_to_minutes(value) + max(0, int(minutes))
        total_minutes = min(total_minutes, (23 * 60) + 59)
        hour = total_minutes // 60
        minute = total_minutes % 60
        return datetime.strptime(f"{hour:02d}:{minute:02d}", "%H:%M").time()

    @classmethod
    def _get_strict_group_grace_minutes(cls, scraper_key: str) -> int:
        if scraper_key == "lotoven_triples":
            return STRICT_EXPECTED_GROUP_GRACE_MINUTES
        return 0

    @classmethod
    def _get_strict_group_time_tolerance_minutes(cls, scraper_key: str) -> int:
        if scraper_key == "lotoven_triples":
            return STRICT_GROUP_TIME_TOLERANCE_MINUTES
        return 0

    @classmethod
    def _is_baseline_provider_due(cls, scraper_key: str, provider_name: str, *, current_time) -> bool:
        del provider_name
        start_time_str = BASELINE_PROVIDER_START_TIMES.get(scraper_key)
        if not start_time_str:
            return True
        return current_time >= cls._parse_time(start_time_str)

    @classmethod
    def _is_scraper_scope_due(cls, scraper_key: str, *, current_time) -> bool:
        start_time_str = SCRAPER_SCOPE_START_TIMES.get(scraper_key)
        if not start_time_str:
            return True
        return current_time >= cls._parse_time(start_time_str)

    @classmethod
    def _matches_nearby_group_time(
        cls,
        expected_group: dict,
        persisted_groups: list[dict],
        matched_group_keys: set[tuple[str, str, str]],
    ) -> bool:
        if expected_group.get("scope") != "group":
            return False

        provider_name = expected_group.get("provider_name") or ""
        draw_time_str = expected_group.get("draw_time") or ""
        if not provider_name or not draw_time_str:
            return False

        tolerance = cls._get_strict_group_time_tolerance_minutes(
            cls._guess_scraper_key_from_provider(provider_name)
        )
        if tolerance <= 0:
            return False

        expected_minutes = cls._time_to_minutes(cls._parse_time(draw_time_str))
        nearest_key = None
        nearest_delta = None

        for group in persisted_groups:
            if group.get("scope") != "group":
                continue
            if group.get("provider_name") != provider_name:
                continue
            candidate_time_str = group.get("draw_time") or ""
            if not candidate_time_str:
                continue
            candidate_key = ("group", provider_name, candidate_time_str)
            if candidate_key in matched_group_keys:
                continue

            candidate_minutes = cls._time_to_minutes(cls._parse_time(candidate_time_str))
            delta = abs(candidate_minutes - expected_minutes)
            if delta > tolerance:
                continue
            if nearest_delta is None or delta < nearest_delta:
                nearest_delta = delta
                nearest_key = candidate_key

        if nearest_key is None:
            return False

        matched_group_keys.add(nearest_key)
        return True

    @staticmethod
    def _guess_scraper_key_from_provider(provider_name: str) -> str:
        return "lotoven_triples" if provider_name.startswith("Triple ") else ""

    @staticmethod
    def _scope_reason_code(scope: str) -> str:
        if scope == "group":
            return "missing_expected_group"
        if scope == "provider":
            return "missing_provider_rows"
        return "missing_scraper_rows"

    @staticmethod
    def _incident_impacts_frontend(incident: ScraperIncident) -> bool:
        return (
            incident.contingency_stage == ScraperIncident.ContingencyStage.MANUAL_REQUIRED
            and incident.detection_scope == "scraper"
        )

    @staticmethod
    def _is_usable_result_origin(result_origin: str) -> bool:
        return result_origin in {
            CurrentResult.ResultOrigin.AUTOMATIC_VALID,
            CurrentResult.ResultOrigin.MANUAL_CONTINGENCY,
            AnimalitoResult.ResultOrigin.AUTOMATIC_VALID,
            AnimalitoResult.ResultOrigin.MANUAL_CONTINGENCY,
        }

    @classmethod
    def _build_fingerprint(
        cls,
        scraper_key: str,
        draw_date,
        scope: str,
        *,
        provider_name: str,
        draw_time_str: str,
        failure_reason_code: str,
    ) -> str:
        return "|".join(
            [
                scraper_key,
                str(draw_date),
                scope,
                provider_name or "-",
                draw_time_str or "-",
                failure_reason_code,
            ]
        )
