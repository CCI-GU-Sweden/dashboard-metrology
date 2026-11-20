"""Verify thresholds and failed REDO with the test dashboard role; roll back all writes."""
import json
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1] / 'dashboard_metrology'
source = json.dumps({name: (root / f'{name}.py').read_text(encoding='utf-8') for name in ('data', 'scoring')})
code = '''import json, os, sys, types
os.environ.setdefault('DJANGO_SETTINGS_MODULE','dashboard.settings')
import django
django.setup()
from django.db import transaction
sources=json.load(sys.stdin)
pkg=types.ModuleType('threshold_probe'); pkg.__path__=[]; sys.modules[pkg.__name__]=pkg
for name in ('data','scoring'):
    mod=types.ModuleType('threshold_probe.'+name); mod.__package__='threshold_probe'; sys.modules[mod.__name__]=mod
    exec(compile(sources[name],name+'.py','exec'),mod.__dict__)
d=sys.modules['threshold_probe.data']; scoring=sys.modules['threshold_probe.scoring']
with transaction.atomic():
    options=d.threshold_options(); assert options
    item=options[0]; mid=item['measurement_id']
    assert d.save_threshold(mid,-1,100.0,90.0,110.0)
    first=next(x for x in d.threshold_options() if x['measurement_id']==mid)
    assert first['expected_value']==100.0 and first['created_by']==-1
    scores={x['id']:x for x in scoring.measurements()}
    assert scores[mid]['threshold_id']==first['threshold_id']
    assert d.save_threshold(mid,-1,101.0,90.0,110.0)
    latest=next(x for x in d.threshold_options() if x['measurement_id']==mid)
    assert latest['version']==first['version']+1 and latest['expected_value']==101.0
    assert {x['id']:x for x in scoring.measurements()}[mid]['threshold_id']==latest['threshold_id']
    failures,_=d.failed_runs()
    if failures:
        fid=failures[0]['id']; assert d.enqueue_failed_redo(fid,-1)=='queued'
        assert d.enqueue_failed_redo(fid,-1)=='already_queued'
    transaction.set_rollback(True)
print('Threshold versions, scoring and failed-fileset REDO passed; changes rolled back')
'''
result = subprocess.run(['oc','-n','core-omero-test','exec','-i','deploy/dashboard-django','--','python','-c',code], input=source.encode(),capture_output=True)
print(result.stdout.decode(errors='replace'))
if result.returncode:
    print('\n'.join(line for line in result.stderr.decode(errors='replace').splitlines() if not line.startswith('I1120')),file=sys.stderr)
sys.exit(result.returncode)
