# core/routing.py
from django.urls import path
from core.ws.consumers import DeviceConsumer

websocket_urlpatterns = [
    path("ws/device/<str:activation_code>/", DeviceConsumer.as_asgi()),
]
