from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_stages(apps, schema_editor):
    Stage = apps.get_model('progress', 'ConstructionStage')
    stages = [
        ('site-preparation', 'Site preparation and clearing', '5.00', 1),
        ('foundation', 'Foundation works', '15.00', 2),
        ('structural-framework', 'Structural framework', '15.00', 3),
        ('wall-construction', 'Wall construction', '15.00', 4),
        ('roofing', 'Roofing', '15.00', 5),
        ('doors-windows', 'Doors and windows', '8.00', 6),
        ('electrical-plumbing', 'Electrical and plumbing', '7.00', 7),
        ('finishing-flooring', 'Finishing and flooring', '10.00', 8),
        ('painting', 'Painting', '5.00', 9),
        ('final-handover', 'Final inspection and handover', '5.00', 10),
    ]
    for code, name, weight, sequence in stages:
        Stage.objects.get_or_create(code=code, defaults={
            'name': name, 'weight': weight, 'sequence': sequence, 'is_active': True,
        })


class Migration(migrations.Migration):
    dependencies = [
        ('progress', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='progressrecord', name='review_status',
            field=models.CharField(choices=[('PENDING', 'Pending review'), ('APPROVED', 'Approved'), ('REJECTED', 'Changes requested')], default='PENDING', max_length=12),
        ),
        migrations.AddField(
            model_name='progressrecord', name='review_comments', field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='progressrecord', name='reviewed_at', field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='progressrecord', name='reviewed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='progress_reviews', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddIndex(
            model_name='progressrecord', index=models.Index(fields=['house', 'stage', 'review_status'], name='progress_pr_house_i_1a1b2f_idx'),
        ),
        migrations.RunPython(seed_stages, migrations.RunPython.noop),
    ]
