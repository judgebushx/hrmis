from django import forms
from apps.progress.models import ConstructionStage, ProgressRecord
from apps.accounts.models import EngineerProfile
from .models import Inspection, Defect

CHECKLISTS = {
    "site-preparation": ["Site boundaries and layout follow approved plan", "Vegetation, debris and unsuitable material cleared", "Site access and drainage arrangements are adequate", "Work area is safe and hazards are controlled"],
    "foundation": ["Excavation dimensions and depth match approved design", "Soil bearing condition is acceptable", "Reinforcement size, spacing and cover are correct", "Formwork and levels are correct before concrete", "Concrete placement and curing are satisfactory"],
    "structural-framework": ["Structural members match approved drawings", "Reinforcement and connections are correctly installed", "Columns, beams and frame are plumb and aligned", "Concrete/connection workmanship is acceptable"],
    "wall-construction": ["Wall materials and dimensions meet specification", "Walls are plumb, level and properly bonded", "Openings and lintels are correctly positioned", "Wall ties and reinforcement are installed where required"],
    "roofing": ["Roof framing and connections are secure", "Roof covering is correctly fixed", "Flashing, ridge and penetrations are weatherproof", "Roof drainage and overhangs are adequate"],
    "doors-windows": ["Doors and windows match approved schedule", "Frames are securely fixed and aligned", "Opening, closing and locking operate correctly", "Seals and weatherproofing are satisfactory"],
    "electrical-plumbing": ["Electrical installation follows approved layout and safety requirements", "Cables, outlets and protective devices are correctly installed", "Water supply and drainage connections are correctly installed", "Leakage and functional tests are satisfactory"],
    "finishing-flooring": ["Floor substrate is sound and level", "Floor finish is properly installed", "Internal finishes meet agreed specification", "Fixtures and fittings are secure and functional"],
    "painting": ["Surface preparation is adequate", "Primer and paint coats are complete", "Coverage and finish are even and free of major defects", "Specified colours and materials are used"],
    "final-handover": ["All approved construction scope is complete", "Building is safe, clean and fit for intended occupancy", "Utilities and fixtures have been functionally tested", "Outstanding defects are resolved or formally recorded", "Beneficiary orientation and handover documentation are complete"],
}

class InspectionForm(forms.ModelForm):
    class Meta:
        model = Inspection
        fields = ["stage", "progress_record", "inspection_date", "outcome", "general_comments"]
        widgets = {"inspection_date": forms.DateInput(attrs={"type": "date"}), "general_comments": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        self.house = kwargs.pop("house", None)
        super().__init__(*args, **kwargs)
        self.fields["stage"].queryset = ConstructionStage.objects.filter(is_active=True)
        if self.house:
            self.fields["progress_record"].queryset = ProgressRecord.objects.filter(house=self.house).order_by("-update_date")
        else:
            self.fields["progress_record"].queryset = ProgressRecord.objects.none()
        stage_id = self.data.get("stage") or self.initial.get("stage")
        stage = ConstructionStage.objects.filter(pk=stage_id).first() if stage_id else None
        self.checklist = CHECKLISTS.get(stage.code, []) if stage else []
        for i, label in enumerate(self.checklist):
            self.fields[f"check_{i}"] = forms.ChoiceField(label=label, choices=[("PASS", "Pass"), ("FAIL", "Fail"), ("NA", "Not applicable")], widget=forms.RadioSelect, required=True)

    def checklist_data(self):
        return {label: self.cleaned_data[f"check_{i}"] for i, label in enumerate(self.checklist)}

class DefectForm(forms.ModelForm):
    class Meta:
        model = Defect
        fields = ["description", "severity", "corrective_action", "assigned_engineer", "due_date"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2, "class": "form-control"}), "corrective_action": forms.Textarea(attrs={"rows": 2, "class": "form-control"}), "due_date": forms.DateInput(attrs={"type": "date", "class": "form-control"})}

    def __init__(self, *args, house=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.house = house
        self.fields["assigned_engineer"].queryset = EngineerProfile.objects.filter(
            is_active=True, user__is_active=True
        ).select_related("user").order_by("user__last_name", "user__first_name")
        self.fields["assigned_engineer"].required = True
        self.fields["assigned_engineer"].label_from_instance = lambda p: (
            f"{p.user.get_full_name() or p.user.username} ({p.employee_id})"
        )
        self.fields["assigned_engineer"].widget.attrs.update({"class": "form-select"})
        if house and house.assigned_engineer_id:
            self.fields["assigned_engineer"].queryset = self.fields["assigned_engineer"].queryset.filter(pk=house.assigned_engineer_id)
            if not self.is_bound:
                self.initial["assigned_engineer"] = house.assigned_engineer_id
        else:
            self.fields["assigned_engineer"].queryset = EngineerProfile.objects.none()

class DefectUpdateForm(forms.ModelForm):
    class Meta:
        model = Defect
        fields = ["severity", "corrective_action", "assigned_engineer", "due_date", "status", "resolution_notes"]

    def __init__(self, *args, house=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_engineer"].queryset = EngineerProfile.objects.filter(is_active=True, user__is_active=True).select_related("user")
        if house and house.assigned_engineer_id:
            self.fields["assigned_engineer"].queryset = self.fields["assigned_engineer"].queryset.filter(pk=house.assigned_engineer_id)
        else:
            self.fields["assigned_engineer"].queryset = EngineerProfile.objects.none()
        self.fields["assigned_engineer"].widget.attrs.update({"class": "form-select"})


class EngineerDefectWorkForm(forms.ModelForm):
    class Meta:
        model = Defect
        fields = ["status", "engineer_update", "rectification_photo"]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
            "engineer_update": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "rectification_photo": forms.ClearableFileInput(attrs={"class": "form-control", "accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (Defect.Status.ACTION, Defect.Status.ACTION.label),
            (Defect.Status.READY, Defect.Status.READY.label),
        ]
        self.fields["engineer_update"].label = "Work undertaken / progress update"
        self.fields["rectification_photo"].label = "Rectification photo (optional)"
