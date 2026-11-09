"""A model behind an OpenAI-compatible chat endpoint. Ollama serves one at /v1/chat/completions. Standard library only."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import zlib


class OllamaModel:
    def __init__(self, model, host="http://localhost:11434", temperature=0.7, seed=0, timeout=600):
        self.model, self.host, self.temperature, self.seed, self.timeout = model, host, temperature, seed, timeout

    def step(self, messages, tools):
        body = {
            "model": self.model,
            "messages": messages,
            "tools": [{"type": "function", "function": t} for t in tools],
            "temperature": self.temperature,
            "seed": self.seed,
            "stream": False,
        }
        req = urllib.request.Request(f"{self.host}/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                msg = json.load(resp)["choices"][0]["message"]
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"{self.host} answered {err.code}: {err.read(300).decode('utf-8', 'replace')}") from err
        calls = [{"id": c["id"], "name": c["function"]["name"], "arguments": c["function"]["arguments"]}
                 for c in msg.get("tool_calls") or []]
        return {"content": msg.get("content") or "", "tool_calls": calls}


def ollama_factory(model, host="http://localhost:11434", temperature=0.7, base_seed=0):
    def make(world, upload_id, repeat=0):
        seed = zlib.crc32(f"{base_seed}/{upload_id}/{repeat}".encode("utf-8")) % (2 ** 31)
        return OllamaModel(model, host, temperature, seed)
    return make
