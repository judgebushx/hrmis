from django.core.exceptions import ValidationError


def validate_milestone_sequence(rows, stages, baseline=True):
    """Require complete, strictly sequential milestone date ranges in stage order."""
    errors = []
    by_stage = {row.get("stage_id"): row for row in rows if row.get("stage_id")}
    previous = None
    for stage in stages:
        row = by_stage.get(stage.pk)
        if not row:
            errors.append(f"{stage.name}: milestone schedule is missing.")
            continue
        start_key, end_key = (("planned_start", "planned_end") if baseline else ("revised_start", "revised_end"))
        start, end = row.get(start_key), row.get(end_key)
        if baseline and (not start or not end):
            errors.append(f"{stage.name}: baseline start and end dates are required.")
            continue
        if not start and not end:
            continue
        if not start or not end:
            errors.append(f"{stage.name}: enter both start and end dates, or leave both blank.")
            continue
        if end < start:
            errors.append(f"{stage.name}: end date cannot be before start date.")
        if previous and start <= previous:
            errors.append(f"{stage.name}: must start after the previous milestone ends ({previous:%d %b %Y}); overlapping or same-day milestone dates are not permitted.")
        previous = end
    return errors
