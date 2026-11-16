import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.accounts.models import EngineerProfile
from apps.housing.models import House
from apps.progress.models import ConstructionStage

def house_photo_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"reconstruction_photos/{instance.house.house_id}/{instance.stage.code}/{uuid.uuid4().hex}.{ext}"

class HousePhoto(models.Model):
    house = models.ForeignKey(House, on_delete=models.PROTECT, related_name="photos")
    engineer = models.ForeignKey(EngineerProfile, on_delete=models.PROTECT, related_name="uploaded_photos")
    stage = models.ForeignKey(ConstructionStage, on_delete=models.PROTECT, related_name="photos")
    image = models.ImageField(upload_to=house_photo_path)
    photo_latitude = models.DecimalField(max_digits=10, decimal_places=7)
    photo_longitude = models.DecimalField(max_digits=10, decimal_places=7)
    distance_from_house = models.DecimalField(max_digits=7, decimal_places=2)
    captured_at_exif = models.CharField(max_length=40, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    image_checksum = models.CharField(max_length=64, db_index=True)
    location_verified = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    class Meta: ordering = ["-uploaded_at"]
    def __str__(self): return f"{self.house.house_id} - {self.stage.name} photo"
