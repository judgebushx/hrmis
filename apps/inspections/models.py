from django.conf import settings
from django.db import models
from apps.housing.models import House
from apps.accounts.models import EngineerProfile
from apps.progress.models import ConstructionStage, ProgressRecord

class Inspection(models.Model):
    class Outcome(models.TextChoices):
        PASS = "PASS", "Pass"
        CONDITIONAL = "CONDITIONAL", "Pass with corrective actions"
        FAIL = "FAIL", "Fail – rework required"
    class ReviewStatus(models.TextChoices):
        PENDING = "PENDING", "Pending supervisor review"
        APPROVED = "APPROVED", "Approved"
        CHANGES = "CHANGES", "Changes requested"

    house = models.ForeignKey(House, on_delete=models.PROTECT, related_name="inspections")
    stage = models.ForeignKey(ConstructionStage, on_delete=models.PROTECT, related_name="inspections")
    progress_record = models.ForeignKey(ProgressRecord, null=True, blank=True, on_delete=models.SET_NULL, related_name="inspections")
    inspected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="site_inspections")
    inspection_date = models.DateField()
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    checklist_responses = models.JSONField(default=dict, blank=True)
    general_comments = models.TextField(blank=True)
    review_status = models.CharField(max_length=12, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="inspections_reviewed")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-inspection_date", "-created_at"]
        indexes = [models.Index(fields=["house", "stage", "review_status"], name="insp_house_stage_stat_idx")]

    def __str__(self):
        return f"{self.house.house_id} – {self.stage.name} – {self.inspection_date}"

class Defect(models.Model):
    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACTION = "ACTION", "Corrective action underway"
        READY = "READY", "Ready for inspection"
        VERIFIED = "VERIFIED", "Verified closed"

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="defects")
    description = models.TextField()
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    corrective_action = models.TextField(blank=True)
    responsible_person = models.CharField(max_length=160, blank=True)
    assigned_engineer = models.ForeignKey(EngineerProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_defects")
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    resolution_notes = models.TextField(blank=True)
    engineer_update = models.TextField(blank=True)
    engineer_updated_at = models.DateTimeField(null=True, blank=True)
    rectification_photo = models.ImageField(upload_to="defect_rectifications/%Y/%m/", null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "due_date", "-created_at"]

    def __str__(self):
        return f"{self.inspection.house.house_id}: {self.description[:60]}"
