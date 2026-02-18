from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from core.api.views import (
    CurrentResultsAPIView,
    DeviceRegisterView,
    DeviceHeartbeatAPIView,
    DeviceStatusAPIView,
    AnimalitosResultsAPIView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    

    path("api/results/", CurrentResultsAPIView.as_view()),
    path("api/animalitos/", AnimalitosResultsAPIView.as_view()),

    path("api/devices/register/", DeviceRegisterView.as_view()),
    path("api/devices/heartbeat/", DeviceHeartbeatAPIView.as_view()),
    path("api/devices/status/", DeviceStatusAPIView.as_view(), name="device-status"),  
]

if settings.DEBUG:
        urlpatterns += staticfiles_urlpatterns()
        
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

