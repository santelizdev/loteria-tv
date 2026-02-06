from django.contrib import admin
from core.models import Transmission

@admin.register(Transmission)
class TransmissionAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at")  # ajusta campos reales
