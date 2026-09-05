import xml.etree.ElementTree as E,json,sys
from pathlib import Path
P=Path(__file__).parent

def stats(path):
 root=E.parse(path);cases=root.findall('.//testcase')
 return {'tests':len(cases),'failed':sorted(c.attrib.get('classname','')+'::'+c.attrib['name'] for c in cases if c.find('failure') is not None or c.find('error') is not None),'skipped':sum(c.find('skipped') is not None for c in cases)}
base=stats(P/'baseline/files.xml');new=stats(P/'files-final.xml')
result={'files_baseline':base,'files_final':new,'new_failure_ids':sorted(set(new['failed'])-set(base['failed'])),'removed_failure_ids':sorted(set(base['failed'])-set(new['failed']))}
for label,path in [('rpc_final','rpc-broad.xml'),('new_tests','new-tests-final.xml')]:
 if (P/path).exists(): result[label]=stats(P/path)
(P/'regression-comparison.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));sys.exit(bool(result['new_failure_ids']))
