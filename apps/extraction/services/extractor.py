"""
Nugget extraction service.

Extracts atomic facts (nuggets) from text using LLM inference.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from apps.experiments.models import PromptVersion

from .llm_client import BaseLLMClient, get_llm_client
from .prompts import get_default_prompts

logger = logging.getLogger(__name__)


class NuggetExtractor:
    """Extracts atomic facts (nuggets) from text using LLM."""

    def __init__(self, client: BaseLLMClient | None = None, backend: str | None = None):
        self.client = client or get_llm_client(backend)

    def extract(
        self,
        text: str,
        prompt_version: PromptVersion | None = None,
        domain: str = "generic",
        temperature: float = 0.1,
    ) -> list[dict[str, Any]]:
        """
        Extract nuggets from text.

        Args:
            text: The text to extract facts from
            prompt_version: Optional PromptVersion model instance
            domain: Domain hint if no prompt_version ('rotowire', 'billsum', 'generic')
            temperature: Sampling temperature

        Returns:
            List of extracted nuggets with 'fact' and 'type' keys
        """
        if prompt_version:
            system_prompt = prompt_version.system_prompt
            user_prompt = prompt_version.render_user_prompt(text=text)
        else:
            system_prompt, user_template = get_default_prompts(domain)
            user_prompt = user_template.format(text=text)

        # Truncate very long texts to avoid context limits
        max_chars = 12000
        if len(user_prompt) > max_chars:
            logger.warning(f"Truncating input from {len(user_prompt)} to {max_chars} chars")
            # Truncate the text portion, keeping the template structure
            text_limit = max_chars - len(user_prompt) + len(text)
            truncated_text = text[:text_limit] + "\n[TRUNCATED]"
            if prompt_version:
                user_prompt = prompt_version.render_user_prompt(text=truncated_text)
            else:
                user_prompt = user_template.format(text=truncated_text)

        response = self.client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
        )

        return self._parse_response(response)

    def extract_batch(
        self,
        texts: list[str],
        prompt_version: PromptVersion | None = None,
        domain: str = "generic",
        temperature: float = 0.1,
    ) -> list[list[dict[str, Any]]]:
        """Extract nuggets from multiple texts."""
        results = []
        for text in texts:
            try:
                nuggets = self.extract(
                    text,
                    prompt_version=prompt_version,
                    domain=domain,
                    temperature=temperature,
                )
                results.append(nuggets)
            except Exception as e:
                logger.error(f"Extraction failed: {e}")
                results.append([])
        return results

    def _parse_response(self, response: str) -> list[dict[str, Any]]:
        """Parse LLM response into structured nuggets."""
        # Clean up response - handle markdown code blocks
        response = response.strip()

        # Remove markdown code block markers
        if response.startswith("```json"):
            response = response[7:]
        elif response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]

        response = response.strip()

        # Try to find JSON array in the response
        try:
            # First, try direct parse
            nuggets = json.loads(response)
            if isinstance(nuggets, list):
                return self._validate_nuggets(nuggets)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON array from mixed content
        json_match = re.search(r"\[[\s\S]*\]", response)
        if json_match:
            try:
                nuggets = json.loads(json_match.group())
                if isinstance(nuggets, list):
                    return self._validate_nuggets(nuggets)
            except json.JSONDecodeError:
                pass

        logger.warning(f"Could not parse nuggets from response: {response[:200]}...")
        return []

    def _validate_nuggets(self, nuggets: list) -> list[dict[str, Any]]:
        """Validate and clean extracted nuggets."""
        valid = []
        for n in nuggets:
            if not isinstance(n, dict):
                continue
            fact = n.get("fact", "")
            if not fact or not isinstance(fact, str):
                continue
            valid.append({
                "fact": fact.strip(),
                "type": str(n.get("type", "unknown")).strip(),
            })
        return valid
