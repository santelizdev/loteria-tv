# =========================
# FILE: core/api/views.py
# =========================
from __future__ import annotations

import json
import random
import string
from datetime import date, datetime
from typing import Any, Dict, Optional, Union

from django.conf import settings
from django.db.models import Max
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import (
    AnimalitoArchive,
    AnimalitoResult,
    CurrentResult,
    Device,
    DeviceTelemetryEvent,
    ResultArchive,
)
from core.services.device_redis_service import DeviceRedisService
from core.services.device_service import DeviceService
from core.services.device_telemetry_service import DeviceTelemetryService


# -----------------------------------------------------------------------------
# Helpers cache-control (CRÍTICO para que NO se quede pegado a respuestas viejas)
# -----------------------------------------------------------------------------
def _apply_no_cache_headers(resp: Response) -> Response:
    """
    Fuerza a que Nginx/CDN/Browser NO cacheen el response.
    Aun cuando Redis esté habilitado, esto evita caches externos agresivos.
    """
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


def _should_bypass_cache(request) -> bool:
    """
    - Si viene ?nocache=1 => bypass inmediato
    - Si settings.RESULTS_CACHE_TTL_SECONDS == 0 => cache desactivado global
    """
    if request.query_params.get("nocache") in ("1", "true", "yes"):
        return True
    ttl = getattr(settings, "RESULTS_CACHE_TTL_SECONDS", 0)
    return int(ttl) <= 0


def _format_time_12h(value) -> str:
    return value.strftime("%I:%M %p")


def _parse_date(value: Optional[str]) -> Union[date, None, str]:
    """
    Retorna:
    - date si parsea
    - None si no viene value
    - "INVALID" si viene value pero no cumple formato
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return "INVALID"


def _resolve_target_date_for_triples() -> Optional[date]:
    """
    Preferencia:
    1) Hoy si existe en CurrentResult
    2) Última fecha en CurrentResult
    3) Última fecha en ResultArchive
    """
    today = timezone.localdate()

    if CurrentResult.objects.filter(draw_date=today).exists():
        return today

    last_current = CurrentResult.objects.aggregate(last=Max("draw_date"))["last"]
    if last_current:
        return last_current

    last_archive = ResultArchive.objects.aggregate(last=Max("draw_date"))["last"]
    return last_archive


def _resolve_target_date_for_animalitos() -> Optional[date]:
    """
    Preferencia:
    1) Hoy si existe en AnimalitoResult
    2) Última fecha en AnimalitoResult
    3) Última fecha en AnimalitoArchive
    """
    today = timezone.localdate()

    if AnimalitoResult.objects.filter(draw_date=today).exists():
        return today

    last_current = AnimalitoResult.objects.aggregate(last=Max("draw_date"))["last"]
    if last_current:
        return last_current

    last_archive = AnimalitoArchive.objects.aggregate(last=Max("draw_date"))["last"]
    return last_archive


def get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip()

# -----------------------------------------------------------------------------
# Serializers (prolijidad + estabilidad de contrato)
# -----------------------------------------------------------------------------
def _extract_signo(extra: Any) -> str:
    """
    Extrae extra['signo'] si existe y es dict.
    Devuelve "" si no aplica. Nunca levanta excepción.
    """
    if not extra or not isinstance(extra, dict):
        return ""
    return (extra.get("signo") or "").strip()


def _serialize_triple_result(r) -> Dict[str, str]:
    """
    Contrato legacy para TVs:
      { "provider": str, "time": "HH:MM AM/PM", "number": str, "image": "" }

    Importante:
    - Si r.extra.signo existe => number = "<winning_number> <signo>"
    - NO se agregan campos nuevos.
    """
    winning = (r.winning_number or "").strip()
    signo = _extract_signo(getattr(r, "extra", None))

    number = f"{winning} {signo}".strip() if signo else winning

    return {
        "provider": r.provider.name,
        "time": _format_time_12h(r.draw_time),
        "number": number,
        "image": r.image_url or "",
    }


def _serialize_animalito_result(r) -> Dict[str, str]:
    """
    Contrato legacy animalitos:
      { "provider": str, "time": "HH:MM AM/PM", "number": str, "animal": str, "image": str }
    """
    return {
        "provider": r.provider.name,
        "time": _format_time_12h(r.draw_time),
        "number": str(r.animal_number),
        "animal": r.animal_name or "",
        "image": r.animal_image_url or "",
    }


# -----------------------------------------------------------------------------
# API Views
# -----------------------------------------------------------------------------
def _normalize_telemetry_message(value: Any) -> str:
    return str(value or "").strip()


def _normalize_telemetry_metadata(value: Any) -> Dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("metadata must be a valid JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    return value
class CurrentResultsAPIView(APIView):
    """
    /api/results/
    Retorna triples. Para providers con signo zodiacal, el signo se embebe en number.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        activation_code = request.query_params.get("code")
        ip_address = get_client_ip(request)

        if not activation_code:
            return _apply_no_cache_headers(
                Response({"detail": "Missing activation code"}, status=status.HTTP_400_BAD_REQUEST)
            )

        try:
            DeviceService.validate_device(activation_code=activation_code, ip_address=ip_address)
        except PermissionError as e:
            return _apply_no_cache_headers(Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN))

        raw_date = request.query_params.get("date")
        parsed = _parse_date(raw_date)
        if parsed == "INVALID":
            return _apply_no_cache_headers(
                Response({"detail": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)
            )

        target_date = parsed or _resolve_target_date_for_triples()
        if not target_date:
            return _apply_no_cache_headers(Response([], status=status.HTTP_200_OK))

        today = timezone.localdate()
        use_archive = target_date < today and ResultArchive.objects.filter(draw_date=target_date).exists()

        # -------------------------
        # CACHE (opcional)
        # -------------------------
        bypass_cache = _should_bypass_cache(request)
        ttl = int(getattr(settings, "RESULTS_CACHE_TTL_SECONDS", 0))
        cache_version = "v4"
        origin = "archive" if use_archive else "current"
        cache_key = f"results:triples:{cache_version}:{origin}:{target_date.isoformat()}"

        if not bypass_cache and ttl > 0:
            cached = DeviceRedisService.get_cache(cache_key)
            if cached is not None:
                return _apply_no_cache_headers(Response(cached, status=status.HTTP_200_OK))

        # -------------------------
        # Query DB
        # -------------------------
        if use_archive:
            qs = (
                ResultArchive.objects.select_related("provider")
                .filter(draw_date=target_date, provider__is_active=True)
                .order_by("provider__name", "draw_time")
            )
        else:
            qs = (
                CurrentResult.objects.select_related("provider")
                .filter(draw_date=target_date, provider__is_active=True)
                .order_by("provider__name", "draw_time")
            )

        data = [_serialize_triple_result(r) for r in qs]

        if not bypass_cache and ttl > 0:
            DeviceRedisService.set_cache(cache_key, data, ttl_seconds=ttl)

        return _apply_no_cache_headers(Response(data, status=status.HTTP_200_OK))


class AnimalitosResultsAPIView(APIView):
    """
    /api/animalitos/
    Retorna animalitos. No hay signo aquí (eso es de triples).
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        activation_code = request.query_params.get("code")
        ip_address = get_client_ip(request)

        if not activation_code:
            return _apply_no_cache_headers(
                Response({"detail": "Missing activation code"}, status=status.HTTP_400_BAD_REQUEST)
            )

        try:
            DeviceService.validate_device(activation_code=activation_code, ip_address=ip_address)
        except PermissionError as e:
            return _apply_no_cache_headers(Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN))

        raw_date = request.query_params.get("date")
        parsed = _parse_date(raw_date)
        if parsed == "INVALID":
            return _apply_no_cache_headers(
                Response({"detail": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)
            )

        target_date = parsed or _resolve_target_date_for_animalitos()
        if not target_date:
            return _apply_no_cache_headers(Response([], status=status.HTTP_200_OK))

        today = timezone.localdate()
        use_archive = target_date < today and AnimalitoArchive.objects.filter(draw_date=target_date).exists()

        # -------------------------
        # CACHE (opcional)
        # -------------------------
        bypass_cache = _should_bypass_cache(request)
        ttl = int(getattr(settings, "RESULTS_CACHE_TTL_SECONDS", 0))
        cache_version = "v4"
        origin = "archive" if use_archive else "current"
        cache_key = f"results:animalitos:{cache_version}:{origin}:{target_date.isoformat()}"

        if not bypass_cache and ttl > 0:
            cached = DeviceRedisService.get_cache(cache_key)
            if cached is not None:
                return _apply_no_cache_headers(Response(cached, status=status.HTTP_200_OK))

        # -------------------------
        # Query DB
        # -------------------------
        if use_archive:
            qs = (
                AnimalitoArchive.objects.select_related("provider")
                .filter(draw_date=target_date)
                .order_by("provider__name", "draw_time")
            )
        else:
            qs = (
                AnimalitoResult.objects.select_related("provider")
                .filter(draw_date=target_date)
                .order_by("provider__name", "draw_time")
            )

        data = [_serialize_animalito_result(r) for r in qs]

        if not bypass_cache and ttl > 0:
            DeviceRedisService.set_cache(cache_key, data, ttl_seconds=ttl)

        return _apply_no_cache_headers(Response(data, status=status.HTTP_200_OK))


class DeviceRegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_id = request.data.get("device_id")
        if not device_id:
            return _apply_no_cache_headers(
                Response({"error": "device_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            )

        activation_code = self._generate_code()
        ip = get_client_ip(request)

        device, created = Device.objects.get_or_create(
            device_id=device_id,
            defaults={
                "activation_code": activation_code,
                "registered_ip": ip,
                "is_active": False,
            },
        )

        return _apply_no_cache_headers(
            Response(
                {
                    "device_id": device.device_id,
                    "activation_code": device.activation_code,
                    "registered": device.is_active,
                },
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )
        )

    def _generate_code(self) -> str:
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


class DeviceHeartbeatAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_id = request.data.get("device_id")
        activation_code = request.data.get("code")
        ip_address = get_client_ip(request)

        if not device_id or not activation_code:
            return _apply_no_cache_headers(
                Response({"detail": "Missing credentials"}, status=status.HTTP_400_BAD_REQUEST)
            )

        try:
            DeviceService.validate_device(activation_code=activation_code, ip_address=ip_address)
        except PermissionError as e:
            return _apply_no_cache_headers(Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN))

        return _apply_no_cache_headers(Response({"status": "ok", "online": True}, status=status.HTTP_200_OK))


class DeviceTelemetryAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_id = request.data.get("device_id")
        activation_code = request.data.get("code")
        event_type = str(request.data.get("event_type") or "").strip().upper()
        message = _normalize_telemetry_message(request.data.get("message"))
        ip_address = get_client_ip(request)

        if not device_id or not activation_code:
            return _apply_no_cache_headers(
                Response({"detail": "Missing credentials"}, status=status.HTTP_400_BAD_REQUEST)
            )

        if event_type not in DeviceTelemetryEvent.EventType.values:
            return _apply_no_cache_headers(
                Response(
                    {
                        "detail": "Invalid event_type",
                        "allowed": list(DeviceTelemetryEvent.EventType.values),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            )

        try:
            metadata = _normalize_telemetry_metadata(request.data.get("metadata"))
        except ValueError as exc:
            return _apply_no_cache_headers(
                Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            )

        try:
            device = DeviceService.validate_device(
                activation_code=activation_code,
                ip_address=ip_address,
            )
        except PermissionError as e:
            return _apply_no_cache_headers(Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN))

        if str(device.device_id) != str(device_id):
            return _apply_no_cache_headers(
                Response({"detail": "Device credentials mismatch"}, status=status.HTTP_403_FORBIDDEN)
            )

        event = DeviceTelemetryService.record_event(
            device=device,
            event_type=event_type,
            ip_address=ip_address,
            message=message,
            metadata=metadata,
        )
        snapshot = device.telemetry_snapshot

        return _apply_no_cache_headers(
            Response(
                {
                    "status": "ok",
                    "event_id": event.id,
                    "event_type": event.event_type,
                    "device": device.activation_code,
                    "last_heartbeat_at": snapshot.last_heartbeat_at.isoformat() if snapshot.last_heartbeat_at else None,
                    "last_ip_address": snapshot.last_ip_address,
                },
                status=status.HTTP_200_OK,
            )
        )


class DeviceStatusAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        activation_code = request.query_params.get("code")
        if not activation_code:
            return _apply_no_cache_headers(
                Response({"detail": "Missing activation code"}, status=status.HTTP_400_BAD_REQUEST)
            )

        try:
            device = Device.objects.select_related("branch__client").get(activation_code=activation_code)
        except Device.DoesNotExist:
            return _apply_no_cache_headers(
                Response({"detail": "Invalid activation code"}, status=status.HTTP_404_NOT_FOUND)
            )

        client_logo_url = ""
        if device.branch and device.branch.client and device.branch.client.logo:
            try:
                client_logo_url = request.build_absolute_uri(device.branch.client.logo.url)
            except Exception:
                client_logo_url = ""

        return _apply_no_cache_headers(
            Response(
                {
                    "is_active": bool(device.is_active and device.branch_id),
                    "branch_id": device.branch_id,
                    "client_logo_url": client_logo_url,
                },
                status=status.HTTP_200_OK,
            )
        )
