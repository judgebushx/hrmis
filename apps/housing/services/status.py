"""Derive automatic reconstruction status from supervisor-approved progress."""
from decimal import Decimal

from apps.progress.models import ConstructionStage, ProgressRecord
from apps.housing.models import House


def sync_house_reconstruction_status(house, *, save=True):
    """Synchronize a house's automatic status from its latest approved milestones.

    Explicit operational states (ON_HOLD and HANDED_OVER) are preserved.
    Pending and changes-requested submissions are never considered.
    COMPLETED requires every active milestone, including ``final-handover``,
    to have a latest approved submission at 100 percent.

    Returns ``(old_status, new_status)``.
    """
    old_status = house.status

    # These are deliberate management decisions, not progress-derived states.
    if old_status in (House.Status.ON_HOLD, House.Status.HANDED_OVER):
        return old_status, old_status

    stages = list(
        ConstructionStage.objects.filter(is_active=True).order_by("sequence", "pk")
    )
    latest_approved = {}
    approved_records = (
        ProgressRecord.objects.filter(
            house_id=house.pk,
            stage__in=stages,
            review_status=ProgressRecord.ReviewStatus.APPROVED,
        )
        .order_by("stage_id", "-update_date", "-created_at", "-pk")
        .only("id", "stage_id", "percentage", "update_date", "created_at")
    )
    for record in approved_records:
        latest_approved.setdefault(record.stage_id, record)

    has_positive_approved_progress = any(
        record.percentage > Decimal("0") for record in latest_approved.values()
    )

    required_stage_ids = {stage.pk for stage in stages}
    final_stage = next((stage for stage in stages if stage.code == "final-handover"), None)
    all_required_milestones_complete = bool(stages and final_stage) and all(
        stage_id in latest_approved
        and latest_approved[stage_id].percentage >= Decimal("100")
        for stage_id in required_stage_ids
    )

    if all_required_milestones_complete:
        new_status = House.Status.COMPLETED
    elif has_positive_approved_progress:
        new_status = House.Status.IN_PROGRESS
    else:
        new_status = House.Status.REGISTERED

    if save and new_status != old_status:
        house.status = new_status
        house.save(update_fields=["status", "updated_at"])
    elif not save:
        house.status = old_status

    return old_status, new_status
