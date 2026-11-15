"""One finite function-call round trip; executes only local integer addition."""
import argparse
import json
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    messages = [{"role": "user", "content":
                 "Use add to calculate 17 + 25. After receiving the result, return only JSON with key result."}]
    base = dict(model="nemotron-lightning", max_tokens=192, temperature=0,
                chat_template_kwargs={"enable_thinking": False})

    def call(**payload):
        request = urllib.request.Request(args.endpoint.rstrip("/") + "/chat/completions",
                                         data=json.dumps(dict(base, **payload)).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)

    tool = {"type": "function", "function": {"name": "add", "description": "Add two integers",
            "parameters": {"type": "object", "properties": {"a": {"type": "integer"},
            "b": {"type": "integer"}}, "required": ["a", "b"]}}}
    first = call(messages=messages, tools=[tool],
                 tool_choice={"type": "function", "function": {"name": "add"}})
    message = first["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    assert len(calls) == 1 and calls[0]["function"]["name"] == "add", first
    values = json.loads(calls[0]["function"]["arguments"])
    assert values == {"a": 17, "b": 25}, values
    messages.extend([message, {"role": "tool", "tool_call_id": calls[0]["id"],
                              "content": json.dumps({"result": values["a"] + values["b"]})}])
    second = call(messages=messages)
    assert json.loads(second["choices"][0]["message"]["content"]) == {"result": 42}, second
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"first": first, "second": second, "passed": True}, indent=2) + "\n")
    print("Function-call round trip: PASS")


if __name__ == "__main__":
    main()
