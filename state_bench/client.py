"""
Shared Azure OpenAI client for STATE-Bench.

This module provides reusable OpenAI and Azure OpenAI clients for
STATE-Bench agent, simulator, and judge calls.

Usage:
    from state_bench.client import LLMClient

    # Chat completion
    client = LLMClient()
    response = client.complete_chat(
        messages=[{"role": "user", "content": "Hello"}],
    )

    # JSON response
    data = client.complete_json(
        prompt="Return a JSON with name and age",
        system_prompt="Return valid JSON only.",
    )
"""

import json
import os
import pprint
import subprocess
import threading
from pathlib import Path
from typing import Any

import yaml
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from openai import APIStatusError, AuthenticationError, AzureOpenAI, OpenAI
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
)

from state_bench.paths import CONFIGS_DIR

EndpointDeployment = tuple[str, str]  # (endpoint_url, deployment_name)


class ContentFilterError(Exception):
    """Raised when Azure content filter blocks or truncates a response."""


load_dotenv()


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


# Core LLM config (max_tokens, retry, defaults)
CONFIG: dict[str, Any] = _load_yaml(CONFIGS_DIR / "llm.yaml")

_DEFAULT_MAX_TOKENS: int = CONFIG["max_tokens"]["default"]


def _before_sleep_print(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    fn = retry_state.fn
    name = f"{fn.__module__}.{fn.__qualname__}" if fn else "unknown"
    print(f"Retrying {name} in {wait:.1f} seconds as it raised {type(exc).__name__}: {exc}")


def _wait_by_error_type(retry_state: RetryCallState) -> float:
    """Return wait time based on exception type.

    Auth errors (expired token) retry after 2 seconds since the token provider
    refreshes automatically. Other errors (rate limits, server errors) use the
    configured wait time.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, AuthenticationError):
        return 2
    return float(CONFIG["retry"]["wait_seconds"])


_llm_retry = retry(
    stop=stop_after_attempt(CONFIG["retry"]["max_attempts"]),
    wait=_wait_by_error_type,
    retry=retry_if_exception_type((APIStatusError, AuthenticationError, json.JSONDecodeError, ContentFilterError)),
    before_sleep=_before_sleep_print,
    reraise=True,
)


def _check_content_filter(response: Any) -> None:
    """Raise ContentFilterError if the response was truncated by Azure content filter.

    Checks response.incomplete_details.reason == "content_filter". This is the
    structured signal from the API — more reliable than keyword matching.
    """
    if (
        response.status == "incomplete"
        and response.incomplete_details
        and response.incomplete_details.reason == "content_filter"
    ):
        # Extract filter details for the error message
        details = ""
        resp_dict = response.model_dump()
        for cf in resp_dict.get("content_filters", []):
            if cf.get("blocked") and cf.get("source_type") == "completion":
                categories = cf.get("content_filter_results", {})
                triggered = [cat for cat, info in categories.items() if info.get("filtered")]
                if triggered:
                    details = f" (categories: {', '.join(triggered)})"
        raise ContentFilterError(f"Azure content filter blocked completion{details}")


def _parse_env_list(var_name: str) -> list[str]:
    """Parse a comma-separated environment variable into a list of stripped strings."""
    raw = os.environ.get(var_name, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _get_env_with_numbered_fallback(var_name: str) -> str:
    """Return env var, falling back to the canonical _1 slot when present."""
    return os.environ.get(var_name) or os.environ.get(f"{var_name}_1", "")


def _get_cli_access_token() -> str | None:
    """Get a fresh Cognitive Services token from local CLI auth if available."""
    commands = [
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://cognitiveservices.azure.com/",
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        ["azd", "auth", "token", "--scope", "https://cognitiveservices.azure.com/.default"],
    ]
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=20)
        except Exception:
            continue
        token = proc.stdout.strip()
        if token:
            return token
    return None


def _build_azure_openai_client(
    endpoint: str, api_version: str, api_key_var: str = "AZURE_OPENAI_API_KEY"
) -> AzureOpenAI:
    """Build an authenticated AzureOpenAI client with deterministic auth precedence."""
    api_key = os.environ.get(api_key_var) or os.environ.get("AZURE_OPENAI_API_KEY")
    if api_key:
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )

    static_token = os.environ.get("AZURE_OPENAI_TOKEN")
    if static_token:
        return AzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token=static_token,
            api_version=api_version,
        )

    if _get_cli_access_token():

        def cli_token_provider() -> str:
            token = _get_cli_access_token()
            if not token:
                raise RuntimeError("Unable to mint Azure OpenAI CLI access token")
            return token

        return AzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=cli_token_provider,
            api_version=api_version,
        )

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")
    return AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=api_version,
    )


def _build_openai_client(api_key_var: str) -> OpenAI:
    """Build an OpenAI SDK client for the OpenAI API."""
    api_key = os.environ.get(api_key_var) or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(f"API key required. Set {api_key_var} or OPENAI_API_KEY.")
    if os.environ.get("STATE_BENCH_AGENT_BASE_URL") or os.environ.get("OPENAI_BASE_URL"):
        raise ValueError("Third-party OpenAI-compatible base URLs are not supported for StateBenchAgent.")
    return OpenAI(api_key=api_key)


def _get_default_deployment() -> str:
    """Get default agent deployment.

    Raises:
        ValueError: If no agent deployments are configured.
    """
    deployments = _parse_env_list("STATE_BENCH_AGENT_DEPLOYMENTS") or _parse_env_list("STATE_BENCH_AGENT_DEPLOYMENTS_1")
    if not deployments:
        raise ValueError("No deployments configured. Set STATE_BENCH_AGENT_DEPLOYMENTS environment variable.")
    return deployments[0]


def _discover_all_endpoints(
    endpoint_var: str = "AZURE_OPENAI_ENDPOINT",
    deployments_var: str = "AZURE_OPENAI_DEPLOYMENTS",
) -> list[EndpointDeployment]:
    """Discover all (endpoint, deployment) pairs from environment variables.

    Supports either unnumbered vars as the primary pool entry or a fully
    numbered layout starting at {endpoint_var}_1 / {deployments_var}_1.
    Additional numbered pools are then read from _2.._10.
    """
    pairs: list[EndpointDeployment] = []

    def add_pairs(endpoint_name: str, deployments_name: str) -> None:
        endpoint = os.environ.get(endpoint_name, "")
        deployments = _parse_env_list(deployments_name)
        if endpoint and deployments:
            for deployment in deployments:
                pairs.append((endpoint, deployment))

    add_pairs(endpoint_var, deployments_var)
    add_pairs(f"{endpoint_var}_1", f"{deployments_var}_1")

    for n in range(2, 11):
        add_pairs(f"{endpoint_var}_{n}", f"{deployments_var}_{n}")

    deduped_pairs: list[EndpointDeployment] = []
    seen_pairs: set[EndpointDeployment] = set()
    for pair in pairs:
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        deduped_pairs.append(pair)

    return deduped_pairs


class LeastBusyPool:
    """Mixin providing least-busy selection across a pool of resources.

    Subclasses must set `self._pool_items` (list of resources) before use.
    """

    def __init__(self) -> None:
        self._pool_items: list[Any] = []
        self._in_flight: list[int] = []
        self._pool_lock = threading.Lock()

    def _init_pool(self, items: list[Any]) -> None:
        self._pool_items = items
        self._in_flight = [0] * len(items)

    def _acquire(self) -> tuple[int, Any]:
        with self._pool_lock:
            idx = min(range(len(self._in_flight)), key=lambda i: self._in_flight[i])
            self._in_flight[idx] += 1
            return idx, self._pool_items[idx]

    def _release(self, idx: int) -> None:
        with self._pool_lock:
            self._in_flight[idx] -= 1


class LLMClient:
    """Simple Azure OpenAI client for general-purpose LLM queries.

    This client handles:
    - Azure AD authentication via DefaultAzureCredential
    - Chat completions
    - JSON-formatted responses

    For complex use cases with conversation threading or state management,
    prefer a purpose-built wrapper around the provider client.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        deployment: str | None = None,
        api_version: str | None = None,
        provider: str = "azure_openai",
        api_key_var: str = "STATE_BENCH_AGENT_API_KEY",
    ):
        """Initialize the Azure OpenAI client.

        Args:
            endpoint: Azure OpenAI endpoint URL. Defaults to STATE_BENCH_AGENT_ENDPOINT env var.
            deployment: Model deployment name. Defaults to first STATE_BENCH_AGENT_DEPLOYMENTS entry.
            api_version: API version. Defaults to STATE_BENCH_AGENT_API_VERSION env var or config default.

        Raises:
            ValueError: If endpoint is not provided and STATE_BENCH_AGENT_ENDPOINT is not set.
            ValueError: If no deployments are configured.
        """
        self.provider = provider
        self._chat_response_history: dict[str, list[dict[str, Any]]] = {}
        if self.provider == "openai":
            self.endpoint = ""
            self.deployment = deployment or os.environ.get("STATE_BENCH_AGENT_MODEL") or os.environ.get("OPENAI_MODEL")
            if not self.deployment:
                raise ValueError("OpenAI model required. Set STATE_BENCH_AGENT_MODEL or pass deployment.")
        else:
            self.endpoint = endpoint or _get_env_with_numbered_fallback("STATE_BENCH_AGENT_ENDPOINT")
            self.deployment = deployment or _get_default_deployment()
        self.api_version = api_version or os.environ.get(
            "STATE_BENCH_AGENT_API_VERSION", CONFIG["defaults"]["api_version"]
        )
        self.deployments = [self.deployment]

        if self.provider == "azure_openai" and not self.endpoint:
            raise ValueError(
                "Azure OpenAI endpoint required. Set STATE_BENCH_AGENT_ENDPOINT environment variable "
                "or pass endpoint parameter."
            )

        if self.provider == "azure_openai":
            # Set up Azure AD authentication. Prefer deterministic local CLI token minting
            # over DefaultAzureCredential discovery so long-running batch jobs don't depend on
            # whichever background credential source happens to be valid.
            self._client = _build_azure_openai_client(self.endpoint, self.api_version, api_key_var=api_key_var)
        elif self.provider == "openai":
            self._client = _build_openai_client(api_key_var)
        else:
            raise ValueError(f"Unknown provider: {self.provider!r}")

    @_llm_retry
    def complete_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
    ) -> str:
        """Generate a completion from a list of messages.

        Args:
            messages: List of message dicts with "role" and "content" keys.
            max_tokens: Maximum tokens in response.
            temperature: Optional sampling temperature. Omitted when None.

        Returns:
            The generated text response.
        """
        kwargs: dict[str, Any] = {
            "model": self.deployment,
            "input": messages,
            "max_output_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = self._client.responses.create(**kwargs)
        _check_content_filter(response)

        return response.output_text

    @_llm_retry
    def complete_with_tools(
        self,
        *,
        instructions: str,
        input: list[Any],
        tools: list[dict[str, Any]],
        previous_response_id: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = 0,
    ) -> Any:
        """Call the Responses API with tool schemas.

        Returns the raw Response object (with .output, .id, .output_text, etc.).
        Used by the agent turn loop for tool-calling conversations.
        """
        kwargs: dict[str, Any] = {
            "model": self.deployment,
            "instructions": instructions,
            "input": input,
            "tools": tools,
            "previous_response_id": previous_response_id,
            "max_output_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = self._client.responses.create(**kwargs)
        _check_content_filter(response)
        return response

    @_llm_retry
    def complete_json_response(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        reasoning_effort: str | None = None,
    ) -> Any:
        """Generate a raw JSON-formatted Responses API result.

        Args:
            prompt: The user prompt/question.
            system_prompt: Optional system prompt to set context.
            max_tokens: Maximum tokens in response.
            reasoning_effort: Optional reasoning effort level ("low", "medium", "high").

        Returns:
            Raw Response object.
        """
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {
            "model": self.deployment,
            "input": messages,
            "max_output_tokens": max_tokens,
            "text": {"format": {"type": "json_object"}},
        }
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        response = self._client.responses.create(**kwargs)
        _check_content_filter(response)
        return response

    @_llm_retry
    def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        """Generate a JSON response.

        Args:
            prompt: The user prompt/question.
            system_prompt: Optional system prompt to set context.
            max_tokens: Maximum tokens in response.
            reasoning_effort: Optional reasoning effort level ("low", "medium", "high").

        Returns:
            Parsed JSON as a dictionary.

        Raises:
            json.JSONDecodeError: If the response is not valid JSON.
        """
        response = self.complete_json_response(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

        try:
            return json.loads(response.output_text)
        except json.JSONDecodeError:
            # Log raw output for debugging truncation/malformed JSON
            raw = response.output_text
            status = response.status
            reason = response.incomplete_details.reason if response.incomplete_details else None
            # Dump full response dict to find Azure-specific content filter fields
            try:
                resp_dict = response.model_dump()
                # Look for any content_filter keys in the response
                filter_keys = {
                    k: v for k, v in resp_dict.items() if "filter" in str(k).lower() or "safety" in str(k).lower()
                }
                if filter_keys:
                    print(f"  Content filter details: {pprint.pformat(filter_keys)}")
                # Also check output items for extra fields
                for i, item in enumerate(resp_dict.get("output", [])):
                    extra = {k: v for k, v in item.items() if k not in ("id", "type", "text", "status")}
                    if extra:
                        print(f"  Output item {i} extra fields: {pprint.pformat(extra)}")
            except Exception:
                pass
            print(f"  JSON parse failed | status={status} | reason={reason} | len={len(raw)} | tail=...{raw[-100:]!r}")
            raise


def _resolve_deployments(
    deployments: list[str] | None = None,
    endpoint_var: str = "STATE_BENCH_AGENT_ENDPOINT",
    deployments_var: str = "STATE_BENCH_AGENT_DEPLOYMENTS",
    provider: str = "azure_openai",
) -> list[EndpointDeployment]:
    """Resolve deployment list from argument or environment, raising if empty.

    When deployments is None (the common case), auto-discovers all configured
    endpoints from the selected endpoint/deployment environment variables.

    When deployments is an explicit list of names, pairs each with the selected
    primary endpoint variable.
    """
    if provider == "openai":
        model = (
            (deployments[0] if deployments else None)
            or os.environ.get("STATE_BENCH_AGENT_MODEL")
            or os.environ.get("OPENAI_MODEL")
        )
        resolved = [model] if model else []
        if not resolved:
            raise ValueError("No OpenAI model configured. Set STATE_BENCH_AGENT_MODEL.")
        return [("", model) for model in resolved]

    if deployments is None:
        pairs = _discover_all_endpoints(endpoint_var, deployments_var)
        if pairs:
            return pairs
        primary_endpoint = os.environ.get(endpoint_var, "")
        if not primary_endpoint:
            raise ValueError(
                f"Azure OpenAI endpoint required. Set {endpoint_var} environment variable or pass endpoint parameter."
            )
        default_deployments = _parse_env_list(deployments_var)
        if not default_deployments:
            raise ValueError(f"No deployments configured. Set {deployments_var} environment variable.")
        return [(primary_endpoint, default_deployments[0])]

    if not deployments:
        raise ValueError("No deployments configured")

    primary_endpoint = os.environ.get(endpoint_var, "")
    if not primary_endpoint:
        raise ValueError(
            f"Azure OpenAI endpoint required. Set {endpoint_var} environment variable or pass endpoint parameter."
        )
    return [(primary_endpoint, d) for d in deployments]


class PooledLLMClient(LeastBusyPool):
    """LLM client that routes every call to the least-busy deployment.

    Drop-in replacement for LLMClient that tracks in-flight requests
    per deployment and always picks the one with the fewest active calls.
    This ensures no endpoint sits idle while another is saturated.

    Usage:
        pool = PooledLLMClient()  # Uses STATE_BENCH_AGENT_DEPLOYMENTS env var
        response = pool.complete_chat(messages)  # Routes to least-busy deployment
    """

    def __init__(
        self,
        deployments: list[str] | None = None,
        endpoint_var: str = "STATE_BENCH_AGENT_ENDPOINT",
        deployments_var: str = "STATE_BENCH_AGENT_DEPLOYMENTS",
        provider: str = "azure_openai",
        api_key_var: str = "STATE_BENCH_AGENT_API_KEY",
        api_version: str | None = None,
        endpoint_deployments: list[EndpointDeployment] | None = None,
    ):
        super().__init__()

        if endpoint_deployments is None:
            endpoint_deployments = _resolve_deployments(deployments, endpoint_var, deployments_var, provider=provider)

        self.deployments = [d for _, d in endpoint_deployments]
        self.clients = [
            LLMClient(
                endpoint=ep,
                deployment=d,
                provider=provider,
                api_key_var=api_key_var,
                api_version=api_version,
            )
            for ep, d in endpoint_deployments
        ]
        self._init_pool(self.clients)
        self._response_client_map: dict[str, int] = {}
        self._response_client_lock = threading.Lock()

        endpoints_summary: dict[str, int] = {}
        for ep, _ in endpoint_deployments:
            endpoints_summary[ep] = endpoints_summary.get(ep, 0) + 1
        for ep, count in endpoints_summary.items():
            print(f"PooledLLMClient: {ep} -> {count} deployments")

    def _remember_response_client(self, response_id: str | None, client_idx: int) -> None:
        if not response_id:
            return
        with self._response_client_lock:
            self._response_client_map[response_id] = client_idx

    def _client_for_previous_response(self, previous_response_id: str | None) -> tuple[int, Any] | None:
        if not previous_response_id:
            return None
        with self._response_client_lock:
            idx = self._response_client_map.get(previous_response_id)
        if idx is None:
            return None
        return idx, self.clients[idx]

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Route a call to the least-busy client, with sticky routing for threaded tool calls."""
        previous_response_id = kwargs.get("previous_response_id") if method == "complete_with_tools" else None
        pinned = self._client_for_previous_response(previous_response_id)
        if pinned is not None:
            idx, client = pinned
            result = getattr(client, method)(*args, **kwargs)
            if method == "complete_with_tools":
                self._remember_response_client(getattr(result, "id", None), idx)
            return result

        idx, client = self._acquire()
        try:
            result = getattr(client, method)(*args, **kwargs)
        except AuthenticationError as first_exc:
            self._release(idx)
            failed = {idx}
            print(f"  Auth error on {client.endpoint}/{client.deployment}, trying other clients...")
            for fallback_idx, fallback_client in enumerate(self.clients):
                if fallback_idx in failed:
                    continue
                try:
                    result = getattr(fallback_client, method)(*args, **kwargs)
                    if method == "complete_with_tools":
                        self._remember_response_client(getattr(result, "id", None), fallback_idx)
                    return result
                except AuthenticationError:
                    failed.add(fallback_idx)
                    print(f"  Auth error on {fallback_client.endpoint}/{fallback_client.deployment}, trying another...")
            raise first_exc
        except Exception:
            self._release(idx)
            raise
        self._release(idx)
        if method == "complete_with_tools":
            self._remember_response_client(getattr(result, "id", None), idx)
        return result

    def complete_chat(
        self, messages: list[dict[str, str]], max_tokens: int = _DEFAULT_MAX_TOKENS, temperature: float | None = None
    ) -> str:
        return self._call("complete_chat", messages, max_tokens, temperature)

    def complete_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        return self._call("complete_json", prompt, system_prompt, max_tokens, reasoning_effort)

    def complete_with_tools(self, **kwargs: Any) -> Any:
        return self._call("complete_with_tools", **kwargs)

    def pinned(self) -> "PinnedClient":
        """Acquire a single deployment for the duration of a tool-calling loop.

        Usage:
            with pool.pinned() as client:
                response = client.complete_with_tools(...)
                # follow-up calls with previous_response_id go to same deployment
                response = client.complete_with_tools(..., previous_response_id=response.id)
        """
        return PinnedClient(self)


class PinnedClient:
    """Context manager that pins a PooledLLMClient to one deployment."""

    def __init__(self, pool: PooledLLMClient):
        self._pool = pool
        self._idx: int | None = None
        self._client: LLMClient | None = None

    def __enter__(self) -> LLMClient:
        self._idx, self._client = self._pool._acquire()
        return self._client

    def __exit__(self, *exc: Any) -> None:
        if self._idx is not None:
            self._pool._release(self._idx)


def build_llm_client(
    *,
    deployments: list[str] | None = None,
    endpoint_var: str = "STATE_BENCH_AGENT_ENDPOINT",
    deployments_var: str = "STATE_BENCH_AGENT_DEPLOYMENTS",
    provider: str = "azure_openai",
    api_key_var: str = "STATE_BENCH_AGENT_API_KEY",
    api_version: str | None = None,
) -> LLMClient | PooledLLMClient:
    """Build a single client for one deployment, or a pooled client for many."""
    endpoint_deployments = _resolve_deployments(
        deployments,
        endpoint_var,
        deployments_var,
        provider=provider,
    )
    if len(endpoint_deployments) == 1:
        endpoint, deployment = endpoint_deployments[0]
        return LLMClient(
            endpoint=endpoint,
            deployment=deployment,
            provider=provider,
            api_key_var=api_key_var,
            api_version=api_version,
        )
    return PooledLLMClient(
        endpoint_deployments=endpoint_deployments,
        provider=provider,
        api_key_var=api_key_var,
        api_version=api_version,
    )


def build_judge_client(env_prefix: str = "JUDGE") -> LLMClient | PooledLLMClient:
    """Compatibility shim: judge traffic uses the shared pooled client."""
    _ = env_prefix
    return build_llm_client()


def build_user_sim_client(api_version: str | None = None) -> LLMClient | PooledLLMClient:
    """Build the locked user-simulator client for canonical protocol runs."""
    return build_llm_client(
        endpoint_var="STATE_BENCH_EVAL_ENDPOINT",
        deployments_var="STATE_BENCH_EVAL_DEPLOYMENTS",
        api_key_var="STATE_BENCH_EVAL_API_KEY",
        api_version=api_version,
    )


def build_locked_judge_client(api_version: str | None = None) -> LLMClient | PooledLLMClient:
    """Build the locked judge client for canonical protocol scoring."""
    return build_llm_client(
        endpoint_var="STATE_BENCH_EVAL_ENDPOINT",
        deployments_var="STATE_BENCH_EVAL_DEPLOYMENTS",
        api_key_var="STATE_BENCH_EVAL_API_KEY",
        api_version=api_version,
    )
