from decimal import Decimal, InvalidOperation
from openpyxl import load_workbook
from django.db import transaction
from apps.accounts.models import EngineerProfile
from apps.locations.models import Island, Municipality, Village
from apps.housing.models import House, HouseAssignment

REQUIRED_HEADERS = ("house_id", "island", "municipality", "village", "latitude", "longitude")
OPTIONAL_HEADERS = (
    "beneficiary_name", "household_reference", "beneficiary_contact", "alternate_contact",
    "household_size", "community", "address_details", "house_type", "bedrooms",
    "damage_classification", "reconstruction_type", "contractor",
    "assigned_engineer_employee_id", "notes",
)
ALL_HEADERS = REQUIRED_HEADERS + OPTIONAL_HEADERS


def _text(value):
    return "" if value is None else str(value).strip()


def _decimal(value, field, row_number, errors, minimum, maximum):
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number < minimum or number > maximum:
            raise InvalidOperation
        return number
    except (InvalidOperation, AttributeError, ValueError):
        errors.append(f"Row {row_number}: {field} must be a valid number between {minimum} and {maximum}.")
        return None


def import_houses_from_workbook(uploaded_file, user):
    """Validate the entire workbook, then import all rows atomically if error-free."""
    workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
    if "Houses" not in workbook.sheetnames:
        return {"created": 0, "errors": ["The workbook must contain a worksheet named 'Houses'."]}

    sheet = workbook["Houses"]
    rows = sheet.iter_rows(values_only=True)
    raw_headers = next(rows, None)
    if not raw_headers:
        return {"created": 0, "errors": ["The Houses worksheet is empty."]}

    headers = [_text(item).lower() for item in raw_headers]
    missing = [name for name in REQUIRED_HEADERS if name not in headers]
    if missing:
        return {"created": 0, "errors": ["Missing required columns: " + ", ".join(missing)]}

    errors, prepared, seen_ids = [], [], set()
    for row_number, values in enumerate(rows, start=2):
        data = {headers[i]: values[i] if i < len(values) else None for i in range(len(headers))}
        if not any(value not in (None, "") for value in data.values()):
            continue

        house_id = _text(data.get("house_id"))
        if not house_id:
            errors.append(f"Row {row_number}: house_id is required.")
        elif house_id in seen_ids or House.objects.filter(house_id=house_id).exists():
            errors.append(f"Row {row_number}: House ID '{house_id}' is duplicated or already exists.")
        seen_ids.add(house_id)

        island_name = _text(data.get("island"))
        municipality_name = _text(data.get("municipality"))
        village_name = _text(data.get("village"))
        island = Island.objects.filter(name__iexact=island_name).first()
        municipality = Municipality.objects.filter(island=island, name__iexact=municipality_name).first() if island else None
        village = Village.objects.filter(municipality=municipality, name__iexact=village_name).first() if municipality else None
        if not island:
            errors.append(f"Row {row_number}: Island '{island_name}' was not found. Create it in Location Administration first.")
        elif not municipality:
            errors.append(f"Row {row_number}: Municipality '{municipality_name}' was not found under {island_name}.")
        elif not village:
            errors.append(f"Row {row_number}: Village '{village_name}' was not found under {municipality_name}, {island_name}.")

        latitude = _decimal(data.get("latitude"), "latitude", row_number, errors, Decimal("-90"), Decimal("90"))
        longitude = _decimal(data.get("longitude"), "longitude", row_number, errors, Decimal("-180"), Decimal("180"))

        def optional_int(key):
            value = data.get(key)
            if value in (None, ""):
                return None
            try:
                number = int(value)
                if number < 0:
                    raise ValueError
                return number
            except (TypeError, ValueError):
                errors.append(f"Row {row_number}: {key} must be a non-negative whole number.")
                return None

        engineer_id = _text(data.get("assigned_engineer_employee_id"))
        engineer = None
        if engineer_id:
            engineer = EngineerProfile.objects.filter(employee_id=engineer_id, is_active=True, user__is_active=True).first()
            if not engineer:
                errors.append(f"Row {row_number}: active engineer employee ID '{engineer_id}' was not found.")

        damage_classification = _text(data.get("damage_classification"))
        reconstruction_type = _text(data.get("reconstruction_type"))
        valid_damage = {value for value, _label in House.DamageClassification.choices}
        valid_reconstruction = {value for value, _label in House.ReconstructionType.choices}
        if damage_classification and damage_classification not in valid_damage:
            errors.append(
                f"Row {row_number}: damage_classification must be one of: "
                + ", ".join(valid_damage) + "."
            )
        if reconstruction_type and reconstruction_type not in valid_reconstruction:
            errors.append(
                f"Row {row_number}: reconstruction_type must be one of: "
                + ", ".join(valid_reconstruction) + "."
            )

        prepared.append({
            "row_number": row_number, "house_id": house_id, "village": village,
            "latitude": latitude, "longitude": longitude, "assigned_engineer": engineer,
            "beneficiary_name": _text(data.get("beneficiary_name")),
            "household_reference": _text(data.get("household_reference")),
            "beneficiary_contact": _text(data.get("beneficiary_contact")),
            "alternate_contact": _text(data.get("alternate_contact")),
            "household_size": optional_int("household_size"),
            "community": _text(data.get("community")),
            "address_details": _text(data.get("address_details")),
            "house_type": _text(data.get("house_type")),
            "bedrooms": optional_int("bedrooms"),
            "damage_classification": damage_classification,
            "reconstruction_type": reconstruction_type,
            "contractor": _text(data.get("contractor")),
            "notes": _text(data.get("notes")),
        })

    workbook.close()
    if errors:
        return {"created": 0, "errors": errors}

    created = 0
    with transaction.atomic():
        for item in prepared:
            engineer = item.pop("assigned_engineer")
            item.pop("row_number")
            house = House.objects.create(created_by=user, assigned_engineer=engineer, **item)
            if engineer:
                HouseAssignment.objects.create(
                    house=house, engineer=engineer, assigned_by=user,
                    reason="Initial assignment during housing register import.",
                )
            created += 1
    return {"created": created, "errors": []}
