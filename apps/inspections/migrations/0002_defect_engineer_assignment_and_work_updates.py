import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
        ('inspections', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='defect',
            name='assigned_engineer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_defects',
                to='accounts.engineerprofile',
            ),
        ),
        migrations.AddField(
            model_name='defect',
            name='engineer_update',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='defect',
            name='engineer_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='defect',
            name='rectification_photo',
            field=models.ImageField(blank=True, null=True, upload_to='defect_rectifications/%Y/%m/'),
        ),
        migrations.AlterField(
            model_name='defect',
            name='status',
            field=models.CharField(
                choices=[
                    ('OPEN', 'Open'),
                    ('ACTION', 'Corrective action underway'),
                    ('READY', 'Ready for inspection'),
                    ('VERIFIED', 'Verified closed'),
                ],
                default='OPEN',
                max_length=10,
            ),
        ),
    ]
