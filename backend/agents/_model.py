"""
Shared model and generation configs for all ADK agents.

Per-agent temperature tuning for Qwen3 4B Q4_K_M:
  commander:  temp=0.5  — routing decisions need precision, less hallucination
  sub-agents: temp=0.7  — balanced creativity for tool selection

Qwen3 instruct (non-thinking) base params: top_p=0.95, top_k=20
presence_penalty kept at 1.0 (1.5 caused model to avoid repeating tool names).

Note: ThinkingConfig(thinking_budget=0) is Gemini-specific and gets silently
dropped by litellm.drop_params for ollama_chat. Real thinking control for Qwen3
on Ollama is the `think` kwarg passed directly to LiteLlm.
"""
from __future__ import annotations

import inspect
import logging
import os
from typing import Any

import litellm
from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm
from google.genai import types as genai_types

load_dotenv()
_logger = logging.getLogger(__name__)


def _ensure_callback(existing: object, callback: str) -> list[str]:
    callbacks: list[str] = []
    if isinstance(existing, list):
        callbacks = [str(item) for item in existing]
    elif isinstance(existing, tuple):
        callbacks = [str(item) for item in existing]
    elif isinstance(existing, str):
        callbacks = [existing]
    if callback not in callbacks:
        callbacks.append(callback)
    return callbacks


def _patch_langfuse_sdk_integration_kwarg() -> None:
    """
    LiteLLM currently passes `sdk_integration` to Langfuse.
    Langfuse 4 removed this kwarg, so we strip it for compatibility.
    """
    from langfuse import Langfuse

    signature = inspect.signature(Langfuse.__init__)
    if "sdk_integration" in signature.parameters:
        return

    if getattr(Langfuse, "_beacon_sdk_kwarg_patch", False):
        return

    original_init = Langfuse.__init__

    def _patched_init(self: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("sdk_integration", None)
        return original_init(self, *args, **kwargs)

    Langfuse.__init__ = _patched_init  # type: ignore[method-assign]
    setattr(Langfuse, "_beacon_sdk_kwarg_patch", True)
    _logger.info("Applied Langfuse compatibility patch for sdk_integration kwarg")


def _configure_langfuse() -> None:
    langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if bool(langfuse_public_key) != bool(langfuse_secret_key):
        _logger.warning(
            "Langfuse observability disabled: set both LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY."
        )
        return

    if not langfuse_public_key:
        return

    _patch_langfuse_sdk_integration_kwarg()

    litellm.success_callback = _ensure_callback(
        getattr(litellm, "success_callback", None),
        "langfuse",
    )
    litellm.failure_callback = _ensure_callback(
        getattr(litellm, "failure_callback", None),
        "langfuse",
    )
    _logger.info("Langfuse observability enabled")

model = "gemini/gemini-2.5-flash"

# Drop unsupported params silently (e.g. presence_penalty not supported by ollama_chat)
litellm.drop_params = True
_configure_langfuse()

QWEN3_INSTRUCT = LiteLlm(
    # model="ollama_chat/qwen3.5:4b-q4_K_M",
    model,
    # api_base="http://100.68.65.126:11434",
    # think=False,  # Ollama-native: disables Qwen3 extended thinking (80s → 7s)
)

# Commander: lower temperature for precise routing decisions
QWEN3_GEN_CONFIG_COMMANDER = genai_types.GenerateContentConfig(
    temperature=0.5,
    top_p=0.95,
    top_k=20,
    # presence_penalty=1.0,
)

# Sub-agents (navigation, thermal): slightly higher temperature for tool reasoning
QWEN3_GEN_CONFIG = genai_types.GenerateContentConfig(
    temperature=0.7,
    top_p=0.95,
    top_k=20,
    # presence_penalty=1.0,
)
