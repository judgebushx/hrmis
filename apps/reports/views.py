import os
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.staticfiles import finders
from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.housing.models import House
from apps.inspections.models import Defect, Inspection
from apps.locations.models import Island
from apps.progress.models import ConstructionStage, ProgressRecord

from .pdf_reports import AUDIENCES, build_report_pdf

TARGET_HOUSES = 700
STALE_DAYS = 30
LOGO_STATIC_PATH = 'hrmis/images/iom-logo-hd.jpg'

# category -> (issue wording, priority, suggested follow-up).  Wording matches the earlier version of the report.
EXCEPTION_CATEGORIES = {
    'ON_HOLD': ('On hold', 'HIGH', 'Confirm hold reason and recovery plan'),
    'INSPECTION_FAILED': ('Inspection failed \u2013 corrective work required', 'HIGH',
                          'Resolve inspection findings and arrange reinspection'),
    'DEFECT_OVERDUE': ('Overdue defect corrective action', 'HIGH',
                       'Assigned engineer to complete corrective action; inspector to verify'),
    'STALE': ('No approved update in over 30 days', 'MEDIUM', 'Request site update and confirm next milestone'),
    'CHANGES': ('Progress submission requires changes', 'MEDIUM',
                'Engineer to address supervisor comments and resubmit progress'),
    'INSPECTION_REVIEW': ('Inspection awaiting supervisor review', 'MEDIUM', 'Supervisor to review inspection'),
}
PRIORITY_ORDER = {'HIGH': 0, 'MEDIUM': 1}
CATEGORY_RANK = {code: i for i, code in enumerate(EXCEPTION_CATEGORIES)}


def _manager(user):
    return user.is_authenticated and user.is_superuser


def _period(request):
    today = timezone.localdate()
    kind = request.GET.get('period', 'weekly')
    if kind == 'monthly':
        start, end = today.replace(day=1), today
    elif kind == 'custom':
        try:
            start = date.fromisoformat(request.GET.get('start', ''))
            end = date.fromisoformat(request.GET.get('end', ''))
        except (TypeError, ValueError):
            start, end = today - timedelta(days=6), today
        if end < start:
            start, end = end, start
    else:
        kind = 'weekly'
        start, end = today - timedelta(days=6), today
    return kind, start, end


def _trend(period_updates, start, end):
    """Submitted vs approved progress updates per day (or per week for long periods)."""
    span = (end - start).days + 1
    weekly = span > 31
    buckets = ((span + 6) // 7) if weekly else span
    submitted, approved = [0] * buckets, [0] * buckets
    rows = (period_updates.annotate(d=TruncDate('update_date')).order_by()
            .values('d', 'review_status').annotate(n=Count('id')))
    for row in rows:
        offset = (row['d'] - start).days
        if offset < 0 or offset >= span:
            continue
        i = offset // 7 if weekly else offset
        submitted[i] += row['n']
        if row['review_status'] == ProgressRecord.ReviewStatus.APPROVED:
            approved[i] += row['n']
    labels = [f'{start + timedelta(days=(i * 7 if weekly else i)):%d %b}' for i in range(buckets)]
    return {'labels': labels, 'submitted': submitted, 'approved': approved, 'weekly': weekly}


def _data(request):
    kind, start, end = _period(request)
    today = timezone.localdate()
    island_id = request.GET.get('island', '').strip()

    houses = House.objects.select_related('village__municipality__island', 'assigned_engineer__user')
    if island_id.isdigit():
        houses = houses.filter(village__municipality__island_id=int(island_id))
    house_list = list(houses)                       # one query; reused for everything below
    house_by_id = {h.pk: h for h in house_list}
    house_ids = list(house_by_id)
    total = len(house_ids)

    status_counts = {key: 0 for key, _ in House.Status.choices}
    for h in house_list:
        status_counts[h.status] = status_counts.get(h.status, 0) + 1

    # ---- progress submissions in the period and the equal-length period before it
    period_updates = ProgressRecord.objects.filter(house_id__in=house_ids, update_date__date__range=(start, end))
    span = (end - start).days + 1
    prev_start, prev_end = start - timedelta(days=span), start - timedelta(days=1)
    previous_updates = ProgressRecord.objects.filter(house_id__in=house_ids,
                                                     update_date__date__range=(prev_start, prev_end))
    RS = ProgressRecord.ReviewStatus

    def by_status(qs):
        counts = {r['review_status']: r['n'] for r in qs.order_by().values('review_status').annotate(n=Count('id'))}
        return counts.get(RS.APPROVED, 0), counts.get(RS.PENDING, 0), counts.get(RS.REJECTED, 0)

    approved_n, pending_n, changes_n = by_status(period_updates)
    prev_approved_n, prev_pending_n, prev_changes_n = by_status(previous_updates)

    # ---- verified progress (latest approved record per house x active stage)
    latest = {}
    records = (ProgressRecord.objects
               .filter(house_id__in=house_ids, review_status=RS.APPROVED, stage__is_active=True)
               .select_related('stage').order_by('house_id', 'stage_id', '-update_date', '-created_at'))
    for rec in records:
        latest.setdefault((rec.house_id, rec.stage_id), rec)
    stages = list(ConstructionStage.objects.filter(is_active=True).order_by('sequence', 'name'))
    total_weight = sum((s.weight for s in stages), Decimal('0'))
    per_house = {}
    for hid in house_ids:
        weighted = sum((s.weight * latest[(hid, s.id)].percentage / Decimal('100')
                        for s in stages if (hid, s.id) in latest), Decimal('0'))
        per_house[hid] = weighted / total_weight * Decimal('100') if total_weight else Decimal('0')
    progress_sum = sum(per_house.values(), Decimal('0'))
    programme_progress = progress_sum / Decimal(TARGET_HOUSES)
    average_progress = progress_sum / Decimal(total) if total else Decimal('0')

    # ---- islands (houses, status counts and average progress in a single pass)
    island_totals = defaultdict(lambda: {'houses': 0, 'in_progress': 0, 'completed': 0, 'progress': Decimal('0')})
    for h in house_list:
        row = island_totals[h.village.municipality.island_id]
        row['houses'] += 1
        row['in_progress'] += h.status == House.Status.IN_PROGRESS
        row['completed'] += h.status in (House.Status.COMPLETED, House.Status.HANDED_OVER)
        row['progress'] += per_house[h.pk]
    island_rows = []
    for island in Island.objects.order_by('name'):
        if island_id.isdigit() and str(island.pk) != island_id:
            continue
        row = island_totals.get(island.pk, {'houses': 0, 'in_progress': 0, 'completed': 0, 'progress': Decimal('0')})
        island_rows.append({
            'name': island.name.title(), 'houses': row['houses'], 'in_progress': row['in_progress'],
            'completed': row['completed'],
            'average_progress': row['progress'] / row['houses'] if row['houses'] else Decimal('0'),
        })

    # ---- milestones
    milestone_rows = []
    for stage in stages:
        values = [latest[(hid, stage.id)].percentage for hid in house_ids if (hid, stage.id) in latest]
        milestone_rows.append({
            'name': stage.name, 'weight': stage.weight,
            'average': sum(values, Decimal('0')) / len(values) if values else Decimal('0'),
            'updated_houses': len(values)})

    # ---- engineers: workload, average progress and activity in the period
    eng = {}
    for h in house_list:
        if h.assigned_engineer_id:
            row = eng.setdefault(h.assigned_engineer_id, {
                'name': str(h.assigned_engineer), 'houses': 0, 'progress': Decimal('0'),
                'submissions': 0, 'approved': 0, 'pending': 0, 'changes': 0})
            row['houses'] += 1
            row['progress'] += per_house[h.pk]
    activity = (period_updates.order_by().values('engineer_id')
                .annotate(sub=Count('id'), appr=Count('id', filter=Q(review_status=RS.APPROVED)),
                          pend=Count('id', filter=Q(review_status=RS.PENDING)),
                          chg=Count('id', filter=Q(review_status=RS.REJECTED))))
    for row in activity:
        if row['engineer_id'] in eng:
            eng[row['engineer_id']].update(submissions=row['sub'], approved=row['appr'],
                                           pending=row['pend'], changes=row['chg'])
    engineer_rows = sorted(({**r, 'average_progress': r['progress'] / r['houses']} for r in eng.values()),
                           key=lambda r: (-r['houses'], r['name']))

    # ---- inspections and defects
    inspections = Inspection.objects.filter(house_id__in=house_ids, inspection_date__range=(start, end))
    defects_period = Defect.objects.filter(inspection__house_id__in=house_ids, created_at__date__range=(start, end))
    defects_open = Defect.objects.filter(inspection__house_id__in=house_ids).exclude(status=Defect.Status.VERIFIED)
    overdue_defects = defects_open.filter(due_date__lt=today)

    # ---- house-level follow-up (prioritised, de-duplicated, no per-house queries)
    exceptions, seen = [], set()

    def flag(house, category):
        key = (house.pk, category)
        if key in seen:
            return
        seen.add(key)
        issue, priority, action = EXCEPTION_CATEGORIES[category]
        exceptions.append({
            'house_id': house.house_id, 'issue': issue, 'category': category, 'priority': priority,
            'engineer': str(house.assigned_engineer) if house.assigned_engineer else 'Unassigned',
            'action': action})

    last_approved = {r['house_id']: r['last'] for r in
                     ProgressRecord.objects.filter(house_id__in=house_ids, review_status=RS.APPROVED)
                     .order_by().values('house_id').annotate(last=Max('update_date'))}
    cutoff = today - timedelta(days=STALE_DAYS)
    for h in house_list:
        if h.status == House.Status.ON_HOLD:
            flag(h, 'ON_HOLD')
        elif h.status == House.Status.IN_PROGRESS:
            last = last_approved.get(h.pk)
            if last is None or last.date() < cutoff:
                flag(h, 'STALE')
    for hid in (ProgressRecord.objects.filter(house_id__in=house_ids, review_status=RS.REJECTED)
                .order_by('-update_date').values_list('house_id', flat=True)):
        flag(house_by_id[hid], 'CHANGES')
    for hid, review_status, outcome in (Inspection.objects.filter(house_id__in=house_ids)
                                        .filter(Q(review_status=Inspection.ReviewStatus.PENDING)
                                                | Q(outcome=Inspection.Outcome.FAIL))
                                        .order_by('-inspection_date')
                                        .values_list('house_id', 'review_status', 'outcome')):
        flag(house_by_id[hid], 'INSPECTION_REVIEW' if review_status == Inspection.ReviewStatus.PENDING
             else 'INSPECTION_FAILED')
    for hid in overdue_defects.order_by('due_date').values_list('inspection__house_id', flat=True):
        flag(house_by_id[hid], 'DEFECT_OVERDUE')
    exceptions.sort(key=lambda e: (PRIORITY_ORDER[e['priority']], CATEGORY_RANK[e['category']], e['house_id']))

    counts = Counter(e['category'] for e in exceptions)
    exception_summary = sorted(
        ({'category': c, 'issue': EXCEPTION_CATEGORIES[c][0], 'priority': EXCEPTION_CATEGORIES[c][1],
          'action': EXCEPTION_CATEGORIES[c][2], 'count': n} for c, n in counts.items()),
        key=lambda r: (PRIORITY_ORDER[r['priority']], -r['count']))

    islands = Island.objects.order_by('name')
    selected_island = next((i for i in islands if island_id.isdigit() and str(i.pk) == island_id), None)

    return {
        'period': kind, 'start': start, 'end': end, 'island_id': island_id,
        'island_name': selected_island.name.title() if selected_island else '',
        'islands': islands, 'total_houses': total,
        'target_houses': TARGET_HOUSES, 'coverage': Decimal(total) / TARGET_HOUSES * 100,
        'status_counts': status_counts, 'programme_progress': programme_progress,
        'average_progress': average_progress, 'approved_updates': approved_n,
        'pending_updates': pending_n, 'changes_requested': changes_n,
        'previous_approved_updates': prev_approved_n,
        'previous_pending_updates': prev_pending_n,
        'previous_changes_requested': prev_changes_n,
        'island_rows': island_rows, 'milestone_rows': milestone_rows, 'engineer_rows': engineer_rows,
        'trend': _trend(period_updates, start, end),
        'inspections_total': inspections.count(),
        'inspections_pass': inspections.filter(outcome=Inspection.Outcome.PASS).count(),
        'inspections_conditional': inspections.filter(outcome=Inspection.Outcome.CONDITIONAL).count(),
        'inspections_fail': inspections.filter(outcome=Inspection.Outcome.FAIL).count(),
        'inspections_pending': inspections.filter(review_status=Inspection.ReviewStatus.PENDING).count(),
        'defects_new': defects_period.count(), 'defects_open': defects_open.count(),
        'defects_overdue': overdue_defects.count(),
        'defects_closed_period': Defect.objects.filter(
            inspection__house_id__in=house_ids, status=Defect.Status.VERIFIED,
            closed_at__date__range=(start, end)).count(),
        'exceptions': exceptions, 'exception_summary': exception_summary,
    }


@login_required
@user_passes_test(_manager)
def report_centre(request):
    return render(request, 'reports/report_centre.html', _data(request))


def _logo_path():
    """Find the IOM logo for the PDF header (works with runserver and with collectstatic)."""
    found = finders.find(LOGO_STATIC_PATH)
    if isinstance(found, (list, tuple)):
        found = found[0] if found else None
    if found:
        return found
    static_root = getattr(settings, 'STATIC_ROOT', None)
    if static_root:
        candidate = os.path.join(static_root, LOGO_STATIC_PATH)
        if os.path.exists(candidate):
            return candidate
    return None


@login_required
@user_passes_test(_manager)
def report_pdf(request):
    data = _data(request)
    audience = request.GET.get('audience', 'management')
    if audience not in AUDIENCES:
        audience = 'management'
    pdf = build_report_pdf(data, audience, generated_at=timezone.localtime(), logo_path=_logo_path(),
                           target=TARGET_HOUSES)
    response = HttpResponse(pdf, content_type='application/pdf')
    disposition = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = (
        f'{disposition}; filename="HRMIS_{audience}_{data["start"]}_{data["end"]}.pdf"')
    return response
