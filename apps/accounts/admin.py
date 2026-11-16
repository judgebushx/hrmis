from django.contrib import admin
from .models import EngineerProfile, InspectorProfile

@admin.register(EngineerProfile)
class EngineerProfileAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "user", "designation", "is_active")
    search_fields = ("employee_id", "user__username", "user__first_name", "user__last_name")

@admin.register(InspectorProfile)
class InspectorProfileAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "user", "designation", "is_active")
    search_fields = ("employee_id", "user__username", "user__first_name", "user__last_name")
    filter_horizontal = ("assigned_houses",)
