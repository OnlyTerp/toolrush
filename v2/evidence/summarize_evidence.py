"""Emit concise evidence tables from raw runs; counts never hand tallied."""
import json,xml.etree.ElementTree as E
from pathlib import Path
P=Path(__file__).parent
unique={}
for filename in ['all-focused-final.xml','compat-final.xml','rpc-final.xml']:
 for case in E.parse(P/filename).findall('.//testcase'):
  unique[(case.attrib['classname'],case.attrib['name'])]='fail' if case.find('failure') is not None or case.find('error') is not None else 'skip' if case.find('skipped') is not None else 'pass'
counts={k:sum(v==k for v in unique.values()) for k in ['pass','fail','skip']}
assert counts['fail']==counts['skip']==0
summary={'regressions':counts,'case_count':len(unique),'benchmarks':{}}
for label,name in [('files','benchmark-plugin.json'),('batches','benchmark-batches.json')]:
 rows=json.loads((P/name).read_text())['results'];summary['benchmarks'][label]={}
 for key,v in rows.items():
  a,b=('off','on') if label=='files' else ('sequential','parallel')
  summary['benchmarks'][label][key]={'baseline_ms':v[a]['median_ms'],'new_ms':v[b]['median_ms'],'new_p95_ms':v[b]['p95_ms'],'speedup':v[a]['median_ms']/v[b]['median_ms']}
for mode in ['stock','old','new']:
 summary['benchmarks']['terminal_'+mode]={k:{f:v[f] for f in ['n','median_ms','p95_ms']} for k,v in json.loads((P/('benchmark-terminal-'+mode+'.json')).read_text())['results'].items()}
summary['negative_controls']=json.loads((P/'negative-controls.json').read_text())['controls']
summary['update']=json.loads((P/'update-simulation.json').read_text())['status']
(P/'evidence-summary.json').write_text(json.dumps(summary,indent=2))
(P/'unique-regressions.json').write_text(json.dumps({'counts':counts,'cases':[{'id':'::'.join(k),'verdict':v} for k,v in sorted(unique.items())]},indent=2))
print(json.dumps(summary,indent=2))
