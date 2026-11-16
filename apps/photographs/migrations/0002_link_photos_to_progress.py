from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('photographs', '0001_initial'),
        ('progress', '0002_progress_review_workflow_and_seed_stages'),
    ]

    operations = [
        migrations.AddField(
            model_name='housephoto', name='progress_record',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='photos', to='progress.progressrecord'),
        ),
    ]
