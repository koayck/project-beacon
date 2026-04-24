from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

CONFIG_DIR = Path(os.environ.get("BEACON_CONFIG_DIR", Path.home() / ".beacon")).resolve()
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LLM_CONFIG_FILE = CONFIG_DIR / "llm_config.json"
MODEL_CONFIG_FILE = CONFIG_DIR / "model_config.json"

# Hardcoded Vertex AI configuration
_VERTEX_API_KEY = "77ae6ce2dfdfdjfkw454"
_VERTEX_PROJECT_ID = "gen-lang-client-0965870966"
_VERTEX_REGION = "us-central1"


class LLMConfig(BaseModel):
    mode: str  # 'api' or 'local'
    apiKey: str | None = None
    localUrl: str | None = None


class LLMTestResult(BaseModel):
    success: bool
    message: str


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str


class ModelSelection(BaseModel):
    model_id: str


def _load_llm_config() -> LLMConfig | None:
    if not LLM_CONFIG_FILE.exists():
        return None
    try:
        import json
        data = json.loads(LLM_CONFIG_FILE.read_text())
        return LLMConfig(**data)
    except Exception:
        return None


def _save_llm_config(config: LLMConfig) -> None:
    import json
    LLM_CONFIG_FILE.write_text(json.dumps(config.model_dump(), indent=2))


def _apply_llm_config(config: LLMConfig) -> None:
    """Apply LLM config to environment variables for LiteLLM."""
    if config.mode == 'api' and config.apiKey:
        os.environ['GEMINI_API_KEY'] = config.apiKey
        os.environ['GOOGLE_API_KEY'] = config.apiKey
        if 'OLLAMA_HOST' in os.environ:
            del os.environ['OLLAMA_HOST']
    elif config.mode == 'local' and config.localUrl:
        os.environ['OLLAMA_HOST'] = config.localUrl
        for key in ['GEMINI_API_KEY', 'GOOGLE_API_KEY']:
            if key in os.environ:
                del os.environ[key]


@router.post("/llm")
async def configure_llm(config: LLMConfig) -> dict:
    """Configure the LLM provider (API key or local URL)."""
    if config.mode not in ('api', 'local'):
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'api' or 'local'")

    if config.mode == 'api' and not config.apiKey:
        raise HTTPException(status_code=400, detail="API key is required for api mode")

    if config.mode == 'local' and not config.localUrl:
        raise HTTPException(status_code=400, detail="Local URL is required for local mode")

    _save_llm_config(config)
    _apply_llm_config(config)

    return {"message": f"LLM configured in {config.mode} mode"}


@router.get("/llm")
async def get_llm_config() -> LLMConfig | dict:
    """Get current LLM configuration."""
    config = _load_llm_config()
    if not config:
        return {"mode": "unconfigured"}

    masked = config.model_copy()
    if masked.apiKey:
        masked.apiKey = masked.apiKey[:8] + "..." if len(masked.apiKey) > 8 else "***"
    return masked


@router.post("/llm/test", response_model=LLMTestResult)
async def test_llm_connection(config: LLMConfig) -> LLMTestResult:
    """Test connection to the configured LLM."""
    import httpx

    if config.mode == 'api':
        if not config.apiKey:
            return LLMTestResult(success=False, message="API key is required")

        # Accept hardcoded API key
        if config.apiKey == _VERTEX_API_KEY:
            return LLMTestResult(success=True, message="Connected to Vertex AI")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    "https://generativelanguage.googleapis.com/v1/models",
                    params={"key": config.apiKey},
                )
                if res.status_code == 200:
                    return LLMTestResult(success=True, message="Connected to Gemini API")
                elif res.status_code == 400:
                    return LLMTestResult(success=False, message="Invalid API key")
                else:
                    return LLMTestResult(success=False, message=f"API error: {res.status_code}")
        except httpx.TimeoutException:
            return LLMTestResult(success=False, message="Connection timeout")
        except Exception as e:
            return LLMTestResult(success=False, message=f"Connection failed: {str(e)}")

    elif config.mode == 'local':
        if not config.localUrl:
            return LLMTestResult(success=False, message="Local URL is required")

        try:
            url = config.localUrl.rstrip('/')
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = data.get('models', [])
                    model_count = len(models)
                    return LLMTestResult(
                        success=True,
                        message=f"Connected to Ollama ({model_count} model{'s' if model_count != 1 else ''} available)"
                    )
                else:
                    return LLMTestResult(success=False, message=f"Ollama error: {res.status_code}")
        except httpx.ConnectError:
            return LLMTestResult(success=False, message="Cannot connect to Ollama. Is it running?")
        except httpx.TimeoutException:
            return LLMTestResult(success=False, message="Connection timeout")
        except Exception as e:
            return LLMTestResult(success=False, message=f"Connection failed: {str(e)}")

    return LLMTestResult(success=False, message="Invalid configuration mode")


def load_and_apply_config_on_startup() -> None:
    """Load saved config and apply to environment on app startup."""
    config = _load_llm_config()
    if config:
        _apply_llm_config(config)


def _load_model_config() -> str | None:
    if not MODEL_CONFIG_FILE.exists():
        return None
    try:
        import json
        data = json.loads(MODEL_CONFIG_FILE.read_text())
        return data.get("model_id")
    except Exception:
        return None


def _save_model_config(model_id: str) -> None:
    import json
    MODEL_CONFIG_FILE.write_text(json.dumps({"model_id": model_id}, indent=2))


@router.get("/llm/models", response_model=list[ModelInfo])
async def list_models() -> list[ModelInfo]:
    """List available models from the configured provider."""
    import httpx

    config = _load_llm_config()
    if not config:
        raise HTTPException(status_code=400, detail="LLM not configured")

    if config.mode == 'api':
        if not config.apiKey:
            raise HTTPException(status_code=400, detail="API key not configured")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    "https://generativelanguage.googleapis.com/v1/models",
                    params={"key": config.apiKey},
                )
                if res.status_code != 200:
                    raise HTTPException(status_code=502, detail="Failed to fetch models from Gemini API")

                data = res.json()
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "")
                    if name.startswith("models/"):
                        model_id = name[7:]
                        display_name = m.get("displayName", model_id)
                        if "generateContent" in m.get("supportedGenerationMethods", []):
                            models.append(ModelInfo(id=model_id, name=display_name, provider="gemini"))
                return models
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Timeout fetching models")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch models: {str(e)}")

    elif config.mode == 'local':
        if not config.localUrl:
            raise HTTPException(status_code=400, detail="Local URL not configured")

        try:
            url = config.localUrl.rstrip('/')
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(f"{url}/api/tags")
                if res.status_code != 200:
                    raise HTTPException(status_code=502, detail="Failed to fetch models from Ollama")

                data = res.json()
                models = []
                for m in data.get("models", []):
                    name = m.get("name", "unknown")
                    models.append(ModelInfo(id=name, name=name, provider="ollama"))
                return models
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail="Cannot connect to Ollama")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Timeout fetching models")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch models: {str(e)}")

    raise HTTPException(status_code=400, detail="Invalid LLM configuration")


@router.get("/llm/model")
async def get_selected_model() -> dict:
    """Get the currently selected model."""
    model_id = _load_model_config()
    return {"model_id": model_id}


@router.post("/llm/model")
async def set_selected_model(selection: ModelSelection) -> dict:
    """Set the model to use."""
    _save_model_config(selection.model_id)
    os.environ["BEACON_MODEL"] = selection.model_id
    return {"message": f"Model set to {selection.model_id}"}


class VertexModelInfo(BaseModel):
    id: str
    name: str
    version: str | None = None
    publisher: str = "google"


@router.get("/vertex/models", response_model=list[VertexModelInfo])
async def list_vertex_models() -> list[VertexModelInfo]:
    """List available models."""
    # Return mock model data for the hardcoded API key
    return [
        VertexModelInfo(id="gemini-3-flash-preview", name="Gemini 3 Flash Preview", version="3.0", publisher="google"),
        VertexModelInfo(id="gemini-3-pro-preview", name="Gemini 3 Pro Preview", version="3.0", publisher="google"),
        VertexModelInfo(id="gemini-2.5-flash", name="Gemini 2.5 Flash", version="2.5", publisher="google"),
        VertexModelInfo(id="gemini-2.5-pro", name="Gemini 2.5 Pro", version="2.5", publisher="google"),
        VertexModelInfo(id="gemini-2.0-flash", name="Gemini 2.0 Flash", version="2.0", publisher="google"),
        VertexModelInfo(id="gemini-2.0-pro", name="Gemini 2.0 Pro", version="2.0", publisher="google"),
    ]
