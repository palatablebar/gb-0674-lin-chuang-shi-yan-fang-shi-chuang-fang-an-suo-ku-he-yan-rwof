from datetime import timezone,timedelta
from app.coerce import instant,span_of

def calculate(row,context):
    zone=timezone(timedelta(hours=8))
    enrolled=instant(row['enrolled']).astimezone(zone).date()
    first,last=span_of(row)
    low=(first.astimezone(zone).date()-enrolled).days
    high=(last.astimezone(zone).date()-enrolled).days
    start,end=context['plans'][row['selected_protocol']][row['visit']]
    if start<=low and high<end:code='IN_WINDOW'
    elif high<start:code='EARLY'
    elif low>=end:code='LATE'
    else:code='PENDING'
    return {'id':row['id'],'subject':row['subject'],'visit':row['visit'],'kind':row['kind'],'day':low,'day_low':low,'day_high':high,'start_day':start,'end_day':end,'selected_protocol':row['selected_protocol'],'precision':row.get('precision','exact'),'at_raw':row.get('at_raw',row['at']),'code':code,'line':row['_line']}

def apply(state):
    state['windows']=[calculate(r,state['context']) for r in state['records']]
    primary=[r for r in state['windows'] if r['kind']=='PRIMARY']
    state['views']['windows']={'title':'访视窗口','rows':state['windows'],'metrics':{'首次访视':len(primary),'窗内':sum(r['code']=='IN_WINDOW' for r in primary),'窗外':sum(r['code'] in ('EARLY','LATE') for r in primary),'待核':sum(r['code']=='PENDING' for r in primary)}}
