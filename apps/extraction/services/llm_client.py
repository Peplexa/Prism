"""
LLM client supporting multiple backends: Ollama (local) and DeepSeek API (cloud).

Provides a unified interface for LLM inference across different providers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Generate completion from LLM."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the LLM backend is available."""
        pass

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Chat completion - default implementation converts to generate."""
        # Build prompt from messages
        system = None
        prompt_parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system = content
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")

        prompt = "\n\n".join(prompt_parts)
        return self.generate(prompt, system=system, temperature=temperature, max_tokens=max_tokens)


class OllamaClient(BaseLLMClient):
    """Client for local LLM inference via Ollama."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout or settings.OLLAMA_TIMEOUT
        self._client = httpx.Client(timeout=self.timeout)

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Generate completion from local LLM."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "stream": False,
        }

        try:
            response = self._client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            return response.json()["response"]
        except httpx.HTTPError as e:
            logger.error(f"Ollama request failed: {e}")
            raise

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """Chat completion from local LLM."""
        payload = {
            "model": self.model,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "stream": False,
        }

        try:
            response = self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
        except httpx.HTTPError as e:
            logger.error(f"Ollama chat request failed: {e}")
            raise

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            return any(self.model in name for name in model_names)
        except Exception as e:
            logger.warning(f"Ollama not available: {e}")
            return False

    def get_model_info(self) -> dict[str, Any]:
        """Get information about the current model."""
        try:
            response = self._client.post(
                f"{self.base_url}/api/show",
                json={"name": self.model},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Could not get model info: {e}")
            return {}

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class DeepSeekClient(BaseLLMClient):
    """
    Client for DeepSeek API (cloud).

    Uses the Anthropic-compatible endpoint for familiarity, but can also
    use the native OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120,
    ):
        self.api_key = api_key or getattr(settings, 'DEEPSEEK_API_KEY', None)
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key required. Set DEEPSEEK_API_KEY in settings or .env"
            )

        self.model = model or getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-reasoner')
        self.base_url = base_url or getattr(
            settings, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com'
        )
        self.timeout = timeout
        self._client = httpx.Client(timeout=self.timeout)

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> str:
        """Generate completion using DeepSeek API (OpenAI-compatible).

        If max_tokens is None, the parameter is omitted from the request so
        the API uses the model's maximum (8K for deepseek-chat/reasoner).
        """
        messages = []

        if system:
            messages.append({"role": "system", "content": system})

        messages.append({"role": "user", "content": prompt})

        return self._call_api(messages, temperature, max_tokens)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> str:
        """Chat completion using DeepSeek API."""
        return self._call_api(messages, temperature, max_tokens)

    def _call_api(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        """Make API call to DeepSeek."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            response = self._client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            logger.error(f"DeepSeek API error: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"DeepSeek request failed: {e}")
            raise

    def is_available(self) -> bool:
        """Check if DeepSeek API is accessible."""
        if not self.api_key:
            return False

        try:
            # Make a minimal API call to check connectivity
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            response = self._client.get(
                f"{self.base_url}/v1/models",
                headers=headers,
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"DeepSeek API not available: {e}")
            return False

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def get_llm_client(backend: str | None = None) -> BaseLLMClient:
    """
    Factory function to get the appropriate LLM client.

    Args:
        backend: 'ollama', 'deepseek', or None (uses settings.LLM_BACKEND)

    Returns:
        Configured LLM client instance
    """
    backend = backend or getattr(settings, 'LLM_BACKEND', 'deepseek')

    if backend == 'deepseek':
        return DeepSeekClient()
    elif backend == 'ollama':
        return OllamaClient()
    else:
        raise ValueError(f"Unknown LLM backend: {backend}")
