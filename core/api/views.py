# =========================
# FILE: core/api/views.py
# =========================
from __future__ import annotations

import random
import string
from datetime import datetime
from typing import Optional

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
    ResultArchive,
)
from core.services.device_redis_service import DeviceRedisService
from core.services.device_service import DeviceService


# -----------------------------------------------------------------------------
# Helpers cache-control (CRÍTICO para que NO se quede pegado a las 12pm)
# -----------------------------------------------------------------------------
def _apply_no_cache_headers(resp: Response) -> Response:
    """
    Fuerza a que Nginx/CDN/Browser NO cacheen el response.
    Esto ataca el síntoma principal: respuesta vieja sirviéndose por horas.
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


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return "INVALID"


def _resolve_target_date_for_triples():
    today = timezone.localdate()

    if CurrentResult.objects.filter(draw_date=today).exists():
        return today

    last_current = CurrentResult.objects.aggregate(last=Max("draw_date"))["last"]
    if last_current:
        return last_current

    last_archive = ResultArchive.objects.aggregate(last=Max("draw_date"))["last"]
    return last_archive


def _resolve_target_date_for_animalitos():
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


class CurrentResultsAPIView(APIView):
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

        data = [
            {
                "provider": r.provider.name,
                "time": _format_time_12h(r.draw_time),
                "number": r.winning_number,
                "image": r.image_url or "",
            }
            for r in qs
        ]

        if not bypass_cache and ttl > 0:
            DeviceRedisService.set_cache(cache_key, data, ttl_seconds=ttl)

        return _apply_no_cache_headers(Response(data, status=status.HTTP_200_OK))


class AnimalitosResultsAPIView(APIView):
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

        data = [
            {
                "provider": r.provider.name,
                "time": _format_time_12h(r.draw_time),
                "number": str(r.animal_number),
                "animal": r.animal_name,
                "image": r.animal_image_url,
            }
            for r in qs
        ]

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

    def _generate_code(self):
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
            return _apply_no_cache_headers(Response({"detail": "Invalid activation code"}, status=status.HTTP_404_NOT_FOUND))

        branch = device.branch
        client = branch.client if branch and getattr(branch, "client_id", None) else None

        client_logo_url = ""
        if client and getattr(client, "logo_url", None):
            client_logo_url = client.logo_url or ""

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