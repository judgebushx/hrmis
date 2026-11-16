from .models import House

def accessible_houses(user):
    """Return houses visible to the user under their active role assignment."""
    qs = House.objects.select_related("village__municipality__island", "assigned_engineer__user")
    if not user.is_authenticated:
        return qs.none()
    if user.is_superuser:
        return qs
    try:
        inspector = user.inspector_profile
        if inspector.is_active and user.is_active:
            return qs.filter(assigned_inspectors=inspector, assigned_inspectors__is_active=True).distinct()
    except Exception:
        pass
    try:
        engineer = user.engineer_profile
        if engineer.is_active and user.is_active:
            return qs.filter(assigned_engineer=engineer, assigned_engineer__is_active=True)
    except Exception:
        pass
    return qs.none()

def can_access_house(user, house):
    return accessible_houses(user).filter(pk=house.pk).exists()
