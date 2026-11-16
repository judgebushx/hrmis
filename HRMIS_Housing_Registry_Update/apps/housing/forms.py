from django import forms
from apps.accounts.models import EngineerProfile
from .models import House


class HouseForm(forms.ModelForm):
    assignment_reason = forms.CharField(
        required=False,
        label="Assignment note",
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
        help_text="Optional note recorded when assigning or reassigning an engineer.",
    )

    class Meta:
        model = House
        exclude = ("created_by", "created_at", "updated_at")
        widgets = {
            "house_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "HR-PNI-0001"}),
            "beneficiary_name": forms.TextInput(attrs={"class": "form-control"}),
            "household_reference": forms.TextInput(attrs={"class": "form-control"}),
            "beneficiary_contact": forms.TextInput(attrs={"class": "form-control"}),
            "alternate_contact": forms.TextInput(attrs={"class": "form-control"}),
            "household_size": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "village": forms.Select(attrs={"class": "form-select"}),
            "community": forms.TextInput(attrs={"class": "form-control"}),
            "address_details": forms.TextInput(attrs={"class": "form-control"}),
            "latitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.0000001"}),
            "longitude": forms.NumberInput(attrs={"class": "form-control", "step": "0.0000001"}),
            "house_type": forms.TextInput(attrs={"class": "form-control"}),
            "bedrooms": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "damage_classification": forms.TextInput(attrs={"class": "form-control"}),
            "reconstruction_type": forms.TextInput(attrs={"class": "form-control"}),
            "contractor": forms.TextInput(attrs={"class": "form-control"}),
            "assigned_engineer": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["village"].queryset = self.fields["village"].queryset.select_related("municipality__island").order_by(
            "municipality__island__name", "municipality__name", "name"
        )
        self.fields["village"].label_from_instance = lambda obj: (
            f"{obj.name} — {obj.municipality.name}, {obj.municipality.island.name}"
        )
        self.fields["assigned_engineer"].queryset = EngineerProfile.objects.filter(
            is_active=True, user__is_active=True
        ).select_related("user").order_by("user__first_name", "user__last_name", "employee_id")
        self.fields["assigned_engineer"].required = False
        self.fields["assignment_reason"].required = False
