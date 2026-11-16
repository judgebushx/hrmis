from django.contrib import admin
from django.core.exceptions import PermissionDenied
from .models import House, HouseAssignment

@admin.register(House)
class HouseAdmin(admin.ModelAdmin):
    list_display = ("house_id", "village", "assigned_engineer", "status")
    search_fields = ("house_id", "beneficiary_name")
    list_filter = ("status", "village__municipality__island")
    def has_module_permission(self, request): return request.user.is_superuser
    def has_view_permission(self, request, obj=None): return request.user.is_superuser
    def has_add_permission(self, request): return request.user.is_superuser
    def has_change_permission(self, request, obj=None): return request.user.is_superuser
    def has_delete_permission(self, request, obj=None): return request.user.is_superuser
    def has_view_permission(self, request, obj=None): return request.user.is_superuser
    def has_add_permission(self, request): return request.user.is_superuser
    def has_change_permission(self, request, obj=None): return request.user.is_superuser
    def has_delete_permission(self, request, obj=None): return request.user.is_superuser

@admin.register(HouseAssignment)
class HouseAssignmentAdmin(admin.ModelAdmin):
    list_display = ("house", "engineer", "assigned_at", "ended_at")
    def has_module_permission(self, request): return request.user.is_superuser
    def has_view_permission(self, request, obj=None): return request.user.is_superuser
    def has_add_permission(self, request): return request.user.is_superuser
    def has_change_permission(self, request, obj=None): return request.user.is_superuser
    def has_delete_permission(self, request, obj=None): return request.user.is_superuser
