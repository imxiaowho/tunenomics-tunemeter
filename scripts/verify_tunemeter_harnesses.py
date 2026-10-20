"""Synthetic-only checks for the six remaining registered format adapters."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import zipfile
from verify_tunemeter_release import dump, lines, fixtures as pi_workbuddy_fixtures

NAMES=('claude','omp','gemini','openclaw','opencode','qwen')
FIELDS=('input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens','total_tokens')
STAMP='2026-09-01T00:10:00Z'
MILLIS=int(datetime(2026,9,1,0,10,tzinfo=timezone.utc).timestamp()*1000)
EXPECTED={name:dict(zip(FIELDS,(125,20,5,10,3 if name=='opencode' else None,135))) for name in NAMES}
for _name in ('gemini','qwen'):
    EXPECTED[_name]=dict(zip(FIELDS,(100,20,None,12,2,112)))


def fixture(root,name,mode='full'):
    sid='PRIVATE_CANARY_SESSION_'+name
    if name=='claude':
        row=dict(type='assistant',uuid='PRIVATE_CANARY_EVENT',sessionId=sid,timestamp=STAMP,
                 message=dict(id='PRIVATE_CANARY_MESSAGE',role='assistant',model='demo-claude',
                 content='PRIVATE_CANARY_CONTENT',usage=dict(input_tokens=100,output_tokens=10,
                     cache_read_input_tokens=20,cache_creation_input_tokens=5)))
        if mode=='missing':del row['message']['usage']['cache_read_input_tokens']
        if mode=='metadata':row=dict(type='user',sessionId=sid,timestamp=STAMP,message=dict(role='user'))
        path=root/'projects'/'demo'/'session.jsonl';rows=[row]
    elif name in {'omp','openclaw'}:
        row=dict(type='message',id='PRIVATE_CANARY_EVENT',timestamp=STAMP,message=dict(role='assistant',
            model='demo-'+name,content='PRIVATE_CANARY_CONTENT',usage=dict(input=100,output=10,cacheRead=20,cacheWrite=5,totalTokens=135)))
        if mode=='missing':del row['message']['usage']['cacheRead']
        rows=[dict(type='session',id=sid)]+([] if mode=='metadata' else [row])
        path=(root/'sessions'/'demo.jsonl' if name=='omp' else root/'agents'/'demo'/'sessions'/'demo.jsonl')
    elif name=='gemini':
        message=dict(type='gemini',id='PRIVATE_CANARY_EVENT',timestamp=STAMP,model='demo-gemini',
            content='PRIVATE_CANARY_CONTENT',tokens=dict(input=100,output=10,cached=20,thoughts=2,total=112,tool=0))
        if mode=='missing':del message['tokens']['cached']
        rows=[dict(sessionId=sid,messages=[] if mode=='metadata' else [message])]
        path=root/'tmp'/'demo'/'chats'/'session-demo.json'
    elif name=='qwen':
        row=dict(type='assistant',uuid='PRIVATE_CANARY_EVENT',sessionId=sid,timestamp=STAMP,model='demo-qwen',
            content='PRIVATE_CANARY_CONTENT',usageMetadata=dict(promptTokenCount=100,candidatesTokenCount=10,
                cachedContentTokenCount=20,thoughtsTokenCount=2,totalTokenCount=112))
        if mode=='missing':del row['usageMetadata']['cachedContentTokenCount']
        if mode=='metadata':row=dict(type='user',sessionId=sid,timestamp=STAMP)
        rows=[row];path=root/'projects'/'demo'/'chats'/'demo.jsonl'
    else:
        row=dict(id='PRIVATE_CANARY_EVENT',sessionID=sid,role='assistant',modelID='demo-opencode',
            content='PRIVATE_CANARY_CONTENT',time=dict(created=MILLIS),
            tokens=dict(input=100,output=10,reasoning=3,total=135,cache=dict(read=20,write=5)))
        if mode=='missing':del row['tokens']['cache']['read']
        if mode=='metadata':row=dict(sessionID=sid,role='user',time=dict(created=MILLIS))
        rows=[row];path=root/'storage'/'message'/'demo'/'message.json'
    if path.suffix=='.json':dump(path,rows[0])
    else:lines(path,rows)
    if mode=='malformed':
        bad=path.with_name('session-bad.json' if name=='gemini' else 'bad'+path.suffix)
        bad.write_text('{invalid',encoding='utf-8')
    return path,rows


def database(root,v2=False):
    root.mkdir(parents=True,exist_ok=True);path=root/'opencode.db'
    table='session_message' if v2 else 'message'
    data=dict(role='assistant',modelID='demo-opencode',model=dict(id='demo-opencode'),
              content='PRIVATE_CANARY_DB_CONTENT',tokens=dict(input=100,output=10,reasoning=3,total=135,cache=dict(read=20,write=5)))
    with sqlite3.connect(path) as db:
        db.execute(f'CREATE TABLE {table} (id TEXT, session_id TEXT, time_created INTEGER, data TEXT'+(', type TEXT)' if v2 else ')'))
        values=['PRIVATE_CANARY_EVENT','PRIVATE_CANARY_SESSION_DB',MILLIS,json.dumps(data)]
        if v2:values.append('compaction')
        db.execute(f'INSERT INTO {table} VALUES ('+','.join('?' for _ in values)+')',values)
    return path


def codex_fixture(root,mode='full'):
    def counters(prompt,cached,write,output,reason):
        return dict(zip(FIELDS,(prompt,cached,write,output,reason,prompt+output)))
    def token(second,total,last=None):
        info=dict(total_token_usage=total)
        if last is not None:info['last_token_usage']=last
        return dict(type='event_msg',timestamp=f'2026-09-01T00:00:{second:02d}Z',payload=dict(type='token_count',info=info))
    def event(second,kind,**payload):
        return dict(type='event_msg',timestamp=f'2026-09-01T00:00:{second:02d}Z',payload=dict(type=kind,**payload))
    rows=[dict(type='session_meta',timestamp='2026-09-01T00:00:00Z',payload=dict(id='PRIVATE_CANARY_CODEX_SESSION')),
          dict(type='turn_context',timestamp='2026-09-01T00:00:05Z',payload=dict(model='demo-codex',turn_id='PRIVATE_CANARY_TURN')),
          event(10,'task_started',turn_id='PRIVATE_CANARY_TURN'),
          token(11,counters(0,0,0,0,0)),
          token(20,counters(100,20,5,10,2),counters(100,20,5,10,2)),
          token(25,counters(150,30,5,15,3),counters(50,10,0,5,1))]
    if mode=='reset':
        rows += [token(26,counters(10,0,0,1,0)),token(27,counters(18,1,0,2,0),counters(8,1,0,1,0))]
    rows += [event(30,'task_complete',turn_id='PRIVATE_CANARY_TURN')]
    if mode=='missing_cache':
        for row in rows:
            for count in row.get('payload',{}).get('info',{}).values():count.pop('cached_input_tokens',None)
    path=root/'sessions'/'demo.jsonl';lines(path,rows)
    if mode=='copied':lines(root/'archived_sessions'/'copy.jsonl',rows)
    if mode=='malformed':
        with path.open('a',encoding='utf-8') as stream:stream.write('{"type":"token_count",\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.output.expanduser().absolute();root.mkdir(parents=True,exist_ok=False)
    digest=hashlib.sha256(args.package.read_bytes()).hexdigest();app=root/'tunemeter.pyz'
    with zipfile.ZipFile(args.package) as z:app.write_bytes(z.read('tunemeter.pyz'))
    results=[];commands=[]
    def run(label,argv):
        proc=subprocess.run([sys.executable,str(app),*map(str,argv)],capture_output=True,text=True,encoding='utf-8',timeout=30)
        result=json.loads(proc.stdout);evidence=dict(label=label,argv=list(map(str,argv)),exit=proc.returncode,stderr=proc.stderr,result=result)
        commands.append(evidence);dump(root/'commands'/f'{len(commands):03d}.json',evidence)
        assert not proc.stderr,proc.stderr
        return proc.returncode,result
    def check(name,fn):
        try:fn();results.append(dict(name=name,status='passed'))
        except Exception as exc:results.append(dict(name=name,status='failed',error=f'{type(exc).__name__}: {exc}'))
        dump(root/'results.json',results)
    def collect(label,locations):
        argv=['collect','--source',','.join(locations),'--start','2026-09-01','--end','2026-09-30',
              '--timezone','+08:00','--output-dir',root/'out'/label]
        for name,path in locations.items():argv+=['--source-root',f'{name}={path}']
        code,result=run(label,argv)
        assert code in {0,3,4},result
        folder=Path(result['artifacts']['output_directory']);batch=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        return code,result,batch
    def per_source(name,mode):
        location=root/'fixtures'/mode/name;fixture(location,name,mode)
        code,result,batch=collect(name+'-'+mode,{name:location});summary=batch['summary']
        if mode=='metadata':
            assert code==3 and summary['usage_events']==0 and summary['total_tokens'] is None
            assert batch['source_inventory'][0]['status']=='empty'
        else:
            expected=copy.deepcopy(EXPECTED[name])
            if mode=='missing':
                expected['cached_input_tokens']=None
                if name in {'claude','omp','openclaw','opencode'}:expected['input_tokens']=None
                if name=='claude':expected['total_tokens']=None
            assert summary['usage_events']==1 and all(summary[k]==v for k,v in expected.items()),summary
            if mode=='malformed':
                assert batch['issues'].get('malformed_records',0)+batch['issues'].get('unreadable_or_unsupported_files',0)>0,batch['issues']
                assert batch['source_inventory'][0]['status']=='partial'
        assert 'PRIVATE_CANARY_' not in Path(result['artifacts']['html_report']).read_text(encoding='utf-8').upper()
    for name in NAMES:
        for mode in ('full','missing','metadata','malformed'):
            check(name+'_'+mode,lambda n=name,m=mode:per_source(n,m))
    locations={name:root/'fixtures'/'combined'/name for name in NAMES}
    for name,path in locations.items():fixture(path,name)
    code,baseline,batch=collect('combined-six',locations)
    def combined():
        expected=dict(zip(FIELDS,(700,120,20,64,7,764)))
        assert batch['summary']['usage_events']==6 and all(batch['summary'][k]==v for k,v in expected.items()),batch['summary']
        assert {row['harness'] for row in batch['by_source']}==set(NAMES)
    check('six_source_hand_calculated_aggregate',combined)
    def roundtrip():
        for cmd in ('report','export'):
            code,result=run('combined-'+cmd,[cmd,'--input',baseline['artifacts']['output_directory'],'--output-dir',root/'out'/cmd])
            assert code==4 and result['summary']['total_tokens']==764 and result['delivery']['status']=='ready_for_customer_review',result
    check('six_source_report_export_roundtrip',roundtrip)
    def privacy():
        with zipfile.ZipFile(baseline['artifacts']['submission_package']) as z:
            manifest=json.loads(z.read('manifest.json'))
            assert {r['name'] for r in manifest['files']}==set(z.namelist())-{'manifest.json'}
            for row in manifest['files']:assert hashlib.sha256(z.read(row['name'])).hexdigest()==row['sha256']
            text='\n'.join(z.read(n).decode('utf-8-sig') for n in z.namelist())
            assert 'PRIVATE_CANARY_' not in text.upper()
            report=json.loads(z.read('summary.json'))
            assert 'usage_events' not in report and 'sessions' not in report and 'turns' not in report
    check('six_source_bundle_privacy_integrity',privacy)
    def omp_namespace():
        location=root/'fixtures'/'omp-sidecall';path,rows=fixture(location,'omp')
        rows.append(dict(type='model_usage',id=rows[1]['id'],timestamp=STAMP,model='demo-omp',usage=rows[1]['message']['usage']))
        lines(path,rows);code,result,local=collect('omp-sidecall',{'omp':location})
        assert local['summary']['usage_events']==2 and local['summary']['total_tokens']==270
        assert {e['accounting']['native_kind'] for e in local['usage_events']}=={'message','model_usage'}
    check('omp_sidecall_identity_namespace',omp_namespace)
    def sqlite_case(v2=False,sidecar=False,unknown=False):
        label='sqlite-'+('v2' if v2 else 'legacy')+('-wal' if sidecar else '')+('-unknown' if unknown else '')
        location=root/'fixtures'/label
        if unknown:
            location.mkdir(parents=True);path=location/'opencode.db'
            with sqlite3.connect(path) as db:db.execute('CREATE TABLE unrelated (value TEXT)')
        else:path=database(location,v2)
        if sidecar:Path(str(path)+'-wal').write_bytes(b'PRIVATE_CANARY_WAL')
        before=hashlib.sha256(path.read_bytes()).hexdigest();code,result,local=collect(label,{'opencode':location})
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before
        if sidecar or unknown:
            assert code==3 and local['summary']['total_tokens'] is None
            issue='live_database_sidecars_not_read' if sidecar else 'unsupported_database_schema'
            assert local['issues'].get(issue,0)>0,local['issues']
        else:
            assert local['summary']['usage_events']==1 and all(local['summary'][k]==v for k,v in EXPECTED['opencode'].items()),local['summary']
            assert not Path(str(path)+'-wal').exists() and not Path(str(path)+'-shm').exists()
    check('opencode_sqlite_legacy_readonly',lambda:sqlite_case())
    check('opencode_sqlite_v2_compaction_readonly',lambda:sqlite_case(v2=True))
    check('opencode_sqlite_active_sidecar_unknown',lambda:sqlite_case(sidecar=True))
    check('opencode_unknown_database_not_zero',lambda:sqlite_case(unknown=True))
    def openclaw_db():
        location=root/'fixtures'/'openclaw-db';path=location/'agents'/'demo'/'agent'/'openclaw-agent.sqlite'
        path.parent.mkdir(parents=True);path.write_bytes(b'PRIVATE_CANARY_UNSUPPORTED')
        code,result,local=collect('openclaw-db',{'openclaw':location})
        assert code==3 and local['summary']['total_tokens'] is None
        assert local['issues'].get('unsupported_openclaw_sqlite_store',0)>0
    check('openclaw_database_gap_not_zero',openclaw_db)
    def codex_case(mode):
        location=root/'fixtures'/('codex-'+mode);codex_fixture(location,mode)
        code,result,local=collect('codex-'+mode,{'codex':location});summary=local['summary']
        assert summary['usage_events']==(3 if mode=='reset' else 2),summary
        assert summary['total_tokens']==(174 if mode=='reset' else 165),summary
        assert summary['completed_turns']==1 and summary['turn_seconds']==20 and summary['covered_seconds']==20,summary
        if mode=='missing_cache':assert summary['cached_input_tokens'] is None
        if mode=='reset':assert local['issues'].get('counter_reset_baselines_excluded',0)>0
        if mode=='malformed':assert local['issues'].get('malformed_selected_lines',0)>0
        if mode=='copied':assert summary['sessions_observed']==1 and summary['files_read']==2
    for mode in ('full','copied','missing_cache','reset','malformed'):
        check('codex_'+mode,lambda m=mode:codex_case(m))
    def nine_sources():
        pi,wb=pi_workbuddy_fixtures(root/'fixtures'/'nine-pi-wb')
        all_locations=dict(locations,codex=root/'fixtures'/'codex-full',pi=pi,workbuddy=wb)
        code,result,local=collect('nine-explicit-sources',all_locations)
        expected=dict(zip(FIELDS,(1155,210,30,106,13,1261)))
        assert local['summary']['usage_events']==12 and all(local['summary'][k]==v for k,v in expected.items()),local['summary']
        assert len(local['by_source'])==9 and local['summary']['covered_seconds']==20
        code,exported=run('nine-export',['export','--input',result['artifacts']['output_directory'],'--output-dir',root/'out'/'nine-export'])
        assert code==4 and exported['summary']['total_tokens']==1261 and exported['delivery']['status']=='ready_for_customer_review'
    check('nine_explicit_roots_aggregate_and_export',nine_sources)
    def unchanged():assert hashlib.sha256(args.package.read_bytes()).hexdigest()==digest
    check('package_unchanged',unchanged)
    failed=[row for row in results if row['status']=='failed']
    receipt=dict(at=datetime.now(timezone.utc).isoformat(),package_sha256=digest,python=sys.version,
        platform=platform.platform(),checks=len(results),passed=len(results)-len(failed),failed=len(failed),cli_invocations=len(commands))
    dump(root/'receipt.json',receipt)
    report=['# TuneMeter 六适配器与 Codex／九源组合虚构数据复测','',f"结果：{receipt['passed']}/{receipt['checks']} 项通过，失败 {len(failed)} 项。",
        f"包 SHA256：`{digest}`",f"Python：`{sys.version.split()[0]}`；平台：`{platform.platform()}`",'',
        '| 检查 | 结果 |','| --- | --- |']
    report += [f"| {row['name']} | {row['status']} |" for row in results]
    report += ['', '## 失败详情']+[f"- {row['name']}: {row['error']}" for row in failed]
    report += ['', '## 限制','只测本脚本生成的已知格式与基本 Codex 累计／时间路径，不认证真实客户端版本、完整 fork 迁移历史或全部 SQLite 布局。无真实日志、source all、联网、安装、浏览器视觉或跨平台验证。',
        'fixture 依据实现字段构造，期望合计独立指定；通过说明当前实现遵循该合成契约，不等于官方格式认证或九底座真实兼容。']
    (root/'report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(root),**receipt,failures=failed),ensure_ascii=False))
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
