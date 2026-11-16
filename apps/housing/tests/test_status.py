from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import EngineerProfile
from apps.housing.models import House
from apps.housing.services.status import sync_house_reconstruction_status
from apps.locations.models import Island, Municipality, Village
from apps.progress.models import ConstructionStage, ProgressRecord


class HouseStatusSynchronizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ConstructionStage.objects.update(is_active=False)
        cls.user = get_user_model().objects.create_user(username="status-test", password="test")
        cls.profile = EngineerProfile.objects.create(
            user=cls.user, employee_id="STATUS-01", designation="Site Engineer"
        )
        island = Island.objects.create(name="Test Island", code="TST")
        municipality = Municipality.objects.create(name="Test Municipality", island=island)
        village = Village.objects.create(name="Test Village", municipality=municipality)
        cls.house = House.objects.create(
            house_id="TEST-0001", village=village, latitude=Decimal("6.9"),
            longitude=Decimal("158.2"), created_by=cls.user,
        )
        cls.stage = ConstructionStage.objects.create(
            code="foundation", name="Foundation works", weight=Decimal("95"), sequence=1
        )
        cls.final_stage = ConstructionStage.objects.create(
            code="final-handover", name="Final inspection and handover",
            weight=Decimal("5"), sequence=2,
        )

    def submit(self, stage, percentage, review_status):
        return ProgressRecord.objects.create(
            house=self.house, stage=stage, engineer=self.profile,
            percentage=Decimal(percentage), update_date=timezone.now(),
            review_status=review_status,
        )

    def test_pending_submission_does_not_change_status(self):
        self.submit(self.stage, "40", ProgressRecord.ReviewStatus.PENDING)
        old, new = sync_house_reconstruction_status(self.house)
        self.assertEqual((old, new), (House.Status.REGISTERED, House.Status.REGISTERED))
        self.house.refresh_from_db()
        self.assertEqual(self.house.status, House.Status.REGISTERED)

    def test_approved_positive_progress_sets_under_reconstruction(self):
        self.submit(self.stage, "40", ProgressRecord.ReviewStatus.APPROVED)
        old, new = sync_house_reconstruction_status(self.house)
        self.assertEqual((old, new), (House.Status.REGISTERED, House.Status.IN_PROGRESS))
        self.house.refresh_from_db()
        self.assertEqual(self.house.status, House.Status.IN_PROGRESS)

    def test_all_milestones_at_100_including_final_inspection_sets_completed(self):
        self.submit(self.stage, "100", ProgressRecord.ReviewStatus.APPROVED)
        self.submit(self.final_stage, "100", ProgressRecord.ReviewStatus.APPROVED)
        _old, new = sync_house_reconstruction_status(self.house)
        self.assertEqual(new, House.Status.COMPLETED)

    def test_on_hold_is_preserved(self):
        self.house.status = House.Status.ON_HOLD
        self.house.save(update_fields=["status"])
        self.submit(self.stage, "50", ProgressRecord.ReviewStatus.APPROVED)
        _old, new = sync_house_reconstruction_status(self.house)
        self.assertEqual(new, House.Status.ON_HOLD)

    def test_handed_over_is_preserved(self):
        self.house.status = House.Status.HANDED_OVER
        self.house.save(update_fields=["status"])
        self.submit(self.stage, "50", ProgressRecord.ReviewStatus.APPROVED)
        _old, new = sync_house_reconstruction_status(self.house)
        self.assertEqual(new, House.Status.HANDED_OVER)

    def test_changes_requested_submission_does_not_change_status(self):
        self.submit(self.stage, "40", ProgressRecord.ReviewStatus.REJECTED)
        _old, new = sync_house_reconstruction_status(self.house)
        self.assertEqual(new, House.Status.REGISTERED)
