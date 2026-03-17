import os
import requests
from typing import Optional, List, Any, Iterator
from langchain.llms.base import LLM
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv("API.env")


class GeminiLLM(LLM):
    model_name: str = "gemini-2.0-flash-lite-001"
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
                stop_sequences=stop
            )
        )
        return response.text

    def _stream(self, prompt: str, stop: Optional[List[str]] = None) -> Iterator[str]:
        response = self.client.models.generate_content_stream(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=self.temperature,
                stop_sequences=stop
            )
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
            "options": {"temperature": self.temperature}
        }
        if stop:
            payload["options"]["stop"] = stop

        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        return response.json()["response"]

    def _stream(self, prompt: str, stop: Optional[List[str]] = None) -> Iterator[str]:
        payload = {
            "model": self.model_name,
            "prompt": f"{self.system_instruction}\n\n{prompt}",
            "stream": True,
            "options": {"temperature": self.temperature}
        }
        with requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            stream=True,
            timeout=120
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    import json
                    chunk = json.loads(line)
                    if not chunk.get("done"):
                        yield chunk.get("response", "")

    @property
    def _llm_type(self) -> str:
        return "ollama"


def get_llm(provider: str = "gemini", **kwargs) -> LLM:
    """
    Factory — resolves provider from LLM_PROVIDER env var.
    kwargs are forwarded to the LLM constructor.
    """
    provider = provider.lower()
    if provider == "gemini":
        return GeminiLLM(
            api_key=kwargs.get("api_key", os.getenv("GENAI_API_KEY")),
            model_name=kwargs.get("model_name", "gemini-2.5-flash"),
            temperature=kwargs.get("temperature", 0.8),
            system_instruction=kwargs.get(
                "system_instruction",
                "Your name is Airi. You are A CYBERSECURITY EXPERT AI ASSISTANT. "
                "Directly ANSWER THE QUERY WITHOUT MENTIONING ANYTHING ABOUT YOURSELF. "
                "Do not answer any question which is not of your DOMAIN."
            )
        )
    elif provider == "ollama":
        return OllamaLLM(
            model_name=kwargs.get("model_name", "llama3.1"),
            base_url=kwargs.get("base_url", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")),
            temperature=kwargs.get("temperature", 0.8),
            system_instruction=kwargs.get(
                "system_instruction",
                "Your name is Airi. You are A CYBERSECURITY EXPERT AI ASSISTANT. "
                "Directly ANSWER THE QUERY WITHOUT MENTIONING ANYTHING ABOUT YOURSELF. "
                "Do not answer any question which is not of your DOMAIN."
            )
        )
    else:
        raise ValueError(f"Unsupported LLM provider: '{provider}'. Valid options: 'gemini', 'ollama'")