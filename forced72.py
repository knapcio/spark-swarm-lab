"""Client-side budget forcing: end the model's own thinking and let it continue the SAME sequence.

Call 1 (thinking on): the chat prompt rendered by the server's own chat template, then raw
completion up to THINK_CAP tokens. If the model closes its thinking itself, its answer is parsed.
If it is cut by the cap without closing its thinking, call 2 sends the exact same token sequence
(prompt + every generated token) followed by "\n</think>\n" and lets the model continue, within the
remaining completion budget. Nothing is copied into a new user message; the server can reuse its
prefix cache. Same rules, verifier, parser and Budget(2 calls, 8192 completion tokens) as scribe.

Transport has no wall-clock quality limit: responses stream, and only a gap of IDLE_TIMEOUT seconds
without any streamed byte (a hung server) or the WALL_LIMIT catastrophe stop counts as a failure.
A genuine transport loss (see transport_lost) is re-sent once, same body and seed, after RETRY_DELAY s and only
within WALL_LIMIT ('request_retry' event). The lost attempt's streamed token count (a lower bound) is charged once in
the accounting (usage.completion_tokens, which the controller tallies, and completion_tokens_charged; request_end gets
attempts=2 and per-attempt counts) but NOT in the Budget: the retry and the forced answer get exactly the budgets an
unretried request gets. A second failure is a failure as before; a request that succeeds at once is unchanged.
No CPU search, teacher, gold answer or cross-case memory.
"""
import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
import uuid

from direct_solver import replay_plan
from followup72 import prompt_for, sha
from harness import parse_json_response

SYSTEM = 'Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.'
VARIANTS = {'forced_explicit': 'index_explicit', 'forced_original': 'index_original',
            'plain_original': 'index_original', 'long_forced_explicit': 'index_explicit',
            'long_forced_original': 'index_original', 'xl_forced_original': 'index_original',
            'xxl_forced_original': 'index_original', 'xl_forced_leftover': 'index_original'}
# long_*: same agent with the whole 16K context: thinking up to 14848, total completion 16000.
# plain_original = the original single reasoning call (index_original, 8192, no second call) on this transport.
THINK_CAP = 7168
TOTAL = 8192  # defaults; per-variant caps in CAPS
CAPS = {name: (14848, 16000) if name.startswith('long_') else (THINK_CAP, TOTAL) for name in VARIANTS}
# xl_*: same deep agent served with a 128K window: thinking up to 30720, total 32768 (= DeepSeek max_tokens).
CAPS['xl_forced_original'] = (30720, 32768)
# xxl_*: thinking-budget scaling point: thinking up to 61440, total 65536 (128K serving).
CAPS['xxl_forced_original'] = (61440, 65536)
# xl_forced_leftover: xl_forced_original plus one sentence at the end of the task prompt (see task_prompt).
CAPS['xl_forced_leftover'] = (30720, 32768)
LEFTOVER_SENTENCE = 'Unused numbers are allowed; stop as soon as the target appears.'
LEFTOVER_VARIANTS = {'xl_forced_leftover'}
END_THINK = '</think>'
FORCE_TEXT = '\n</think>\n'
IDLE_TIMEOUT = 120
WALL_LIMIT = 14400  # catastrophe stop only; a 61K-token thinking request under load can exceed 30 min
RETRY_DELAY = 2.0  # one re-dispatch of the same body after an upstream disconnect (all variants)


# Shim error chunks are '{type(exc).__name__}: {exc}' for aiohttp/connection errors on its upstream (inkling/shim.py,
# completions()). Only these names mean the upstream connection was lost. Not retried: ServerTimeoutError and other
# timeouts, plain 'ConnectionError: upstream HTTP <status>' (a server answer with a body) and any SGLang-reported error.
SHIM_DISCONNECTS = ('ServerDisconnectedError', 'ClientConnectionError', 'ServerConnectionError', 'ClientOSError',
                    'ClientConnectorError', 'ClientConnectionResetError', 'ConnectionResetError',
                    'ConnectionRefusedError', 'ConnectionAbortedError', 'BrokenPipeError')
SOCKET_LOSS = (ConnectionResetError, ConnectionRefusedError, ConnectionAbortedError, BrokenPipeError,
               http.client.IncompleteRead)  # RemoteDisconnected is a ConnectionResetError


def shim_disconnect(error):
    message = error.get('message', '') if isinstance(error, dict) else str(error)
    return isinstance(message, str) and message.split(':', 1)[0].strip() in SHIM_DISCONNECTS


def transport_lost(exc):
    """Genuine transport loss: shim disconnect chunk, socket reset/refused/broken pipe, or EOF before a finish_reason
    (including a partial JSON frame at EOF). Everything else, including HTTP errors and timeouts, is not."""
    if getattr(exc, 'transport_lost', False):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        exc = exc.reason
    return isinstance(exc, SOCKET_LOSS)


def lost(exc):
    exc.transport_lost = True
    return exc


def split_answer(text):
    """Answer = text after the LAST end-of-thinking marker; None if the model never closed thinking."""
    if END_THINK not in text:
        return None, text
    reasoning, _, answer = text.rpartition(END_THINK)
    return answer, reasoning


def parse_plan(answer):
    if answer is None:
        return None
    try:
        return parse_json_response(answer)
    except (ValueError, json.JSONDecodeError):
        return None


class ForcedClient:
    def __init__(self, endpoint, model, budget, events, seed, idle_timeout=IDLE_TIMEOUT, wall_limit=WALL_LIMIT):
        self.base = endpoint.rstrip('/').removesuffix('/v1')
        self.model, self.budget, self.events, self.seed = model, budget, events, seed
        self.idle_timeout, self.wall_limit = idle_timeout, wall_limit
        self.infra_failures = self.budget_failures = 0
        self.retries, self.retry_delay = 1, RETRY_DELAY

    def post(self, path, body, timeout):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json'})
        return urllib.request.urlopen(request, timeout=timeout)

    def chat_prompt_ids(self, prompt):
        messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]
        with self.post('/tokenize', dict(model=self.model, messages=messages, add_generation_prompt=True,
                                         chat_template_kwargs={'enable_thinking': True}), 60) as response:
            return json.load(response)['tokens']

    def force_ids(self):
        with self.post('/tokenize', dict(model=self.model, prompt=FORCE_TEXT, add_special_tokens=False), 60) as response:
            return json.load(response)['tokens']

    def complete(self, agent_id, stage, prompt_ids, max_tokens, thinking_closed=False, **context):
        request_id = uuid.uuid4().hex[:12]
        if not self.budget.reserve(max_tokens):
            self.budget_failures += 1
            self.events.emit('budget_exhausted', agent_id=agent_id, stage=stage, **context)
            return dict(request_id=request_id, dispatched=False, response_received=False, text='', token_ids=[],
                        finish_reason=None, usage={}, error='budget_exhausted', answer=None)
        material = f'{self.seed}:{agent_id}:{stage}:{json.dumps(prompt_ids)}'
        seed = int.from_bytes(hashlib.sha256(material.encode()).digest()[:4], 'big')
        body = dict(model=self.model, prompt=prompt_ids, max_tokens=max_tokens, temperature=0.8, seed=seed,
                    stream=True, return_token_ids=True, stream_options={'include_usage': True})
        wire_sha = hashlib.sha256(json.dumps(body).encode()).hexdigest()
        self.events.emit('request_start', request_id=request_id, agent_id=agent_id, endpoint_index=0, stage=stage,
                         request_body={k: v for k, v in body.items() if k != 'prompt'},
                         prompt_token_count=len(prompt_ids), prompt_ids_sha256=sha(json.dumps(prompt_ids)),
                         request_body_sha256=wire_sha, request_max_tokens=max_tokens, request_thinking=True, **context)
        start = time.monotonic()
        attempts = []  # completion tokens streamed by each lost attempt (a lower bound on the server's work)
        while True:
            text, token_ids, finish, usage, error, received = '', [], None, {}, None, False
            try:
                # Socket timeout applies per read: it detects a silent server, not a slow one.
                with self.post('/v1/completions', body, self.idle_timeout) as response:
                    for raw in response:
                        if time.monotonic() - start > self.wall_limit:
                            raise TimeoutError(f'wall limit {self.wall_limit}s exceeded')
                        # Only the last line of a stream cut at EOF lacks its newline. A complete line that does not
                        # decode or parse is a server fault (not retried); a cut one (torn JSON, half a UTF-8
                        # character) is transport loss.
                        torn = not raw.endswith(b'\n')
                        try:
                            line = raw.decode().strip()
                            if not line.startswith('data:') or line == 'data: [DONE]':
                                continue
                            chunk = json.loads(line[5:])
                        except ValueError as exc:  # UnicodeDecodeError, JSONDecodeError
                            raise lost(exc) if torn else exc
                        if chunk.get('error'):
                            exc = ConnectionError(f"server stream error: {str(chunk['error'])[:200]}")
                            raise lost(exc) if shim_disconnect(chunk['error']) else exc
                        for choice in chunk.get('choices', []):
                            text += choice.get('text') or ''
                            token_ids += choice.get('token_ids') or []
                            finish = choice.get('finish_reason') or finish
                        if chunk.get('usage'):
                            usage = {k: v for k, v in chunk['usage'].items()
                                     if k in ('prompt_tokens', 'completion_tokens', 'total_tokens') and type(v) is int}
                received = finish is not None
                if not received:
                    raise lost(ConnectionError('stream ended without finish_reason'))
            except Exception as exc:
                elapsed = time.monotonic() - start if not attempts and transport_lost(exc) else None
                if elapsed is not None and elapsed + self.retry_delay <= self.wall_limit:
                    time.sleep(self.retry_delay)
                    if time.monotonic() - start <= self.wall_limit:  # never dispatch past the wall limit
                        # Upstream lost: send the same body (same seed) once more; the lost attempt is charged below.
                        attempts.append(len(token_ids))
                        self.events.emit('request_retry', request_id=request_id, agent_id=agent_id, stage=stage,
                                         attempt=2, error=f'{type(exc).__name__}: {str(exc)[:300]}',
                                         lost_completion_tokens=len(token_ids),
                                         lost_completion_tokens_is_lower_bound=True, lost_text_chars=len(text),
                                         elapsed_ms=round(elapsed * 1000, 2), retry_delay_s=self.retry_delay,
                                         request_body_sha256=wire_sha, **context)
                        continue
                error = f'{type(exc).__name__}: {str(exc)[:300]}'
                self.infra_failures += 1
            break
        reported = usage.get('completion_tokens')
        if received and reported is not None and reported != len(token_ids):
            error = error or f'token id count {len(token_ids)} != reported {reported}'
            self.infra_failures += 1  # accounting fault: stop admissions rather than silently skip forcing
        # The Budget (and so every later max_tokens) sees only the delivered attempt, exactly as without a retry.
        self.budget.settle(max_tokens, reported)
        charged = max_tokens if reported is None else reported
        retry_fields = {}
        if attempts:
            # Accounting charges the lost attempt once (its streamed ids, a lower bound on the server's work):
            # completion_tokens_charged and usage.completion_tokens, the field the controller tallies (plan_of).
            extra = sum(attempts)
            charged += extra
            usage['completion_tokens'] = (reported or 0) + extra
            if 'total_tokens' in usage:
                usage['total_tokens'] += extra
            usage['lost_attempt_completion_tokens'] = extra
            retry_fields = dict(attempts=len(attempts) + 1,
                                attempt_completion_tokens=attempts + [len(token_ids) if reported is None else reported],
                                lost_completion_tokens_lower_bound=extra)
        usage['estimated'] = reported is None
        answer, reasoning = split_answer(text)
        if answer is None and thinking_closed:  # thinking was already closed before this call
            answer, reasoning = text, ''
        self.events.emit('request_end', request_id=request_id, agent_id=agent_id, endpoint_index=0, stage=stage,
                         latency_ms=round((time.monotonic() - start) * 1000, 2), usage=usage,
                         completion_tokens_charged=charged, error=error,
                         response=answer, reasoning=reasoning, finish_reason=finish, response_received=received,
                         closed_thinking=answer is not None, token_ids=token_ids, request_body_sha256=wire_sha,
                         **retry_fields, **context)
        return dict(request_id=request_id, dispatched=True, response_received=received, text=text,
                    token_ids=token_ids, finish_reason=finish, usage=usage, error=error, answer=answer)


def task_prompt(e, initial, variant, extra=''):
    prompt = prompt_for(e, initial, VARIANTS[variant])
    if variant in LEFTOVER_VARIANTS:
        # Last sentence of the task text, before any per-agent extra: everything up to here is byte-identical to
        # xl_forced_original, and all agents of a case still share the prompt through this sentence.
        prompt += ' ' + LEFTOVER_SENTENCE
    if extra:  # controller-supplied context (strategy hint, judge critique, shared board); never gold information
        prompt += '\n' + extra.strip()
    return prompt


def run_forced(experiment, initial, puzzle_id, variant, agent_id=0, extra=''):
    if variant not in VARIANTS:
        raise ValueError('unknown variant')
    e = experiment
    client = e.client
    think_cap, total = CAPS[variant]
    budget = client.budget.snapshot()
    if (e.args.allow_fractions or budget['max_calls'] != 2 or budget['max_completion_tokens'] != total
            or budget['calls'] != 0 or budget['completion_tokens_reserved'] != 0):
        raise ValueError('fresh case Budget(2, variant total) and integer rules required')
    root = e.node(initial, None, 0, puzzle_id, agent_id)
    prompt = task_prompt(e, initial, variant, extra)
    prompt_ids = client.chat_prompt_ids(prompt)
    plain = variant.startswith('plain_')
    first = client.complete(agent_id, 'plan', prompt_ids, total if plain else think_cap, node_id=root,
                            puzzle_id=puzzle_id, variant=variant, followup_phase='think')
    plan, second, forced = parse_plan(first['answer']), None, False
    # Same trigger as the scribe commit: no parsed plan, cut by length, own tokens available.
    remaining = total - client.budget.snapshot()['completion_tokens_charged']
    eligible = (not plain and plan is None and first['response_received'] and first['finish_reason'] == 'length'
                and len(first['token_ids']) > 0 and first['error'] is None and remaining > 0)
    if eligible:
        forced = first['answer'] is None  # still thinking -> force the end; else just let the answer finish
        suffix = client.force_ids() if forced else []
        e.events.emit('budget_forced' if forced else 'answer_continued', node_id=root, puzzle_id=puzzle_id,
                      variant=variant, parent_request_id=first['request_id'],
                      forced_after_tokens=len(first['token_ids']), remaining_completion_tokens=remaining)
        second = client.complete(agent_id, 'forced_answer' if forced else 'continued_answer',
                                 prompt_ids + first['token_ids'] + suffix, remaining, thinking_closed=True,
                                 node_id=root, puzzle_id=puzzle_id, variant=variant,
                                 followup_phase='forced_answer' if forced else 'continued_answer',
                                 parent_request_id=first['request_id'])
        # A forced continuation may first finish its thinking and close it again (answer after last marker).
        answer = second['answer']
        if not forced:  # the first call already holds the start of the answer
            answer = first['answer'] + (second['text'] if END_THINK not in second['text'] else second['answer'])
        plan = parse_plan(answer)
    result = replay_plan(e, initial, root, plan, puzzle_id, agent_id)
    result.update(method=variant, variant=variant, first_request_id=first['request_id'],
                  first_finish_reason=first['finish_reason'], first_closed_thinking=first['answer'] is not None,
                  budget_forced=forced, answer_continued=bool(second) and not forced,
                  forced_request_id=second['request_id'] if second else None,
                  forced_finish_reason=second['finish_reason'] if second else None,
                  forced_closed_thinking_again=(END_THINK in second['text']) if second else None)
    return result
