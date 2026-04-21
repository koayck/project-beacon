"""
Shared model and generation configs for all ADK agents.

Per-agent temperature tuning profiles:
  strategic agents (commander/parser/planner/recovery):
    temp=0.35, top_p=0.9, with thinking enabled
  execution agents (navigation/scan/supply loops):
    temp=0.25, top_p=0.9, no extra thinking config

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
from google.genai import types
from openinference.instrumentation.google_adk import GoogleADKInstrumentor


from langfuse import get_client

load_dotenv()

langfuse = get_client()

# Verify connection
if langfuse.auth_check():
    print("Langfuse client is authenticated and ready!")
else:
    print("Authentication failed. Please check your credentials and host.")

GoogleADKInstrumentor().instrument()

litellm.callbacks = ["langfuse_otel"]


model = "gemini-3-flash-preview"
# model = "gemini-2.5-flash"

# # Drop unsupported params silently (e.g. presence_penalty not supported by ollama_chat)
litellm.drop_params = True

_THINKING_CONFIG = types.ThinkingConfig(include_thoughts=True, thinking_budget=4096)

QWEN3_INSTRUCT = model

# QWEN3_INSTRUCT = LiteLlm(
#     # model="ollama_chat/qwen3.5:4b-q4_K_M",
#     model,
#     # api_base="http://100.68.65.126:11434",
#     # think=False,  # Ollama-native: disables Qwen3 extended thinking (80s → 7s)
# )

# Strategic profile: precise planning/routing with model thinking enabled.
QWEN3_GEN_CONFIG_COMMANDER = types.GenerateContentConfig(
    temperature=0.35,
    top_p=0.9,
    top_k=20,
    thinking_config=_THINKING_CONFIG,
)

# Execution profile: deterministic tool-using loops (no explicit thinking config).
QWEN3_GEN_CONFIG_EXECUTION = types.GenerateContentConfig(
    temperature=0.25,
    top_p=0.9,
    top_k=20,
)

# Backward-compatible alias for existing execution agents.
QWEN3_GEN_CONFIG = QWEN3_GEN_CONFIG_EXECUTION
