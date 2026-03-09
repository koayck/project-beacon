"""
Shared model and generation config for all ADK agents.

Parameters follow Qwen3 instruct (non-thinking) recommendations:
  temperature=1.0, top_p=0.95, top_k=20, presence_penalty=1.5
  thinking disabled via think=False (Ollama-native API param)

Note: ThinkingConfig(thinking_budget=0) is a Gemini-specific concept and gets
silently dropped by litellm.drop_params for ollama_chat. The real thinking
control for Qwen3 on Ollama is the `think` kwarg passed directly to LiteLlm,
which flows through: LiteLlm._additional_args → litellm.acompletion → Ollama API.
"""
from __future__ import annotations

import litellm
from google.adk.models.lite_llm import LiteLlm
from google.genai import types as genai_types

# Drop unsupported params silently (e.g. presence_penalty not supported by ollama_chat)
litellm.drop_params = True

QWEN3_INSTRUCT = LiteLlm(
    model="ollama_chat/qwen3.5:4b",
    think=False,  # Ollama-native: disables Qwen3 extended thinking (80s → 7s)
)

QWEN3_GEN_CONFIG = genai_types.GenerateContentConfig(
    temperature=1.0,
    top_p=0.95,
    top_k=20,
    presence_penalty=1.5,
)
