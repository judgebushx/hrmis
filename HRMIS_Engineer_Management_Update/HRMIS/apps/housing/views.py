from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db.models import Q
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .access import accessible_houses
from .forms import HouseForm
from .models import House, HouseAssignment
from .services.excel_import import ALL_HEADERS, import_houses_from_workbook


def superuser_required(view_func):
    return user_passes_test(lambda user: user.is_authenticated and user.is_superuser)(view_func)


@login_required
def house_list(request):
    houses = accessible_houses(request.user)
    search = request.GET.get("q", "").strip()
    island = request.GET.get("island", "").strip()
    status = request.GET.get("status", "").strip()
    if search:
        houses = houses.filter(Q(house_id__icontains=search) | Q(beneficiary_name__icontains=search))
    if island:
        houses = houses.filter(village__municipality__island_id=island)
    if status:
        houses = houses.filter(status=status)
    paginator = Paginator(houses.distinct(), 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    islands = []
    if request.user.is_superuser:
        from apps.locations.models import Island
        islands = Island.objects.order_by("name")
    map_points = [
        {"id": h.house_id, "lat": float(h.latitude), "lon": float(h.longitude), "status": h.get_status_display(), "url": f"/houses/{h.pk}/"}
        for h in page_obj.object_list
    ]
    context = {
        "page_obj": page_obj, "houses": page_obj.object_list, "search": search,
        "selected_island": island, "selected_status": status, "islands": islands,
        "statuses": House.Status.choices, "total_houses": accessible_houses(request.user).count(),
        "assigned_count": accessible_houses(request.user).filter(assigned_engineer__isnull=False).count(),
        "unassigned_count": accessible_houses(request.user).filter(assigned_engineer__isnull=True).count(),
        "map_points": map_points,
    }
    return render(request, "housing/house_list.html", context)


@login_required
def house_detail(request, pk):
    house = get_object_or_404(
        House.objects.select_related("village__municipality__island", "assigned_engineer__user"), pk=pk
    )
    if not accessible_houses(request.user).filter(pk=house.pk).exists():
        raise PermissionDenied("You are not assigned to this house.")
    return render(request, "housing/house_detail.html", {"house": house})


@superuser_required
def house_create(request):
    if request.method == "POST":
        form = HouseForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                house = form.save(commit=False)
                house.created_by = request.user
                house.save()
                if house.assigned_engineer:
                    HouseAssignment.objects.create(
                        house=house, engineer=house.assigned_engineer,
                        assigned_by=request.user,
                        reason=form.cleaned_data.get("assignment_reason", ""),
                    )
            messages.success(request, f"House {house.house_id} was registered.")
            return redirect("housing:house-detail", pk=house.pk)
    else:
        form = HouseForm()
    return render(request, "housing/house_form.html", {"form": form, "page_title": "Register a house"})


@superuser_required
def house_update(request, pk):
    house = get_object_or_404(House, pk=pk)
    previous_engineer = house.assigned_engineer
    if request.method == "POST":
        form = HouseForm(request.POST, instance=house)
        if form.is_valid():
            with transaction.atomic():
                updated = form.save()
                new_engineer = updated.assigned_engineer
                if previous_engineer != new_engineer:
                    HouseAssignment.objects.filter(house=house, ended_at__isnull=True).update(ended_at=timezone.now())
                    if new_engineer:
                        HouseAssignment.objects.create(
                            house=house, engineer=new_engineer, assigned_by=request.user,
                            reason=form.cleaned_data.get("assignment_reason", ""),
                        )
            messages.success(request, f"House {house.house_id} was updated.")
            return redirect("housing:house-detail", pk=house.pk)
    else:
        form = HouseForm(instance=house)
    return render(request, "housing/house_form.html", {"form": form, "house": house, "page_title": f"Edit {house.house_id}"})


@superuser_required
def house_delete(request, pk):
    house = get_object_or_404(House, pk=pk)
    if request.method == "POST":
        house_id = house.house_id
        try:
            house.delete()
            messages.success(request, f"House {house_id} was deleted.")
        except Exception:
            messages.error(request, "This house has linked records and cannot be deleted. Consider changing its status instead.")
        return redirect("housing:house-list")
    return render(request, "housing/house_confirm_delete.html", {"house": house})


@superuser_required
def download_import_template(request):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Houses"
    sheet.append(list(ALL_HEADERS))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(ALL_HEADERS))}1"
    from openpyxl.worksheet.datavalidation import DataValidation
    lat_col = get_column_letter(ALL_HEADERS.index("latitude") + 1)
    lon_col = get_column_letter(ALL_HEADERS.index("longitude") + 1)
    lat_validation = DataValidation(type="decimal", operator="between", formula1="-90", formula2="90", allow_blank=False)
    lon_validation = DataValidation(type="decimal", operator="between", formula1="-180", formula2="180", allow_blank=False)
    sheet.add_data_validation(lat_validation)
    sheet.add_data_validation(lon_validation)
    lat_validation.add(f"{lat_col}2:{lat_col}1001")
    lon_validation.add(f"{lon_col}2:{lon_col}1001")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="174A7E")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[1].height = 32
    widths = {
        "house_id": 20, "beneficiary_name": 28, "household_reference": 20,
        "beneficiary_contact": 20, "alternate_contact": 20, "household_size": 15,
        "island": 18, "municipality": 22, "village": 24, "community": 22,
        "address_details": 30, "latitude": 16, "longitude": 16,
        "house_type": 20, "bedrooms": 12, "damage_classification": 24,
        "reconstruction_type": 24, "contractor": 24,
        "assigned_engineer_employee_id": 28, "notes": 32,
    }
    for index, header in enumerate(ALL_HEADERS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = widths.get(header, 20)
    instructions = workbook.create_sheet("Instructions")
    guidance = [
        ["HRMIS Housing Register Import Template"],
        ["Complete one row per house on the Houses worksheet. Do not rename the worksheet or column headers."],
        ["Required columns: house_id, island, municipality, village, latitude, longitude."],
        ["House IDs must be unique. Suggested format: HR-PNI-0001, HR-CHK-0001, HR-YAP-0001, HR-KSA-0001."],
        ["Island, municipality and village names must match records already configured in HRMIS Location Administration."],
        ["Latitude must be between -90 and 90; longitude must be between -180 and 180. Use decimal degrees."],
        ["Optional fields may be left blank. Phone numbers should be entered as text to preserve leading zeros and + signs."],
        ["assigned_engineer_employee_id is optional and must match an active engineer's Employee ID in HRMIS."],
        ["The import is all-or-nothing: if any row has an error, no houses will be imported. Correct the errors and upload again."],
        ["Do not include beneficiary sensitive information that is not necessary for reconstruction monitoring."],
    ]
    for row in guidance:
        instructions.append(row)
    instructions.column_dimensions["A"].width = 115
    for cell in instructions[1]:
        cell.font = Font(bold=True, size=14, color="174A7E")
    for row in instructions.iter_rows(min_row=2):
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="HRMIS_Housing_Import_Template.xlsx"'
    workbook.save(response)
    return response


@superuser_required
def import_houses(request):
    result = None
    if request.method == "POST":
        uploaded_file = request.FILES.get("workbook")
        if not uploaded_file:
            messages.error(request, "Select an Excel workbook to upload.")
        elif not uploaded_file.name.lower().endswith(".xlsx"):
            messages.error(request, "Only .xlsx Excel workbooks are supported.")
        elif uploaded_file.size > 10 * 1024 * 1024:
            messages.error(request, "The workbook exceeds the 10 MB upload limit.")
        else:
            try:
                result = import_houses_from_workbook(uploaded_file, request.user)
                if result["errors"]:
                    messages.error(request, f"Import stopped: {len(result['errors'])} issue(s) found. No houses were imported.")
                else:
                    messages.success(request, f"Successfully imported {result['created']} house(s).")
            except Exception as exc:
                messages.error(request, f"The workbook could not be processed: {exc}")
    return render(request, "housing/house_import.html", {"result": result})
