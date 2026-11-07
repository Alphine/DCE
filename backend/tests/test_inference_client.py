"""Vultr inference client: contract, retries, timeouts, budget, secret hygiene, model list. No network."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.agent.inference_client import (
    InferenceError,
    InferencePolicy,
    MockInference,
    PlanRequest,
    TokenBudgetExceeded,
    VultrInference,
    make_inference,
)
from app.config import Settings

BASE = "https://api.vultrinference.com/v1"
KEY = "vk-TEST-SECRET-do-not-leak-0123456789"
MODEL = "test-model-id"


def _ok(text: str = '{"ok": true}', prompt: int = 10, completion: int = 5) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion},
    })


def _client(handler: Any, *, policy: InferencePolicy | None = None, sleeps: list[float] | None = None,
            clock: Any = None) -> VultrInference:
    sleep_log = sleeps if sleeps is not None else []

    async def fake_sleep(seconds: float) -> None:
        sleep_log.append(seconds)

    kwargs: dict[str, Any] = {"policy": policy or InferencePolicy(), "transport": httpx.MockTransport(handler),
                              "sleep": fake_sleep}
    if clock is not None:
        kwargs["clock"] = clock
    return VultrInference(BASE, KEY, MODEL, **kwargs)


def _messages(text: str = "hello") -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def _complete(client: VultrInference, *, max_tokens: int = 100, retries: int = 2) -> Any:
    return asyncio.run(client.complete(_messages(), max_tokens=max_tokens, op="test", retries=retries))


def test_success_path_uses_contract_and_returns_typed_result() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok('{"a": 1}', prompt=12, completion=7)

    result = _complete(_client(handler), max_tokens=100)

    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == f"{BASE}/chat/completions"
    assert request.method == "POST"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == MODEL
    assert body["max_tokens"] == 100
    assert result.text == '{"a": 1}'
    assert result.model_id == MODEL
    assert (result.prompt_tokens, result.completion_tokens) == (12, 7)
    assert result.attempts == 1
    assert result.latency_ms >= 0


def test_429_then_success_retries_once_and_honours_retry_after() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "rate"})
        return _ok()

    result = _complete(_client(handler, sleeps=sleeps), retries=2)

    assert len(calls) == 2
    assert result.attempts == 2
    assert sleeps == [1.0]


def test_401_is_not_retried() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"error": "unauthorized"})

    with pytest.raises(InferenceError) as info:
        _complete(_client(handler, sleeps=sleeps), retries=2)

    assert info.value.code == "INFERENCE_UNAVAILABLE"
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.parametrize("status", [400, 403])
def test_other_client_errors_are_not_retried(status: int) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(InferenceError):
        _complete(_client(handler), retries=2)
    assert len(calls) == 1


def test_timeout_is_retried_then_typed_error() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(InferenceError) as info:
        _complete(_client(handler, sleeps=sleeps), retries=2)

    assert info.value.code == "INFERENCE_TIMEOUT"
    assert len(calls) == 3          # first attempt plus two retries, never more
    assert len(sleeps) == 2


def test_total_timeout_bounds_the_whole_call() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return _ok()

    policy = InferencePolicy(total_timeout_s=0.05)
    client = VultrInference(BASE, KEY, MODEL, policy=policy, transport=httpx.MockTransport(slow))
    with pytest.raises(InferenceError) as info:
        asyncio.run(client.complete(_messages(), max_tokens=10, op="test", retries=0))
    assert info.value.code == "INFERENCE_TIMEOUT"


def test_budget_exceeded_before_any_request_is_sent() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _ok()

    # Input: 400 characters is about 100 estimated tokens, above a 10-token input budget.
    small_input = _client(handler, policy=InferencePolicy(input_budget_tokens=10))
    with pytest.raises(TokenBudgetExceeded) as info:
        asyncio.run(small_input.complete([{"role": "user", "content": "x" * 400}], max_tokens=5, op="t", retries=2))
    assert info.value.code == "TOKEN_BUDGET_EXCEEDED"

    # Output: max_tokens above the output budget is refused, not silently clamped.
    small_output = _client(handler, policy=InferencePolicy(output_budget_tokens=50))
    with pytest.raises(TokenBudgetExceeded):
        _complete(small_output, max_tokens=500)

    assert calls == []


def test_key_never_appears_in_exception_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    def leaking(request: httpx.Request) -> httpx.Response:
        # A forced transport error whose text contains the key.
        raise httpx.ConnectError(f"connect failed, auth={KEY}", request=request)

    def echoing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"server echoed {KEY}")

    for handler in (leaking, echoing):
        client = _client(handler, policy=InferencePolicy(max_retries=0))
        with pytest.raises(InferenceError) as info:
            _complete(client, retries=0)
        err = info.value
        assert KEY not in str(err)
        assert KEY not in repr(err)
        assert KEY not in err.message
        assert err.__context__ is None
        assert err.__cause__ is None
        assert KEY not in repr(client)

    assert KEY not in caplog.text
    for record in caplog.records:
        assert KEY not in record.getMessage()


def test_model_list_falls_back_to_configured_model_when_list_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/models")
        raise httpx.ConnectError("no route", request=request)

    client = _client(handler, policy=InferencePolicy(max_retries=0))
    models = asyncio.run(client.list_models())

    assert models.source == "configured_fallback"
    assert models.models == (MODEL,)


def test_model_list_from_provider_is_cached_until_ttl_expires() -> None:
    calls: list[int] = []
    now = [1000.0]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})

    policy = InferencePolicy(model_list_ttl_s=60.0)
    client = _client(handler, policy=policy, clock=lambda: now[0])

    first = asyncio.run(client.list_models())
    second = asyncio.run(client.list_models())
    assert first.source == "provider"
    assert first.models == ("model-a", "model-b")
    assert second == first
    assert len(calls) == 1

    now[0] += 61.0
    asyncio.run(client.list_models())
    assert len(calls) == 2


def test_retry_after_is_capped() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3600"})
        return _ok()

    policy = InferencePolicy(retry_after_cap_s=5.0)
    _complete(_client(handler, policy=policy, sleeps=sleeps), retries=2)
    assert sleeps == [5.0]


def test_plan_keeps_planner_interface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok(json.dumps({"tools": ["csv_analyzer"]}))

    request = PlanRequest(instruction="x", requested_outputs=[], dataset_name="d", profile={},
                          limits={"timeout_s": 30, "memory_mb": 512, "pids": 64})
    plan = asyncio.run(_client(handler).plan(request))
    assert plan == {"tools": ["csv_analyzer"]}


def test_plan_uses_the_full_output_ceiling_for_reasoning_models() -> None:
    # A reasoning model spends max_tokens on reasoning first; a 1500 cap returned empty content live.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok(json.dumps({"tools": ["csv_analyzer"]}))

    request = PlanRequest(instruction="x", requested_outputs=[], dataset_name="d", profile={},
                          limits={"timeout_s": 30, "memory_mb": 512, "pids": 64})
    asyncio.run(_client(handler).plan(request))
    body = json.loads(seen[0].content)
    assert body["max_tokens"] == InferencePolicy().output_budget_tokens


def test_mock_mode_never_touches_the_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("network client constructed in mock mode")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    client = make_inference(Settings(_env_file=None, data_dir=tmp_path, inference_mode="mock"))
    assert isinstance(client, MockInference)
    models = asyncio.run(client.list_models())
    assert models.source == "mock"


def test_make_inference_passes_policy_from_settings(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, data_dir=tmp_path, inference_mode="vultr",
                        vultr_inference_key="vk-TEST-not-real", inference_model="m",
                        inference_total_timeout_s=7.5, inference_budget_output_tokens=321)
    client = make_inference(settings)
    assert isinstance(client, VultrInference)
    assert client._policy.total_timeout_s == 7.5
    assert client._policy.output_budget_tokens == 321
    assert "vk-TEST-not-real" not in repr(client)
