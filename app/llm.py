"""Typed model responses with explicit provider-specific request formats."""

from __future__ import annotations

import base64
import json
from typing import cast

from anthropic import APIError as AnthropicAPIError
from anthropic import APITimeoutError as AnthropicTimeoutError
from anthropic import AsyncAnthropic
from anthropic.types import ImageBlockParam, TextBlockParam
from openai import (
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
)
from openai.types.chat import ChatCompletionContentPartParam
from openai.types.responses import ResponseInputContentParam
from pydantic import BaseModel, ValidationError

from app.config import Settings

PROVIDERS = ("openai", "deepseek", "ollama", "anthropic")
_JSON_INSTRUCTION = """\

Return a JSON object matching this schema, with no surrounding prose or code fence:
"""


class StructuredOutputError(RuntimeError):
    """A provider request failed or did not produce a complete typed record."""


def endpoint(provider: str, settings: Settings, override: str | None) -> str:
    """Resolve the provider API endpoint, honoring an explicit override.

    Args:
        provider: Generation or extraction service provider name.
        settings: Runtime settings for extraction, storage, or models.
        override: Optional endpoint override.

    Returns:
        Resolved API endpoint.
    """
    if provider not in PROVIDERS:
        raise ValueError("Unsupported model provider")
    return (
        override
        or {
            "openai": settings.openai_base_url or "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com",
            "ollama": "http://127.0.0.1:11434/v1",
            "anthropic": "https://api.anthropic.com",
        }[provider]
    )


def api_key(provider: str, settings: Settings) -> str:
    """Select the API key used for a given generation provider.

    Args:
        provider: Generation or extraction service provider name.
        settings: Runtime settings for extraction, storage, or models.

    Returns:
        Credential for the selected provider.
    """
    if provider == "ollama":
        return "ollama"
    name, value = {
        "openai": ("OPENAI_API_KEY", settings.openai_api_key),
        "deepseek": ("DEEPSEEK_API_KEY", settings.deepseek_api_key),
        "anthropic": ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
    }[provider]
    if not value or not value.strip():
        raise ValueError(f"Set {name} for the selected model provider")
    return value


def create_client(
    provider: str, *, api_key: str, base_url: str, timeout: int
) -> AsyncOpenAI | AsyncAnthropic:
    """Instantiate the matching asynchronous model-provider client.

    Args:
        provider: Generation or extraction service provider name.
        api_key: Credential used to authenticate with the provider.
        base_url: Provider API base URL.
        timeout: Request timeout in seconds.

    Returns:
        Configured asynchronous model client.
    """
    if provider == "anthropic":
        return AsyncAnthropic(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0
        )
    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
        _strict_response_validation=True,
    )


def system_prompt(prompt: str, response_model: type[BaseModel], provider: str) -> str:
    """Adjust the system instructions for provider-specific structured output.

    Args:
        prompt: Base system instruction text.
        response_model: Pydantic schema used to validate structured output.
        provider: Generation or extraction service provider name.

    Returns:
        Provider-adjusted system prompt.
    """
    if provider == "deepseek":
        return (
            prompt
            + _JSON_INSTRUCTION
            + json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        )
    return prompt


async def generate_structured_response[ResponseModel: BaseModel](
    client: AsyncOpenAI | AsyncAnthropic,
    *,
    provider: str,
    model: str,
    response_model: type[ResponseModel],
    system: str,
    user: str,
    max_tokens: int,
    image: bytes | None = None,
) -> tuple[ResponseModel, int | None]:
    """Request a typed model response and report observed token usage.

    Args:
        client: Asynchronous model-provider client.
        provider: Generation or extraction service provider name.
        model: Generation model identifier.
        response_model: Pydantic schema used to validate structured output.
        system: System instruction text for the model.
        user: User prompt sent to the provider.
        max_tokens: Maximum output tokens requested.
        image: Optional image supplied alongside the user prompt.

    Returns:
        Validated response and reported output token usage.
    """
    try:
        if provider == "anthropic":
            content: list[TextBlockParam | ImageBlockParam] = [
                {"type": "text", "text": user}
            ]
            if image is not None:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(image).decode("ascii"),
                        },
                    }
                )
            message = await cast(AsyncAnthropic, client).messages.parse(
                model=model,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_format=response_model,
                max_tokens=max_tokens,
            )
            if message.stop_reason != "end_turn":
                raise StructuredOutputError(
                    "returned a filtered or incomplete response"
                )
            text = "".join(
                block.text for block in message.content if block.type == "text"
            )
            parsed = message.parsed_output
            tokens = message.usage.output_tokens
        elif provider == "openai":
            inputs: list[ResponseInputContentParam] = [
                {"type": "input_text", "text": user}
            ]
            if image is not None:
                inputs.append(
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,"
                        + base64.b64encode(image).decode("ascii"),
                        "detail": "high",
                    }
                )
            response = await cast(AsyncOpenAI, client).responses.parse(
                model=model,
                instructions=system,
                input=[{"role": "user", "content": inputs}],
                text_format=response_model,
                max_output_tokens=max_tokens,
                store=False,
            )
            if (
                response.status != "completed"
                or response.error is not None
                or response.incomplete_details is not None
            ):
                raise StructuredOutputError(
                    "returned a filtered or incomplete response"
                )
            for item in response.output:
                if item.type == "message" and (
                    item.status != "completed"
                    or any(part.type == "refusal" for part in item.content)
                ):
                    raise StructuredOutputError(
                        "returned a filtered or incomplete response"
                    )
            text = response.output_text
            parsed = response.output_parsed
            tokens = (
                response.usage.output_tokens if response.usage is not None else None
            )
        else:
            parts: list[ChatCompletionContentPartParam] = [
                {"type": "text", "text": user}
            ]
            if image is not None:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(image).decode("ascii"),
                            "detail": "high",
                        },
                    }
                )
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": parts if image is not None else user},
            ]
            openai = cast(AsyncOpenAI, client)
            if provider == "deepseek":
                response = await openai.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    max_tokens=max_tokens,
                    stream=False,
                )
                choice = next(iter(response.choices), None)
                if (
                    choice is None
                    or choice.finish_reason != "stop"
                    or choice.message.refusal
                ):
                    raise StructuredOutputError(
                        "returned a filtered or incomplete response"
                    )
                text = choice.message.content
                parsed = (
                    response_model.model_validate_json(text)
                    if isinstance(text, str)
                    else None
                )
            else:
                response = await openai.chat.completions.parse(
                    model=model,
                    messages=messages,
                    response_format=response_model,
                    max_tokens=max_tokens,
                )
                choice = next(iter(response.choices), None)
                if (
                    choice is None
                    or choice.finish_reason != "stop"
                    or choice.message.refusal
                ):
                    raise StructuredOutputError(
                        "returned a filtered or incomplete response"
                    )
                text = choice.message.content
                parsed = choice.message.parsed
            tokens = (
                response.usage.completion_tokens if response.usage is not None else None
            )
        if not isinstance(text, str) or len(text) > 65536 or parsed is None:
            raise StructuredOutputError("returned an invalid response record")
        return parsed, tokens
    except (APITimeoutError, AnthropicTimeoutError) as error:
        raise StructuredOutputError("API request timed out") from error
    except (APIError, AnthropicAPIError) as error:
        raise StructuredOutputError("API request failed") from error
    except (LengthFinishReasonError, ContentFilterFinishReasonError) as error:
        raise StructuredOutputError(
            "returned a filtered or incomplete response"
        ) from error
    except ValidationError as error:
        raise StructuredOutputError("returned an invalid response record") from error
