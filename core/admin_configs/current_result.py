from django.contrib import admin
from core.models import CurrentResult

@admin.register(CurrentResult)
class CurrentResultAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "draw_date", "draw_time", "winning_number")
    list_filter = ("provider", "draw_date")
    search_fields = ("provider__name", "winning_number")
    ordering = ("provider__name", "draw_time")
