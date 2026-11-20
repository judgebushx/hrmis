from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("housing", "0002_house_alternate_contact_house_bedrooms_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="house",
            name="damage_classification",
            field=models.CharField(
                blank=True,
                choices=[
                    ("MINOR", "Minor damage"),
                    ("MODERATE", "Moderate damage"),
                    ("SEVERE", "Severe damage"),
                    ("DESTROYED", "Destroyed"),
                    ("OTHER", "Other"),
                ],
                max_length=100,
            ),
        ),
        migrations.AlterField(
            model_name="house",
            name="reconstruction_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("FULL", "Full reconstruction"),
                    ("PARTIAL", "Partial reconstruction"),
                    ("MAJOR_REHABILITATION", "Major rehabilitation"),
                    ("REPAIR", "Repair / rehabilitation"),
                    ("OTHER", "Other"),
                ],
                max_length=120,
            ),
        ),
    ]
