from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.housing.models import House, HouseAssignment
from .forms import (
    EngineerCreateForm, EngineerUpdateForm,
    EngineerPasswordResetForm, BulkHouseAssignmentForm,
)
from .models import EngineerProfile


def superuser_required(view_func):
    return user_passes_test(
        lambda user: user.is_authenticated and user.is_superuser
    )(view_func)


@superuser_required
def engineer_list(request):
    profiles = EngineerProfile.objects.select_related("user").annotate(
        current_house_count=Count("current_houses", distinct=True)
    ).order_by("user__last_name", "user__first_name", "employee_id")

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "active")
    if query:
        profiles = profiles.filter(
            Q(employee_id__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(designation__icontains=query)
        )
    if status == "active":
        profiles = profiles.filter(is_active=True, user__is_active=True)
    elif status == "inactive":
        profiles = profiles.filter(Q(is_active=False) | Q(user__is_active=False))

    return render(request, "accounts/engineer_list.html", {
        "engineers": profiles,
        "search": query,
        "selected_status": status,
        "total_engineers": EngineerProfile.objects.count(),
        "active_engineers": EngineerProfile.objects.filter(
            is_active=True, user__is_active=True
        ).count(),
    })


@superuser_required
def engineer_create(request):
    if request.method == "POST":
        form = EngineerCreateForm(request.POST)
        if form.is_valid():
            profile = form.save()
            messages.success(
                request,
                f"Engineer {profile.user.get_full_name()} ({profile.employee_id}) was created. "
                "Share the temporary password securely with the engineer."
            )
            return redirect("accounts:engineer-detail", pk=profile.pk)
    else:
        form = EngineerCreateForm()
    return render(request, "accounts/engineer_form.html", {
        "form": form, "page_title": "Register engineer", "creating": True,
    })


@superuser_required
def engineer_detail(request, pk):
    profile = get_object_or_404(
        EngineerProfile.objects.select_related("user"), pk=pk
    )
    current_houses = House.objects.filter(
        assigned_engineer=profile
    ).select_related("village__municipality__island").order_by("house_id")
    history = HouseAssignment.objects.filter(
        engineer=profile
    ).select_related("house", "assigned_by").order_by("-assigned_at")
    return render(request, "accounts/engineer_detail.html", {
        "engineer": profile,
        "current_houses": current_houses,
        "assignment_history": history,
    })


@superuser_required
def engineer_update(request, pk):
    profile = get_object_or_404(
        EngineerProfile.objects.select_related("user"), pk=pk
    )
    if request.method == "POST":
        form = EngineerUpdateForm(request.POST, profile=profile)
        if form.is_valid():
            if not form.cleaned_data["is_active"] and House.objects.filter(
                assigned_engineer=profile
            ).exists():
                form.add_error(
                    "is_active",
                    "Reassign this engineer's currently assigned houses before deactivating the account."
                )
            else:
                form.save()
                messages.success(request, "Engineer details were updated.")
                return redirect("accounts:engineer-detail", pk=profile.pk)
    else:
        form = EngineerUpdateForm(profile=profile)
    return render(request, "accounts/engineer_form.html", {
        "form": form, "page_title": f"Edit {profile.employee_id}",
        "engineer": profile, "creating": False,
    })


@superuser_required
def engineer_password_reset(request, pk):
    profile = get_object_or_404(EngineerProfile.objects.select_related("user"), pk=pk)
    if request.method == "POST":
        form = EngineerPasswordResetForm(request.POST, user=profile.user)
        if form.is_valid():
            form.save()
            messages.success(request, "The engineer's password has been reset. Share the new temporary password securely.")
            return redirect("accounts:engineer-detail", pk=profile.pk)
    else:
        form = EngineerPasswordResetForm(user=profile.user)
    return render(request, "accounts/engineer_password_reset.html", {
        "form": form, "engineer": profile,
    })


@superuser_required
def bulk_assign_houses(request):
    initial_engineer = request.GET.get("engineer") or None
    if request.method == "POST":
        form = BulkHouseAssignmentForm(request.POST)
        if form.is_valid():
            engineer = form.cleaned_data["engineer"]
            selected_houses = list(form.cleaned_data["houses"])
            reason = form.cleaned_data.get("reason", "").strip()
            changed = 0
            unchanged = 0
            with transaction.atomic():
                for house in House.objects.select_for_update(of=("self",)).filter(
                    pk__in=[item.pk for item in selected_houses]
                ).select_related("assigned_engineer"):
                    if house.assigned_engineer_id == engineer.pk:
                        unchanged += 1
                        continue

                    previous_engineer = house.assigned_engineer
                    HouseAssignment.objects.filter(
                        house=house, ended_at__isnull=True
                    ).update(ended_at=timezone.now())

                    house.assigned_engineer = engineer
                    house.save(update_fields=["assigned_engineer", "updated_at"])

                    HouseAssignment.objects.create(
                        house=house,
                        engineer=engineer,
                        assigned_by=request.user,
                        reason=reason,
                    )

                    from apps.audit.models import AuditEvent
                    AuditEvent.objects.create(
                        user=request.user,
                        house=house,
                        action="HOUSE_ENGINEER_ASSIGNED" if previous_engineer is None else "HOUSE_ENGINEER_REASSIGNED",
                        object_type="HouseAssignment",
                        object_id=str(house.pk),
                        details={
                            "previous_engineer_id": previous_engineer.pk if previous_engineer else None,
                            "new_engineer_id": engineer.pk,
                            "new_employee_id": engineer.employee_id,
                            "reason": reason,
                        },
                    )
                    changed += 1

            messages.success(
                request,
                f"Assignment complete: {changed} house(s) assigned to "
                f"{engineer.user.get_full_name() or engineer.user.username}. "
                f"{unchanged} already had this engineer."
            )
            return redirect("accounts:engineer-detail", pk=engineer.pk)
    else:
        form = BulkHouseAssignmentForm(initial_engineer=initial_engineer)

    return render(request, "accounts/house_assignment_form.html", {
        "form": form,
        "page_title": "Assign houses to an engineer",
    })


@superuser_required
def inspector_list(request):
    from .models import InspectorProfile
    profiles = InspectorProfile.objects.select_related("user").prefetch_related("assigned_houses").order_by("user__last_name", "employee_id")
    return render(request, "accounts/inspector_list.html", {"inspectors": profiles})

@superuser_required
def inspector_create(request):
    from .forms import InspectorCreateForm
    if request.method == "POST":
        form=InspectorCreateForm(request.POST)
        if form.is_valid():
            profile=form.save(); messages.success(request, f"Inspector {profile.employee_id} created and house assignments saved.")
            return redirect("accounts:inspector-list")
    else: form=InspectorCreateForm()
    return render(request, "accounts/inspector_form.html", {"form":form})


@superuser_required
def inspector_list(request):
    from .models import InspectorProfile
    profiles = InspectorProfile.objects.select_related("user").prefetch_related("assigned_houses").order_by("user__last_name", "employee_id")
    return render(request, "accounts/inspector_list.html", {"inspectors": profiles})

@superuser_required
def inspector_create(request):
    from .forms import InspectorCreateForm
    if request.method == "POST":
        form=InspectorCreateForm(request.POST)
        if form.is_valid():
            profile=form.save(); messages.success(request, f"Inspector {profile.employee_id} created and house assignments saved.")
            return redirect("accounts:inspector-list")
    else: form=InspectorCreateForm()
    return render(request, "accounts/inspector_form.html", {"form":form})


@superuser_required
def inspector_update(request, pk):
    from .models import InspectorProfile
    from .forms import InspectorUpdateForm
    profile = get_object_or_404(
        InspectorProfile.objects.select_related("user").prefetch_related("assigned_houses"),
        pk=pk,
    )
    if request.method == "POST":
        form = InspectorUpdateForm(request.POST, profile=profile)
        if form.is_valid():
            form.save()
            messages.success(request, f"Inspector {profile.employee_id} was updated.")
            return redirect("accounts:inspector-list")
    else:
        form = InspectorUpdateForm(profile=profile)
    return render(request, "accounts/inspector_form.html", {
        "form": form, "page_title": f"Edit inspector {profile.employee_id}",
        "is_edit": True, "profile": profile,
    })
