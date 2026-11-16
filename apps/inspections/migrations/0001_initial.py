import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('housing', '0002_house_alternate_contact_house_bedrooms_and_more'),
        ('progress', '0002_progress_review_workflow_and_seed_stages'),
    ]
    operations = [
        migrations.CreateModel(name='Inspection', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('inspection_date', models.DateField()),
            ('outcome', models.CharField(choices=[('PASS', 'Pass'), ('CONDITIONAL', 'Pass with corrective actions'), ('FAIL', 'Fail – rework required')], max_length=16)),
            ('checklist_responses', models.JSONField(blank=True, default=dict)),
            ('general_comments', models.TextField(blank=True)),
            ('review_status', models.CharField(choices=[('PENDING', 'Pending supervisor review'), ('APPROVED', 'Approved'), ('CHANGES', 'Changes requested')], default='PENDING', max_length=12)),
            ('reviewed_at', models.DateTimeField(blank=True, null=True)),
            ('review_comments', models.TextField(blank=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('house', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='inspections', to='housing.house')),
            ('inspected_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='site_inspections', to=settings.AUTH_USER_MODEL)),
            ('progress_record', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='inspections', to='progress.progressrecord')),
            ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='inspections_reviewed', to=settings.AUTH_USER_MODEL)),
            ('stage', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='inspections', to='progress.constructionstage')),
        ], options={'ordering': ['-inspection_date', '-created_at']}),
        migrations.CreateModel(name='Defect', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('description', models.TextField()),
            ('severity', models.CharField(choices=[('LOW', 'Low'), ('MEDIUM', 'Medium'), ('HIGH', 'High'), ('CRITICAL', 'Critical')], default='MEDIUM', max_length=10)),
            ('corrective_action', models.TextField(blank=True)),
            ('responsible_person', models.CharField(blank=True, max_length=160)),
            ('due_date', models.DateField(blank=True, null=True)),
            ('status', models.CharField(choices=[('OPEN', 'Open'), ('ACTION', 'Corrective action underway'), ('VERIFIED', 'Verified closed')], default='OPEN', max_length=10)),
            ('resolution_notes', models.TextField(blank=True)),
            ('closed_at', models.DateTimeField(blank=True, null=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('inspection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='defects', to='inspections.inspection')),
        ], options={'ordering': ['status', 'due_date', '-created_at']}),
        migrations.AddIndex(model_name='inspection', index=models.Index(fields=['house', 'stage', 'review_status'], name='insp_house_stage_stat_idx')),
    ]
