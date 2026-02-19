# =========================
# FILE: core/api/views.py
# =========================
from __future__ import annotations

import random
import string
from datetime import datetime
from typing import Optional

from django.conf import settings   
from django.db.models import Count, Max
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

RESULTS_CACHE_TTL_SECONDS = 3   # o 0 si quieres sin cache
DEVICE_HEARTBEAT_TTL_SECONDS = 90

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
    """
    Decide qué fecha devolver si NO mandan ?date=
    Prioridad:
      1) hoy si hay CurrentResult hoy
      2) último draw_date en CurrentResult
      3) último draw_date en ResultArchive
      4) None
    """
    today = timezone.localdate()

    if CurrentResult.objects.filter(draw_date=today).exists():
        return today

    last_current = CurrentResult.objects.aggregate(last=Max("draw_date"))["last"]
    if last_current:
        return last_current

    last_archive = ResultArchive.objects.aggregate(last=Max("draw_date"))["last"]
    return last_archive


def _resolve_target_date_for_animalitos():
    """
    Decide qué fecha devolver si NO mandan ?date=
    Prioridad:
      1) hoy si hay AnimalitoResult hoy
      2) último draw_date en AnimalitoResult
      3) último draw_date en AnimalitoArchive
      4) None
    """
    today = timezone.localdate()

    if AnimalitoResult.objects.filter(draw_date=today).exists():
        return today

    last_current = AnimalitoResult.objects.aggregate(last=Max("draw_date"))["last"]
    if last_current:
        return last_current

    last_archive = AnimalitoArchive.objects.aggregate(last=Max("draw_date"))["last"]
    return last_archive


def _signature_for_triples(*, target_date, use_archive: bool) -> str:
    """
    Firma barata para invalidar cache cuando entran resultados nuevos.
    Evita el síntoma de "se quedó pegado a las 12pm" por caches viejos.
    """
    model = ResultArchive if use_archive else CurrentResult
    agg = model.objects.filter(draw_date=target_date).aggregate(
        n=Count("id"),
        last=Max("draw_time"),
    )
    n = agg["n"] or 0
    last = agg["last"].isoformat() if agg["last"] else "none"
    return f"{n}:{last}"


def _signature_for_animalitos(*, target_date, use_archive: bool) -> str:
    model = AnimalitoArchive if use_archive else AnimalitoResult
    agg = model.objects.filter(draw_date=target_date).aggregate(
        n=Count("id"),
        last=Max("draw_time"),
    )
    n = agg["n"] or 0
    last = agg["last"].isoformat() if agg["last"] else "none"
    return f"{n}:{last}"


class CurrentResultsAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    CACHE_TTL = getattr(settings, "RESULTS_CACHE_TTL_SECONDS", 5)

    def get(self, request):
        activation_code = request.query_params.get("code")
        ip_address = get_client_ip(request)

        if not activation_code:
            return Response(
                {"detail": "Missing activation code"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # validar device
        try:
            DeviceService.validate_device(activation_code=activation_code, ip_address=ip_address)
        except PermissionError as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        raw_date = request.query_params.get("date")
        parsed = _parse_date(raw_date)
        if parsed == "INVALID":
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_date = parsed or _resolve_target_date_for_triples()
        if not target_date:
            return Response([], status=status.HTTP_200_OK)

        today = timezone.localdate()
        use_archive = target_date < today and ResultArchive.objects.filter(draw_date=target_date).exists()

        # cache key por fecha + origen + firma (count + max draw_time)
        cache_version = "v3"
        origin = "archive" if use_archive else "current"
        sig = _signature_for_triples(target_date=target_date, use_archive=use_archive)
        cache_key = f"results:triples:{cache_version}:{origin}:{target_date.isoformat()}:{sig}"

        cached = DeviceRedisService.get_cache(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        model = ResultArchive if use_archive else CurrentResult
        qs = (
            model.objects.select_related("provider")
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

        DeviceRedisService.set_cache(cache_key, data, ttl_seconds=self.CACHE_TTL)
        return Response(data, status=status.HTTP_200_OK)


class AnimalitosResultsAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    CACHE_TTL = getattr(settings, "RESULTS_CACHE_TTL_SECONDS", 5)   
    def get(self, request):
        activation_code = request.query_params.get("code")
        ip_address = get_client_ip(request)

        if not activation_code:
            return Response(
                {"detail": "Missing activation code"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # validar device
        try:
            DeviceService.validate_device(activation_code=activation_code, ip_address=ip_address)
        except PermissionError as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        raw_date = request.query_params.get("date")
        parsed = _parse_date(raw_date)
        if parsed == "INVALID":
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_date = parsed or _resolve_target_date_for_animalitos()
        if not target_date:
            return Response([], status=status.HTTP_200_OK)

        today = timezone.localdate()
        use_archive = target_date < today and AnimalitoArchive.objects.filter(draw_date=target_date).exists()

        cache_version = "v4"
        origin = "archive" if use_archive else "current"
        sig = _signature_for_animalitos(target_date=target_date, use_archive=use_archive)
        cache_key = f"results:animalitos:{cache_version}:{origin}:{target_date.isoformat()}:{sig}"

        cached = DeviceRedisService.get_cache(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        model = AnimalitoArchive if use_archive else AnimalitoResult
        qs = (
            model.objects.select_related("provider")
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

        DeviceRedisService.set_cache(cache_key, data, ttl_seconds=self.CACHE_TTL)
        return Response(data, status=status.HTTP_200_OK)


class DeviceRegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_id = request.data.get("device_id")
        if not device_id:
            return Response({"error": "device_id is required"}, status=status.HTTP_400_BAD_REQUEST)

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

        return Response(
            {
                "device_id": device.device_id,
                "activation_code": device.activation_code,
                "registered": device.is_active,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _generate_code(self):
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def get_client_ip(request) -> str:
    # Nginx suele setear X-Real-IP; Cloudflare / proxies setean X-Forwarded-For
    x_real_ip = (request.META.get("HTTP_X_REAL_IP") or "").strip()
    if x_real_ip:
        return x_real_ip

    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()

    return (request.META.get("REMOTE_ADDR") or "").strip()


class DeviceHeartbeatAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_id = request.data.get("device_id")
        activation_code = request.data.get("code")
        ip_address = get_client_ip(request)

        if not device_id or not activation_code:
            return Response({"detail": "Missing credentials"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            DeviceService.validate_device(activation_code=activation_code, ip_address=ip_address)
        except PermissionError as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        return Response({"status": "ok", "online": True}, status=status.HTTP_200_OK)


class DeviceStatusAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        activation_code = request.query_params.get("code")
        if not activation_code:
            return Response({"detail": "Missing activation code"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            device = Device.objects.select_related("branch__client").get(activation_code=activation_code)
        except Device.DoesNotExist:
            return Response({"detail": "Invalid activation code"}, status=status.HTTP_404_NOT_FOUND)

        branch = device.branch
        client = branch.client if branch and getattr(branch, "client_id", None) else None

        client_logo_url = ""
        if client and getattr(client, "logo_url", None):
            client_logo_url = client.logo_url or ""

        return Response(
            {
                "is_active": bool(device.is_active and device.branch_id),
                "branch_id": device.branch_id,
                "client_logo_url": client_logo_url,
            },
            status=status.HTTP_200_OK,
        )
