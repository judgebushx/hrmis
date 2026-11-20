import hashlib
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.accounts.models import EngineerProfile
from apps.housing.access import accessible_houses
from apps.housing.services.status import sync_house_reconstruction_status
from apps.photographs.models import HousePhoto
from apps.photographs.validators import validate_photo_for_house
from apps.audit.models import AuditEvent
from .forms import ProgressReviewForm, ProgressSubmissionForm
from .models import ConstructionStage, ProgressRecord

MAX_PHOTO_SIZE = 10 * 1024 * 1024
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "HEIF", "HEIC"}


def _engineer_profile(user):
    try:
        profile = user.engineer_profile
    except EngineerProfile.DoesNotExist:
        raise PermissionDenied("An active engineer account is required.")
    if not profile.is_active or not user.is_active:
        raise PermissionDenied("Your engineer account is inactive.")
    return profile


def _verified_progress_summary(house):
    """Use the latest approved submission for each stage; never count pending claims."""
    stages = list(ConstructionStage.objects.filter(is_active=True))
    total_weight = sum((s.weight for s in stages), Decimal("0"))
    weighted = Decimal("0")
    stage_rows = []
    for stage in stages:
        record = ProgressRecord.objects.filter(
            house=house, stage=stage, review_status=ProgressRecord.ReviewStatus.APPROVED
        ).order_by("-update_date", "-created_at").first()
        pct = record.percentage if record else Decimal("0")
        weighted += stage.weight * pct / Decimal("100")
        stage_rows.append({"stage": stage, "record": record, "percentage": pct})
    overall = (weighted / total_weight * Decimal("100")) if total_weight else Decimal("0")
    return stage_rows, overall.quantize(Decimal("0.01")), total_weight


@login_required
def house_progress(request, house_pk):
    house = get_object_or_404(accessible_houses(request.user), pk=house_pk)
    profile = None
    if not request.user.is_superuser:
        profile = _engineer_profile(request.user)
        if house.assigned_engineer_id != profile.pk:
            raise PermissionDenied("You are not currently assigned to this house.")

    if request.method == "POST":
        if request.user.is_superuser:
            raise PermissionDenied("Superusers review progress; engineers submit progress updates.")
        form = ProgressSubmissionForm(request.POST)
        uploads = request.FILES.getlist("photos")
        if len(uploads) > 10:
            form.add_error(None, "You can upload a maximum of 10 photographs per progress update.")
        for photo in uploads:
            if photo.size > MAX_PHOTO_SIZE:
                form.add_error(None, f"{photo.name}: file exceeds the 10 MB limit.")
        if form.is_valid() and not form.errors:
            stage = form.cleaned_data["stage"]
            prepared = []
            # Validate every image before creating any database or file records.
            for uploaded in uploads:
                try:
                    meta = validate_photo_for_house(uploaded, house)
                    uploaded.seek(0)
                    with Image.open(uploaded) as img:
                        if img.format not in ALLOWED_IMAGE_FORMATS:
                            raise ValueError("Only original JPEG, PNG or supported HEIC/HEIF images are accepted.")
                        img.verify()
                    uploaded.seek(0)
                    digest = hashlib.sha256(uploaded.read()).hexdigest()
                    uploaded.seek(0)
                    if HousePhoto.objects.filter(house=house, image_checksum=digest).exists():
                        raise ValueError("This photograph has already been uploaded for this house.")
                    if any(existing_digest == digest for _, _, existing_digest in prepared):
                        raise ValueError("This photograph is duplicated within the selected upload batch.")
                    prepared.append((uploaded, meta, digest))
                except (ValueError, UnidentifiedImageError, OSError) as exc:
                    form.add_error(None, f"{uploaded.name}: {exc}")
                except Exception as exc:
                    form.add_error(None, f"{uploaded.name}: image could not be validated ({exc}).")
            if not form.errors:
                with transaction.atomic():
                    record = ProgressRecord.objects.create(
                        house=house, stage=stage, engineer=profile,
                        percentage=form.cleaned_data["percentage"],
                        status=form.cleaned_data["status"],
                        update_date=timezone.now(), remarks=form.cleaned_data["remarks"],
                    )
                    for uploaded, meta, digest in prepared:
                        HousePhoto.objects.create(
                            house=house, progress_record=record, engineer=profile,
                            stage=stage, image=uploaded,
                            photo_latitude=meta["latitude"],
                            photo_longitude=meta["longitude"],
                            distance_from_house=meta["distance_metres"],
                            captured_at_exif=meta["captured_at_exif"] or "",
                            image_checksum=digest,
                            location_verified=True,
                            description=form.cleaned_data["remarks"],
                        )
                    AuditEvent.objects.create(
                        user=request.user, house=house,
                        action="PROGRESS_SUBMITTED", object_type="ProgressRecord",
                        object_id=str(record.pk),
                        details={"stage": stage.code, "percentage": str(record.percentage),
                                 "status": record.status, "photo_count": len(prepared)},
                        ip_address=request.META.get("REMOTE_ADDR"),
                    )
                messages.success(request, "Progress update submitted for supervisor review.")
                return redirect("progress:house-progress", house_pk=house.pk)
    else:
        form = ProgressSubmissionForm()

    stage_rows, official_progress, total_weight = _verified_progress_summary(house)
    records = list(
        house.progress_records
        .select_related("stage", "engineer__user", "reviewed_by")
        .prefetch_related("photos")
        .order_by("-update_date", "-created_at")
    )

    # Compare the latest submission for each milestone against the latest
    # earlier supervisor-approved submission (the approved visual baseline).
    comparisons = []
    for row in stage_rows:
        stage_records = [item for item in records if item.stage_id == row["stage"].pk]
        if not stage_records:
            continue
        latest_submission = stage_records[0]
        approved_baseline = (
            ProgressRecord.objects
            .filter(
                house=house,
                stage=row["stage"],
                review_status=ProgressRecord.ReviewStatus.APPROVED,
            )
            .exclude(pk=latest_submission.pk)
            .select_related("engineer__user", "reviewed_by")
            .prefetch_related("photos")
            .order_by("-update_date", "-created_at")
            .first()
        )
        comparisons.append({
            "stage": row["stage"],
            "before": approved_baseline,
            "after": latest_submission,
        })

    # Older records may pre-date the progress_record foreign key. Keep those
    # photographs visible, but separate them from submission-linked evidence.
    unlinked_photos = (
        house.photos.filter(progress_record__isnull=True)
        .select_related("stage", "engineer__user")
        .order_by("-uploaded_at")
    )
    return render(request, "progress/house_progress.html", {
        "house": house, "form": form, "stage_rows": stage_rows,
        "official_progress": official_progress, "total_weight": total_weight,
        "records": records, "unlinked_photos": unlinked_photos,
        "comparisons": comparisons,
        "can_submit": bool(profile),
    })


@user_passes_test(lambda u: u.is_authenticated and u.is_superuser)
def progress_review_list(request):
    pending = ProgressRecord.objects.filter(
        review_status=ProgressRecord.ReviewStatus.PENDING
    ).select_related("house", "stage", "engineer__user", "house__village__municipality__island")
    return render(request, "progress/progress_review_list.html", {
        "pending_records": pending,
        "pending_count": pending.count(),
    })


@user_passes_test(lambda u: u.is_authenticated and u.is_superuser)
def progress_review(request, record_pk):
    record = get_object_or_404(
        ProgressRecord.objects.select_related("house", "stage", "engineer__user"), pk=record_pk
    )
    if request.method == "POST":
        form = ProgressReviewForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                record.review_status = form.cleaned_data["decision"]
                record.reviewed_by = request.user
                record.reviewed_at = timezone.now()
                record.review_comments = form.cleaned_data["review_comments"].strip()
                record.save(update_fields=["review_status", "reviewed_by", "reviewed_at", "review_comments"])

                status_before = record.house.status
                status_after = status_before
                if record.review_status == ProgressRecord.ReviewStatus.APPROVED:
                    status_before, status_after = sync_house_reconstruction_status(record.house)

                AuditEvent.objects.create(
                    user=request.user, house=record.house,
                    action="PROGRESS_" + record.review_status,
                    object_type="ProgressRecord", object_id=str(record.pk),
                    details={"stage": record.stage.code, "percentage": str(record.percentage),
                             "comments": record.review_comments,
                             "house_status_before": status_before,
                             "house_status_after": status_after},
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
            if status_before != status_after:
                messages.success(
                    request,
                    f"Progress submission approved. House status updated to {record.house.get_status_display()}.",
                )
            else:
                messages.success(request, "Progress submission review saved.")
            return redirect("progress:house-progress", house_pk=record.house_id)
    else:
        form = ProgressReviewForm()
    return render(request, "progress/progress_review.html", {
        "record": record,
        "form": form,
        # The review template uses these values to construct the house map link.
        "house_latitude": record.house.latitude,
        "house_longitude": record.house.longitude,
    })
