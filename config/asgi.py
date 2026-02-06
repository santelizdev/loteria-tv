# config/asgi.py
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

django_asgi_app = get_asgi_application()  # <-- esto ejecuta django.setup()

import core.routing  # <-- IMPORT DESPUÉS del setup

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(core.routing.websocket_urlpatterns)
        ),
    }
)
