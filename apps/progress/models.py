from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from apps.housing.models import House
from apps.accounts.models import EngineerProfile


class ConstructionStage(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                 validators=[MinValueValidator(0), MaxValueValidator(100)])
    sequence = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sequence", "name"]

    def __str__(self):
        return self.name


class ProgressRecord(models.Model):
    class StageStatus(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        COMPLETED = "COMPLETED", "Completed"
        BLOCKED = "BLOCKED", "Blocked"

    class ReviewStatus(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Changes requested"

    house = models.ForeignKey(House, on_delete=models.PROTECT, related_name="progress_records")
    stage = models.ForeignKey(ConstructionStage, on_delete=models.PROTECT, related_name="progress_records")
    engineer = models.ForeignKey(EngineerProfile, on_delete=models.PROTECT, related_name="progress_records")
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)])
    status = models.CharField(max_length=20, choices=StageStatus.choices, default=StageStatus.NOT_STARTED)
    update_date = models.DateTimeField()
    remarks = models.TextField(blank=True)
    review_status = models.CharField(max_length=12, choices=ReviewStatus.choices, default=ReviewStatus.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="progress_reviews")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-update_date", "-created_at"]
        indexes = [models.Index(fields=["house", "stage", "review_status"], name="progress_pr_house_i_1a1b2f_idx")]

    def __str__(self):
        return f"{self.house.house_id}: {self.stage.name} ({self.percentage}%)"
