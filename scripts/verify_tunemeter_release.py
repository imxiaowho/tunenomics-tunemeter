"""Repeatable synthetic-only CLI release checks; never probe default roots."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import zipfile

FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens',
          'output_tokens', 'reasoning_output_tokens', 'total_tokens')


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')


def pi_event(identity, minute=10, small=False, marker='A'):
    usage = dict(input=50 if small else 100, cacheRead=10 if small else 20,
                 cacheWrite=0 if small else 5, output=5 if small else 10,
                 totalTokens=65 if small else 135)
    return dict(type='message', id=identity, timestamp=f'2026-09-01T00:{minute:02d}:00Z',
                message=dict(role='assistant', model='sentinel-model-pi', usage=usage,
                             content=f'PRIVATE_CANARY_CONTENT_{marker}',
                             tool_arguments={'path': f'C:/PRIVATE_CANARY_PATH_{marker}'}))


def header(identity, parent=None):
    row = dict(type='session', id=identity)
    if parent is not None:
        row['parentSession'] = str(parent)
    return row


def fixtures(root, marker='A'):
    pi = root / 'pi'; wb = root / 'wb'
    sid = f'PRIVATE_CANARY_SESSION_{marker}'
    lines(pi / 'sessions' / f'date_{sid}.jsonl', [header(sid),
          pi_event(f'PRIVATE_CANARY_EVENT_{marker}_1', marker=marker),
          pi_event(f'PRIVATE_CANARY_EVENT_{marker}_2', 11, True, marker)])
    rows = []
    for i, (prompt, cached, output, reasoning) in enumerate(((80, 20, 8, 2), (40, 10, 4, 1))):
        rows.append(dict(type='function_call' if i == 0 else 'message', role='assistant',
            id=f'PRIVATE_CANARY_EVENT_WB_{marker}_{i}', sessionId=f'PRIVATE_CANARY_SESSION_WB_{marker}',
            timestamp=f'2026-09-01T00:{12+i}:00Z',
            message=dict(content=f'PRIVATE_CANARY_CONTENT_{marker}', usage=dict(
                input_tokens=prompt, cache_read_input_tokens=cached,
                output_tokens=output, total_tokens=prompt+output)),
            providerData=dict(model='sentinel-model-wb', rawUsage=dict(
                cache_creation_input_tokens=0, credit=987654,
                completion_tokens_details=dict(reasoning_tokens=reasoning)))))
    lines(wb / 'projects' / 'demo' / 'session.jsonl', rows)
    return pi, wb


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = []; self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'script', 'iframe', 'object', 'embed'}:
            self.active.append(tag)
        if any(k.startswith('on') for k in attrs):
            self.active.append('event_handler')
        if any(k in {'src', 'href'} and str(v).startswith(('http:', 'https:', '//')) for k, v in attrs.items()):
            self.active.append('external_resource')

    def handle_data(self, data):
        self.text.append(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory; never overwritten')
    args = parser.parse_args()
    root = args.output.expanduser().absolute(); root.mkdir(parents=True, exist_ok=False)
    original = args.package.read_bytes(); digest = hashlib.sha256(original).hexdigest()
    app = root / 'tunemeter.pyz'
    with zipfile.ZipFile(args.package) as archive:
        app.write_bytes(archive.read('tunemeter.pyz'))
    results = []; commands = []; counter = 0

    def run(label, argv):
        nonlocal counter
        counter += 1
        proc = subprocess.run([sys.executable, str(app), *map(str, argv)],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)
        result = json.loads(proc.stdout)
        evidence = dict(label=label, argv=list(map(str, argv)), exit=proc.returncode,
                        stderr=proc.stderr, result=result)
        commands.append(evidence); dump(root / 'commands' / f'{counter:03d}.json', evidence)
        assert not proc.stderr, 'Unexpected stderr'
        return proc.returncode, result

    def check(name, operation):
        try:
            operation(); results.append(dict(name=name, status='passed'))
        except Exception as exc:
            results.append(dict(name=name, status='failed', error=f'{type(exc).__name__}: {exc}'))
        dump(root / 'results.json', results)

    def collect(label, pi, wb=None):
        argv = ['collect', '--source', 'pi,workbuddy' if wb else 'pi',
                '--source-root', f'pi={pi}', '--start', '2026-09-01', '--end', '2026-09-30',
                '--timezone', '+08:00', '--output-dir', root / 'out' / label]
        if wb:
            argv += ['--source-root', f'workbuddy={wb}']
        code, result = run(label, argv)
        assert code in {0, 4}, (label, code, result.get('issues'))
        folder = Path(result['artifacts']['output_directory'])
        batch = json.loads((folder / 'summary.json').read_text(encoding='utf-8'))
        return result, batch

    pi, wb = fixtures(root / 'fixtures' / 'base')
    baseline, batch = collect('baseline', pi, wb)

    def baseline_check():
        expected = dict(usage_events=4, input_tokens=305, cached_input_tokens=60,
                        cache_write_input_tokens=5, output_tokens=27, reasoning_output_tokens=3, total_tokens=332)
        assert all(batch['summary'][k] == value for k, value in expected.items()), batch['summary']
        assert baseline['delivery']['status'] == 'ready_for_customer_review'
    check('hand_calculated_mixed_baseline', baseline_check)

    def import_case(name, mutate, expected, detail=None, index=None):
        changed = copy.deepcopy(batch); mutate(changed)
        path = root / 'cases' / f'{name}.json'; dump(path, changed)
        for command in ('report', 'export'):
            output = root / 'out' / f'{name}-{command}'
            argv = [command, '--input', path, '--output-dir', output]
            if command == 'report': argv += ['--format', 'json']
            code, result = run(f'{name}-{command}', argv)
            assert code == 2 and result.get('error_kind') == expected, result
            if detail:
                assert result['error_details']['code'] == detail
                assert set(result['error_details']) <= {'code', 'section', 'fields', 'event_index', 'source'}
                if index is not None: assert result['error_details']['event_index'] == index
            else: assert 'error_details' not in result
            assert not output.exists() or not any(output.rglob('*')), 'Failure wrote files'
            assert 'PRIVATE_CANARY_' not in json.dumps(result) and 'native_usage' not in json.dumps(result)

    mutations = (
        ('source_count', lambda b: b['source_inventory'][0].update(usage_events=3), 'SnapshotConsistencyError', 'source_event_count_conflict', None),
        ('native_conflict', lambda b: b['usage_events'][1].update(total_tokens=66), 'SnapshotConsistencyError', 'native_normalized_conflict', 1),
        ('summary_conflict', lambda b: b['summary'].update(total_tokens=333), 'SnapshotConsistencyError', 'summary_aggregate_conflict', None),
        ('wrong_type', lambda b: b['usage_events'][0].update(total_tokens='PRIVATE_CANARY_ILLEGAL'), 'ValueError', None, None),
        ('negative', lambda b: b['usage_events'][0].update(input_tokens=-1), 'ValueError', None, None),
        ('null_events', lambda b: b.update(usage_events=None), 'ValueError', None, None),
    )
    for name, mutate, error, detail, index in mutations:
        check(name, lambda n=name, m=mutate, e=error, d=detail, i=index: import_case(n, m, e, d, i))

    def missing_events():
        changed = copy.deepcopy(batch); del changed['usage_events']
        path = root / 'cases' / 'missing.json'; dump(path, changed)
        code, result = run('missing-report', ['report', '--input', path, '--format', 'json'])
        assert code == 4 and result['report']['summary']['total_tokens'] == 332
        assert all(row['total_tokens'] is None for row in result['by_source'])
        code, result = run('missing-export', ['export', '--input', path, '--output-dir', root/'out'/'missing-export'])
        assert code == 2 and result['delivery']['status'] == 'blocked' and not result['artifacts']
    check('missing_event_evidence', missing_events)

    def lineage_case(kind):
        pi = root/'fixtures'/kind/'pi'; a=pi/'sessions'/'archive'/'date_root-a.jsonl'
        b=pi/'sessions'/'branch'/'date_child-a.jsonl'
        first=pi_event('PRIVATE_CANARY_REPLAY'); second=pi_event('PRIVATE_CANARY_NEW', 11, True)
        declared = a if kind == 'direct' else pi/'sessions'/'old'/'date_root-a.jsonl'
        if kind != 'missing_parent':
            lines(a, [header('different-id' if kind == 'header_mismatch' else 'root-a', b if kind == 'cycle' else None), first])
        if kind == 'ambiguous': lines(pi/'sessions'/'second'/'date_root-a.jsonl', [header('root-a'), first])
        if kind == 'cycle': declared = a
        lines(b, [header('child-a', declared), first, second])
        result, local = collect('lineage-'+kind, pi)
        if kind in {'direct','relocated'}:
            assert local['summary']['usage_events'] == 2 and local['summary']['total_tokens'] == 200
            assert result['delivery']['status'] == 'ready_for_customer_review'
            if kind == 'relocated': assert local['issues']['resolved_lineage_parents_by_filename'] == 1
        else:
            expected_issue = {'ambiguous': 'ambiguous_lineage_parents',
                'header_mismatch': 'lineage_parent_header_mismatch',
                'missing_parent': 'unresolved_lineage_parents', 'cycle': 'cyclic_lineage_headers'}[kind]
            assert local['issues'].get(expected_issue, 0) > 0, local['issues']
            assert result['delivery']['status'] == 'blocked'
            assert 'submission_package' not in result['artifacts']
            code, refused = run('lineage-export-'+kind, ['export','--input',result['artifacts']['output_directory'],
                                '--output-dir',root/'out'/('refused-'+kind)])
            assert code == 2 and refused['delivery']['status'] == 'blocked'
    for kind in ('direct','relocated','ambiguous','header_mismatch','missing_parent','cycle'):
        check('lineage_'+kind, lambda k=kind: lineage_case(k))

    def unrelated():
        pi=root/'fixtures'/'unrelated'/'pi'
        for sid in ('one','two'):
            lines(pi/'sessions'/f'date_{sid}.jsonl',[header(sid),pi_event('same-short-id')])
        result, local=collect('unrelated',pi)
        assert local['summary']['usage_events']==2 and local['summary']['total_tokens']==270
        assert result['delivery']['status']=='ready_for_customer_review'
    check('unrelated_short_ids_stay_separate', unrelated)

    def manifest_privacy():
        with zipfile.ZipFile(baseline['artifacts']['submission_package']) as z:
            manifest=json.loads(z.read('manifest.json'))
            declared={row['name']:row['sha256'] for row in manifest['files']}
            assert set(declared)==set(z.namelist())-{'manifest.json'}
            for name, expected in declared.items(): assert hashlib.sha256(z.read(name)).hexdigest()==expected, name
            texts={name:z.read(name).decode('utf-8-sig') for name in z.namelist()}
        combined='\n'.join(texts.values())
        assert 'PRIVATE_CANARY_' not in combined.upper(), 'Sensitive marker propagated'
        for sid in ('PRIVATE_CANARY_SESSION_A','PRIVATE_CANARY_SESSION_WB_A'):
            assert 'S-'+hashlib.sha256(sid.encode()).hexdigest()[:12] not in combined
        assert 'sentinel-model-pi' in combined and 'sentinel-model-wb' in combined
        def walk(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    assert key!='native_usage', 'Native object in submitted JSON'
                    assert not (key in {'usage_events','sessions','turns'} and isinstance(item,list))
                    walk(item)
            elif isinstance(value,list):
                for item in value:walk(item)
        walk(json.loads(texts['summary.json']))
        dump(root/'privacy-classification.json',dict(sensitive_marker_hits=0,
            allowed_model_labels=['sentinel-model-pi','sentinel-model-wb'],
            broad_sentinel_hits=len(re.findall('sentinel-',combined,re.I)),
            allowed_manifest_sha256_count=len(declared),manifest_entries_verified=len(declared),
            limit='Marker/structure checks only; not anonymity or full reidentification proof'))
    check('manifest_every_file_and_classified_privacy',manifest_privacy)

    def differential():
        p,w=fixtures(root/'fixtures'/'different','B');result,local=collect('different-markers',p,w)
        for key in ('usage_events',*FIELDS):assert local['summary'][key]==batch['summary'][key]
        with zipfile.ZipFile(result['artifacts']['submission_package']) as z:
            combined='\n'.join(z.read(n).decode('utf-8-sig') for n in z.namelist())
        assert 'PRIVATE_CANARY_' not in combined.upper()
        assert all(local['by_source'][i][k]==batch['by_source'][i][k] for i in range(2) for k in ('usage_events',*FIELDS))
    check('limited_identifier_differential',differential)

    def html_check():
        code,result=run('html-report',['report','--input',baseline['artifacts']['output_directory'],
                         '--format','html','--output-dir',root/'out'/'html'])
        assert code==4
        text=Path(result['artifacts']['html_report']).read_text(encoding='utf-8');page=Page();page.feed(text)
        assert not page.active and 'PRIVATE_CANARY_' not in text.upper()
        assert 'TuneMeter' in text and '2 个来源有本期用量记录' in ''.join(page.text)
    check('html_generation_and_structure',html_check)
    def unchanged():
        assert hashlib.sha256(args.package.read_bytes()).hexdigest()==digest, 'Package changed'
    check('original_package_unchanged',unchanged)

    failed=[r for r in results if r['status']!='passed']
    metadata=dict(at=datetime.now(timezone.utc).isoformat(),package_sha256=digest,
                  python=sys.version,platform=platform.platform(),checks=len(results),
                  passed=len(results)-len(failed),failed=len(failed),cli_invocations=len(commands))
    dump(root/'receipt.json',metadata)
    report=['# TuneMeter 独立虚构数据复测','',
            f"结果：{metadata['passed']}/{metadata['checks']} 项通过；失败 {len(failed)} 项。",
            f"被测 CLI ZIP SHA256：`{digest}`",f"Python：`{sys.version.split()[0]}`；平台：`{platform.platform()}`",'',
            '仅运行本脚本生成的 Pi/WorkBuddy 虚构目录；无真实日志、联网、安装或包修改。',
            '逐次 CLI 命令、退出码和信封保存在 commands/；结果见 results.json。','',
            '| 检查 | 结果 |','| --- | --- |']
    report += [f"| {row['name']} | {row['status']} |" for row in results]
    for row in failed:report += ['',f"失败 {row['name']}：{row['error']}"]
    report += ['', '## 边界','',
        'HTML 仅验证实际生成和结构，不是浏览器视觉检查。标记差分只证明本组标记替换未改变已断言聚合，不证明不可重识别或绝对匿名。',
        'manifest 验证的是包内文件一致性，不是加密签名或原始记录认证。允许模型标签和清单哈希与敏感哨兵分别分类。',
        '未覆盖真实用户数据、其他六个适配器、Codex 新运行回归、跨平台和全部损坏输入。']
    (root/'report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(root),**metadata,failures=failed),ensure_ascii=False))
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(main())
