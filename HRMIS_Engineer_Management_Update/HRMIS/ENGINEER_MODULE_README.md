# HRMIS Engineer Management & House Assignment Update

This update adds a superuser-only engineer management workflow to the existing HRMIS project.

## Features

- Register engineer user accounts and linked `EngineerProfile` records.
- Edit engineer employment/contact details and activate/deactivate accounts.
- Reset engineer passwords.
- Search and filter engineer accounts.
- View current house assignments and assignment history.
- Assign multiple houses to one engineer in a single transaction.
- Reassign houses while closing the previous assignment record.
- Record assignment actions in `AuditEvent`.
- Add an Engineer Management link to the housing registry.

## Installation

1. Back up your current HRMIS project folder and PostgreSQL database.
2. Before replacing `config/settings.py`, copy your existing local database settings into a local `.env` file in the same folder as `manage.py`. Use `.env.example` as the structure. Do not share `.env`.
3. Extract this update over the existing project folder, preserving your existing `.env`, database, media files and migration files.
4. Activate the same virtual environment used by the existing HRMIS installation.
5. Run:

   ```powershell
   python manage.py check
   python manage.py makemigrations --check --dry-run
   python manage.py migrate
   python manage.py runserver
   ```

No database model changes are included in this update, so no new migrations should be necessary.

## Where to find it

Sign in as a Django superuser and open the Housing Registry. Select **Manage engineers**.

Routes:
- `/management/engineers/`
- `/management/engineers/new/`
- `/management/engineers/assign-houses/`

Only superusers can access these management views.

## Assignment behaviour

- A house can have one current assigned engineer.
- Assigning the same engineer again does not create a duplicate history row.
- Reassigning a house closes the previous open `HouseAssignment` and creates a new history row.
- The house's `assigned_engineer` field is updated in the same database transaction.
- An engineer cannot be deactivated while houses remain assigned; reassign those houses first.
- Engineers are ordinary non-staff Django users and cannot access Django Admin.
- Existing house-level access filtering remains in place: engineers see only houses currently assigned to their active profile.

## Security note

The project settings now read database credentials and the Django secret key from environment variables. Keep `.env` out of source control and distribution archives. If database credentials were previously shared in a project archive, rotate the database password and update the local `.env`.
