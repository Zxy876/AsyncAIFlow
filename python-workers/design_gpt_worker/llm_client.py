from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import google.generativeai as genai


@dataclass
class LlmConfig:
    api_key: str
    model: str
    temperature: float = 0.2
    timeout_seconds: int = 120
    response_schema_text: str | None = None


class GeminiJsonClient:
    def __init__(self, config: LlmConfig) -> None:
        self.config = config
        for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            os.environ.pop(proxy_var, None)
        genai.configure(api_key=config.api_key)
        self.model = genai.GenerativeModel(model_name=config.model)

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        prompt_parts = [system_prompt.strip()]
        if self.config.response_schema_text:
            prompt_parts.append(
                "You must produce JSON that conforms to this Design Schema v0.1 definition:\n"
                + self.config.response_schema_text.strip()
            )
        prompt_parts.append(user_prompt.strip())
        combined_prompt = "\n\n".join(part for part in prompt_parts if part)

        response = self.model.generate_content(
            combined_prompt,
            generation_config=genai.GenerationConfig(
                temperature=self.config.temperature,
                response_mime_type="application/json",
            ),
            request_options={"timeout": self.config.timeout_seconds},
        )
        content = (response.text or "").strip()
        if not content:
            raise ValueError("Gemini returned empty response text")
        return json.loads(content)
