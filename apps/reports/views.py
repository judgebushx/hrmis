from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from apps.housing.models import House
from apps.locations.models import Island
from apps.progress.models import ConstructionStage, ProgressRecord
from apps.inspections.models import Inspection, Defect

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak, KeepTogether, HRFlowable)

TARGET_HOUSES = 700
BLUE = colors.HexColor('#174a7e')
PALE = colors.HexColor('#edf3f8')
MUTED = colors.HexColor('#526273')


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


def _data(request):
    kind, start, end = _period(request)
    island_id = request.GET.get('island', '').strip()
    houses = House.objects.select_related('village__municipality__island', 'assigned_engineer__user')
    if island_id.isdigit():
        houses = houses.filter(village__municipality__island_id=int(island_id))
    house_ids = list(houses.values_list('id', flat=True))
    total = len(house_ids)
    status_counts = {key: houses.filter(status=key).count() for key, _ in House.Status.choices}

    period_updates = ProgressRecord.objects.filter(house_id__in=house_ids, update_date__date__range=(start, end))
    approved_period = period_updates.filter(review_status=ProgressRecord.ReviewStatus.APPROVED)
    pending_period = period_updates.filter(review_status=ProgressRecord.ReviewStatus.PENDING)
    changes_period = period_updates.filter(review_status=ProgressRecord.ReviewStatus.REJECTED)
    span = (end - start).days + 1
    prev_start, prev_end = start - timedelta(days=span), start - timedelta(days=1)
    previous_updates = ProgressRecord.objects.filter(house_id__in=house_ids, update_date__date__range=(prev_start, prev_end))
    previous_approved = previous_updates.filter(review_status=ProgressRecord.ReviewStatus.APPROVED).count()

    latest = {}
    records = ProgressRecord.objects.filter(
        house_id__in=house_ids, review_status=ProgressRecord.ReviewStatus.APPROVED,
        stage__is_active=True,
    ).select_related('stage').order_by('house_id', 'stage_id', '-update_date', '-created_at')
    for rec in records:
        latest.setdefault((rec.house_id, rec.stage_id), rec)
    stages = list(ConstructionStage.objects.filter(is_active=True).order_by('sequence', 'name'))
    total_weight = sum((s.weight for s in stages), Decimal('0'))
    per_house = {}
    for hid in house_ids:
        weighted = sum((s.weight * latest[(hid, s.id)].percentage / Decimal('100')
                        for s in stages if (hid, s.id) in latest), Decimal('0'))
        per_house[hid] = weighted / total_weight * Decimal('100') if total_weight else Decimal('0')
    programme_progress = sum(per_house.values(), Decimal('0')) / Decimal(TARGET_HOUSES)
    average_progress = sum(per_house.values(), Decimal('0')) / Decimal(total) if total else Decimal('0')

    island_rows = []
    for island in Island.objects.order_by('name'):
        if island_id.isdigit() and str(island.pk) != island_id:
            continue
        subset = houses.filter(village__municipality__island=island)
        island_rows.append({'name': island.name.title(), 'houses': subset.count(),
                            'in_progress': subset.filter(status=House.Status.IN_PROGRESS).count(),
                            'completed': subset.filter(status__in=[House.Status.COMPLETED, House.Status.HANDED_OVER]).count()})

    milestone_rows = []
    for stage in stages:
        values = [latest[(hid, stage.id)].percentage for hid in house_ids if (hid, stage.id) in latest]
        milestone_rows.append({'name': stage.name,
            'average': sum(values, Decimal('0')) / len(values) if values else Decimal('0'),
            'updated_houses': len(values)})

    inspections = Inspection.objects.filter(house_id__in=house_ids, inspection_date__range=(start, end))
    defects_period = Defect.objects.filter(inspection__house_id__in=house_ids, created_at__date__range=(start, end))
    defects_open = Defect.objects.filter(inspection__house_id__in=house_ids).exclude(status=Defect.Status.VERIFIED)
    overdue_defects = defects_open.filter(due_date__lt=timezone.localdate())
    exceptions = []
    exception_keys = set()
    def add_exception(h, issue, action):
        key = (h.pk, issue)
        if key in exception_keys or len(exceptions) >= 150:
            return
        exception_keys.add(key)
        exceptions.append({'house_id': h.house_id, 'issue': issue,
            'engineer': str(h.assigned_engineer) if h.assigned_engineer else 'Unassigned',
            'action': action})

    # Operational follow-up includes schedule freshness, progress review decisions,
    # inspection quality/review actions and overdue corrective work.
    for h in houses.filter(status__in=[House.Status.ON_HOLD, House.Status.IN_PROGRESS]).select_related('assigned_engineer__user')[:150]:
        latest_house = max((r.update_date for r in ProgressRecord.objects.filter(house=h, review_status=ProgressRecord.ReviewStatus.APPROVED)), default=None)
        stale = not latest_house or latest_house.date() < timezone.localdate() - timedelta(days=30)
        if h.status == House.Status.ON_HOLD:
            add_exception(h, 'On hold', 'Confirm hold reason and recovery plan')
        elif stale:
            add_exception(h, 'No approved update in over 30 days', 'Request site update and confirm next milestone')

    for rec in ProgressRecord.objects.filter(house_id__in=house_ids, review_status=ProgressRecord.ReviewStatus.REJECTED).select_related('house__assigned_engineer__user').order_by('-update_date')[:150]:
        add_exception(rec.house, 'Progress submission requires changes', 'Engineer to address supervisor comments and resubmit progress')
    for insp in Inspection.objects.filter(house_id__in=house_ids).filter(Q(review_status=Inspection.ReviewStatus.PENDING) | Q(outcome=Inspection.Outcome.FAIL)).select_related('house__assigned_engineer__user').order_by('-inspection_date')[:150]:
        issue = 'Inspection awaiting supervisor review' if insp.review_status == Inspection.ReviewStatus.PENDING else 'Inspection failed – corrective work required'
        action = 'Supervisor to review inspection' if insp.review_status == Inspection.ReviewStatus.PENDING else 'Resolve inspection findings and arrange reinspection'
        add_exception(insp.house, issue, action)
    for defect in overdue_defects.select_related('inspection__house__assigned_engineer__user').order_by('due_date')[:150]:
        add_exception(defect.inspection.house, 'Overdue defect corrective action', 'Assigned engineer to complete corrective action; inspector to verify')
    return {
        'period': kind, 'start': start, 'end': end, 'island_id': island_id,
        'islands': Island.objects.order_by('name'), 'total_houses': total,
        'target_houses': TARGET_HOUSES, 'coverage': Decimal(total) / TARGET_HOUSES * 100,
        'status_counts': status_counts, 'programme_progress': programme_progress,
        'average_progress': average_progress, 'approved_updates': approved_period.count(),
        'pending_updates': pending_period.count(), 'changes_requested': changes_period.count(),
        'previous_approved_updates': previous_approved,
        'previous_pending_updates': previous_updates.filter(review_status=ProgressRecord.ReviewStatus.PENDING).count(),
        'previous_changes_requested': previous_updates.filter(review_status=ProgressRecord.ReviewStatus.REJECTED).count(),
        'island_rows': island_rows, 'milestone_rows': milestone_rows,
        'inspections_total': inspections.count(),
        'inspections_pass': inspections.filter(outcome=Inspection.Outcome.PASS).count(),
        'inspections_conditional': inspections.filter(outcome=Inspection.Outcome.CONDITIONAL).count(),
        'inspections_fail': inspections.filter(outcome=Inspection.Outcome.FAIL).count(),
        'inspections_pending': inspections.filter(review_status=Inspection.ReviewStatus.PENDING).count(),
        'defects_new': defects_period.count(), 'defects_open': defects_open.count(),
        'defects_overdue': overdue_defects.count(),
        'defects_closed_period': Defect.objects.filter(inspection__house_id__in=house_ids,
            status=Defect.Status.VERIFIED, closed_at__date__range=(start, end)).count(),
        'exceptions': exceptions,
    }


@login_required
@user_passes_test(_manager)
def report_centre(request):
    return render(request, 'reports/report_centre.html', _data(request))


def _table(rows, widths, font=8):
    t = Table(rows, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),BLUE), ('TEXTCOLOR',(0,0),(-1,0),colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('GRID',(0,0),(-1,-1),.35,colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]), ('FONTSIZE',(0,0),(-1,-1),font),
        ('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),6),
        ('RIGHTPADDING',(0,0),(-1,-1),6), ('TOPPADDING',(0,0),(-1,-1),5),
        ('BOTTOMPADDING',(0,0),(-1,-1),5),
    ]))
    return t


def _chart_rows(data):
    # ReportLab-native bar visualization; no external charting dependency.
    rows = [['Construction milestone', 'Approved progress']]
    for item in data['milestone_rows']:
        pct = float(item['average'])
        bar = Table([[Paragraph(f'{pct:.1f}%', getSampleStyleSheet()['BodyText'])]], colWidths=[max(18, 95 * max(0, min(100, pct)) / 100) * mm])
        bar.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#2f75b5')),('TEXTCOLOR',(0,0),(-1,-1),colors.white),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4)]))
        rows.append([item['name'], bar])
    return rows


@login_required
@user_passes_test(_manager)
def report_pdf(request):
    data = _data(request)
    audience = request.GET.get('audience', 'management')
    labels = {'programme':'Programme operational report','management':'Country Office management report','donor':'Donor progress report'}
    if audience not in labels: audience = 'management'
    title = labels[audience]
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=15*mm, bottomMargin=17*mm, title=title)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='RTitle', parent=styles['Title'], fontSize=18, leading=22, textColor=BLUE, alignment=TA_LEFT, spaceAfter=4))
    styles.add(ParagraphStyle(name='NoteSmall', parent=styles['Normal'], fontSize=7.5, leading=10, textColor=MUTED))
    styles.add(ParagraphStyle(name='Section', parent=styles['Heading2'], fontSize=12, leading=15, textColor=BLUE, keepWithNext=True, spaceBefore=7, spaceAfter=5))
    P=lambda s: Paragraph(str(s), styles['BodyText'])
    story=[Paragraph('IOM MICRONESIA | HOUSING RECONSTRUCTION',styles['Heading2']),Paragraph(title,styles['RTitle']),
        P(f"Reporting period: {data['start']:%d %B %Y} – {data['end']:%d %B %Y}"),
        Paragraph(f"Generated: {timezone.localtime():%d %B %Y, %H:%M} (Pohnpei time)",styles['NoteSmall']),Spacer(1,5*mm)]

    if audience == 'programme':
        story += [Paragraph('1. Weekly operational snapshot',styles['Section']),
            P(f"{data['total_houses']} houses are registered against the 700-house target. {data['status_counts'].get('IN_PROGRESS',0)} are under reconstruction; {data['approved_updates']} progress update(s) were approved in this period, while {data['pending_updates']} await review and {data['changes_requested']} require changes."),
            _table([['Operational indicator','Current period','Previous period'],
                ['Approved progress updates',data['approved_updates'],data['previous_approved_updates']],
                ['Pending review',data['pending_updates'],data['previous_pending_updates']],
                ['Changes requested',data['changes_requested'],data['previous_changes_requested']],
                ['Inspections conducted',data['inspections_total'],'Not available in baseline'],
                ['New defects',data['defects_new'],'Not available in baseline']], [78*mm,42*mm,48*mm]),
            Paragraph('2. Houses requiring follow-up',styles['Section'])]
        exrows=[['House ID','Issue','Assigned engineer','Suggested follow-up']]
        exrows += [[x['house_id'],x['issue'],x['engineer'],x['action']] for x in data['exceptions']]
        if len(exrows)==1: exrows.append(['No flagged houses','','',''])
        story += [_table(exrows,[28*mm,48*mm,43*mm,49*mm],7),Paragraph('3. Inspection and defect workload',styles['Section']),
            P(f"Inspections: {data['inspections_total']} total ({data['inspections_pass']} passed, {data['inspections_conditional']} conditional, {data['inspections_fail']} failed); {data['inspections_pending']} pending review. Defects: {data['defects_new']} new, {data['defects_open']} currently open, {data['defects_overdue']} overdue, and {data['defects_closed_period']} verified closed in the period."),
            Paragraph('4. Construction milestone snapshot',styles['Section']),_table(_chart_rows(data),[82*mm,80*mm],7),
            Paragraph('5. Priorities for the next period',styles['Section']),P('Follow up on flagged houses, pending progress reviews, inspection actions and overdue defects. Confirm an accountable staff member and target date for each action.')]
    elif audience == 'management':
        story += [Paragraph('1. Executive summary',styles['Section']),
            P(f"HRMIS records {data['total_houses']} of 700 target houses ({data['coverage']:.1f}% registration coverage). Official programme physical progress is {data['programme_progress']:.2f}%; average verified progress among registered houses is {data['average_progress']:.2f}%. There are {data['status_counts'].get('IN_PROGRESS',0)} houses under reconstruction and {data['status_counts'].get('ON_HOLD',0)} on hold."),
            _table([['Management KPI','Value','Management KPI','Value'],
                ['Registered houses',data['total_houses'],'Programme target',700],
                ['Programme physical progress',f"{data['programme_progress']:.2f}%",'Registration coverage',f"{data['coverage']:.1f}%"],
                ['Under reconstruction',data['status_counts'].get('IN_PROGRESS',0),'On hold',data['status_counts'].get('ON_HOLD',0)],
                ['Completed / handed over',data['status_counts'].get('COMPLETED',0)+data['status_counts'].get('HANDED_OVER',0),'Open / overdue defects',f"{data['defects_open']} / {data['defects_overdue']}" ]],[42*mm,25*mm,48*mm,43*mm]),
            Paragraph('2. Period activity versus previous comparable period',styles['Section']),
            _table([['Indicator','Previous period','Current period'],
                ['Approved progress updates',data['previous_approved_updates'],data['approved_updates']],
                ['Pending progress reviews',data['previous_pending_updates'],data['pending_updates']],
                ['Changes requested',data['previous_changes_requested'],data['changes_requested']]], [68*mm,45*mm,45*mm]),
            Paragraph('3. Geographic coverage',styles['Section']),
            _table([['Island','Registered','Under reconstruction','Completed / handed over']]+[[r['name'],r['houses'],r['in_progress'],r['completed']] for r in data['island_rows']],[38*mm,32*mm,48*mm,48*mm]),
            Paragraph('4. Milestone performance',styles['Section']),_table(_chart_rows(data),[82*mm,80*mm],7),
            Paragraph('5. Quality assurance and implementation risks',styles['Section']),
            P(f"Inspections during period: {data['inspections_total']}; passed {data['inspections_pass']}, conditional {data['inspections_conditional']}, failed {data['inspections_fail']}, pending review {data['inspections_pending']}. Defects: {data['defects_new']} new, {data['defects_open']} open and {data['defects_overdue']} overdue. Changes-requested progress submissions: {data['changes_requested']}."),
            Paragraph('6. Management attention required',styles['Section']),
            P(f"Review {len(data['exceptions'])} house-level follow-up flags, resolve pending approvals, address any failed inspections and ensure overdue defects have agreed corrective actions and deadlines.")]
    else:
        story += [Paragraph('1. Results at a glance',styles['Section']),
            P(f"During the reporting period, HRMIS recorded {data['total_houses']} houses in the programme registry against a target of 700 ({data['coverage']:.1f}% registration coverage). Verified programme physical progress stands at {data['programme_progress']:.2f}%, based on supervisor-approved milestone records."),
            _table([['Results indicator','Reported value'],['Houses registered',data['total_houses']],['Programme target',700],['Registration coverage',f"{data['coverage']:.1f}%"],['Programme physical progress',f"{data['programme_progress']:.2f}%"],['Houses under reconstruction',data['status_counts'].get('IN_PROGRESS',0)],['Houses completed / handed over',data['status_counts'].get('COMPLETED',0)+data['status_counts'].get('HANDED_OVER',0)]],[95*mm,65*mm]),
            Paragraph('2. Reporting-period activity',styles['Section']),
            _table([['Activity indicator','Previous comparable period','Current period'],['Approved progress updates',data['previous_approved_updates'],data['approved_updates']],['Pending progress reviews',data['previous_pending_updates'],data['pending_updates']],['Changes requested',data['previous_changes_requested'],data['changes_requested']]], [68*mm,45*mm,45*mm]),
            Paragraph('3. Geographic implementation coverage',styles['Section']),
            _table([['Island','Registered houses','Under reconstruction','Completed / handed over']]+[[r['name'],r['houses'],r['in_progress'],r['completed']] for r in data['island_rows']],[38*mm,38*mm,43*mm,47*mm]),
            Paragraph('4. Construction progress by milestone',styles['Section']),_table(_chart_rows(data),[82*mm,80*mm],7),
            Paragraph('5. Quality assurance',styles['Section']),
            P(f"The programme recorded {data['inspections_total']} inspection(s) in the period: {data['inspections_pass']} passed, {data['inspections_conditional']} passed with corrective actions, and {data['inspections_fail']} failed. {data['defects_new']} new defect(s) were recorded; {data['defects_closed_period']} were verified closed during the period."),
            Paragraph('6. Implementation challenges and mitigation',styles['Section']),
            P(f"Operational follow-up flags identify {len(data['exceptions'])} houses for review, including stale progress reporting or on-hold status. Programme teams will follow up with responsible staff, review constraints and monitor corrective actions through HRMIS."),
            Paragraph('7. Priorities for the next reporting period',styles['Section']),
            P('Continue reconstruction monitoring, maintain timely engineering progress submissions, complete required quality inspections and follow up outstanding corrective actions.')]

    story += [Spacer(1,4*mm),HRFlowable(width='100%',thickness=.5,color=colors.HexColor('#cbd5e1')),
        Paragraph('Reporting methodology: Official physical progress uses the latest supervisor-approved record for each active construction stage. Programme progress is weighted by construction-stage weights and measured against the 700-house programme target. Pending and changes-requested submissions are excluded. Inspection and defect indicators are reported separately from construction progress. Previous-period progress submission counts compare an equal-length period immediately preceding the selected reporting period.',styles['NoteSmall'])]

    def footer(canvas, d):
        canvas.saveState(); canvas.setFont('Helvetica',7); canvas.setFillColor(MUTED)
        canvas.drawString(16*mm,9*mm,'HRMIS | IOM Micronesia Housing Reconstruction')
        canvas.drawRightString(A4[0]-16*mm,9*mm,f'Page {d.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    response=HttpResponse(buf.getvalue(),content_type='application/pdf')
    response['Content-Disposition']=f'attachment; filename="HRMIS_{audience}_{data["start"]}_{data["end"]}.pdf"'
    return response
