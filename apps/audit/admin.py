from django.contrib import admin
from .models import AuditEvent
@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "house", "object_type")
    readonly_fields = ("user", "house", "action", "object_type", "object_id", "details", "ip_address", "created_at")
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
