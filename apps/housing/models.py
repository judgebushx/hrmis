from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from apps.accounts.models import EngineerProfile
from apps.locations.models import Village


class House(models.Model):
    class DamageClassification(models.TextChoices):
        MINOR = "MINOR", "Minor damage"
        MODERATE = "MODERATE", "Moderate damage"
        SEVERE = "SEVERE", "Severe damage"
        DESTROYED = "DESTROYED", "Destroyed"
        OTHER = "OTHER", "Other"

    class ReconstructionType(models.TextChoices):
        FULL = "FULL", "Full reconstruction"
        PARTIAL = "PARTIAL", "Partial reconstruction"
        MAJOR_REHABILITATION = "MAJOR_REHABILITATION", "Major rehabilitation"
        REPAIR = "REPAIR", "Repair / rehabilitation"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Registered"
        IN_PROGRESS = "IN_PROGRESS", "Under reconstruction"
        ON_HOLD = "ON_HOLD", "On hold"
        COMPLETED = "COMPLETED", "Completed"
        HANDED_OVER = "HANDED_OVER", "Handed over"

    house_id = models.CharField(max_length=24, unique=True, db_index=True)
    beneficiary_name = models.CharField(max_length=200, blank=True)
    household_reference = models.CharField(max_length=100, blank=True)
    beneficiary_contact = models.CharField(max_length=40, blank=True)
    alternate_contact = models.CharField(max_length=40, blank=True)
    household_size = models.PositiveSmallIntegerField(null=True, blank=True)

    village = models.ForeignKey(Village, on_delete=models.PROTECT, related_name="houses")
    community = models.CharField(max_length=120, blank=True)
    address_details = models.CharField(max_length=255, blank=True)

    latitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    house_type = models.CharField(max_length=100, blank=True)
    bedrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    damage_classification = models.CharField(max_length=100, choices=DamageClassification.choices, blank=True)
    reconstruction_type = models.CharField(max_length=120, choices=ReconstructionType.choices, blank=True)
    contractor = models.CharField(max_length=200, blank=True)

    assigned_engineer = models.ForeignKey(
        EngineerProfile, on_delete=models.PROTECT,
        related_name="current_houses", null=True, blank=True,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REGISTERED)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="houses_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["house_id"]
        permissions = [("view_all_houses", "Can view all houses")]

    def __str__(self):
        return self.house_id

    @property
    def island(self):
        return self.village.municipality.island


class HouseAssignment(models.Model):
    house = models.ForeignKey(House, on_delete=models.PROTECT, related_name="assignment_history")
    engineer = models.ForeignKey(EngineerProfile, on_delete=models.PROTECT, related_name="assignment_history")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assignments_made")
    assigned_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.house.house_id} → {self.engineer}"
