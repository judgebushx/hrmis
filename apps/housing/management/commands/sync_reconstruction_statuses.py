from django.core.management.base import BaseCommand
from django.db import transaction

from apps.housing.models import House
from apps.housing.services.status import sync_house_reconstruction_status


class Command(BaseCommand):
    help = (
        "Recalculate automatic house statuses from latest supervisor-approved "
        "construction milestone submissions. ON_HOLD and HANDED_OVER are preserved."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show proposed status changes without saving them.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        changed = 0
        unchanged = 0
        with transaction.atomic():
            houses = House.objects.select_for_update().order_by("house_id")
            for house in houses.iterator():
                old_status, new_status = sync_house_reconstruction_status(
                    house, save=not dry_run
                )
                if old_status != new_status:
                    changed += 1
                    self.stdout.write(
                        f"{house.house_id}: {old_status} -> {new_status}"
                    )
                else:
                    unchanged += 1
            if dry_run:
                transaction.set_rollback(True)

        action = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(
            f"{action} {changed} house status(es); {unchanged} unchanged."
        ))
