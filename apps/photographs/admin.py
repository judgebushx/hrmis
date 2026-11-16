from django.contrib import admin
from .models import HousePhoto
@admin.register(HousePhoto)
class HousePhotoAdmin(admin.ModelAdmin):
    list_display = ("house", "stage", "engineer", "distance_from_house", "location_verified", "uploaded_at")
    readonly_fields = ("uploaded_at", "image_checksum", "photo_latitude", "photo_longitude", "distance_from_house", "location_verified")
