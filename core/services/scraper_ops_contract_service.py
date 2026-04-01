from __future__ import annotations

from dataclasses import asdict, dataclass

from django.conf import settings


@dataclass(frozen=True)
class ScraperPhaseZeroContract:
    result_model: str
    group_key: tuple[str, ...]
    validation_profile: str
    expected_group_scope: tuple[str, ...]
    real_failure_definition: str
    alert_trigger_definition: str
    enforcement_status: str
    manual_resolution_scope: str


class ScraperOpsContractService:
    CONTRACTS = {
        "lotoven_triples": ScraperPhaseZeroContract(
            result_model="CurrentResult",
            group_key=("provider", "draw_date", "draw_time"),
            validation_profile="mixed",
            expected_group_scope=(
                "Table simple baseline: Trio Activo, La Ricachona, Triple Centena, Triple Dorado, Triple Facil, Terminal Trio, Terminal La Granjita, La Ruca.",
                "Triple Chance estricto por grupo A/B/C en 13:00, 16:00 y 19:00.",
                "Triple Caracas A/B/C en 13:00 y 16:30.",
                "Triple Caliente A/B/C en 13:00, 16:30 y 19:10.",
                "Triple Tachira A/B/C en 13:15 y 16:45.",
                "Triple Zamorano A/C en 10:00, 12:00 y 14:00.",
            ),
            real_failure_definition=(
                "Fallo real cuando la corrida revienta, no deja OK del dia o no persiste grupos "
                "usables en los horarios estrictos ya codificados. Providers table_simple quedan "
                "en baseline hasta tener instrumentacion por ejecucion."
            ),
            alert_trigger_definition=(
                "Crear alerta operativa cuando el monitor detecta failed_today, missing_today o stale "
                "durante la ventana operativa."
            ),
            enforcement_status=(
                "Mixto: el scraper ya filtra horarios estrictos para Triple Chance/ABC, "
                "pero el monitor actual sigue agregado por scraper y no por incidente."
            ),
            manual_resolution_scope=(
                "Futuro incidente debe resolver solo provider + draw_date + draw_time afectados."
            ),
        ),
        "tuazar_triples": ScraperPhaseZeroContract(
            result_model="CurrentResult",
            group_key=("provider", "draw_date", "draw_time"),
            validation_profile="baseline",
            expected_group_scope=(
                "Chance Astral por provider + fecha + horario.",
                "Triple Gana por provider + fecha + horario.",
                "Super Gana por provider + fecha + horario.",
                "Solo se consideran filas vencidas hasta cutoff; no hay matriz horaria estricta cerrada todavia.",
            ),
            real_failure_definition=(
                "Fallo real cuando la corrida revienta, faltan bloques principales o no queda ningun "
                "OK del dia. La completitud por horario puntual sigue pendiente. Tras 3 intentos "
                "sin resultado util, la contingencia escala directo a carga manual."
            ),
            alert_trigger_definition=(
                "Telegram solo cuando la contingencia escala a carga manual o el comando falla de forma tecnica."
            ),
            enforcement_status=(
                "Baseline: cobertura minima por providers y cutoff; falta validacion funcional por horario esperado."
            ),
            manual_resolution_scope=(
                "Futuro incidente debe restringir la correccion al provider y horario faltante."
            ),
        ),
        "lotoven_animalitos": ScraperPhaseZeroContract(
            result_model="AnimalitoResult",
            group_key=("provider", "draw_date", "draw_time"),
            validation_profile="baseline",
            expected_group_scope=(
                "Providers baseline monitoreados del origen Lotoven: Cazaloton, La Granjita, Loto Chaima, Lotto Rey y Mega Animal 40.",
                "Grupo de resultado: provider + fecha + horario cuando el scraper trae filas parciales.",
                "Si el scraper viene totalmente vacio, se mantiene incidente unico a nivel scraper en vez de un incidente por provider."
            ),
            real_failure_definition=(
                "Fallo real cuando la corrida revienta, parsea 0 en contexto operativo, no registra "
                "OK del dia o deja providers baseline monitoreados sin filas utilizables mientras otros providers del mismo origen si llegaron. "
                "Lotto Rey permite fallback temporal via TuAzar antes de habilitar carga manual."
            ),
            alert_trigger_definition=(
                "Telegram solo cuando se activa el scraper de emergencia o cuando ya toca carga manual."
            ),
            enforcement_status=(
                "Baseline: se persiste por provider/horario, pero la validacion funcional exacta sigue abierta."
            ),
            manual_resolution_scope=(
                "Futuro incidente debe permitir cargar solo el animalito del provider y horario afectados."
            ),
        ),
        "condor_animalitos": ScraperPhaseZeroContract(
            result_model="AnimalitoResult",
            group_key=("provider", "draw_date", "draw_time"),
            validation_profile="baseline",
            expected_group_scope=(
                "Condor Gana por provider + fecha + horario.",
                "Hoy soporta filas vencidas hasta cutoff para HOY y lectura puntual de AYER.",
                "No existe aun una matriz horaria formal cerrada dentro del monitor."
            ),
            real_failure_definition=(
                "Fallo real cuando la corrida revienta, parsea 0 en horario operativo o no registra "
                "OK del dia. Tras 3 intentos sin datos utiles, la contingencia escala a carga manual."
            ),
            alert_trigger_definition=(
                "Telegram solo cuando la contingencia escala a carga manual o el comando falla de forma tecnica."
            ),
            enforcement_status=(
                "Baseline: proveedor y persistencia estan acotados, pero falta incidente funcional por horario."
            ),
            manual_resolution_scope=(
                "Futuro incidente debe acotar la intervencion al horario exacto de Condor Gana."
            ),
        ),
    }

    @classmethod
    def get_contract(cls, scraper_key: str) -> ScraperPhaseZeroContract:
        try:
            return cls.CONTRACTS[scraper_key]
        except KeyError as exc:
            raise KeyError(f"Missing phase-0 contract for scraper_key: {scraper_key}") from exc

    @classmethod
    def build_global_contract(cls) -> dict:
        return {
            "primary_alert_channel": getattr(settings, "SCRAPER_ALERT_PRIMARY_CHANNEL", "email"),
            "alert_recipient_sources": (
                "SCRAPER_ALERT_EMAILS",
                "SCRAPER_ALERT_USERNAMES",
                "SCRAPER_ALERT_GROUPS",
            ),
            "viewer_groups": tuple(getattr(settings, "SCRAPER_INCIDENT_VIEWER_GROUPS", ("Administradores",))),
            "resolver_groups": tuple(getattr(settings, "SCRAPER_INCIDENT_RESOLVER_GROUPS", ("Administradores",))),
            "automatic_origin_label": getattr(
                settings,
                "SCRAPER_RESULT_AUTOMATIC_ORIGIN_LABEL",
                "automatic_valid",
            ),
            "manual_origin_label": getattr(
                settings,
                "SCRAPER_RESULT_MANUAL_ORIGIN_LABEL",
                "manual_contingency",
            ),
            "fallback_origin_label": getattr(
                settings,
                "SCRAPER_RESULT_FALLBACK_ORIGIN_LABEL",
                "automatic_fallback",
            ),
        }

    @classmethod
    def build_operational_matrix(cls) -> list[dict]:
        from core.services.scraper_health_service import ScraperHealthService

        cls.validate_registry_alignment()
        matrix = []
        for scraper_key, definition in ScraperHealthService.iter_active_definitions():
            contract = cls.get_contract(scraper_key)
            matrix.append(
                {
                    "scraper_key": scraper_key,
                    "label": definition.label,
                    "command_name": definition.command_name,
                    "starts_hour": definition.starts_hour,
                    "ends_hour": definition.ends_hour,
                    **asdict(contract),
                }
            )
        return matrix

    @classmethod
    def build_contract_snapshot(cls) -> dict:
        return {
            "global_contract": cls.build_global_contract(),
            "scrapers": cls.build_operational_matrix(),
        }

    @classmethod
    def build_admin_summary(cls, scraper_key: str) -> str:
        contract = cls.get_contract(scraper_key)
        global_contract = cls.build_global_contract()
        scope = " | ".join(contract.expected_group_scope)
        group_key = " + ".join(contract.group_key)
        resolver_groups = ", ".join(global_contract["resolver_groups"]) or "-"
        viewer_groups = ", ".join(global_contract["viewer_groups"]) or "-"
        return (
            f"Modelo={contract.result_model}\n"
            f"Clave de grupo={group_key}\n"
            f"Perfil validacion={contract.validation_profile}\n"
            f"Canal alerta={global_contract['primary_alert_channel']}\n"
            f"Grupos viewer={viewer_groups}\n"
            f"Grupos resolver={resolver_groups}\n"
            f"Origen auto={global_contract['automatic_origin_label']}\n"
            f"Origen fallback={global_contract['fallback_origin_label']}\n"
            f"Origen manual={global_contract['manual_origin_label']}\n"
            f"Scope esperado={scope}\n"
            f"Fallo real={contract.real_failure_definition}\n"
            f"Trigger alerta={contract.alert_trigger_definition}\n"
            f"Estado de enforcement={contract.enforcement_status}\n"
            f"Resolucion manual={contract.manual_resolution_scope}"
        )

    @classmethod
    def validate_registry_alignment(cls) -> None:
        from core.services.scraper_health_service import ScraperHealthService

        registry_keys = set(ScraperHealthService.REGISTRY.keys())
        contract_keys = set(cls.CONTRACTS.keys())
        missing_contracts = sorted(registry_keys - contract_keys)
        extra_contracts = sorted(contract_keys - registry_keys)
        if missing_contracts or extra_contracts:
            problems = []
            if missing_contracts:
                problems.append(f"missing_contracts={missing_contracts}")
            if extra_contracts:
                problems.append(f"extra_contracts={extra_contracts}")
            raise RuntimeError("Phase-0 scraper contract registry mismatch: " + " ".join(problems))
