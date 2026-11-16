# HRMIS – Housing Reconstruction Monitoring Information System

Django/PostgreSQL application for house-level monitoring of the IOM Micronesia housing reconstruction programme.

## Current capabilities
- FSM Island → Municipality → Village location hierarchy.
- House registry with unique House ID, beneficiary/project details and registered GPS coordinates.
- Excel bulk import and interactive Leaflet house map.
- Engineer profiles, account administration, bulk house assignment and assignment history.
- Engineer access limited to currently assigned houses; superusers can access the full registry.
- Configurable construction milestones and weighted progress submissions.
- Append-only engineer progress updates with supervisor approval/request-changes workflow.
- Original geo-tagged photographic evidence linked to house, milestone and progress submission.
- EXIF GPS proximity check against the registered house coordinates (maximum 15 metres).
- Audit events for engineer assignments and progress submission/review.

## Local setup
1. Create/activate a Python virtual environment.
2. Install requirements: `python -m pip install -r requirements.txt`.
3. Create `.env` from `.env.example` and set the database credentials and secret key.
4. Run `python manage.py migrate`.
5. Create a superuser if one does not already exist: `python manage.py createsuperuser`.
6. Run `python manage.py runserver`.

## Progress workflow
Engineers open a house assigned to them and select **Reconstruction progress & photos**. Each submission is retained as a new record and can include multiple original geo-tagged images. A Django superuser reviews the submission. Only the latest approved submission for each active milestone contributes to the official weighted progress calculation.

The 10 milestone weights included in the migration are proposed defaults and must be confirmed by the reconstruction technical team before operational use.

## Production considerations
This is a development increment. Before production deployment, complete role-based supervisor permissions, security review, authenticated/private media delivery, antivirus scanning, image retention policy, backups, automated tests and deployment configuration. EXIF metadata can be spoofed; the GPS distance rule is a proximity check, not cryptographic proof of physical presence.


## Programme Management Dashboard
- Superuser-only programme-wide dashboard at `/management/dashboard/`.
- 700-house target coverage, verified programme progress, house status, pending reviews and photo GPS quality indicators.
- Interactive clustered house map, filtered by island and house status, with links to house records.
- Charts for house status, island distribution, milestone completion and engineer workload/performance.
- Island, municipality, milestone, engineer and house-level summary tables.
- Excel export (`Programme Summary`, `House Register`, `Engineer Performance`, `Milestone Performance` worksheets).
- Progress calculations use the latest supervisor-approved submission per active milestone. Pending and changes-requested submissions are excluded from verified progress.
- The dashboard does not infer schedule delays because the current House model does not contain approved baseline start/end dates or milestone due dates. It instead reports on-hold houses, pending reviews, blocked latest milestone reports and houses without approved progress.
- The 700-house target is currently configured as a constant in `apps/dashboard/views.py` (`PROGRAMME_TARGET`) and can be changed there if the approved programme target changes.

Dashboard access currently follows the existing HRMIS security model: superusers only. A separate programme-manager/supervisor role should be introduced before granting dashboard access to non-superuser accounts.
