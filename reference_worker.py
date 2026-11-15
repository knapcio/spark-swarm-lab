#!/usr/bin/env python3
"""Plan-first, direct-only transport adapter for the unchanged frozen verifiers."""
import argparse
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
SOURCE_REVISION = 'cbcde299716b7842536b008880a089590e9816f8'
SENTINEL = 'http://opus-reference.invalid/v1'
OPUS = 'claude-opus-5-5'


def json_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def source_pin(source):
    revision = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    require(revision == SOURCE_REVISION, 'Wrong frozen evaluation source revision')
    require(not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True).strip(), 'Frozen tracked source changed')
    names = subprocess.check_output(['git', '-C', str(source), 'ls-files'], text=True).splitlines()
    return dict(revision=revision, sha256={n: sha(source / n) for n in names if (source / n).is_file()})


def verify_gate(root, audit_cohorts=True):
    """Final follow-up receipt, original-development and primary gates, hash-linked."""
    runs = root / 'runs'
    read = lambda name: json.loads((runs / name).read_text())
    final = read('throughput-followup-v2-complete.json')
    require(final.get('verified') is True and final.get('development_cohorts') == 16 and final.get('evaluation_cohorts') == 9, 'Final throughput-v2 completion required')
    for key, name in [('ledger_sha256', 'throughput-followup-v2-ledger.json'), ('selection_sha256', 'throughput-followup-v2-selection.json')]:
        require(final.get(key) == sha(runs / name), 'Final throughput audit hash mismatch')
    original = read('throughput-development-v2-recovery.json')
    require(all(original.get(k) is True for k in ['verified', 'development_complete', 'primary_complete', 'solo_complete']), 'Original throughput gate incomplete')
    require(original.get('ledger_sha256') == sha(runs / 'throughput-development-v2-ledger.json'), 'Original throughput ledger changed')
    primary = read('evaluation-v2-state.json')
    require(primary.get('protocol') == 'clean-serving-evaluation-v2' and all(primary.get(k) is True for k in ['verified', 'primary_complete', 'solo_complete']), 'Primary and solo gates incomplete')
    for filename, count in [('throughput-development-v2-ledger.json', 20), ('throughput-followup-v2-ledger.json', 25)]:
        entries = read(filename)
        require(len(entries) == count and len({e['name'] for e in entries}) == count, 'Throughput matrix incomplete/duplicate')
        for e in entries:
            require(e.get('verified') is True and e.get('returncode') == 0 and e.get('incomplete') is False and e.get('source_changed') is False and e.get('source_revision') == final['source_revision'] and '-v2-' in e['name'], 'Unverified/mixed-runtime throughput cohort')
            require(e.get('completed_cases') == (96 if e.get('split') == 'evaluation' else 32), 'Throughput case count mismatch')
            for name in (['metadata', 'summary', 'cohort'] if audit_cohorts else []):
                require(e.get('audit', {}).get(name + '_sha256') == sha(runs / e['name'] / (name + '.json')), 'Throughput cohort audit changed')
    return dict(completion_sha256=sha(runs / 'throughput-followup-v2-complete.json'), source_revision=final['source_revision'])


def cli_settings(cli, body):
    require(body.get('model') == OPUS and body.get('max_tokens') == 8192, 'Opus reference must use exact pinned model and 8192 output cap')
    messages = body['messages']
    require([m['role'] for m in messages] == ['system', 'user'] and all(isinstance(m['content'], str) for m in messages), 'Expected exact system/user messages')
    argv = [cli, '--safe-mode', '--restricted', '--print', '--model', OPUS, '--effort', 'medium',
            '--system-prompt', messages[0]['content'], '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
            '--disable-slash-commands', '--no-chrome', '--setting-sources', '', '--settings', '{"disableAllHooks":true}',
            '--no-session-persistence', '--permission-prompts', 'none', '--max-turns', '1', '--output-format', 'json']
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('ANTHROPIC_', 'CLAUDE_CODE_')) and key not in ('CLAUDE_CODE_OAUTH_TOKEN',):
            env.pop(key)
    env.update(CLAUDE_CODE_MAX_OUTPUT_TOKENS='8192', CLAUDE_CODE_MAX_TURNS='1', CLAUDE_CODE_EFFORT_LEVEL='medium',
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', CLAUDE_CODE_DISABLE_CLAUDE_MDS='1',
               CLAUDE_CODE_DISABLE_AUTO_MEMORY='1', CLAUDE_CODE_DISABLE_BACKGROUND_TASKS='1', CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION='false')
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        env.pop(key, None)
    return argv, env, messages[1]['content']


def token_usage(result):
    raw = result.get('usage') or {}
    keys = ['input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens']
    valid = lambda value: type(value) is int and value >= 0
    usage = {}
    # input_tokens excludes cache-read/write tokens in Anthropic accounting.
    if all(valid(raw.get(k)) for k in keys):
        usage['prompt_tokens'] = sum(raw.get(k, 0) for k in keys)
    if valid(raw.get('output_tokens')):
        usage['completion_tokens'] = raw['output_tokens']
    if len(usage) == 2:
        usage['total_tokens'] = sum(usage.values())
    return usage


class OpusTransport:
    def __init__(self, cli, record, runner=subprocess.run):
        self.cli, self.record, self.runner = cli, Path(record), runner

    def __call__(self, request, timeout=None, **kwargs):
        require(request.full_url == SENTINEL + '/chat/completions', 'Opus adapter refuses non-sentinel HTTP requests')
        body = json.loads(request.data)
        argv, env, prompt = cli_settings(self.cli, body)
        evidence = dict(provider='anthropic_cli', requested_model=OPUS, request=body,
                        request_sha256=hashlib.sha256(request.data).hexdigest(), argv=argv,
                        actual_parameters=dict(output_cap=8192, effort='medium', reasoning='adaptive_always_on'),
                        unsupported_not_forwarded=['temperature', 'seed', 'chat_template_kwargs'],
                        system_sha256=hashlib.sha256(body['messages'][0]['content'].encode()).hexdigest(),
                        user_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                        settings_sha256=json_sha(dict(argv=argv, per_process_controls={k:v for k,v in env.items() if k.startswith('CLAUDE_CODE_') and 'TOKEN' not in k})),
                        seed_scope='replication label only; no provider seed', environment_keys_set=sorted(k for k in env if k.startswith('CLAUDE_CODE_')),
                        finish_reason=None, stop_reason_status='unknown_unless_cli_reports_it')
        start = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix='swarm-opus-reference-') as cwd:
                # Inherit the case process group: the existing controller owns deadline termination.
                completed = self.runner(argv, input=prompt.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        cwd=cwd, env=env, timeout=timeout, start_new_session=False)
            stderr = completed.stderr or b''
            evidence.update(cli_returncode=completed.returncode, stderr_bytes=len(stderr), stderr_sha256=hashlib.sha256(stderr).hexdigest(),
                            stdout_bytes=len(completed.stdout), stdout_sha256=hashlib.sha256(completed.stdout).hexdigest())
            require(completed.returncode == 0, 'Opus CLI process failed (stderr retained only as hash/size)')
            result = json.loads(completed.stdout)
            evidence.update({k: result.get(k) for k in ['result', 'usage', 'modelUsage', 'num_turns', 'is_error', 'subtype', 'stop_reason', 'total_cost_usd', 'duration_ms', 'duration_api_ms']})
            require(not result.get('is_error') and isinstance(result.get('result'), str), 'Opus CLI returned an error or no model text')
            models = result.get('modelUsage')
            require(isinstance(models, dict) and len(models) == 1, 'Opus actual single-model usage identity missing/ambiguous')
            raw_model, actual = next(iter(models.items()))
            require(actual.get('canonicalModel', raw_model) == OPUS and actual.get('provider') == 'firstParty', 'Opus actual model/provider mismatch')
            require(result.get('num_turns') == 1, 'Opus reference must complete one agentic turn')
            reason = result.get('stop_reason')
            evidence['finish_reason'] = 'length' if reason == 'max_tokens' else reason
            usage = token_usage(result)
            evidence.update(usage_sha256=json_sha(result.get('usage')), model_usage_sha256=json_sha(models))
            evidence.update(mapped_usage=usage, usage_missing_fields=[k for k in ['prompt_tokens', 'completion_tokens'] if k not in usage],
                            input_accounting='uncached input + cache-read input + cache-creation input; output includes thinking',
                            stderr_classification='empty' if not stderr else 'nonempty_uninspected')
            return io.BytesIO(json.dumps(dict(choices=[dict(message=dict(content=result['result']), finish_reason=evidence['finish_reason'])], usage=usage)).encode())
        except BaseException as exc:
            evidence['failure_classification'] = 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else type(exc).__name__
            # Never put raw CLI stderr, account details or exception payloads into harness events.
            raise RuntimeError('Opus transport failure: ' + evidence['failure_classification']) from None
        finally:
            evidence['transport_wall_seconds'] = time.monotonic() - start
            with self.record.open('a') as output:
                output.write(json.dumps(evidence, ensure_ascii=False) + '\n')


class OpenAIRecorder:
    """Record only the selected endpoint; preserve its normal OpenAI transport."""
    def __init__(self, endpoint, record, urlopen):
        self.url = endpoint.rstrip('/') + '/chat/completions'
        self.record, self.urlopen = Path(record), urlopen

    def __call__(self, request, timeout=None, **kwargs):
        require(request.full_url == self.url, 'Reference transport refuses unexpected endpoint')
        evidence = dict(provider='deepseek_openai', request=json.loads(request.data),
                        request_sha256=hashlib.sha256(request.data).hexdigest())
        start = time.monotonic()
        try:
            with self.urlopen(request, timeout=timeout, **kwargs) as response:
                raw = response.read()
            result = json.loads(raw)
            evidence.update(raw_response=result, response_sha256=hashlib.sha256(raw).hexdigest())
            return io.BytesIO(raw)
        except BaseException as exc:
            evidence['failure_classification'] = type(exc).__name__
            raise RuntimeError('Reference OpenAI transport failure: ' + type(exc).__name__) from None
        finally:
            evidence['transport_wall_seconds'] = time.monotonic() - start
            with self.record.open('a') as output:
                output.write(json.dumps(evidence, ensure_ascii=False) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['opus', 'deepseek'], required=True)
    parser.add_argument('--source', type=Path, default=HERE / '.runtime/evaluation-v2-source')
    parser.add_argument('--domain', choices=['arithmetic', 'coding'], required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--transport-record', type=Path, required=True)
    parser.add_argument('--cli', default=str(Path.home() / '.local/bin/claude'))
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('harness_args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    forwarded = args.harness_args[1:] if args.harness_args[:1] == ['--'] else args.harness_args
    require('--method' in forwarded and forwarded[forwarded.index('--method') + 1] == 'direct', 'Reference worker supports only frozen direct methods')
    if not args.run or args.plan:
        print(json.dumps(dict(mode='plan', provider=args.provider, model=args.model, source=str(args.source), domain=args.domain, harness_args=forwarded)))
        return 0
    verify_gate(HERE, audit_cohorts=False)
    pin = source_pin(args.source)
    require(not args.transport_record.exists() and not args.transport_record.with_suffix('.context.json').exists(), 'Transport/context record already exists')
    sys.path.insert(0, str(args.source))
    h = importlib.import_module('harness')
    original = h.Client
    class NamedClient(original):
        def __init__(self, endpoints, model, *values, **kwargs):
            super().__init__(endpoints, args.model, *values, **kwargs)
    h.Client = NamedClient
    if args.provider == 'opus':
        require(args.model == OPUS, 'Only exact preflighted Opus model is supported')
        urllib.request.urlopen = OpusTransport(args.cli, args.transport_record)
    else:
        endpoint = forwarded[forwarded.index('--endpoint') + 1]
        urllib.request.urlopen = OpenAIRecorder(endpoint, args.transport_record, urllib.request.urlopen)
    cli_version = subprocess.check_output([args.cli, '--version'], text=True, timeout=20).strip() if args.provider == 'opus' else None
    args.transport_record.with_suffix('.context.json').write_text(json.dumps(dict(source=pin, provider=args.provider, model=args.model, cli_version=cli_version,
        worker_sha256=sha(__file__), argv=forwarded, opus_preflight_sha256=sha(HERE.parent.parent / 'diagnostics/swarm-prototype-20261115/opus-access-preflight-20261115.json') if args.provider == 'opus' else None, scope='Separate strong-model reference; never pool with Nemotron',
        timing='Case controller wall includes CLI startup/auth/network or local endpoint time plus grading; not GPU decode throughput'), indent=2) + '\n')
    module = h if args.domain == 'arithmetic' else importlib.import_module('coding_harness')
    return module.main(forwarded)


if __name__ == '__main__':
    raise SystemExit(main())
