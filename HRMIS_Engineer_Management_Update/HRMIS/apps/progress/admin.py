from django.contrib import admin
from .models import ConstructionStage, ProgressRecord
admin.site.register(ConstructionStage)
@admin.register(ProgressRecord)
class ProgressRecordAdmin(admin.ModelAdmin):
    list_display = ("house", "stage", "percentage", "status", "engineer", "update_date")
    readonly_fields = ("created_at",)
