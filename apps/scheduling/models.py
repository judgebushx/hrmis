import calendar
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.housing.models import House
from apps.progress.models import ConstructionStage


class ProgrammePlan(models.Model):
    """Programme-wide dates and target. One active plan is used by HRMIS."""
    name = models.CharField(max_length=160, default="IOM Micronesia Housing Reconstruction Programme")
    target_houses = models.PositiveIntegerField(default=700, validators=[MinValueValidator(1)])
    project_start = models.DateField()
    project_end = models.DateField()
    construction_deadline = models.DateField(
        help_text="Construction should be complete by this date, leaving time for closeout."
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="programme_plans_updated",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["project_start"]

    def clean(self):
        errors = {}
        if self.project_end and self.project_start and self.project_end <= self.project_start:
            errors["project_end"] = "Project end must be after project commencement."
        if self.project_start and self.project_end:
            month_index = self.project_start.year * 12 + self.project_start.month - 1 + 36
            year, month_zero = divmod(month_index, 12)
            month = month_zero + 1
            anniversary_day = min(self.project_start.day, calendar.monthrange(year, month)[1])
            expected_end = self.project_start.replace(year=year, month=month, day=anniversary_day) - timedelta(days=1)
            if self.project_end != expected_end:
                errors["project_end"] = "The project end date must reflect the agreed 36-month programme duration."
        if self.construction_deadline and self.project_end and self.construction_deadline >= self.project_end:
            errors["construction_deadline"] = "Construction deadline must leave a closeout period before project end."
        if self.construction_deadline and self.project_start and self.construction_deadline <= self.project_start:
            errors["construction_deadline"] = "Construction deadline must be after project commencement."
        if self.project_end and self.construction_deadline:
            month_index = self.project_end.year * 12 + self.project_end.month - 1 - 3
            year, month_zero = divmod(month_index, 12)
            month = month_zero + 1
            latest_allowed_day = min(self.project_end.day, calendar.monthrange(year, month)[1])
            latest_allowed_deadline = self.project_end.replace(year=year, month=month, day=latest_allowed_day)
            if self.construction_deadline > latest_allowed_deadline:
                errors["construction_deadline"] = "Construction must finish at least three calendar months before the overall project end."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.name


class HouseSchedule(models.Model):
    house = models.OneToOneField(House, on_delete=models.CASCADE, related_name="schedule")
    baseline_start = models.DateField(null=True, blank=True)
    baseline_completion = models.DateField(null=True, blank=True)
    revised_start = models.DateField(null=True, blank=True)
    revised_completion = models.DateField(null=True, blank=True)
    planning_notes = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="house_schedules_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["baseline_start", "house__house_id"]

    def clean(self):
        errors = {}
        if self.baseline_start and self.baseline_completion and self.baseline_completion < self.baseline_start:
            errors["baseline_completion"] = "Baseline completion cannot be before baseline start."
        if self.revised_start and self.revised_completion and self.revised_completion < self.revised_start:
            errors["revised_completion"] = "Revised completion cannot be before revised start."
        if errors:
            raise ValidationError(errors)

    @property
    def effective_start(self):
        return self.revised_start or self.baseline_start

    @property
    def effective_completion(self):
        return self.revised_completion or self.baseline_completion

    def __str__(self):
        return f"Schedule: {self.house.house_id}"


class MilestoneSchedule(models.Model):
    house_schedule = models.ForeignKey(HouseSchedule, on_delete=models.CASCADE, related_name="milestones")
    stage = models.ForeignKey(ConstructionStage, on_delete=models.PROTECT, related_name="house_schedules")
    planned_start = models.DateField(null=True, blank=True)
    planned_end = models.DateField(null=True, blank=True)
    revised_start = models.DateField(null=True, blank=True)
    revised_end = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["stage__sequence", "stage__name"]
        constraints = [
            models.UniqueConstraint(fields=["house_schedule", "stage"], name="uniq_house_schedule_stage"),
            models.CheckConstraint(
                condition=Q(planned_end__isnull=True) | Q(planned_start__isnull=True) | Q(planned_end__gte=models.F("planned_start")),
                name="sched_planned_dates_ordered",
            ),
            models.CheckConstraint(
                condition=Q(revised_end__isnull=True) | Q(revised_start__isnull=True) | Q(revised_end__gte=models.F("revised_start")),
                name="sched_revised_dates_ordered",
            ),
        ]

    def clean(self):
        errors = {}
        if self.planned_start and self.planned_end and self.planned_end < self.planned_start:
            errors["planned_end"] = "Planned end cannot be before planned start."
        if self.revised_start and self.revised_end and self.revised_end < self.revised_start:
            errors["revised_end"] = "Revised end cannot be before revised start."
        if errors:
            raise ValidationError(errors)

    @property
    def effective_start(self):
        return self.revised_start or self.planned_start

    @property
    def effective_end(self):
        return self.revised_end or self.planned_end

    def __str__(self):
        return f"{self.house_schedule.house.house_id} - {self.stage.name}"
