# core/api/views.py

import random
import string
from datetime import datetime

from django.db.models import Max
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from core.models import (
    Device,
    CurrentResult,
    AnimalitoResult,
)
from core.services.device_service import DeviceService
from core.services.device_redis_service import DeviceRedisService



#views


class CurrentResultsAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    CACHE_KEY = "results:current:all"
    CACHE_TTL = 120  # 2 min (la data cambia por hora, pero queremos absorber bursts de TVs)

    def get(self, request):
        activation_code = request.query_params.get("code")
        ip_address = request.META.get("REMOTE_ADDR")

        if not activation_code:
            return Response(
                {"detail": "Missing activation code"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            DeviceService.validate_device(
                activation_code=activation_code,
                ip_address=ip_address,
            )
        except PermissionError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN,
            )

        # -----------------------------
        # 1) Cache-first (Redis)
        # -----------------------------
        cached = DeviceRedisService.get_cache(self.CACHE_KEY)
        if cached:
            return Response(cached, status=status.HTTP_200_OK)

        # -----------------------------
        # 2) Fallback DB
        # -----------------------------
        results = (
            CurrentResult.objects
            .select_related("provider")
            .filter(provider__is_active=True)
            .order_by("provider__name", "draw_time")
        )

        data = [
            {
                "provider": r.provider.name,
                "time": r.draw_time.strftime("%H:%M"),
                "number": r.winning_number,
                # Mantengo "image" para compatibilidad con tu frontend aunque esté vacío
                "image": r.image_url or "",
            }
            for r in results
        ]

        # -----------------------------
        # 3) Repoblar cache
        # -----------------------------
        DeviceRedisService.set_cache(self.CACHE_KEY, data, ttl_seconds=self.CACHE_TTL)

        return Response(data, status=status.HTTP_200_OK)



class DeviceRegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_id = request.data.get("device_id")

        if not device_id:
            return Response(
                {"error": "device_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        activation_code = self._generate_code()
        ip = self._get_ip(request)

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
        return "".join(
            random.choices(string.ascii_uppercase + string.digits, k=6)
        )

    def _get_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        return xff.split(",")[0] if xff else request.META.get("REMOTE_ADDR")

#ENDPOINT HEARTBEAT
class DeviceHeartbeatAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        device_id = request.data.get("device_id")
        activation_code = request.data.get("code")
        ip_address = request.META.get("REMOTE_ADDR")

        if not device_id or not activation_code:
            return Response(
                {"detail": "Missing credentials"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            device = DeviceService.validate_device(
                activation_code=activation_code,
                ip_address=ip_address,
            )
        except PermissionError as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            {
                "status": "ok",
                "online": True,
            },
            status=status.HTTP_200_OK,
        )


#STATUS
class DeviceStatusAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        activation_code = request.query_params.get("code")
        if not activation_code:
            return Response({"detail": "Missing activation code"}, status=status.HTTP_400_BAD_REQUEST)

        # Busca por activation_code (DB)
        try:
            device = Device.objects.select_related("branch").get(activation_code=activation_code)
        except Device.DoesNotExist:
            return Response({"detail": "Invalid activation code"}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "is_active": bool(device.is_active and device.branch_id),
            "branch_id": device.branch_id,
        }, status=status.HTTP_200_OK)

#RESULTADOS_ANIMALITOS
class AnimalitosResultsAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    CACHE_TTL = 120  # segundos

    def get(self, request):
        activation_code = request.query_params.get("code")
        ip_address = request.META.get("REMOTE_ADDR")

        # 1️⃣ VALIDAR DEVICE (siempre primero)
        try:
            DeviceService.validate_device(
                activation_code=activation_code,
                ip_address=ip_address,
            )
        except PermissionError as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        # 2️⃣ Fecha objetivo
        raw_date = request.query_params.get("date")
        if raw_date:
            try:
                target_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"detail": "Invalid date format. Use YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            today = timezone.localdate()
            last = AnimalitoResult.objects.aggregate(last=Max("draw_date"))["last"]
            target_date = today if AnimalitoResult.objects.filter(draw_date=today).exists() else last

        if not target_date:
            return Response([], status=status.HTTP_200_OK)

        # 3️⃣ Cache
        CACHE_VERSION = "v2"  # sube a v3, v4… cuando cambie el payload
        cache_key = f"results:animalitos:{CACHE_VERSION}:{target_date.isoformat()}"
        cached = DeviceRedisService.get_cache(cache_key)
        if cached:
            return Response(cached, status=status.HTTP_200_OK)

        # 4️⃣ Query DB
        qs = (
            AnimalitoResult.objects
            .select_related("provider")
            .filter(draw_date=target_date)
            .order_by("provider__name", "draw_time")
        )

        data = [
            {
                "provider": r.provider.name,
                "time": r.draw_time.strftime("%H:%M"),
                "number": str(r.animal_number),
                "animal": r.animal_name,
                "image": r.animal_image_url,
            }
            for r in qs
        ]

        # 5️⃣ Guardar cache
        DeviceRedisService.set_cache(
            cache_key,
            data,
            ttl_seconds=self.CACHE_TTL,
        )

        return Response(data, status=status.HTTP_200_OK)

