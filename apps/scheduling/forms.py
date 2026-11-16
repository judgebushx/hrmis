from django import forms
from django.forms import inlineformset_factory
from django.db.models import Q

from apps.housing.models import House
from apps.progress.models import ConstructionStage
from .models import HouseSchedule, MilestoneSchedule, ProgrammePlan


class ProgrammePlanForm(forms.ModelForm):
    class Meta:
        model = ProgrammePlan
        fields = ("name", "project_start", "project_end", "construction_deadline")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "project_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "project_end": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "construction_deadline": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("project_start", "project_end", "construction_deadline"):
            self.fields[field].input_formats = ["%Y-%m-%d"]


class HouseScheduleForm(forms.ModelForm):
    class Meta:
        model = HouseSchedule
        fields = ("baseline_start", "baseline_completion", "revised_start", "revised_completion", "planning_notes")
        widgets = {
            "baseline_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "baseline_completion": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "revised_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "revised_completion": forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
            "planning_notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("baseline_start", "baseline_completion", "revised_start", "revised_completion"):
            self.fields[field].input_formats = ["%Y-%m-%d"]
        self.fields["baseline_start"].required = True
        self.fields["baseline_completion"].required = True


class MilestoneScheduleForm(forms.ModelForm):
    class Meta:
        model = MilestoneSchedule
        fields = ("stage", "planned_start", "planned_end", "revised_start", "revised_end", "notes")
        widgets = {
            "stage": forms.HiddenInput(),
            "planned_start": forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}, format="%Y-%m-%d"),
            "planned_end": forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}, format="%Y-%m-%d"),
            "revised_start": forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}, format="%Y-%m-%d"),
            "revised_end": forms.DateInput(attrs={"type": "date", "class": "form-control form-control-sm"}, format="%Y-%m-%d"),
            "notes": forms.TextInput(attrs={"class": "form-control form-control-sm", "placeholder": "Optional note"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active_stages = ConstructionStage.objects.filter(is_active=True)
        if self.instance.pk and self.instance.stage_id:
            self.fields["stage"].queryset = ConstructionStage.objects.filter(Q(is_active=True) | Q(pk=self.instance.stage_id))
        else:
            self.fields["stage"].queryset = active_stages
        for field in ("planned_start", "planned_end", "revised_start", "revised_end"):
            self.fields[field].input_formats = ["%Y-%m-%d"]


MilestoneScheduleFormSet = inlineformset_factory(
    HouseSchedule, MilestoneSchedule, form=MilestoneScheduleForm, extra=0, can_delete=False,
)


class BulkScheduleForm(forms.Form):
    houses = forms.ModelMultipleChoiceField(
        queryset=House.objects.none(),
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "12"}),
        help_text="Only houses without an existing baseline schedule are listed.",
    )
    cohort_start = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d"),
        input_formats=["%Y-%m-%d"],
    )
    houses_per_cohort = forms.IntegerField(min_value=1, max_value=200, initial=25, widget=forms.NumberInput(attrs={"class": "form-control"}))
    cohort_interval_days = forms.IntegerField(min_value=1, max_value=365, initial=20, widget=forms.NumberInput(attrs={"class": "form-control"}), help_text="Days between the start of successive cohorts.")

    DEFAULT_DURATIONS = {
        "site-preparation": 14, "foundation": 45, "structural-framework": 45,
        "wall-construction": 45, "roofing": 35, "doors-windows": 25,
        "electrical-plumbing": 30, "finishing-flooring": 45,
        "painting": 25, "final-handover": 20,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Include unscheduled houses and schedules whose milestone rows are
        # missing/incomplete, allowing repair of earlier bulk-generation runs.
        self.fields["houses"].queryset = House.objects.select_related("village__municipality__island").filter(
            Q(schedule__isnull=True)
            | Q(schedule__baseline_start__isnull=True, schedule__baseline_completion__isnull=True)
            | Q(schedule__milestones__isnull=True)
            | Q(schedule__milestones__planned_start__isnull=True)
            | Q(schedule__milestones__planned_end__isnull=True)
        ).distinct().order_by("house_id")
        self.fields["cohort_start"].input_formats = ["%Y-%m-%d"]
        self.stage_duration_fields = []
        for stage in ConstructionStage.objects.filter(is_active=True).order_by("sequence", "name"):
            field_name = f"duration_{stage.pk}"
            self.fields[field_name] = forms.IntegerField(
                min_value=1, max_value=365,
                initial=self.DEFAULT_DURATIONS.get(stage.code, 30),
                widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "min": "1", "max": "365"}),
                label=f"{stage.name} (days)",
            )
            self.stage_duration_fields.append({"stage": stage, "field": self[field_name]})
