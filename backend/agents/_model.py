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

import litellm
from google.adk.models.lite_llm import LiteLlm
from google.genai import types as genai_types
from dotenv import load_dotenv

load_dotenv()

model = "gemini/gemini-2.5-flash"

# Drop unsupported params silently (e.g. presence_penalty not supported by ollama_chat)
litellm.drop_params = True

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
