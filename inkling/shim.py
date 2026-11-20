#!/usr/bin/env python3
"""vLLM-dialect adapter in front of an SGLang Inkling-2-Mini server.

The Swarm Lab harness speaks the vLLM dialect it was built against: ``/tokenize`` with chat messages and
``chat_template_kwargs.enable_thinking``, raw ``/v1/completions`` over token ids with ``return_token_ids``,
``</think>`` as the end-of-thinking marker and ``vllm:num_requests_*`` metrics. This adapter maps that
dialect onto Inkling's own format without touching the harness:

* chat prompts are rendered with the checkpoint's own chat template; ``enable_thinking`` True/False maps to
  ``reasoning_effort`` THINK_EFFORT / NOTHINK_EFFORT (an explicit ``reasoning_effort`` wins);
* generated Inkling messages ``<|message_model|><|content_thinking|>…<|end_message|>`` and
  ``<|message_model|><|content_text|>…`` are rendered as ``thinking</think>answer``;
* the forcing suffix ``"\\n</think>\\n"`` tokenizes to Inkling's own close-thinking/open-answer tokens
  ``<|end_message|><|message_model|><|content_text|>``, so a forced continuation stays on the model's
  native format and the server can reuse its prefix cache;
* token ids are the model's real ids; usage is the server's own count.

Stdlib + aiohttp + transformers only (all present in the SGLang image).
"""
import asyncio
import json
import os
import re
import time

import aiohttp
from aiohttp import web
from transformers import AutoTokenizer

UPSTREAM = os.environ.get('UPSTREAM', 'http://127.0.0.1:30000')
MODEL_DIR = os.environ.get('MODEL_DIR', '/model')
LISTEN_HOST = os.environ.get('LISTEN_HOST', '127.0.0.1')
LISTEN_PORT = int(os.environ.get('LISTEN_PORT', '18096'))
SERVED = os.environ.get('SERVED', 'inkling')
THINK_EFFORT = os.environ.get('THINK_EFFORT', 'high')
NOTHINK_EFFORT = os.environ.get('NOTHINK_EFFORT', 'none')

END_MESSAGE, MESSAGE_MODEL, CONTENT_TEXT = 200010, 200001, 200004
FORCE_IDS = [END_MESSAGE, MESSAGE_MODEL, CONTENT_TEXT]
HEADER = re.compile(r'(?:<\|message_model\|>[^<]*)?<\|content_(thinking|text|tool_error|invoke_tool_text|'
                    r'invoke_tool_json)\|>')
DROP = re.compile(r'<\|(?:end_message|content_model_end_sampling|endoftext|message_model)\|>')

tok = AutoTokenizer.from_pretrained(MODEL_DIR)
STATS = dict(requests=0, inflight=0, non_monotonic=0, upstream_errors=0)


def effort(body):
    kwargs = body.get('chat_template_kwargs') or {}
    value = body.get('reasoning_effort', kwargs.get('reasoning_effort'))
    if value is not None:
        return value
    return THINK_EFFORT if kwargs.get('enable_thinking', True) else NOTHINK_EFFORT


def render(text, closed):
    """Inkling generated text (special tokens kept) -> vLLM-dialect 'thinking</think>answer'."""
    out, pos = [], 0
    for match in HEADER.finditer(text):
        out.append(DROP.sub('', text[pos:match.start()]))
        if match.group(1) != 'thinking' and not closed:
            out.append('</think>')
            closed = True
        pos = match.end()
    tail = text[pos:]
    tail = re.sub(r'<\|message_model\|>[^<]*$', '', tail)  # header still waiting for its content tag
    out.append(DROP.sub('', tail))
    return ''.join(out)


def chat_ids(body):
    text = tok.apply_chat_template(body['messages'], tools=body.get('tools'), tokenize=False,
                                   reasoning_effort=effort(body))
    return tok.encode(text, add_special_tokens=False)


async def tokenize(request):
    body = await request.json()
    if 'messages' in body:
        ids = chat_ids(body)
    elif body.get('prompt', '').strip() == '</think>':
        ids = list(FORCE_IDS)
    else:
        ids = tok.encode(body.get('prompt', ''), add_special_tokens=False)
    return web.json_response(dict(tokens=ids, count=len(ids), max_model_len=None))


def finish_of(meta):
    reason = (meta or {}).get('finish_reason')
    if reason is None:
        return None
    kind = reason.get('type') if isinstance(reason, dict) else str(reason)
    return {'stop': 'stop', 'length': 'length'}.get(kind, kind)


async def completions(request):
    body = await request.json()
    prompt = body['prompt']
    if isinstance(prompt, str):
        prompt = tok.encode(prompt, add_special_tokens=False)
    if prompt and isinstance(prompt[0], list):
        return web.json_response({'error': 'batched prompts unsupported'}, status=400)
    closed = bool(prompt) and prompt[-1] == CONTENT_TEXT
    params = dict(max_new_tokens=body.get('max_tokens', 16), temperature=body.get('temperature', 1.0),
                  top_p=body.get('top_p', 1.0), skip_special_tokens=False, spaces_between_special_tokens=False)
    if body.get('seed') is not None:
        params['sampling_seed'] = int(body['seed'])
    if body.get('stop'):
        params['stop'] = body['stop']
    upstream = dict(input_ids=prompt, sampling_params=params, stream=True)
    stream = bool(body.get('stream'))
    cid = 'cmpl-' + os.urandom(8).hex()
    STATS['requests'] += 1
    STATS['inflight'] += 1
    resp = None
    sent_text, sent_ids, last_meta, final_text, ids_all = '', 0, {}, '', []
    try:
        if stream:
            resp = web.StreamResponse(headers={'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache'})
            await resp.prepare(request)
        async with request.app['session'].post(UPSTREAM + '/generate', json=upstream) as up:
            if up.status != 200:
                raise ConnectionError(f'upstream HTTP {up.status}: {(await up.text())[:200]}')
            async for raw in up.content:
                line = raw.decode().strip()
                if not line.startswith('data:') or line == 'data: [DONE]':
                    continue
                chunk = json.loads(line[5:])
                if 'error' in chunk:
                    raise ConnectionError(str(chunk['error'])[:200])
                ids_all = chunk.get('output_ids') or ids_all
                last_meta = chunk.get('meta_info') or last_meta
                final_text = render(chunk.get('text', ''), closed)
                if stream:
                    if final_text.startswith(sent_text):
                        delta, sent_text = final_text[len(sent_text):], final_text
                    else:
                        STATS['non_monotonic'] += 1
                        delta = ''
                    new_ids = ids_all[sent_ids:]
                    sent_ids = len(ids_all)
                    finish = finish_of(last_meta)
                    if delta or new_ids or finish:
                        payload = dict(id=cid, object='text_completion', created=int(time.time()), model=SERVED,
                                       choices=[dict(index=0, text=delta, token_ids=new_ids, finish_reason=finish)])
                        await resp.write(f'data: {json.dumps(payload)}\n\n'.encode())
        usage = dict(prompt_tokens=last_meta.get('prompt_tokens', len(prompt)),
                     completion_tokens=last_meta.get('completion_tokens', len(ids_all)))
        usage['total_tokens'] = usage['prompt_tokens'] + usage['completion_tokens']
        finish = finish_of(last_meta)
        if stream:
            if final_text != sent_text and not final_text.startswith(sent_text):
                STATS['non_monotonic'] += 1
            payload = dict(id=cid, object='text_completion', created=int(time.time()), model=SERVED, choices=[],
                           usage=usage)
            await resp.write(f'data: {json.dumps(payload)}\n\n'.encode())
            await resp.write(b'data: [DONE]\n\n')
            return resp
        return web.json_response(dict(id=cid, object='text_completion', created=int(time.time()), model=SERVED,
                                      choices=[dict(index=0, text=final_text, token_ids=ids_all,
                                                    finish_reason=finish)], usage=usage))
    except (aiohttp.ClientError, ConnectionError, asyncio.TimeoutError) as exc:
        STATS['upstream_errors'] += 1
        message = f'{type(exc).__name__}: {exc}'[:300]
        if resp is not None:
            await resp.write(f'data: {json.dumps(dict(error=dict(message=message)))}\n\n'.encode())
            return resp
        return web.json_response({'error': {'message': message}}, status=502)
    finally:
        STATS['inflight'] -= 1


async def chat(request):
    body = await request.json()
    body['reasoning_effort'] = effort(body)
    kwargs = dict(body.pop('chat_template_kwargs', None) or {})
    kwargs.pop('enable_thinking', None)
    kwargs['reasoning_effort'] = body['reasoning_effort']
    body['chat_template_kwargs'] = kwargs
    body['model'] = SERVED
    STATS['requests'] += 1
    STATS['inflight'] += 1
    try:
        async with request.app['session'].post(UPSTREAM + '/v1/chat/completions', json=body) as up:
            if not body.get('stream'):
                return web.Response(body=await up.read(), status=up.status, content_type='application/json')
            resp = web.StreamResponse(status=up.status, headers={'Content-Type': 'text/event-stream'})
            await resp.prepare(request)
            async for raw in up.content.iter_any():
                await resp.write(raw)
            return resp
    finally:
        STATS['inflight'] -= 1


async def metrics(request):
    async with request.app['session'].get(UPSTREAM + '/metrics') as up:
        text = await up.text()
    values = {}
    for name in ('num_running_reqs', 'num_queue_reqs'):
        m = re.search(rf'^sglang:{name}{{[^}}]*}} (\S+)', text, re.M)
        values[name] = float(m.group(1)) if m else 0.0
    extra = (f'vllm:num_requests_running{{model_name="{SERVED}"}} {values["num_running_reqs"]}\n'
             f'vllm:num_requests_waiting{{model_name="{SERVED}"}} {values["num_queue_reqs"]}\n'
             f'shim:inflight{{}} {STATS["inflight"]}\nshim:requests{{}} {STATS["requests"]}\n'
             f'shim:non_monotonic{{}} {STATS["non_monotonic"]}\nshim:upstream_errors{{}} {STATS["upstream_errors"]}\n')
    return web.Response(text=extra + text, content_type='text/plain')


async def health(request):
    async with request.app['session'].get(UPSTREAM + '/health') as up:
        return web.Response(status=up.status)


async def models(request):
    return web.json_response(dict(object='list', data=[dict(id=SERVED, object='model', owned_by='swarm-lab')]))


async def on_startup(app):
    app['session'] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_read=None),
                                           connector=aiohttp.TCPConnector(limit=0))


async def on_cleanup(app):
    await app['session'].close()


def main():
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_post('/tokenize', tokenize)
    app.router.add_post('/v1/completions', completions)
    app.router.add_post('/v1/chat/completions', chat)
    app.router.add_get('/metrics', metrics)
    app.router.add_get('/health', health)
    app.router.add_get('/v1/models', models)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)


if __name__ == '__main__':
    main()
