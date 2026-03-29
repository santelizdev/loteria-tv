from django.contrib import admin

from core.models import CruzDailyContent


@admin.register(CruzDailyContent)
class CruzDailyContentAdmin(admin.ModelAdmin):
    list_display = ("draw_date", "display_order", "card_type", "title", "image_url")
    list_filter = ("draw_date", "card_type")
    search_fields = ("title", "image_alt", "image_url")
    ordering = ("-draw_date", "display_order")
