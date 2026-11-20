from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.housing.models import House
from apps.progress.models import ConstructionStage, ProgressRecord
from .forms import BulkScheduleForm, HouseScheduleForm, MilestoneScheduleFormSet, ProgrammePlanForm
from .models import HouseSchedule, MilestoneSchedule, ProgrammePlan
from .validation import validate_milestone_sequence

DEFAULT_START = date(2026, 11, 1)
DEFAULT_PROJECT_END = date(2029, 10, 31)
DEFAULT_CONSTRUCTION_DEADLINE = date(2029, 7, 31)
ZERO = Decimal("0")
HUNDRED = Decimal("100")
VARIANCE_TOLERANCE = Decimal("5.00")


def _manager_only(user):
    if not user.is_authenticated or not user.is_superuser:
        raise PermissionDenied("Programme planning is restricted to authorised programme managers.")


def _programme_plan():
    plan = ProgrammePlan.objects.order_by("pk").first()
    if plan:
        return plan
    return ProgrammePlan.objects.create(
        name="IOM Micronesia Housing Reconstruction Programme", target_houses=700,
        project_start=DEFAULT_START, project_end=DEFAULT_PROJECT_END,
        construction_deadline=DEFAULT_CONSTRUCTION_DEADLINE,
    )


def _approved_progress_by_house():
    """
    Return current approved progress and a conservative, time-series trend per house.

    A forecast requires at least two distinct approved update dates, at least
    seven days between the first and latest observations, and a positive net
    increase in weighted progress. Multiple stage updates on the same date are
    treated as one observation so they do not artificially inflate the rate.
    """
    stages = list(ConstructionStage.objects.filter(is_active=True).order_by("sequence", "name"))
    total_weight = sum((s.weight for s in stages), ZERO)
    records = ProgressRecord.objects.filter(
        review_status=ProgressRecord.ReviewStatus.APPROVED, stage__is_active=True,
    ).select_related("stage").order_by("house_id", "update_date", "created_at", "pk")

    by_house = {}
    for record in records:
        observed_at = timezone.localtime(record.update_date)
        observed_date = observed_at.date()
        by_house.setdefault(record.house_id, {}).setdefault(observed_date, []).append(record)

    result = {}
    for house_id, dated_records in by_house.items():
        latest_by_stage = {}
        snapshots = []
        for observed_date in sorted(dated_records):
            for record in dated_records[observed_date]:
                latest_by_stage[record.stage_id] = record.percentage

            weighted = sum(
                (stage.weight * latest_by_stage.get(stage.pk, ZERO) / HUNDRED for stage in stages),
                ZERO,
            )
            actual_on_date = (
                (weighted / total_weight * HUNDRED).quantize(Decimal("0.01"))
                if total_weight else ZERO
            )
            snapshots.append((observed_date, actual_on_date))

        latest_records = {}
        for stage_id in {record.stage_id for records_on_date in dated_records.values() for record in records_on_date}:
            latest_records[stage_id] = max(
                (record for records_on_date in dated_records.values() for record in records_on_date
                 if record.stage_id == stage_id),
                key=lambda record: (record.update_date, record.created_at, record.pk),
            )

        stage_values = {stage.pk: latest_records[stage.pk].percentage if stage.pk in latest_records else ZERO
                        for stage in stages}
        latest_dates = [record.update_date for record in latest_records.values()]
        first_date, first_actual = snapshots[0]
        latest_date, latest_actual = snapshots[-1]
        span_days = (latest_date - first_date).days
        net_increase = latest_actual - first_actual
        rate_per_day = (net_increase / Decimal(span_days)) if span_days > 0 and net_increase > ZERO else ZERO

        result[house_id] = {
            "actual": latest_actual,
            "stages": stage_values,
            "last_approved_at": max(latest_dates) if latest_dates else None,
            "trend_points": len(snapshots),
            "trend_span_days": span_days,
            "trend_rate_per_day": rate_per_day,
            "trend_first_actual": first_actual,
            "trend_latest_date": latest_date,
        }
    return stages, total_weight, result


def _planned_percent(schedule, stages, total_weight, as_of):
    """Time-phased planned progress: each milestone's weight times elapsed schedule fraction."""
    if not schedule or not total_weight:
        return ZERO
    by_stage = {row.stage_id: row for row in schedule.milestones.all()}
    planned_weighted = ZERO
    for stage in stages:
        row = by_stage.get(stage.pk)
        if not row or not row.effective_start or not row.effective_end:
            continue
        start, end = row.effective_start, row.effective_end
        if as_of < start:
            fraction = ZERO
        elif as_of >= end:
            fraction = HUNDRED
        else:
            fraction = Decimal((as_of - start).days) / Decimal(max((end - start).days, 1)) * HUNDRED
        planned_weighted += stage.weight * fraction / HUNDRED
    return (planned_weighted / total_weight * HUNDRED).quantize(Decimal("0.01"))


def _schedule_metrics(house, schedule, stages, total_weight, progress_map, as_of, inactive_days=30):
    progress = progress_map.get(house.pk, {"actual": ZERO, "stages": {}, "last_approved_at": None})
    actual = progress["actual"]
    planned = _planned_percent(schedule, stages, total_weight, as_of)
    variance = (actual - planned).quantize(Decimal("0.01"))
    overdue = []
    scheduled_count = 0
    active_stage_ids = {stage.pk for stage in stages}
    for row in schedule.milestones.all() if schedule else []:
        if row.stage_id not in active_stage_ids:
            continue
        if row.planned_start and row.planned_end:
            scheduled_count += 1
        pct = progress["stages"].get(row.stage_id, ZERO)
        if row.effective_end and row.effective_end < as_of and pct < HUNDRED and house.status not in (
            House.Status.ON_HOLD, House.Status.COMPLETED, House.Status.HANDED_OVER
        ):
            overdue.append(row.stage.name)

    last_approved_at = progress.get("last_approved_at")
    if last_approved_at:
        last_update_date = timezone.localtime(last_approved_at).date()
    elif schedule and schedule.baseline_start:
        last_update_date = schedule.baseline_start
    else:
        last_update_date = house.created_at.date()
    days_since_update = max((as_of - last_update_date).days, 0)
    no_recent_approval = bool(
        schedule and schedule.baseline_start and as_of >= schedule.baseline_start
        and days_since_update >= inactive_days
        and house.status not in (House.Status.ON_HOLD, House.Status.COMPLETED, House.Status.HANDED_OVER)
    )

    # Conservative forecast: extrapolate only from distinct, dated approved
    # progress observations, never from programme elapsed time alone.
    forecast_finish = None
    projected_risk = False
    forecast_label = "No approved progress yet"
    forecast_rate = progress.get("trend_rate_per_day", ZERO)
    trend_points = progress.get("trend_points", 0)
    trend_span_days = progress.get("trend_span_days", 0)
    latest_trend_date = progress.get("trend_latest_date")

    if house.status in (House.Status.COMPLETED, House.Status.HANDED_OVER):
        forecast_finish = latest_trend_date or as_of
        forecast_label = "Completed / handed over"
    elif actual >= HUNDRED:
        forecast_finish = latest_trend_date or as_of
        forecast_label = "100% verified — completion confirmation pending"
    elif trend_points < 2:
        forecast_label = "Awaiting a second approved update"
    elif trend_span_days < 7:
        forecast_label = "Building progress history (minimum 7 days)"
    elif forecast_rate <= ZERO:
        forecast_label = "No measurable progress increase"
    elif latest_trend_date and (as_of - latest_trend_date).days >= inactive_days:
        forecast_label = "Trend is stale — approved update required"
    else:
        remaining_progress = max(HUNDRED - actual, ZERO)
        days_to_finish = (remaining_progress / forecast_rate)
        forecast_finish = as_of + timedelta(days=int(days_to_finish.to_integral_value(rounding="ROUND_CEILING")))
        forecast_label = "Forecast based on approved progress trend"
        expected_completion = (
            (schedule.revised_completion or schedule.baseline_completion)
            if schedule else None
        )
        if expected_completion and forecast_finish > expected_completion:
            projected_risk = True
            forecast_label = "At risk — projected after baseline completion"

    if (forecast_finish and schedule and schedule.baseline_completion
            and forecast_finish > schedule.baseline_completion):
        projected_risk = True
    if (forecast_finish and schedule and schedule.baseline_completion
            and forecast_finish > schedule.baseline_completion
            and forecast_label == "Forecast based on approved progress trend"):
        forecast_label = "At risk — projected after baseline completion"

    if house.status == House.Status.ON_HOLD:
        status, label = "ON_HOLD", "On hold"
    elif house.status in (House.Status.COMPLETED, House.Status.HANDED_OVER):
        status, label = "COMPLETE", "Completed / handed over"
    elif not schedule or not schedule.baseline_start or not schedule.baseline_completion or scheduled_count < len(stages):
        status, label = "UNSCHEDULED", "Schedule incomplete"
    elif overdue or variance < -VARIANCE_TOLERANCE or projected_risk:
        status, label = "BEHIND", "Behind schedule"
    elif variance > VARIANCE_TOLERANCE:
        status, label = "AHEAD", "Ahead of schedule"
    else:
        status, label = "ON_TRACK", "On schedule"

    return {
        "actual": actual, "planned": planned, "variance": variance,
        "status": status, "status_label": label,
        "overdue_count": len(overdue), "overdue_stages": overdue,
        "scheduled_milestones": scheduled_count,
        "last_approved_at": last_approved_at,
        "days_since_update": days_since_update,
        "no_recent_approval": no_recent_approval,
        "projected_finish": forecast_finish,
        "projected_risk": projected_risk,
        "forecast_label": forecast_label,
        "forecast_rate_per_day": forecast_rate,
        "forecast_trend_points": trend_points,
        "forecast_trend_span_days": trend_span_days,
    }


def _schedule_rows(houses, stages, total_weight, progress_map, as_of, inactive_days):
    rows = []
    for house in houses:
        schedule = getattr(house, "schedule", None)
        metrics = _schedule_metrics(house, schedule, stages, total_weight, progress_map, as_of, inactive_days)
        rows.append({
            "house": house, "schedule": schedule, "metrics": metrics,
            "location": f"{house.village.name}, {house.village.municipality.name}, {house.village.municipality.island.name}",
            "engineer": str(house.assigned_engineer) if house.assigned_engineer else "Unassigned",
        })
    return rows


@login_required
def programme_schedule(request):
    _manager_only(request.user)
    plan = _programme_plan()
    if request.method == "POST":
        form = ProgrammePlanForm(request.POST, instance=plan)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            conflicts = []
            if updated.project_start and (
                HouseSchedule.objects.filter(Q(baseline_start__lt=updated.project_start) | Q(revised_start__lt=updated.project_start)).exists()
                or MilestoneSchedule.objects.filter(Q(planned_start__lt=updated.project_start) | Q(revised_start__lt=updated.project_start)).exists()
            ):
                conflicts.append("Some house or milestone schedule start dates fall before the proposed programme commencement.")
            if updated.construction_deadline:
                if HouseSchedule.objects.filter(Q(baseline_completion__gt=updated.construction_deadline) | Q(revised_completion__gt=updated.construction_deadline)).exists():
                    conflicts.append("Some house construction completion dates fall after the proposed construction deadline.")
                if MilestoneSchedule.objects.filter(Q(planned_end__gt=updated.construction_deadline) | Q(revised_end__gt=updated.construction_deadline) | Q(planned_start__gt=updated.construction_deadline) | Q(revised_start__gt=updated.construction_deadline)).exists():
                    conflicts.append("Some milestone dates fall after the proposed construction deadline.")
            if conflicts:
                for error in conflicts:
                    form.add_error(None, error)
            else:
                updated.save()
                messages.success(request, "Programme planning dates updated.")
                return redirect("scheduling:programme-schedule")
    else:
        form = ProgrammePlanForm(instance=plan)

    try:
        inactive_days = int(request.GET.get("inactive_days", "30"))
    except (TypeError, ValueError):
        inactive_days = 30
    inactive_days = min(max(inactive_days, 7), 180)
    stages, total_weight, progress_map = _approved_progress_by_house()
    as_of = timezone.localdate()
    houses = list(House.objects.select_related("village__municipality__island", "assigned_engineer__user")
                  .prefetch_related("schedule__milestones__stage").order_by("house_id"))
    rows = _schedule_rows(houses, stages, total_weight, progress_map, as_of, inactive_days)
    total_timeline_days = max((plan.construction_deadline - plan.project_start).days, 1)
    for row in rows:
        schedule = row["schedule"]
        if schedule and schedule.effective_start and schedule.effective_completion:
            left = (schedule.effective_start - plan.project_start).days / total_timeline_days * 100
            width = (schedule.effective_completion - schedule.effective_start).days / total_timeline_days * 100
            row["timeline_left"] = round(max(0, min(100, left)), 1)
            row["timeline_width"] = round(max(1, min(100 - row["timeline_left"], width)), 1)
        else:
            row["timeline_left"] = 0
            row["timeline_width"] = 0
    counts = {key: 0 for key in ("UNSCHEDULED", "ON_TRACK", "AHEAD", "BEHIND", "ON_HOLD", "COMPLETE")}
    overdue_milestones = no_progress_count = projected_risk_count = 0
    planned_sum = actual_sum = ZERO
    inactive_rows = []
    alert_rows = []
    for row in rows:
        m = row["metrics"]
        counts[m["status"]] += 1
        overdue_milestones += m["overdue_count"]
        no_progress_count += int(m["no_recent_approval"])
        projected_risk_count += int(m["projected_risk"])
        planned_sum += m["planned"]
        actual_sum += m["actual"]
        if m["no_recent_approval"]:
            inactive_rows.append(row)
        if m["no_recent_approval"] or m["overdue_count"] or m["projected_risk"]:
            alert_rows.append(row)
    return render(request, "scheduling/programme_schedule.html", {
        "plan": plan, "form": form, "rows": rows, "house_count": len(houses),
        "scheduled_count": len(houses) - counts["UNSCHEDULED"],
        "schedule_coverage_percent": (Decimal(len(houses) - counts["UNSCHEDULED"]) / Decimal(len(houses)) * HUNDRED).quantize(Decimal("0.1")) if houses else ZERO,
        "unscheduled_count": counts["UNSCHEDULED"], "on_track_count": counts["ON_TRACK"],
        "ahead_count": counts["AHEAD"], "behind_count": counts["BEHIND"],
        "on_hold_schedule_count": counts["ON_HOLD"], "schedule_complete_count": counts["COMPLETE"],
        "overdue_milestones": overdue_milestones,
        "no_progress_count": no_progress_count, "projected_risk_count": projected_risk_count,
        "inactive_rows": inactive_rows, "alert_rows": alert_rows, "inactive_days": inactive_days,
        "average_planned": (planned_sum / len(houses)).quantize(Decimal("0.01")) if houses else ZERO,
        "average_actual": (actual_sum / len(houses)).quantize(Decimal("0.01")) if houses else ZERO,
        "as_of": as_of, "construction_days_remaining": (plan.construction_deadline - as_of).days,
    })


@login_required
def bulk_schedule(request):
    _manager_only(request.user)
    plan = _programme_plan()
    stages = list(ConstructionStage.objects.filter(is_active=True).order_by("sequence", "name"))
    if request.method == "POST":
        form = BulkScheduleForm(request.POST)
        if form.is_valid():
            selected = list(form.cleaned_data["houses"].order_by("house_id"))
            start_date = form.cleaned_data["cohort_start"]
            cohort_size = form.cleaned_data["houses_per_cohort"]
            cohort_gap = form.cleaned_data["cohort_interval_days"]
            durations = {stage.pk: form.cleaned_data[f"duration_{stage.pk}"] for stage in stages}
            total_house_duration = sum(durations.values())
            if not stages:
                form.add_error(None, "No active construction milestones are configured.")
            elif start_date < plan.project_start:
                form.add_error("cohort_start", f"Cohort start cannot be before programme commencement ({plan.project_start:%d %b %Y}).")
            else:
                # Keep existing house baselines when repairing; calculate dates
                # only for houses without a baseline.
                projected = []
                for index, house in enumerate(selected):
                    cohort_no = index // cohort_size
                    generated_start = start_date + timedelta(days=cohort_no * cohort_gap)
                    existing = getattr(house, "schedule", None)
                    effective_start = existing.baseline_start if existing and existing.baseline_start else generated_start
                    effective_end = existing.baseline_completion if existing and existing.baseline_completion else effective_start + timedelta(days=total_house_duration - 1)
                    projected.append(effective_end)
                last_completion = max(projected) if projected else start_date
                if last_completion > plan.construction_deadline:
                    form.add_error(None, f"The latest selected house schedule would finish on {last_completion:%d %b %Y}, after the construction deadline of {plan.construction_deadline:%d %b %Y}. Adjust cohort dates or milestone durations before saving.")
                else:
                    with transaction.atomic():
                        processed = repaired = 0
                        for index, house in enumerate(selected):
                            cohort_no = index // cohort_size
                            generated_start = start_date + timedelta(days=cohort_no * cohort_gap)
                            generated_end = generated_start + timedelta(days=total_house_duration - 1)
                            schedule, schedule_created = HouseSchedule.objects.get_or_create(
                                house=house,
                                defaults={
                                    "baseline_start": generated_start,
                                    "baseline_completion": generated_end,
                                    "updated_by": request.user,
                                    "planning_notes": f"Bulk generated schedule · Cohort {cohort_no + 1} · {cohort_size} houses per cohort · stage-specific durations.",
                                },
                            )
                            # Preserve existing house baseline dates; fill only
                            # missing values on previously-created schedules.
                            if not schedule.baseline_start:
                                schedule.baseline_start = generated_start
                            if not schedule.baseline_completion:
                                schedule.baseline_completion = schedule.baseline_start + timedelta(days=total_house_duration - 1)
                            schedule.updated_by = request.user
                            if not schedule.planning_notes:
                                schedule.planning_notes = f"Bulk generated schedule · Cohort {cohort_no + 1} · {cohort_size} houses per cohort · stage-specific durations."
                            schedule.save()

                            cursor = schedule.baseline_start
                            had_missing = False
                            for stage in stages:
                                generated_milestone_end = cursor + timedelta(days=durations[stage.pk] - 1)
                                milestone, _ = MilestoneSchedule.objects.get_or_create(
                                    house_schedule=schedule,
                                    stage=stage,
                                    defaults={
                                        "planned_start": cursor,
                                        "planned_end": generated_milestone_end,
                                        "notes": f"Bulk schedule · Cohort {cohort_no + 1}",
                                    },
                                )
                                if not milestone.planned_start and not milestone.planned_end:
                                    milestone.planned_start = cursor
                                    milestone.planned_end = generated_milestone_end
                                    if not milestone.notes:
                                        milestone.notes = f"Bulk schedule · Cohort {cohort_no + 1}"
                                    milestone.save()
                                    had_missing = True
                                elif milestone.planned_start and milestone.planned_end:
                                    # Never overwrite an existing milestone.
                                    cursor = milestone.planned_end + timedelta(days=1)
                                    continue
                                else:
                                    # Leave a partially completed date pair for
                                    # manual review rather than guessing.
                                    had_missing = True
                                cursor = milestone.planned_end + timedelta(days=1) if milestone.planned_end else generated_milestone_end + timedelta(days=1)
                            processed += 1
                            if not schedule_created and had_missing:
                                repaired += 1
                    messages.success(request, f"Bulk scheduling complete: {processed} houses processed; {repaired} existing schedules repaired with missing milestone dates. Existing house and milestone dates were preserved.")
                    return redirect("scheduling:programme-schedule")
    else:
        form = BulkScheduleForm(initial={"cohort_start": plan.project_start})
    return render(request, "scheduling/bulk_schedule.html", {"form": form, "plan": plan, "stages": stages})


@login_required
def programme_gantt(request):
    _manager_only(request.user)
    plan = _programme_plan()
    stages, total_weight, progress_map = _approved_progress_by_house()
    as_of = timezone.localdate()
    houses_qs = House.objects.select_related("village__municipality__island", "assigned_engineer__user").prefetch_related("schedule__milestones__stage").order_by("house_id")
    q = request.GET.get("q", "").strip()
    if q:
        houses_qs = houses_qs.filter(Q(house_id__icontains=q) | Q(beneficiary_name__icontains=q))
    island = request.GET.get("island", "")
    if island:
        houses_qs = houses_qs.filter(village__municipality__island_id=island)
    paginator = Paginator(houses_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    total_days = max((plan.construction_deadline - plan.project_start).days, 1)
    gantt_rows = []
    for house in page_obj.object_list:
        schedule = getattr(house, "schedule", None)
        metrics = _schedule_metrics(house, schedule, stages, total_weight, progress_map, as_of)
        bars = []
        by_stage = {m.stage_id: m for m in schedule.milestones.all()} if schedule else {}
        for stage in stages:
            m = by_stage.get(stage.pk)
            if not m or not m.planned_start or not m.planned_end:
                continue
            left = max(0, min(100, (m.planned_start - plan.project_start).days / total_days * 100))
            width = max(0.5, min(100 - left, ((m.planned_end - m.planned_start).days + 1) / total_days * 100))
            bars.append({"stage": stage, "left": round(left, 3), "width": round(width, 3), "start": m.planned_start, "end": m.planned_end})
        gantt_rows.append({"house": house, "schedule": schedule, "metrics": metrics, "bars": bars})
    islands = House.objects.values("village__municipality__island_id", "village__municipality__island__name").distinct().order_by("village__municipality__island__name")
    months = []
    cursor = date(plan.project_start.year, plan.project_start.month, 1)
    while cursor <= plan.construction_deadline:
        months.append(cursor.strftime("%b %Y"))
        year, month = (cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1)
        cursor = date(year, month, 1)
    return render(request, "scheduling/programme_gantt.html", {
        "plan": plan, "page_obj": page_obj, "gantt_rows": gantt_rows,
        "stages": stages, "islands": islands, "selected_island": island, "q": q,
        "months": months, "month_count": len(months), "as_of": as_of,
    })


@login_required
def house_schedule_edit(request, house_pk):
    _manager_only(request.user)
    house = get_object_or_404(House.objects.select_related("village__municipality__island", "assigned_engineer__user"), pk=house_pk)
    plan = _programme_plan()
    schedule, _created = HouseSchedule.objects.get_or_create(house=house, defaults={"baseline_start": None, "baseline_completion": None})
    active_stages = list(ConstructionStage.objects.filter(is_active=True).order_by("sequence", "name"))
    existing_ids = set(schedule.milestones.values_list("stage_id", flat=True))
    for stage in active_stages:
        if stage.pk not in existing_ids:
            MilestoneSchedule.objects.get_or_create(house_schedule=schedule, stage=stage)

    if request.method == "POST":
        form = HouseScheduleForm(request.POST, instance=schedule)
        formset = MilestoneScheduleFormSet(request.POST, instance=schedule, prefix="milestones")
        if form.is_valid() and formset.is_valid():
            candidate = form.save(commit=False)
            errors = []
            if candidate.baseline_start and candidate.baseline_start < plan.project_start:
                errors.append(f"Baseline start cannot be before programme commencement ({plan.project_start:%d %b %Y}).")
            if candidate.baseline_completion and candidate.baseline_completion > plan.construction_deadline:
                errors.append(f"Baseline construction completion must be on or before {plan.construction_deadline:%d %b %Y}.")
            if candidate.baseline_start and candidate.baseline_completion and candidate.baseline_completion < candidate.baseline_start:
                errors.append("Baseline completion cannot be before baseline start.")
            if candidate.revised_start and candidate.revised_start < plan.project_start:
                errors.append("Revised construction start cannot be before programme commencement.")
            if candidate.revised_completion and candidate.revised_completion > plan.construction_deadline:
                errors.append("Revised construction completion must be on or before the construction deadline.")

            normalized = []
            revised_rows = []
            for milestone_form in formset.forms:
                cleaned = getattr(milestone_form, "cleaned_data", {})
                if not cleaned:
                    continue
                stage = cleaned.get("stage")
                if not stage:
                    continue
                item = dict(cleaned)
                item["stage_id"] = stage.pk
                normalized.append(item)
                # Revised sequence is validated only where revised dates are being used.
                revised_start = cleaned.get("revised_start")
                revised_end = cleaned.get("revised_end")
                if bool(revised_start) != bool(revised_end):
                    milestone_form.add_error("revised_end" if revised_start else "revised_start", "Enter both revised dates, or leave both revised dates blank.")
                revised_rows.append({
                    "stage_id": stage.pk,
                    "revised_start": revised_start or cleaned.get("planned_start"),
                    "revised_end": revised_end or cleaned.get("planned_end"),
                })
                for field_name in ("planned_start", "planned_end", "revised_start", "revised_end"):
                    value = cleaned.get(field_name)
                    if value and value > plan.construction_deadline:
                        milestone_form.add_error(field_name, "Milestone dates must be on or before the construction deadline.")
                    if field_name in ("planned_start", "revised_start") and value and value < plan.project_start:
                        milestone_form.add_error(field_name, "Milestone start cannot be before programme commencement.")
                if candidate.baseline_start and cleaned.get("planned_start") and cleaned["planned_start"] < candidate.baseline_start:
                    milestone_form.add_error("planned_start", "Milestone cannot start before the house baseline start.")
                if candidate.baseline_completion and cleaned.get("planned_end") and cleaned["planned_end"] > candidate.baseline_completion:
                    milestone_form.add_error("planned_end", "Milestone cannot end after the house baseline completion.")
            for error in validate_milestone_sequence(normalized, active_stages, baseline=True):
                form.add_error(None, error)
            # Revised dates may be partially revised; use revised date where supplied and baseline otherwise.
            for error in validate_milestone_sequence(revised_rows, active_stages, baseline=False):
                form.add_error(None, "Revised sequence: " + error)

            if not errors and not any(mf.errors for mf in formset.forms) and not form.non_field_errors():
                with transaction.atomic():
                    candidate.updated_by = request.user
                    candidate.save()
                    formset.save()
                messages.success(request, f"Construction schedule saved for {house.house_id}.")
                return redirect("scheduling:house-schedule-edit", house_pk=house.pk)
            for error in errors:
                form.add_error(None, error)
    else:
        form = HouseScheduleForm(instance=schedule)
        formset = MilestoneScheduleFormSet(instance=schedule, prefix="milestones")

    return render(request, "scheduling/house_schedule_form.html", {
        "house": house, "plan": plan, "form": form, "formset": formset, "stages": active_stages,
    })
