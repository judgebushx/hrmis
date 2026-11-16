from collections import defaultdict
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.accounts.models import EngineerProfile
from apps.housing.models import House
from apps.locations.models import Island, Municipality
from apps.photographs.models import HousePhoto
from apps.progress.models import ConstructionStage, ProgressRecord


PROGRAMME_TARGET = 700
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def _require_programme_access(user):
    # The current HRMIS permission model grants programme-wide access to
    # superusers only. This avoids exposing cross-engineer records to engineers.
    if not user.is_authenticated or not user.is_superuser:
        raise PermissionDenied("Programme-wide monitoring access is restricted to authorised programme managers.")


def _filtered_houses(request):
    qs = (
        House.objects
        .select_related(
            "village__municipality__island",
            "assigned_engineer__user",
        )
        .order_by("house_id")
    )

    selected_island = request.GET.get("island", "").strip()
    selected_municipality = request.GET.get("municipality", "").strip()
    selected_engineer = request.GET.get("engineer", "").strip()
    selected_status = request.GET.get("status", "").strip()
    search = request.GET.get("q", "").strip()

    valid_statuses = {value for value, _label in House.Status.choices}
    if selected_island.isdigit():
        qs = qs.filter(village__municipality__island_id=int(selected_island))
    else:
        selected_island = ""

    if selected_municipality.isdigit():
        qs = qs.filter(village__municipality_id=int(selected_municipality))
    else:
        selected_municipality = ""

    if selected_engineer.isdigit():
        qs = qs.filter(assigned_engineer_id=int(selected_engineer))
    else:
        selected_engineer = ""

    if selected_status in valid_statuses:
        qs = qs.filter(status=selected_status)
    else:
        selected_status = ""

    if search:
        qs = qs.filter(
            Q(house_id__icontains=search)
            | Q(beneficiary_name__icontains=search)
            | Q(village__name__icontains=search)
            | Q(village__municipality__name__icontains=search)
            | Q(assigned_engineer__employee_id__icontains=search)
            | Q(assigned_engineer__user__first_name__icontains=search)
            | Q(assigned_engineer__user__last_name__icontains=search)
        )

    return qs, selected_island, selected_municipality, selected_engineer, selected_status, search


def _build_dashboard_data(request):
    (houses_qs, selected_island, selected_municipality, selected_engineer,
     selected_status, search) = _filtered_houses(request)

    allowed_stale_days = (7, 14, 30, 60, 90)
    try:
        stale_days = int(request.GET.get("stale_days", "30"))
    except (TypeError, ValueError):
        stale_days = 30
    if stale_days not in allowed_stale_days:
        stale_days = 30
    houses = list(houses_qs)
    house_ids = [house.pk for house in houses]
    house_count = len(houses)

    active_stages = list(ConstructionStage.objects.filter(is_active=True).order_by("sequence", "name"))
    total_weight = sum((stage.weight for stage in active_stages), ZERO)

    # One ordered query retrieves approved submissions for all filtered houses.
    # The first record for each house/milestone is the latest approved version.
    approved_records = (
        ProgressRecord.objects
        .filter(
            house_id__in=house_ids,
            stage__is_active=True,
            review_status=ProgressRecord.ReviewStatus.APPROVED,
        )
        .select_related("stage")
        .order_by("house_id", "stage_id", "-update_date", "-created_at")
    )
    latest_approved = {}
    latest_approved_by_house = {}
    for record in approved_records:
        key = (record.house_id, record.stage_id)
        if key not in latest_approved:
            latest_approved[key] = record
        current = latest_approved_by_house.get(record.house_id)
        if current is None or (record.update_date, record.created_at) > (current.update_date, current.created_at):
            latest_approved_by_house[record.house_id] = record

    # Staleness is measured from the most recent supervisor-approved update.
    # If no approval exists, house registration date is used as the baseline.
    # Completed, handed-over and explicitly on-hold houses are excluded.
    now = timezone.now()
    stale_cutoff = now - timedelta(days=stale_days)
    active_statuses = (House.Status.REGISTERED, House.Status.IN_PROGRESS)
    stale_houses = []
    house_activity = {}
    for house in houses:
        latest_record = latest_approved_by_house.get(house.pk)
        reference_date = latest_record.update_date if latest_record else house.created_at
        days_since_update = max((now - reference_date).days, 0) if reference_date else 0
        is_stale = (
            house.status in active_statuses
            and reference_date is not None
            and reference_date <= stale_cutoff
        )
        house_activity[house.pk] = {
            "last_approved_at": latest_record.update_date if latest_record else None,
            "days_since_update": days_since_update,
            "is_stale": is_stale,
            "has_approved_update": latest_record is not None,
            "activity_label": "No approved update yet" if latest_record is None else timezone.localtime(latest_record.update_date).strftime("%d %b %Y"),
        }
        if is_stale:
            stale_houses.append(house)

    house_progress = {}
    house_has_approved = set()
    for house in houses:
        weighted_score = ZERO
        for stage in active_stages:
            record = latest_approved.get((house.pk, stage.pk))
            if record:
                weighted_score += stage.weight * record.percentage / HUNDRED
                if record.percentage > ZERO:
                    house_has_approved.add(house.pk)
        score = (weighted_score / total_weight * HUNDRED) if total_weight else ZERO
        house_progress[house.pk] = score.quantize(Decimal("0.01"))

    registered_count = house_count
    registration_coverage = (
        Decimal(registered_count) / Decimal(PROGRAMME_TARGET) * HUNDRED
        if PROGRAMME_TARGET else ZERO
    )
    sum_house_progress = sum(house_progress.values(), ZERO)
    programme_progress = (
        sum_house_progress / Decimal(PROGRAMME_TARGET)
        if PROGRAMME_TARGET else ZERO
    )
    average_registered_progress = (
        sum_house_progress / Decimal(registered_count)
        if registered_count else ZERO
    )

    status_counts = {value: 0 for value, _label in House.Status.choices}
    for house in houses:
        status_counts[house.status] = status_counts.get(house.status, 0) + 1

    completed_count = (
        status_counts.get(House.Status.COMPLETED, 0)
        + status_counts.get(House.Status.HANDED_OVER, 0)
    )
    assigned_count = sum(1 for house in houses if house.assigned_engineer_id)
    unassigned_count = registered_count - assigned_count
    on_hold_count = status_counts.get(House.Status.ON_HOLD, 0)
    in_progress_count = status_counts.get(House.Status.IN_PROGRESS, 0)
    no_approved_progress_count = registered_count - len(house_has_approved)

    submissions = ProgressRecord.objects.filter(house_id__in=house_ids)
    submission_totals = submissions.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(review_status=ProgressRecord.ReviewStatus.PENDING)),
        approved=Count("id", filter=Q(review_status=ProgressRecord.ReviewStatus.APPROVED)),
        changes_requested=Count("id", filter=Q(review_status=ProgressRecord.ReviewStatus.REJECTED)),
        blocked=Count("id", filter=Q(status=ProgressRecord.StageStatus.BLOCKED)),
    )
    pending_count = submission_totals["pending"] or 0
    pending_by_house = {
        row["house_id"]: row["pending"]
        for row in submissions.values("house_id").annotate(
            pending=Count("id", filter=Q(review_status=ProgressRecord.ReviewStatus.PENDING))
        )
    }

    # Latest submitted record (regardless of review outcome) identifies a
    # currently reported blocked milestone without treating it as approved.
    latest_submissions = (
        submissions.select_related("stage")
        .order_by("house_id", "stage_id", "-update_date", "-created_at")
    )
    latest_by_house_stage = {}
    for record in latest_submissions:
        key = (record.house_id, record.stage_id)
        if key not in latest_by_house_stage:
            latest_by_house_stage[key] = record
    latest_blocked_count = sum(
        1 for record in latest_by_house_stage.values()
        if record.status == ProgressRecord.StageStatus.BLOCKED
    )

    # Milestone bottlenecks: stale, incomplete approved work and old pending
    # submissions are reported separately to avoid conflating delivery delay
    # with supervisor review delay.
    bottleneck_rows = []
    active_houses = [house for house in houses if house.status in active_statuses]
    for stage in active_stages:
        stale_incomplete = 0
        awaiting_review = 0
        no_approved = 0
        for house in active_houses:
            approved = latest_approved.get((house.pk, stage.pk))
            submitted = latest_by_house_stage.get((house.pk, stage.pk))
            if approved is not None:
                if approved.percentage < HUNDRED and approved.update_date <= stale_cutoff:
                    stale_incomplete += 1
            if submitted is not None:
                if approved is None:
                    no_approved += 1
                if (submitted.review_status == ProgressRecord.ReviewStatus.PENDING
                        and submitted.update_date <= stale_cutoff):
                    awaiting_review += 1
        bottleneck_rows.append({
            "stage": stage,
            "stale_incomplete": stale_incomplete,
            "awaiting_review": awaiting_review,
            "no_approved": no_approved,
        })
    bottleneck_rows.sort(
        key=lambda row: (-(row["stale_incomplete"] + row["awaiting_review"]), row["stage"].sequence)
    )

    # Island and municipality summaries are based on the current filter scope.
    island_groups = {}
    municipality_groups = {}
    for house in houses:
        island = house.village.municipality.island
        municipality = house.village.municipality
        score = house_progress[house.pk]
        island_row = island_groups.setdefault(island.pk, {
            "id": island.pk, "name": island.name, "houses": 0, "in_progress": 0,
            "completed": 0, "progress_sum": ZERO,
        })
        island_row["houses"] += 1
        island_row["in_progress"] += int(house.status == House.Status.IN_PROGRESS)
        island_row["completed"] += int(house.status in (
            House.Status.COMPLETED, House.Status.HANDED_OVER
        ))
        island_row["progress_sum"] += score

        municipality_row = municipality_groups.setdefault(municipality.pk, {
            "id": municipality.pk, "name": municipality.name, "island": island.name,
            "houses": 0, "progress_sum": ZERO,
        })
        municipality_row["houses"] += 1
        municipality_row["progress_sum"] += score

    island_rows = []
    for row in sorted(island_groups.values(), key=lambda item: item["name"]):
        row["average_progress"] = (
            row["progress_sum"] / Decimal(row["houses"])
        ).quantize(Decimal("0.01")) if row["houses"] else ZERO
        island_rows.append(row)

    municipality_rows = []
    for row in sorted(municipality_groups.values(), key=lambda item: (item["island"], item["name"])):
        row["average_progress"] = (
            row["progress_sum"] / Decimal(row["houses"])
        ).quantize(Decimal("0.01")) if row["houses"] else ZERO
        municipality_rows.append(row)

    # Per-milestone figures use the latest approved submission for each house.
    stage_rows = []
    for stage in active_stages:
        values = [
            latest_approved[(house.pk, stage.pk)].percentage
            for house in houses
            if (house.pk, stage.pk) in latest_approved
        ]
        completion_sum = sum(values, ZERO)
        avg = (
            completion_sum / Decimal(registered_count)
            if registered_count else ZERO
        )
        stage_rows.append({
            "stage": stage,
            "weight": stage.weight,
            "houses_updated": len(values),
            "average_completion": avg.quantize(Decimal("0.01")),
            "weighted_contribution": (
                stage.weight * avg / HUNDRED
            ).quantize(Decimal("0.01")),
        })

    # Engineer workload and review statistics are scoped to houses currently
    # assigned to each engineer in the selected programme view.
    engineer_profiles = (
        EngineerProfile.objects
        .filter(current_houses__in=houses)
        .select_related("user")
        .annotate(current_house_count=Count("current_houses", distinct=True))
        .distinct()
        .order_by("user__last_name", "user__first_name", "employee_id")
    )
    engineer_record_stats = {
        row["engineer_id"]: row
        for row in submissions.values("engineer_id").annotate(
            total=Count("id"),
            approved=Count("id", filter=Q(review_status=ProgressRecord.ReviewStatus.APPROVED)),
            pending=Count("id", filter=Q(review_status=ProgressRecord.ReviewStatus.PENDING)),
            changes_requested=Count("id", filter=Q(review_status=ProgressRecord.ReviewStatus.REJECTED)),
        )
    }
    engineer_house_scores = defaultdict(list)
    for house in houses:
        if house.assigned_engineer_id:
            engineer_house_scores[house.assigned_engineer_id].append(house_progress[house.pk])

    engineer_rows = []
    for profile in engineer_profiles:
        scores = engineer_house_scores.get(profile.pk, [])
        average = (
            sum(scores, ZERO) / Decimal(len(scores))
        ).quantize(Decimal("0.01")) if scores else ZERO
        stats = engineer_record_stats.get(profile.pk, {})
        engineer_rows.append({
            "profile": profile,
            "house_count": profile.current_house_count,
            "average_progress": average,
            "submissions": stats.get("total", 0),
            "approved": stats.get("approved", 0),
            "pending": stats.get("pending", 0),
            "changes_requested": stats.get("changes_requested", 0),
        })
    engineer_rows.sort(key=lambda row: (-row["house_count"], row["profile"].employee_id))

    photo_stats = HousePhoto.objects.filter(house_id__in=house_ids).aggregate(
        total=Count("id"),
        gps_passed=Count("id", filter=Q(location_verified=True, distance_from_house__lte=15)),
        gps_failed=Count("id", filter=Q(location_verified=False) | Q(distance_from_house__gt=15)),
    )

    # All filtered houses are mapped; the table below is paginated separately.
    map_points = []
    for house in houses:
        map_points.append({
            "id": house.house_id,
            "lat": float(house.latitude),
            "lon": float(house.longitude),
            "status": house.get_status_display(),
            "status_code": house.status,
            "location": f"{house.village.name}, {house.village.municipality.name}, {house.village.municipality.island.name}",
            "engineer": str(house.assigned_engineer) if house.assigned_engineer else "Unassigned",
            "progress": float(house_progress[house.pk]),
            "last_update": house_activity[house.pk]["activity_label"],
            "days_since_update": house_activity[house.pk]["days_since_update"],
            "stale": house_activity[house.pk]["is_stale"],
            "url": reverse("housing:house-detail", kwargs={"pk": house.pk}),
        })

    # Filtered house register rows include computed verified progress and activity.
    for house in houses:
        house.dashboard_progress = house_progress[house.pk]
        house.dashboard_pending = pending_by_house.get(house.pk, 0)
        house.dashboard_last_update = house_activity[house.pk]["activity_label"]
        house.dashboard_days_since_update = house_activity[house.pk]["days_since_update"]
        house.dashboard_stale = house_activity[house.pk]["is_stale"]

    paginator = Paginator(houses, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    islands = Island.objects.order_by("name")
    municipalities = Municipality.objects.select_related("island").order_by("island__name", "name")
    if selected_island:
        municipalities = municipalities.filter(island_id=int(selected_island))
    engineers = EngineerProfile.objects.filter(is_active=True).select_related("user").order_by(
        "user__last_name", "user__first_name", "employee_id"
    )
    status_choices = House.Status.choices

    return {
        "target": PROGRAMME_TARGET,
        "registered_count": registered_count,
        "registration_coverage": registration_coverage.quantize(Decimal("0.01")),
        "outstanding_target": max(PROGRAMME_TARGET - registered_count, 0),
        "in_progress_count": in_progress_count,
        "completed_count": completed_count,
        "handed_over_count": status_counts.get(House.Status.HANDED_OVER, 0),
        "on_hold_count": on_hold_count,
        "assigned_count": assigned_count,
        "unassigned_count": unassigned_count,
        "programme_progress": programme_progress.quantize(Decimal("0.01")),
        "average_registered_progress": average_registered_progress.quantize(Decimal("0.01")),
        "pending_count": pending_count,
        "approved_submission_count": submission_totals["approved"] or 0,
        "changes_requested_count": submission_totals["changes_requested"] or 0,
        "submission_count": submission_totals["total"] or 0,
        "blocked_submission_count": latest_blocked_count,
        "no_approved_progress_count": no_approved_progress_count,
        "stale_days": stale_days,
        "stale_days_options": allowed_stale_days,
        "stale_houses": stale_houses,
        "stale_house_count": len(stale_houses),
        "bottleneck_rows": bottleneck_rows,
        "photo_count": photo_stats["total"] or 0,
        "photo_gps_passed": photo_stats["gps_passed"] or 0,
        "photo_gps_failed": photo_stats["gps_failed"] or 0,
        "island_rows": island_rows,
        "municipality_rows": municipality_rows,
        "stage_rows": stage_rows,
        "engineer_rows": engineer_rows,
        "map_points": map_points,
        "all_houses": houses,
        "house_progress": house_progress,
        "page_obj": page_obj,
        "houses": page_obj.object_list,
        "islands": islands,
        "municipalities": municipalities,
        "engineers": engineers,
        "status_choices": status_choices,
        "selected_island": selected_island,
        "selected_municipality": selected_municipality,
        "selected_engineer": selected_engineer,
        "selected_status": selected_status,
        "search": search,
        "status_chart": {
            "labels": [label for _value, label in status_choices],
            "values": [status_counts.get(value, 0) for value, _label in status_choices],
        },
        "island_chart": {
            "labels": [row["name"] for row in island_rows],
            "values": [row["houses"] for row in island_rows],
            "progress": [float(row["average_progress"]) for row in island_rows],
        },
        "stage_chart": {
            "labels": [row["stage"].name for row in stage_rows],
            "values": [float(row["average_completion"]) for row in stage_rows],
        },
        "engineer_chart": {
            "labels": [row["profile"].user.get_full_name() or row["profile"].employee_id for row in engineer_rows[:10]],
            "values": [float(row["average_progress"]) for row in engineer_rows[:10]],
        },
    }


@login_required
def programme_dashboard(request):
    _require_programme_access(request.user)
    data = _build_dashboard_data(request)
    return render(request, "dashboard/programme_dashboard.html", data)


@login_required
def programme_export(request):
    _require_programme_access(request.user)
    data = _build_dashboard_data(request)

    workbook = Workbook()
    summary = workbook.active
    summary.title = "Programme Summary"
    summary.append(["IOM Micronesia - Housing Reconstruction Programme"])
    summary.append(["Programme target", data["target"]])
    summary.append(["Houses registered (current filter)", data["registered_count"]])
    summary.append(["Registration coverage (%)", float(data["registration_coverage"])])
    summary.append(["Programme verified progress (%)", float(data["programme_progress"])])
    summary.append(["Average verified progress among registered houses (%)", float(data["average_registered_progress"])])
    summary.append(["Under reconstruction", data["in_progress_count"]])
    summary.append(["Completed / handed over", data["completed_count"]])
    summary.append(["On hold", data["on_hold_count"]])
    summary.append(["Unassigned houses", data["unassigned_count"]])
    summary.append(["Pending supervisor reviews", data["pending_count"]])
    summary.append(["Photographs", data["photo_count"]])
    summary.append(["GPS passed photographs", data["photo_gps_passed"]])
    summary.append(["GPS failed photographs", data["photo_gps_failed"]])
    summary.append([f"Houses requiring follow-up (no approved update for {data['stale_days']}+ days)", data["stale_house_count"]])

    houses_sheet = workbook.create_sheet("House Register")
    houses_sheet.append([
        "House ID", "Beneficiary", "Island", "Municipality", "Village",
        "Engineer", "House status", "Verified progress (%)", "Pending reviews",
        "Latitude", "Longitude", "Last approved update", "Days since update", "Stale follow-up",
    ])
    for house in data["all_houses"]:
        houses_sheet.append([
            house.house_id,
            house.beneficiary_name,
            house.village.municipality.island.name,
            house.village.municipality.name,
            house.village.name,
            str(house.assigned_engineer) if house.assigned_engineer else "Unassigned",
            house.get_status_display(),
            float(data["house_progress"][house.pk]),
            house.dashboard_pending,
            float(house.latitude),
            float(house.longitude),
            house.dashboard_last_update,
            house.dashboard_days_since_update,
            "Yes" if house.dashboard_stale else "No",
        ])

    followup_sheet = workbook.create_sheet("Follow-up Register")
    followup_sheet.append(["House ID", "Beneficiary", "Island", "Municipality", "Village", "Engineer", "House status", "Verified progress (%)", "Last approved update", "Days since update", "Follow-up reason"])
    for house in data["stale_houses"]:
        followup_sheet.append([
            house.house_id, house.beneficiary_name,
            house.village.municipality.island.name, house.village.municipality.name,
            house.village.name, str(house.assigned_engineer) if house.assigned_engineer else "Unassigned",
            house.get_status_display(), float(data["house_progress"][house.pk]),
            house.dashboard_last_update, house.dashboard_days_since_update,
            "No approved update yet" if house.dashboard_last_update == "No approved update yet" else f"No approved update for {house.dashboard_days_since_update} days",
        ])

    bottleneck_sheet = workbook.create_sheet("Milestone Bottlenecks")
    bottleneck_sheet.append(["Milestone", "Stale incomplete approved work", "Old pending submissions", "Houses with submissions but no approved update"])
    for row in data["bottleneck_rows"]:
        bottleneck_sheet.append([row["stage"].name, row["stale_incomplete"], row["awaiting_review"], row["no_approved"]])

    engineers_sheet = workbook.create_sheet("Engineer Performance")
    engineers_sheet.append([
        "Employee ID", "Engineer", "Designation", "Assigned houses",
        "Average verified progress (%)", "Submissions", "Approved",
        "Pending review", "Changes requested",
    ])
    for row in data["engineer_rows"]:
        profile = row["profile"]
        engineers_sheet.append([
            profile.employee_id,
            profile.user.get_full_name() or profile.user.username,
            profile.designation,
            row["house_count"],
            float(row["average_progress"]),
            row["submissions"],
            row["approved"],
            row["pending"],
            row["changes_requested"],
        ])

    milestones_sheet = workbook.create_sheet("Milestone Performance")
    milestones_sheet.append([
        "Construction milestone", "Weight (%)", "Houses with approved update",
        "Average verified completion (%)", "Weighted contribution (%)",
    ])
    for row in data["stage_rows"]:
        milestones_sheet.append([
            row["stage"].name,
            float(row["weight"]),
            row["houses_updated"],
            float(row["average_completion"]),
            float(row["weighted_contribution"]),
        ])

    header_fill = PatternFill("solid", fgColor="174A7E")
    header_font = Font(bold=True, color="FFFFFF")
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2" if sheet.max_row > 1 else "A1"
        if sheet.max_row > 1:
            for cell in sheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(wrap_text=True, vertical="center")
        for column_cells in sheet.columns:
            letter = get_column_letter(column_cells[0].column)
            max_length = max(
                (len(str(cell.value)) for cell in column_cells if cell.value is not None),
                default=10,
            )
            sheet.column_dimensions[letter].width = min(max(max_length + 2, 14), 42)
        sheet.auto_filter.ref = sheet.dimensions if sheet.max_row > 1 else "A1"

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="HRMIS_Programme_Monitoring.xlsx"'
    workbook.save(response)
    return response
