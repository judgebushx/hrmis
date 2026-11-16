from django.conf import settings
from django.db import models
from apps.housing.models import House
from apps.accounts.models import EngineerProfile

class ConstructionStage(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    sequence = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    class Meta: ordering = ["sequence"]
    def __str__(self): return self.name

class ProgressRecord(models.Model):
    class StageStatus(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked"
    house = models.ForeignKey(House, on_delete=models.PROTECT, related_name="progress_records")
    stage = models.ForeignKey(ConstructionStage, on_delete=models.PROTECT, related_name="progress_records")
    engineer = models.ForeignKey(EngineerProfile, on_delete=models.PROTECT, related_name="progress_records")
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=StageStatus.choices, default=StageStatus.NOT_STARTED)
    update_date = models.DateTimeField()
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-update_date", "-created_at"]
    def __str__(self): return f"{self.house.house_id}: {self.stage.name} ({self.percentage}%)"
