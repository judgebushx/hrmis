from django.contrib import admin
from .models import EngineerProfile
@admin.register(EngineerProfile)
class EngineerProfileAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "user", "designation", "is_active")
    search_fields = ("employee_id", "user__username", "user__first_name", "user__last_name")
