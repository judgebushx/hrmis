from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from apps.housing.access import accessible_houses
from apps.housing.models import House
from apps.audit.models import AuditEvent
from .forms import InspectionForm, DefectForm, DefectUpdateForm, EngineerDefectWorkForm
from .models import Inspection, Defect


def _is_assigned_inspector(user, house):
    if not user.is_authenticated or not user.is_active:
        return False
    try:
        profile = user.inspector_profile
        return profile.is_active and profile.assigned_houses.filter(pk=house.pk).exists()
    except Exception:
        return False


def _can_manage_house(user, house):
    return bool(user.is_authenticated and (user.is_superuser or _is_assigned_inspector(user, house)))


def _is_house_engineer(user, house):
    if not user.is_authenticated or not user.is_active:
        return False
    try:
        profile = user.engineer_profile
        return profile.is_active and house.assigned_engineer_id == profile.pk
    except Exception:
        return False

@login_required
def inspection_list(request):
    if request.user.is_superuser:
        qs = Inspection.objects.select_related("house", "stage", "inspected_by", "reviewed_by")
    else:
        qs = Inspection.objects.filter(house__in=accessible_houses(request.user)).select_related("house", "stage", "inspected_by")
    status = request.GET.get("status", "ALL")
    if status != "ALL":
        qs = qs.filter(review_status=status)
    return render(request, "inspections/inspection_list.html", {"inspections": qs, "selected_status": status, "open_defects": Defect.objects.filter(inspection__in=qs).exclude(status=Defect.Status.VERIFIED).count()})

@login_required
def inspection_create(request, house_pk):
    house = get_object_or_404(accessible_houses(request.user), pk=house_pk)
    if not _can_manage_house(request.user, house):
        raise PermissionDenied("You may only inspect houses currently assigned to you.")
    if request.method == "POST":
        form = InspectionForm(request.POST, house=house)
        if form.is_valid():
            inspection = form.save(commit=False)
            inspection.house = house
            inspection.inspected_by = request.user
            inspection.checklist_responses = form.checklist_data()
            with transaction.atomic():
                inspection.save()
                AuditEvent.objects.create(user=request.user, house=house, action="SITE_INSPECTION_SUBMITTED", object_type="Inspection", object_id=str(inspection.pk), details={"stage": inspection.stage.code, "outcome": inspection.outcome}, ip_address=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Site inspection submitted for supervisor review.")
            return redirect("inspections:inspection-detail", pk=inspection.pk)
    else:
        form = InspectionForm(house=house, initial={"inspection_date": timezone.localdate(), "stage": request.GET.get("stage")})
    return render(request, "inspections/inspection_form.html", {"form": form, "house": house})

@login_required
def inspection_detail(request, pk):
    inspection = get_object_or_404(Inspection.objects.select_related("house", "stage", "inspected_by", "reviewed_by"), pk=pk)
    if not request.user.is_superuser and not accessible_houses(request.user).filter(pk=inspection.house_id).exists():
        raise PermissionDenied
    defect_form = DefectForm(house=inspection.house)
    if request.method == "POST" and request.POST.get("action") == "add_defect":
        if not _can_manage_house(request.user, inspection.house):
            raise PermissionDenied
        defect_form = DefectForm(request.POST, house=inspection.house)
        if defect_form.is_valid():
            defect = defect_form.save(commit=False)
            defect.inspection = inspection
            defect.save()
            AuditEvent.objects.create(user=request.user, house=inspection.house, action="INSPECTION_DEFECT_CREATED", object_type="Defect", object_id=str(defect.pk), details={"severity": defect.severity, "assigned_engineer_id": defect.assigned_engineer_id}, ip_address=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Defect recorded.")
            return redirect("inspections:inspection-detail", pk=inspection.pk)
    return render(request, "inspections/inspection_detail.html", {"inspection": inspection, "defect_form": defect_form, "can_manage": _can_manage_house(request.user, inspection.house)})

@login_required
def defect_update(request, pk):
    defect = get_object_or_404(Defect.objects.select_related("inspection__house", "assigned_engineer__user"), pk=pk)
    if not _can_manage_house(request.user, defect.inspection.house):
        raise PermissionDenied("Only the assigned inspector or a superuser can manage defect assignments and verification.")
    if request.method == "POST":
        form = DefectUpdateForm(request.POST, instance=defect, house=defect.inspection.house)
        if form.is_valid():
            obj = form.save(commit=False)
            if obj.status == Defect.Status.VERIFIED:
                obj.closed_at = timezone.now()
            else:
                obj.closed_at = None
            obj.save()
            AuditEvent.objects.create(user=request.user, house=obj.inspection.house, action="INSPECTION_DEFECT_UPDATED", object_type="Defect", object_id=str(obj.pk), details={"status": obj.status, "assigned_engineer_id": obj.assigned_engineer_id}, ip_address=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Defect assignment or verification updated.")
            return redirect("inspections:inspection-detail", pk=obj.inspection_id)
    else:
        form = DefectUpdateForm(instance=defect, house=defect.inspection.house)
    return render(request, "inspections/defect_form.html", {"form": form, "defect": defect})


@login_required
def my_assigned_defects(request):
    if request.user.is_superuser:
        defects = Defect.objects.select_related("inspection__house", "inspection__stage", "assigned_engineer__user")
    else:
        try:
            profile = request.user.engineer_profile
        except Exception:
            raise PermissionDenied("This page is for registered engineers.")
        if not profile.is_active:
            raise PermissionDenied("Your engineer profile is inactive.")
        defects = Defect.objects.filter(assigned_engineer=profile).select_related("inspection__house", "inspection__stage")
    status = request.GET.get("status", "OPEN")
    if status == "ALL":
        pass
    elif status in Defect.Status.values:
        defects = defects.filter(status=status)
    else:
        status = "OPEN"
        defects = defects.exclude(status=Defect.Status.VERIFIED)
    return render(request, "inspections/my_assigned_defects.html", {"defects": defects, "selected_status": status})


@login_required
def defect_work_update(request, pk):
    defect = get_object_or_404(Defect.objects.select_related("inspection__house", "assigned_engineer__user"), pk=pk)
    if not _is_house_engineer(request.user, defect.inspection.house) or defect.assigned_engineer_id != request.user.engineer_profile.pk:
        raise PermissionDenied("Only the engineer assigned to this defect may update its corrective work.")
    if defect.status == Defect.Status.VERIFIED:
        messages.info(request, "This defect has already been verified and closed.")
        return redirect("inspections:my-assigned-defects")
    if request.method == "POST":
        form = EngineerDefectWorkForm(request.POST, request.FILES, instance=defect)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.engineer_updated_at = timezone.now()
            obj.save()
            AuditEvent.objects.create(user=request.user, house=obj.inspection.house, action="DEFECT_CORRECTIVE_WORK_UPDATED", object_type="Defect", object_id=str(obj.pk), details={"status": obj.status, "photo_uploaded": bool(obj.rectification_photo)}, ip_address=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Corrective work update submitted to the inspection team.")
            return redirect("inspections:my-assigned-defects")
    else:
        form = EngineerDefectWorkForm(instance=defect)
    return render(request, "inspections/defect_work_form.html", {"form": form, "defect": defect})

@user_passes_test(lambda u: u.is_authenticated and u.is_superuser)
def inspection_review(request, pk):
    inspection = get_object_or_404(Inspection, pk=pk)
    if request.method == "POST":
        decision = request.POST.get("decision")
        comments = request.POST.get("review_comments", "").strip()
        if decision not in [Inspection.ReviewStatus.APPROVED, Inspection.ReviewStatus.CHANGES]:
            messages.error(request, "Select a valid review decision.")
        else:
            inspection.review_status = decision
            inspection.review_comments = comments
            inspection.reviewed_by = request.user
            inspection.reviewed_at = timezone.now()
            inspection.save(update_fields=["review_status", "review_comments", "reviewed_by", "reviewed_at"])
            AuditEvent.objects.create(user=request.user, house=inspection.house, action="SITE_INSPECTION_" + decision, object_type="Inspection", object_id=str(inspection.pk), details={"comments": comments}, ip_address=request.META.get("REMOTE_ADDR"))
            messages.success(request, "Inspection review saved.")
            return redirect("inspections:inspection-detail", pk=inspection.pk)
    return render(request, "inspections/inspection_review.html", {"inspection": inspection})
