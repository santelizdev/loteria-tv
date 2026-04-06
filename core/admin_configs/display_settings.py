from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import reverse

from core.models import DisplaySettings


@admin.register(DisplaySettings)
class DisplaySettingsAdmin(admin.ModelAdmin):
    fields = ("rotation_seconds", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        if DisplaySettings.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = DisplaySettings.get_solo()
        url = reverse("admin:core_displaysettings_change", args=[obj.pk])
        return HttpResponseRedirect(url)
