from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
import unicodedata, re, calendar
from app.config import SENTINELS
from app.errors import BusinessError

def number(value, unit=''):
    text = unicodedata.normalize('NFKC', str(value)).strip()
    if text.upper() in SENTINELS or text in SENTINELS:
        raise BusinessError('MISSING_VALUE', '数值缺失')
    if unit and text.endswith(unit):
        text = text[:-len(unit)].strip()
    if ',' in text:
        if not re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+(\.\d+)?', text):
            raise BusinessError('BAD_NUMBER', '千分位格式错误')
        text = text.replace(',', '')
    try:
        val = Decimal(text)
        if not val.is_finite(): raise InvalidOperation
        return val
    except InvalidOperation:
        raise BusinessError('BAD_NUMBER', '数值格式错误')

def money(value):
    return format(Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'f')

def instant(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None: raise ValueError
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise BusinessError('BAD_TIME', '时间缺少有效偏移')

STUDY_ZONE = timezone(timedelta(hours=8))  # Asia/Shanghai 研究中心日历
_PARTIAL_FORMS = (
    ('year', re.compile(r'^(\d{4})$')),
    ('month', re.compile(r'^(\d{4})-(\d{2})$')),
    ('day', re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')),
)

def partial(value):
    """部分日期→可能区间。年/月/日精度按研究中心日历解释为闭区间 [start,end]；
    完整时刻（须带偏移）为精确点，start==end。原始字符串保留在 raw。"""
    text = unicodedata.normalize('NFKC', str(value)).strip()
    for precision, pattern in _PARTIAL_FORMS:
        match = pattern.fullmatch(text)
        if not match: continue
        parts = [int(g) for g in match.groups()]
        try:
            if precision == 'year':
                start = datetime(parts[0], 1, 1, tzinfo=STUDY_ZONE)
                end = datetime(parts[0], 12, 31, 23, 59, 59, 999999, tzinfo=STUDY_ZONE)
            elif precision == 'month':
                start = datetime(parts[0], parts[1], 1, tzinfo=STUDY_ZONE)
                end = datetime(parts[0], parts[1], calendar.monthrange(parts[0], parts[1])[1], 23, 59, 59, 999999, tzinfo=STUDY_ZONE)
            else:
                start = datetime(parts[0], parts[1], parts[2], tzinfo=STUDY_ZONE)
                end = datetime(parts[0], parts[1], parts[2], 23, 59, 59, 999999, tzinfo=STUDY_ZONE)
        except ValueError:
            raise BusinessError('BAD_TIME', '日期格式错误')
        return {'raw': text, 'precision': precision,
                'start': start.astimezone(timezone.utc), 'end': end.astimezone(timezone.utc)}
    exact = instant(text)
    return {'raw': text, 'precision': 'exact', 'start': exact, 'end': exact}

def span_of(row, start_key='at', end_key='at_end'):
    """读取记录的可能区间；缺末端或末端倒置时退化为精确点，保证不放大区间。"""
    start = instant(row[start_key])
    marker = row.get(end_key)
    end = instant(marker) if marker else start
    return (start, end) if end >= start else (start, start)

def decstr(value):
    return format(value, 'f') if isinstance(value, Decimal) else value
