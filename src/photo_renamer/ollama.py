from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import requests

PROMPT_VERSION = "2026-05-11.short-inferable-filename.v1"

DEFAULT_PROMPT = """You are helping rename a personal photo library.

Look at the image and return a short filename phrase.

Rules:
- Use 2 to 5 lowercase words.
- Prefer concrete visible subjects, actions, places, or events.
- Infer obvious context when it is likely, such as christmas dinner, wedding speech, beach sunset, or family at table.
- Do not include camera metadata, dates, numbers, punctuation, file extensions, or explanations.
- Return only the phrase.

Good examples:
family at table
dog on grass
christmas dinner
brighton seafront
children opening presents
"""


def build_prompt(guidance: str | None = None) -> str:
    guidance = (guidance or "").strip()
    if not guidance:
        return DEFAULT_PROMPT
    return f"{DEFAULT_PROMPT}\nAdditional user guidance:\n{guidance}\n"


@dataclass(frozen=True)
class OllamaConfig:
    model: str = "gemma4:e4b"
    url: str = "http://localhost:11434"
    timeout: float = 180.0
    temperature: float = 0.0
    prompt: str = DEFAULT_PROMPT


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, config: OllamaConfig):
        self.config = config

    def describe(self, image_path: Path) -> str:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": self.config.model,
            "prompt": self.config.prompt,
            "stream": False,
            "images": [encoded],
            "options": {"temperature": self.config.temperature},
        }
        url = self.config.url.rstrip("/") + "/api/generate"

        try:
            response = requests.post(url, json=payload, timeout=self.config.timeout)
        except requests.RequestException as exc:
            raise OllamaError(f"Could not reach Ollama at {url}: {exc}") from exc

        if response.status_code >= 400:
            raise OllamaError(f"Ollama returned HTTP {response.status_code}: {response.text[:500]}")

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaError(f"Ollama returned non-JSON response: {response.text[:500]}") from exc

        text = data.get("response")
        if not isinstance(text, str) or not text.strip():
            raise OllamaError(f"Ollama response did not contain a description: {data!r}")
        return text.strip()
