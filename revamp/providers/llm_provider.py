"""
app/providers/llm_provider.py

Updated to match the upstream repo's latest changes:
  - Added GrokLLM (xAI's Grok, via the OpenAI-compatible chat/completions
    endpoint) as a third provider alongside Gemini and Ollama.
  - Generation and evaluation are now resolved independently:
    get_generation_llm() / get_evaluation_llm(), each driven by their own
    setting (GENERATION_LLM_PROVIDER / EVALUATION_LLM_PROVIDER) instead of
    a single LLM_PROVIDER for everything. This lets the judge stay on
    Gemini Flash-Lite for comparable scoring even when generation runs on
    Ollama or Grok.

load_dotenv() removed; everything takes an injected Settings instance.
"""
import json
from typing import Any, Iterator, List, Optional

import requests
from google import genai
from google.genai import types
from langchain.llms.base import LLM

from app.config import Settings

DEFAULT_SYSTEM_INSTRUCTION = (
    "Your name is Airi. You are A CYBERSECURITY EXPERT AI ASSISTANT. "
    "Directly ANSWER THE QUERY WITHOUT MENTIONING ANYTHING ABOUT YOURSELF. "
    "Do not answer any question which is not of your DOMAIN."
)

JUDGE_SYSTEM_INSTRUCTION = (
    "You are a JUDGE for evaluating LLM responses. "
    "Provide SCORE (True or False) and a single-line COMMENT."
)


class GeminiLLM(LLM):
    model_name: str = "gemini-2.5-flash"
    api_key: str
    temperature: float = 0.7
    system_instruction: str = "You are a helpful assistant."
    client: Any = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = genai.Client(api_key=self.api_key)

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=self.temperature,
                stop_sequences=stop,
            ),
        )
        return response.text

    def _stream(self, prompt: str, stop: Optional[List[str]] = None) -> Iterator[str]:
        response = self.client.models.generate_content_stream(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=self.temperature,
                stop_sequences=stop,
            ),
        )
        for chunk in response:
            yield chunk.text

    @property
    def _llm_type(self) -> str:
        return "gemini"


class OllamaLLM(LLM):
    model_name: str = "llama3.1"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.7
    system_instruction: str = "You are a helpful assistant."

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        payload = {
            "model": self.model_name,
            "prompt": f"{self.system_instruction}\n\n{prompt}",
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if stop:
            payload["options"]["stop"] = stop
        response = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["response"]

    def _stream(self, prompt: str, stop: Optional[List[str]] = None) -> Iterator[str]:
        payload = {
            "model": self.model_name,
            "prompt": f"{self.system_instruction}\n\n{prompt}",
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        with requests.post(
            f"{self.base_url}/api/generate", json=payload, stream=True, timeout=120
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if not chunk.get("done"):
                        yield chunk.get("response", "")

    @property
    def _llm_type(self) -> str:
        return "ollama"


class GrokLLM(LLM):
    """xAI Grok via the OpenAI-compatible chat/completions endpoint."""

    model_name: str = "grok-4-fast-reasoning"
    api_key: str
    base_url: str = "https://api.x.ai/v1"
    temperature: float = 0.7
    system_instruction: str = "You are a helpful assistant."

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "stream": False,
        }
        if stop:
            payload["stop"] = stop

        response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _stream(self, prompt: str, stop: Optional[List[str]] = None) -> Iterator[str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "stream": True,
        }
        if stop:
            payload["stop"] = stop

        with requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, stream=True, timeout=120) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"]
                if "content" in delta:
                    yield delta["content"]

    @property
    def _llm_type(self) -> str:
        return "grok"


def get_llm(settings: Settings, provider: Optional[str] = None, **kwargs) -> LLM:
    """
    Factory — provider defaults to settings.LLM_PROVIDER but can be
    overridden explicitly (benchmarks always want a Gemini AND an Ollama
    instance side by side regardless of any single default).
    """
    provider = (provider or settings.LLM_PROVIDER).lower()

    if provider == "gemini":
        return GeminiLLM(
            api_key=kwargs.get("api_key", settings.GENAI_API_KEY),
            model_name=kwargs.get("model_name", "gemini-2.5-flash"),
            temperature=kwargs.get("temperature", 0.8),
            system_instruction=kwargs.get("system_instruction", DEFAULT_SYSTEM_INSTRUCTION),
        )
    elif provider == "grok":
        return GrokLLM(
            api_key=kwargs.get("api_key", settings.XAI_API_KEY),
            model_name=kwargs.get("model_name", settings.GROK_MODEL),
            temperature=kwargs.get("temperature", 0.8),
            system_instruction=kwargs.get("system_instruction", DEFAULT_SYSTEM_INSTRUCTION),
        )
    elif provider == "ollama":
        return OllamaLLM(
            model_name=kwargs.get("model_name", settings.OLLAMA_MODEL),
            base_url=kwargs.get("base_url", settings.OLLAMA_BASE_URL),
            temperature=kwargs.get("temperature", 0.8),
            system_instruction=kwargs.get("system_instruction", DEFAULT_SYSTEM_INSTRUCTION),
        )
    raise ValueError(f"Unsupported LLM provider: '{provider}'. Valid options: 'gemini', 'ollama', 'grok'")


def get_generation_llm(settings: Settings, **kwargs) -> LLM:
    """The LLM used for RAG / code generation. Resolved from GENERATION_LLM_PROVIDER."""
    return get_llm(settings, provider=settings.GENERATION_LLM_PROVIDER, **kwargs)


def get_evaluation_llm(settings: Settings, **kwargs) -> LLM:
    """
    The LLM used as the judge (LLM-as-a-Judge, code security evaluation,
    benchmark scoring). Resolved from EVALUATION_LLM_PROVIDER.

    gemini-2.0-flash-lite-001 is a Gemini-only model id — only applied
    when the resolved evaluation provider is actually gemini, mirroring
    the fix in testing_folder/ab_testing.py's _build_evaluator_llm().
    Otherwise get_llm() falls back to that provider's own default model.
    """
    if settings.EVALUATION_LLM_PROVIDER.lower() == "gemini" and "model_name" not in kwargs:
        kwargs["model_name"] = "gemini-2.0-flash-lite-001"
    kwargs.setdefault("temperature", 0.3)
    kwargs.setdefault("system_instruction", JUDGE_SYSTEM_INSTRUCTION)
    return get_llm(settings, provider=settings.EVALUATION_LLM_PROVIDER, **kwargs)