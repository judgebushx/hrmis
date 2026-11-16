from django.contrib import admin
from .models import ConstructionStage, ProgressRecord

@admin.register(ConstructionStage)
class ConstructionStageAdmin(admin.ModelAdmin):
    list_display = ("sequence", "name", "code", "weight", "is_active")
    list_editable = ("weight", "is_active")
    ordering = ("sequence",)
    search_fields = ("name", "code")

@admin.register(ProgressRecord)
class ProgressRecordAdmin(admin.ModelAdmin):
    list_display = ("house", "stage", "percentage", "status", "review_status", "engineer", "update_date")
    list_filter = ("review_status", "status", "stage")
    search_fields = ("house__house_id", "engineer__employee_id", "engineer__user__username")
    readonly_fields = ("created_at", "update_date")
