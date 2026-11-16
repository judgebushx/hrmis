# HRMIS – Housing Reconstruction Monitoring Information System

Starter foundation for the IOM Micronesia 700-house reconstruction monitoring application.

## Included in this first increment
- Django project configuration for Django 6.1 and PostgreSQL.
- Engineer profiles linked to Django users.
- FSM location hierarchy: Island → Municipality → Village.
- House registry with registered latitude/longitude and current engineer.
- Historical house assignment records.
- Engineer queryset restriction: engineers see only their currently assigned houses; superusers see all houses.
- Superuser-only house CRUD in Django admin.
- Construction stages and append-only progress history model.
- House-linked photo model and unique house/stage media paths.
- EXIF GPS extraction and 15-metre Haversine validation service.
- Basic login, house list and house detail pages.

## Important implementation notes
- This is a development starter, not a production-ready deployment. Add tests, CSRF/security review, upload limits, antivirus scanning, backup policy and production storage configuration before deployment.
- The photo validation service is provided in `apps/photographs/validators.py`. The next increment should wire it into a protected upload form/view and add automated tests using real geotagged test images.
- Only original images with usable EXIF GPS are accepted by the validation service. Do not strip EXIF before validation.
- The current house-list/detail pages enforce engineer visibility. Any future progress, photo, API or export endpoint must use the same `accessible_houses()` / `can_access_house()` checks.
- Superuser-only CRUD is enforced in Django admin for the House model. Engineers should update progress and upload evidence through dedicated application views, not Django admin.
- The 15-metre threshold is defined centrally as `MAX_DISTANCE_METRES`.
- GPS EXIF can be edited or spoofed. The check establishes coordinate proximity, not cryptographic proof of physical presence. Consider collecting live browser GPS as an additional signal in a later increment.

## Local setup (Windows PowerShell)
1. Create and activate a virtual environment:
   `py -3.12 -m venv .venv`
   `.venv\Scripts\Activate.ps1`
2. Install dependencies:
   `python -m pip install --upgrade pip`
   `pip install -r requirements.txt`
3. Create a PostgreSQL database named `hrmis` and copy `.env.example` to `.env`; update credentials.
4. Run:
   `python manage.py check`
   `python manage.py makemigrations accounts locations housing progress photographs audit`
   `python manage.py migrate`
   `python manage.py createsuperuser`
   `python manage.py runserver`
5. Open `http://127.0.0.1:8000/admin/` and create Island, Municipality, Village, EngineerProfile and House records. Create Django users first, then link engineer profiles.

## Next development increment
Build controlled admin workflows for location setup, engineer onboarding, house registration and assignment/reassignment, then implement the protected progress and photo upload workflows with tests.
