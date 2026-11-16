from django import forms
from .models import ConstructionStage, ProgressRecord


class ProgressSubmissionForm(forms.ModelForm):
    class Meta:
        model = ProgressRecord
        fields = ["stage", "percentage", "status", "remarks"]
        widgets = {
            "stage": forms.Select(attrs={"class": "form-select"}),
            "percentage": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 100, "step": "0.01"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Describe work completed, quantities, issues or constraints"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].queryset = ConstructionStage.objects.filter(is_active=True)
        self.fields["stage"].empty_label = "Select construction stage"

    def clean(self):
        cleaned = super().clean()
        percentage = cleaned.get("percentage")
        status = cleaned.get("status")
        if percentage is not None and status == ProgressRecord.StageStatus.COMPLETED and percentage != 100:
            self.add_error("percentage", "A completed stage must be recorded as 100%.")
        if percentage is not None and percentage > 0 and status == ProgressRecord.StageStatus.NOT_STARTED:
            self.add_error("status", "Select In progress, Completed or Blocked when progress is above 0%.")
        return cleaned


class ProgressReviewForm(forms.Form):
    decision = forms.ChoiceField(choices=[("APPROVED", "Approve"), ("REJECTED", "Request changes")],
        widget=forms.Select(attrs={"class": "form-select"}))
    review_comments = forms.CharField(required=False, widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == "REJECTED" and not cleaned.get("review_comments", "").strip():
            self.add_error("review_comments", "Explain what needs to be corrected.")
        return cleaned
