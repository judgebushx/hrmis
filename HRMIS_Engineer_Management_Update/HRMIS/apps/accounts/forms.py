from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import EngineerProfile
from apps.housing.models import House

User = get_user_model()


class EngineerCreateForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-control"}))
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    employee_id = forms.CharField(max_length=50, widget=forms.TextInput(attrs={"class": "form-control"}))
    designation = forms.CharField(max_length=120, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    phone = forms.CharField(max_length=40, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    password1 = forms.CharField(label="Temporary password", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={"class": "form-control"}))

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already in use.")
        return username

    def clean_employee_id(self):
        employee_id = self.cleaned_data["employee_id"].strip()
        if EngineerProfile.objects.filter(employee_id__iexact=employee_id).exists():
            raise ValidationError("This employee ID is already registered.")
        return employee_id

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        if password1:
            candidate = User(
                username=cleaned.get("username", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
                email=cleaned.get("email", ""),
            )
            try:
                validate_password(password1, candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        user = User(
            username=data["username"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data.get("email", ""),
            is_staff=False,
            is_superuser=False,
            is_active=True,
        )
        user.set_password(data["password1"])
        user.save()
        profile = EngineerProfile.objects.create(
            user=user,
            employee_id=data["employee_id"],
            designation=data.get("designation", ""),
            phone=data.get("phone", ""),
            is_active=True,
        )
        return profile


class EngineerUpdateForm(forms.Form):
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))
    employee_id = forms.CharField(max_length=50, widget=forms.TextInput(attrs={"class": "form-control"}))
    designation = forms.CharField(max_length=120, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    phone = forms.CharField(max_length=40, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    is_active = forms.BooleanField(required=False, label="Engineer account active")

    def __init__(self, *args, profile, **kwargs):
        self.profile = profile
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.update({
                "first_name": profile.user.first_name,
                "last_name": profile.user.last_name,
                "email": profile.user.email,
                "employee_id": profile.employee_id,
                "designation": profile.designation,
                "phone": profile.phone,
                "is_active": profile.is_active and profile.user.is_active,
            })

    def clean_employee_id(self):
        employee_id = self.cleaned_data["employee_id"].strip()
        if EngineerProfile.objects.filter(employee_id__iexact=employee_id).exclude(pk=self.profile.pk).exists():
            raise ValidationError("This employee ID is already registered.")
        return employee_id

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        user = self.profile.user
        user.first_name = data["first_name"]
        user.last_name = data["last_name"]
        user.email = data.get("email", "")
        user.is_active = data["is_active"]
        user.is_staff = False
        user.is_superuser = False
        user.save()
        self.profile.employee_id = data["employee_id"]
        self.profile.designation = data.get("designation", "")
        self.profile.phone = data.get("phone", "")
        self.profile.is_active = data["is_active"]
        self.profile.save()
        return self.profile


class EngineerPasswordResetForm(forms.Form):
    password1 = forms.CharField(label="New temporary password", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={"class": "form-control"}))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The passwords do not match.")
        if p1:
            try:
                validate_password(p1, self.user)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self):
        self.user.set_password(self.cleaned_data["password1"])
        self.user.save(update_fields=["password"])
        return self.user


class BulkHouseAssignmentForm(forms.Form):
    engineer = forms.ModelChoiceField(
        queryset=EngineerProfile.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Assign to engineer",
    )
    houses = forms.ModelMultipleChoiceField(
        queryset=House.objects.none(),
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "14"}),
        label="Select houses",
        help_text="Use Ctrl (Windows) or Command (Mac) to select multiple houses.",
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        label="Assignment note",
    )

    def __init__(self, *args, initial_engineer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["engineer"].queryset = EngineerProfile.objects.filter(
            is_active=True, user__is_active=True
        ).select_related("user").order_by("user__last_name", "user__first_name")
        self.fields["engineer"].label_from_instance = lambda p: (
            f"{p.user.get_full_name() or p.user.username} ({p.employee_id})"
        )
        self.fields["houses"].queryset = House.objects.select_related(
            "village__municipality__island", "assigned_engineer__user"
        ).order_by("house_id")
        self.fields["houses"].label_from_instance = lambda h: (
            f"{h.house_id} — {h.village.name}, {h.village.municipality.name}"
            + (f" — currently: {h.assigned_engineer}" if h.assigned_engineer_id else " — unassigned")
        )
        if initial_engineer and not self.is_bound:
            self.fields["engineer"].initial = initial_engineer
