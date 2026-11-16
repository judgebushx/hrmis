# HRMIS Reconstruction Progress Monitoring Update

This update adds a protected, house-level reconstruction progress workflow to the existing HRMIS Housing Registry and Engineer Management application.

## Included

- Seeded, configurable construction stages and proposed weights (total 100%). The project team should confirm or amend these weights before operational reporting.
- Append-only progress submissions per house and construction stage.
- Engineer submission restricted to houses currently assigned to that engineer.
- Supervisor (Django superuser) review: approve or request changes, with reviewer, timestamp and comments retained.
- Official house progress calculated from the latest approved submission for each active stage; pending/rejected claims do not contribute.
- Multiple original mobile photographs per submission (maximum 10 per update, 10 MB each).
- EXIF GPS validation against the registered house coordinates, with a strict maximum of 15 metres.
- Per-house/per-stage UUID media paths, image SHA-256 checksums, capture timestamp, coordinates and measured distance.
- House-level photo gallery and progress history.
- Audit events for progress submission and supervisor review.
- Development media serving when `DEBUG=True`.
- PostgreSQL-safe `select_for_update(of=("self",))` in bulk engineer assignment.

## Installation

1. Back up the HRMIS project folder and PostgreSQL database.
2. Extract this ZIP into the existing HRMIS project root, allowing files to merge/overwrite.
3. Preserve your existing `.env`, database, and `media/` folder. Do not distribute `.env`.
4. Activate the same Python virtual environment used to run HRMIS.
5. Run:

   ```powershell
   python -m pip install -r requirements.txt
   python manage.py check
   python manage.py migrate
   python manage.py runserver
   ```

The included migrations add review fields and link each photo to its progress submission, and seed the proposed 10 construction stages. Do not delete or recreate existing migrations.

## User workflow

1. Sign in as an engineer and open one of the houses assigned to that account.
2. Select **Reconstruction progress & photos**.
3. Submit a stage, completion percentage, status and remarks.
4. Optionally attach up to 10 original geo-tagged mobile photos. Every selected image must contain GPS EXIF coordinates within 15 metres of the registered house point.
5. A Django superuser opens the same house progress page and selects **Review** on a submission.
6. Approve or request changes. Only the latest approved record per active stage contributes to the official weighted progress percentage.

## Routes

- `/progress/houses/<house-primary-key>/` — house progress, submission history and photo evidence.
- `/progress/reviews/<progress-record-primary-key>/` — superuser review screen.
- The house detail page links to its progress page.
- `/admin/` → Construction stages — configure milestone names, sequence, weights and active status.

## Important operational notes

- The supplied stage weights are a proposed starting configuration, not an approved bill of quantities or engineering standard. Confirm with the reconstruction technical team before using them for donor or management reporting.
- The current reviewer role is restricted to Django superusers. A dedicated supervisor group/permission model can be introduced if required.
- EXIF GPS can be altered or spoofed. The 15-metre check validates the image's embedded coordinates, not cryptographic proof that the engineer was physically present. A later increment can add browser/device live-GPS corroboration and anomaly flags.
- Original image files are retained. Ensure production IIS/web-server configuration serves media securely and backs up the media directory. Do not expose the media directory publicly if the photographs contain sensitive household information; use authenticated media delivery or private object storage for production.
- Test with genuine original geo-tagged images from the target mobile devices. Messaging applications and social platforms may strip EXIF metadata.
- Run a complete access-control test using two engineer accounts, including direct URL attempts against another engineer's house.
