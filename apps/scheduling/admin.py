from django.contrib import admin
from .models import MilestoneSchedule, HouseSchedule, ProgrammePlan

class MilestoneScheduleInline(admin.TabularInline):
    model = MilestoneSchedule
    extra = 0

@admin.register(HouseSchedule)
class HouseScheduleAdmin(admin.ModelAdmin):
    list_display = ("house", "baseline_start", "baseline_completion", "revised_completion", "updated_at")
    search_fields = ("house__house_id", "house__beneficiary_name")
    inlines = [MilestoneScheduleInline]

@admin.register(ProgrammePlan)
class ProgrammePlanAdmin(admin.ModelAdmin):
    list_display = ("name", "target_houses", "project_start", "construction_deadline", "project_end", "updated_at")
