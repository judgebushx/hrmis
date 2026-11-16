import math
from PIL import Image, ExifTags
from PIL.ExifTags import TAGS, GPSTAGS

MAX_DISTANCE_METRES = 15.0

def _to_degrees(value):
    parts = [float(x) for x in value]
    return parts[0] + parts[1] / 60 + parts[2] / 3600

def extract_exif_gps(image_file):
    """Return (latitude, longitude, captured_at) from original image EXIF, or raise ValueError."""
    try:
        image_file.seek(0)
        image = Image.open(image_file)
        exif = image.getexif()
        gps_ifd = exif.get_ifd(0x8825)
        gps = {GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
        lat, lon = gps.get("GPSLatitude"), gps.get("GPSLongitude")
        lat_ref, lon_ref = gps.get("GPSLatitudeRef"), gps.get("GPSLongitudeRef")
        if not all([lat, lon, lat_ref, lon_ref]):
            raise ValueError("Photograph has no complete GPS EXIF metadata.")
        latitude, longitude = _to_degrees(lat), _to_degrees(lon)
        if str(lat_ref).upper() == "S": latitude = -latitude
        if str(lon_ref).upper() == "W": longitude = -longitude
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Photograph contains invalid GPS coordinates.")
        captured = exif.get(0x9003) or exif.get(0x0132)
        return latitude, longitude, str(captured) if captured else None
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Unable to read GPS metadata. Upload the original geo-tagged image.") from exc
    finally:
        try: image_file.seek(0)
        except Exception: pass

def haversine_metres(lat1, lon1, lat2, lon2):
    radius = 6371008.8
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))

def validate_photo_for_house(image_file, house):
    lat, lon, captured_at = extract_exif_gps(image_file)
    distance = haversine_metres(house.latitude, house.longitude, lat, lon)
    if distance > MAX_DISTANCE_METRES:
        raise ValueError(f"Photograph rejected: GPS location is {distance:.1f} metres from this house. Maximum allowed distance is 15 metres.")
    return {"latitude": lat, "longitude": lon, "captured_at_exif": captured_at, "distance_metres": round(distance, 2)}
