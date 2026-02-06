from django.contrib import admin
from core.models import Branch

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("id", "client", "is_active", "paid_until")
    list_filter = ("is_active",)
