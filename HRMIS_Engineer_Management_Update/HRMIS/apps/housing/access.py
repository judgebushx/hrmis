from .models import House

def accessible_houses(user):
    """Superusers see all houses; other users see only their current assignments."""
    qs = House.objects.select_related("village__municipality__island", "assigned_engineer__user")
    if not user.is_authenticated:
        return qs.none()
    if user.is_superuser:
        return qs
    try:
        profile = user.engineer_profile
    except Exception:
        return qs.none()
    return qs.filter(assigned_engineer=profile, assigned_engineer__is_active=True)

def can_access_house(user, house):
    return accessible_houses(user).filter(pk=house.pk).exists()
