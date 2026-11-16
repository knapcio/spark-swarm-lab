"""Follow-up-only request metadata and per-call overrides; legacy Client stays frozen."""
from concurrent.futures import CancelledError
import hashlib
import json
import time
import urllib.request
import uuid
from harness import Client as BaseClient, parse_json_response


class FollowupClient(BaseClient):
    def call(self, agent_id, stage, prompt, *, thinking=None, max_tokens=None, return_meta=False, **context):
        cap = self.max_tokens if max_tokens is None else max_tokens
        think = self.thinking if thinking is None else thinking
        if type(cap) is not int or cap <= 0 or type(think) is not bool:
            raise ValueError("positive integer max_tokens and boolean thinking required")
        endpoint_index = agent_id % len(self.endpoints)
        endpoint = self.endpoints[endpoint_index].rstrip("/")
        url = endpoint if endpoint.endswith("/chat/completions") else endpoint + "/chat/completions"
        request_id = uuid.uuid4().hex[:12]
        # Wait outside the budget so queued requests do not hold token reservations.
        with self.limits[endpoint_index]:
            if not self.budget.reserve(cap):
                with self.failure_lock:
                    self.budget_failures += 1
                self.events.emit("budget_exhausted", agent_id=agent_id, stage=stage, **context)
                meta = dict(request_id=request_id, finish_reason=None, reasoning=None,
                            response_received=False, request_dispatched=False, error="budget_exhausted", usage={})
                return (None, meta) if return_meta else None
            start = time.monotonic()
            body, wire, preparation_error = None, None, None
            try:
                material = f"{self.seed}:{agent_id}:{stage}:{prompt}"
                request_seed = int.from_bytes(hashlib.sha256(material.encode()).digest()[:4], "big")
                body = dict(model=self.model, messages=[
                    {"role": "system", "content": getattr(self, "system_prompt", "Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.")},
                    {"role": "user", "content": prompt}], max_tokens=cap,
                    temperature=0.8, seed=request_seed, stream=False,
                    chat_template_kwargs={"enable_thinking": think})
                wire = json.dumps(body).encode()
            except Exception as exc:
                preparation_error = exc
            wire_sha = hashlib.sha256(wire).hexdigest() if wire is not None else None
            self.events.emit("request_start", request_id=request_id, agent_id=agent_id,
                             endpoint_index=endpoint_index, stage=stage, request_body=body if wire is not None else None,
                             request_body_sha256=wire_sha, request_max_tokens=cap,
                             request_thinking=think, **context)
            usage, error, content = {}, None, None
            reasoning, finish_reason, response_received = None, None, False
            response_model, raw_usage_record = None, None
            cancellation = None
            dispatched = False
            try:
                if preparation_error is not None:
                    raise preparation_error
                request = urllib.request.Request(url, data=wire,
                                                 headers={"Content-Type": "application/json"})
                dispatched = True
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.load(response)
                response_model, raw_usage_record = data.get("model"), data.get("usage")
                raw_usage = raw_usage_record or {}
                for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = raw_usage.get(name)
                    if type(value) is int and value >= 0:
                        usage[name] = value
                choice = data["choices"][0]
                message = choice["message"]
                content = message.get("content")
                finish_reason = choice.get("finish_reason")
                reasoning = message.get("reasoning_content", message.get("reasoning"))
                response_received = True
                parser = getattr(self, "response_parser", None)
                result = parser(content, stage) if parser else parse_json_response(content)
            except BaseException as exc:
                # Request JSON is recorded above; never record headers, credentials,
                # or an HTTP exception's complete response body.
                error = f"{type(exc).__name__}: {str(exc)[:300]}"
                if not isinstance(exc, Exception) or isinstance(exc, CancelledError):
                    cancellation = exc
                if not response_received and cancellation is None:
                    with self.failure_lock:
                        self.infra_failures += 1
                result = None
            reported = usage.get("completion_tokens")
            self.budget.settle(cap, reported)
            usage["estimated"] = reported is None
            self.events.emit("request_end", request_id=request_id, agent_id=agent_id,
                             endpoint_index=endpoint_index, stage=stage,
                             latency_ms=round((time.monotonic() - start) * 1000, 2),
                             usage=usage, completion_tokens_charged=cap if reported is None else reported,
                             error=error, response=content, reasoning=reasoning,
                             finish_reason=finish_reason, response_received=response_received,
                             response_model=response_model, raw_usage=raw_usage_record,
                             cancelled=cancellation is not None, request_body_sha256=wire_sha, **context)
            if cancellation is not None:
                raise cancellation
            meta = dict(request_id=request_id, finish_reason=finish_reason, reasoning=reasoning,
                        content=content, response_received=response_received, request_dispatched=dispatched,
                        response_model=response_model, raw_usage=raw_usage_record,
                        error=error, usage=dict(usage), request_body_sha256=wire_sha)
            return (result, meta) if return_meta else result

