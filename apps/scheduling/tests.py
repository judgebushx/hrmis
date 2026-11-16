from datetime import date
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .models import ProgrammePlan


class ProgrammePlanDateValidationTests(SimpleTestCase):
    def make_plan(self, **overrides):
        values = {
            "name": "Test programme",
            "target_houses": 700,
            "project_start": date(2026, 11, 1),
            "project_end": date(2029, 10, 31),
            "construction_deadline": date(2029, 7, 31),
        }
        values.update(overrides)
        return ProgrammePlan(**values)

    def test_agreed_36_month_timeline_is_valid(self):
        self.make_plan().clean()

    def test_rejects_project_end_that_is_not_36_months(self):
        with self.assertRaises(ValidationError):
            self.make_plan(project_end=date(2029, 9, 30)).clean()

    def test_rejects_construction_deadline_with_less_than_three_months_closeout(self):
        with self.assertRaises(ValidationError):
            self.make_plan(construction_deadline=date(2029, 8, 1)).clean()

from types import SimpleNamespace
from .validation import validate_milestone_sequence


class MilestoneSequenceValidationTests(SimpleTestCase):
    def setUp(self):
        self.stages = [
            SimpleNamespace(pk=1, name="Site preparation"),
            SimpleNamespace(pk=2, name="Foundation works"),
            SimpleNamespace(pk=3, name="Structural framework"),
        ]

    def test_accepts_strictly_sequential_milestones(self):
        rows = [
            {"stage_id": 1, "planned_start": date(2026, 11, 1), "planned_end": date(2026, 11, 5)},
            {"stage_id": 2, "planned_start": date(2026, 11, 6), "planned_end": date(2026, 11, 12)},
            {"stage_id": 3, "planned_start": date(2026, 11, 13), "planned_end": date(2026, 11, 20)},
        ]
        self.assertEqual(validate_milestone_sequence(rows, self.stages, baseline=True), [])

    def test_rejects_overlapping_milestones(self):
        rows = [
            {"stage_id": 1, "planned_start": date(2026, 11, 1), "planned_end": date(2026, 11, 8)},
            {"stage_id": 2, "planned_start": date(2026, 11, 7), "planned_end": date(2026, 11, 12)},
            {"stage_id": 3, "planned_start": date(2026, 11, 13), "planned_end": date(2026, 11, 20)},
        ]
        errors = validate_milestone_sequence(rows, self.stages, baseline=True)
        self.assertTrue(any("overlapping" in error for error in errors))

    def test_requires_each_baseline_milestone(self):
        rows = [
            {"stage_id": 1, "planned_start": date(2026, 11, 1), "planned_end": date(2026, 11, 8)},
            {"stage_id": 2, "planned_start": None, "planned_end": None},
        ]
        errors = validate_milestone_sequence(rows, self.stages[:2], baseline=True)
        self.assertTrue(any("baseline start and end dates are required" in error for error in errors))


class PlannedProgressCalculationTests(SimpleTestCase):
    def test_planned_progress_uses_weighted_time_elapsed(self):
        from decimal import Decimal
        from types import SimpleNamespace
        from .views import _planned_percent

        stage = SimpleNamespace(pk=1, weight=Decimal("40.00"))
        second_stage = SimpleNamespace(pk=2, weight=Decimal("60.00"))
        milestone = SimpleNamespace(stage_id=1, planned_start=date(2026, 11, 1), planned_end=date(2026, 11, 11), revised_start=None, revised_end=None, effective_start=date(2026, 11, 1), effective_end=date(2026, 11, 11))
        schedule = SimpleNamespace(milestones=SimpleNamespace(all=lambda: [milestone]))
        # Five elapsed days of a ten-day milestone: half of its 40% weight is planned.
        self.assertEqual(_planned_percent(schedule, [stage, second_stage], Decimal("100.00"), date(2026, 11, 6)), Decimal("20.00"))

    def test_planned_progress_is_zero_before_milestone_start(self):
        from decimal import Decimal
        from types import SimpleNamespace
        from .views import _planned_percent

        stage = SimpleNamespace(pk=1, weight=Decimal("100.00"))
        milestone = SimpleNamespace(stage_id=1, planned_start=date(2026, 11, 10), planned_end=date(2026, 11, 20), revised_start=None, revised_end=None, effective_start=date(2026, 11, 10), effective_end=date(2026, 11, 20))
        schedule = SimpleNamespace(milestones=SimpleNamespace(all=lambda: [milestone]))
        self.assertEqual(_planned_percent(schedule, [stage], Decimal("100.00"), date(2026, 11, 9)), Decimal("0.00"))
