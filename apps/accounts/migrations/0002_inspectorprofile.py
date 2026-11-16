from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ("housing", "0001_initial"), ("accounts", "0001_initial")]
    operations = [migrations.CreateModel(name="InspectorProfile", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("employee_id", models.CharField(max_length=50, unique=True)), ("designation", models.CharField(blank=True, max_length=120)), ("phone", models.CharField(blank=True, max_length=40)), ("is_active", models.BooleanField(default=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="inspector_profile", to=settings.AUTH_USER_MODEL)), ("assigned_houses", models.ManyToManyField(blank=True, related_name="assigned_inspectors", to="housing.house"))])]
