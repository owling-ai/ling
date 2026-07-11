from __future__ import annotations

import asyncio
import json

import pytest

from backend import engine, realtime


class _RejectedConnection(Exception):
    def __init__(self, status_code: int):
        self.response = type("Response", (), {"status_code": status_code})()


@pytest.mark.parametrize(
    ("status_code", "code", "message", "retryable"),
    [
        (401, "provider_auth_failed", "StepFun 鉴权失败，请检查 API Key 和模型权限", False),
        (402, "provider_quota_exceeded", "StepFun API 额度不足，请检查套餐与账单", False),
        (404, "provider_not_found", "StepFun 实时模型或接口不存在，请检查模型配置", False),
        (429, "provider_rate_limited", "StepFun 请求过于频繁，请稍后再试", True),
        (503, "provider_unavailable", "StepFun 服务暂时不可用，请稍后再试", True),
    ],
)
def test_provider_error_event_translates_http_status(
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    event = realtime._provider_error_event("stepfun", _RejectedConnection(status_code))

    assert event == {
        "type": "ling.error",
        "code": code,
        "message": message,
        "provider": "stepfun",
        "retryable": retryable,
    }


def test_bridge_reports_stepfun_quota_instead_of_exception_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.messages: list[dict] = []
            self.accepted = False
            self.closed = False

        async def accept(self) -> None:
            self.accepted = True

        async def send_text(self, raw: str) -> None:
            self.messages.append(json.loads(raw))

        async def close(self) -> None:
            self.closed = True

    async def reject_stepfun(*_args, **_kwargs) -> None:
        raise _RejectedConnection(402)

    monkeypatch.setenv("STEPFUN_API_KEY", "test-key")
    monkeypatch.setattr(engine, "get_session", lambda _session_id: {"pack": {}})
    monkeypatch.setattr(realtime, "_bridge_stepfun", reject_stepfun)
    client = Client()

    asyncio.run(realtime.bridge(client, "test-session", "stepfun"))

    assert client.accepted is True
    assert client.closed is True
    assert client.messages == [
        {
            "type": "ling.error",
            "code": "provider_quota_exceeded",
            "message": "StepFun API 额度不足，请检查套餐与账单",
            "provider": "stepfun",
            "retryable": False,
        }
    ]
