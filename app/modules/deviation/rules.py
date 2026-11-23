from collections import defaultdict

def detect(windows,context):
    primary=defaultdict(list)
    for row in windows:
        if row['kind']=='PRIMARY':primary[(row['subject'],row['visit'])].append(row)
    issues=[];completed=[];pending=[]
    for subject in sorted(context['subjects']):
        for visit in context['required_visits']:
            items=primary.get((subject,visit),[])
            if not items:issues.append({'subject':subject,'visit':visit,'id':'','code':'MISSING_PRIMARY'});continue
            if len(items)>1:issues.append({'subject':subject,'visit':visit,'id':','.join(r['id'] for r in items),'code':'DUPLICATE_PRIMARY'});continue
            row=items[0]
            if row['code']=='PENDING':
                pending.append({'id':row['id'],'subject':row['subject'],'visit':row['visit'],'at_raw':row['at_raw'],'precision':row['precision'],'day_low':row['day_low'],'day_high':row['day_high'],'start_day':row['start_day'],'end_day':row['end_day'],'code':'WINDOW_PENDING','line':row['line'],'reason':f"可能区间第{row['day_low']}~{row['day_high']}日跨窗[{row['start_day']},{row['end_day']})"})
            elif row['code']!='IN_WINDOW':issues.append({**row,'code':'WINDOW_'+row['code']})
            else:completed.append(row)
    return issues,completed,pending

def apply(state):
    issues,completed,pending=detect(state['windows'],state['context']);state.update(deviations=issues,completed=completed,pending=pending)
    state['views']['deviation']={'title':'偏离复核','rows':issues,'metrics':{'完成访视':len(completed),'缺失或偏离':len(issues),'缺首次访视':sum(x['code']=='MISSING_PRIMARY' for x in issues),'待核':len(pending)}}
