# Initial reconstruction planning and scheduling schema.
import django.db.models.deletion
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models


def seed_programme_plan(apps, schema_editor):
    ProgrammePlan = apps.get_model("scheduling", "ProgrammePlan")
    ProgrammePlan.objects.get_or_create(
        name="IOM Micronesia Housing Reconstruction Programme",
        defaults={
            "target_houses": 700,
            "project_start": "2026-11-01",
            "project_end": "2029-10-31",
            "construction_deadline": "2029-07-31",
        },
    )


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("housing", "0001_initial"),
        ("progress", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="ProgrammePlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="IOM Micronesia Housing Reconstruction Programme", max_length=160)),
                ("target_houses", models.PositiveIntegerField(default=700, validators=[MinValueValidator(1)])),
                ("project_start", models.DateField()),
                ("project_end", models.DateField()),
                ("construction_deadline", models.DateField(help_text="Construction should be complete by this date, leaving time for closeout.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="programme_plans_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["project_start"]},
        ),
        migrations.CreateModel(
            name="HouseSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("baseline_start", models.DateField(blank=True, null=True)),
                ("baseline_completion", models.DateField(blank=True, null=True)),
                ("revised_start", models.DateField(blank=True, null=True)),
                ("revised_completion", models.DateField(blank=True, null=True)),
                ("planning_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("house", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="schedule", to="housing.house")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="house_schedules_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["baseline_start", "house__house_id"]},
        ),
        migrations.CreateModel(
            name="MilestoneSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("planned_start", models.DateField(blank=True, null=True)),
                ("planned_end", models.DateField(blank=True, null=True)),
                ("revised_start", models.DateField(blank=True, null=True)),
                ("revised_end", models.DateField(blank=True, null=True)),
                ("notes", models.CharField(blank=True, max_length=500)),
                ("house_schedule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="milestones", to="scheduling.houseschedule")),
                ("stage", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="house_schedules", to="progress.constructionstage")),
            ],
            options={"ordering": ["stage__sequence", "stage__name"]},
        ),
        migrations.AddConstraint(
            model_name="milestoneschedule",
            constraint=models.UniqueConstraint(fields=("house_schedule", "stage"), name="uniq_house_schedule_stage"),
        ),
        migrations.AddConstraint(
            model_name="milestoneschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(("planned_end__isnull", True), ("planned_start__isnull", True), ("planned_end__gte", models.F("planned_start")), _connector="OR"),
                name="sched_planned_dates_ordered",
            ),
        ),
        migrations.AddConstraint(
            model_name="milestoneschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(("revised_end__isnull", True), ("revised_start__isnull", True), ("revised_end__gte", models.F("revised_start")), _connector="OR"),
                name="sched_revised_dates_ordered",
            ),
        ),
        migrations.RunPython(seed_programme_plan, migrations.RunPython.noop),
    ]
