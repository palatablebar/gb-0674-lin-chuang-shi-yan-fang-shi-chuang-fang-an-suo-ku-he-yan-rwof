from app.engine import evaluate
from app.coerce import partial
from app.modules.protocol.rules import normalize
from app.modules.retest.rules import adjudicate
from app.archive import serialize
from app.errors import BusinessError
from app import main, store
from fastapi.testclient import TestClient
from copy import deepcopy
import pytest, zipfile, io, json

@pytest.fixture
def partial_batch():
    return evaluate({'dataset':'partial'})

def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB_PATH',str(tmp_path/'test.sqlite'));return TestClient(main.app)

# 可能区间解析
def test_partial_parse_month():
    s=partial('2026-10');assert s['precision']=='month';assert s['start'].isoformat()=='2026-09-30T16:00:00+00:00';assert s['end'].isoformat()=='2026-10-31T15:59:59.999999+00:00'
def test_partial_parse_day_and_year():
    assert partial('2026-10-08')['precision']=='day';assert partial('2026')['precision']=='year'
def test_partial_parse_exact_kept():
    s=partial('2026-10-08T08:00:00+08:00');assert s['precision']=='exact' and s['start']==s['end']
def test_partial_invalid_rejected():
    for bad in ('2026-13','2026-02-30','2026-1','abc','2026-10-08T08:00:00'):
        with pytest.raises(BusinessError) as e:partial(bad)
        assert e.value.code=='BAD_TIME'

# 裁决：全在窗内才算完成
def test_day_precision_in_window_completes(partial_batch):
    row=next(r for r in partial_batch['completed'] if r['id']=='00002-V1');assert row['day_low']==row['day_high']==7
def test_window_start_day_precision_completes(partial_batch):
    assert any(r['id']=='00003-V1' and r['code']=='IN_WINDOW' for r in partial_batch['completed'])

# 裁决：全在窗外才记偏离
def test_month_fully_late_is_deviation(partial_batch):
    assert any(r['id']=='00007-V1' and r['code']=='WINDOW_LATE' for r in partial_batch['deviations'])
def test_day_fully_early_is_deviation(partial_batch):
    assert any(r['id']=='00008-V1' and r['code']=='WINDOW_EARLY' for r in partial_batch['deviations'])

# 裁决：跨窗边界保留待核并阻断锁库
def test_month_crossing_pending(partial_batch):
    row=next(r for r in partial_batch['pending'] if r['id']=='00004-V1')
    assert row['code']=='WINDOW_PENDING' and row['at_raw']=='2026-10' and row['day_low']==0 and row['day_high']==30 and '跨窗' in row['reason']
def test_year_precision_pending(partial_batch):
    row=next(r for r in partial_batch['pending'] if r['id']=='00006-V1');assert row['precision']=='year' and row['day_low']<0
def test_pending_not_deviation_not_completed(partial_batch):
    ids={r['id'] for r in partial_batch['pending']}
    assert ids=={'00004-V1','00005-V2','00006-V1'}
    assert not ids&{r.get('id') for r in partial_batch['deviations']};assert not ids&{r['id'] for r in partial_batch['completed']}
def test_pending_blocks_lock(partial_batch):
    b=partial_batch['balance'];assert b['pending']==3 and b['blocked']==7 and b['status']=='待处理'
    assert partial_batch['archive']['status']=='待处理'
def test_partial_batch_counts(partial_batch):
    b=partial_batch['balance'];assert b['input']==40 and b['accepted']==40 and b['completed']==33 and b['deviations']==4 and b['row_balanced']

# 区间跨方案生效边界→隔离，原始日期保留
def test_straddle_protocol_quarantined(clean):
    row=dict(clean['records'][0],at='2026-10')
    with pytest.raises(BusinessError) as e:normalize(row,clean['context'])
    assert e.value.code=='PROTOCOL_CONFLICT'

# 复检时距按区间保守判定
def test_retest_partial_parent_selected(partial_batch):
    row=next(r for r in partial_batch['selected_results'] if r['primary_id']=='00002-V1');assert row['id']=='00002-R1' and row['code']=='RETEST_SELECTED'
def test_retest_unprovable_order(clean):
    rows=[dict(r) for r in clean['records']]
    parent=next(r for r in rows if r['id']=='00001-V1');parent['at_end']='2026-10-08T23:59:59+08:00'
    retest=next(r for r in rows if r['id']=='00001-R1');retest['at']='2026-10-08T12:00:00+08:00';retest['at_end']=retest['at']
    _,issues=adjudicate(rows,clean['context']);assert any(i['id']=='00001-R1' and i['code']=='RETEST_WINDOW' for i in issues)

# 原始日期不丢失：记录、页面视图、冻结凭证均保留原始精度
def test_original_precision_kept_in_records(partial_batch):
    row=next(r for r in partial_batch['records'] if r['id']=='00004-V1');assert row['at_raw']=='2026-10' and row['precision']=='month'
def test_certificate_preserves_precision(partial_batch):
    z=zipfile.ZipFile(io.BytesIO(serialize(partial_batch)));cert=json.loads(z.read('certificate.json'))
    row=next(w for w in cert['windows'] if w['id']=='00004-V1');assert row['at_raw']=='2026-10' and row['precision']=='month'
    assert {p['id'] for p in cert['pending']}=={'00004-V1','00005-V2','00006-V1'}
def test_certificate_in_export_endpoint(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch);run=c.post('/api/runs',json={'dataset':'partial'}).json()
    z=zipfile.ZipFile(io.BytesIO(c.get('/api/export/'+run['manifest']['run_id']).content))
    assert 'certificate.json' in z.namelist() and '2026-10' in z.read('certificate.json').decode()

# 重跑不能新增或改换区间
def test_rerun_intervals_stable(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    a=c.post('/api/runs',json={'dataset':'partial'}).json();rid=a['manifest']['run_id']
    b=c.post('/api/runs/'+rid+'/rerun').json()
    assert b['manifest']['run_id']==rid
    shape=lambda s:[(w['id'],w['day_low'],w['day_high'],w['precision'],w['code']) for w in s['windows']]
    assert shape(a)==shape(b);assert a['pending']==b['pending']

# 替换失败保留旧版
def test_rerun_failure_keeps_old(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch);a=c.post('/api/runs',json={'dataset':'partial'}).json();rid=a['manifest']['run_id']
    def broken(*args,**kwargs):raise BusinessError('RULES_BROKEN','规则故障')
    monkeypatch.setattr(main,'evaluate',broken)
    assert c.post('/api/runs/'+rid+'/rerun').status_code==422
    assert c.get('/api/runs/'+rid).json()['manifest']['sha256']==a['manifest']['sha256']
def test_store_conflict_keeps_original(tmp_path):
    path=str(tmp_path/'s.sqlite');result=evaluate({'dataset':'partial'});store.save(path,result)
    mutated=deepcopy(result);mutated['windows'][0]['day_high']=999;store.save(path,mutated)
    assert store.get(path,result['manifest']['run_id'])['windows'][0]['day_high']!=999

# 页面显示可能区间与阻断原因
def test_page_shows_interval_and_reason(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch);run=c.post('/api/runs',json={'dataset':'partial'}).json();rid=run['manifest']['run_id']
    html=c.get('/locking?run_id='+rid).text
    assert '待核阻断' in html and '跨窗' in html and '2026-10' in html
    html=c.get('/windows?run_id='+rid).text
    assert '区间首日' in html and '原始日期' in html
