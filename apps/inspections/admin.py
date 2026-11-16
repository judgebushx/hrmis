from django.contrib import admin
from .models import Inspection, Defect

class DefectInline(admin.TabularInline):
    model = Defect
    extra = 0

@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ("house", "stage", "inspection_date", "outcome", "review_status", "inspected_by")
    list_filter = ("outcome", "review_status", "stage")
    search_fields = ("house__house_id", "house__beneficiary_name")
    inlines = [DefectInline]

@admin.register(Defect)
class DefectAdmin(admin.ModelAdmin):
    list_display = ("inspection", "severity", "status", "due_date", "responsible_person")
    list_filter = ("severity", "status")
