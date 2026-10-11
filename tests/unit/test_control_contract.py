"""Control contracts across real SDK layers and simulated upstream transports."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from mijiaAPI_V2.api_client import MijiaAPI
from mijiaAPI_V2.domain.exceptions import ExecutionUnknownError, ValidationError
from mijiaAPI_V2.domain.models import (
    ActionParameter,
    Credential,
    Device,
    DeviceAction,
    DeviceProperty,
)
from mijiaAPI_V2.infrastructure.http_client import AsyncHttpClient, HttpClient
from mijiaAPI_V2.infrastructure.cache_manager import CacheManager
from mijiaAPI_V2.repositories.device_repository import DeviceRepositoryImpl
from mijiaAPI_V2.repositories.device_spec_repository import DeviceSpecRepositoryImpl
from mijiaAPI_V2.repositories.interfaces import DeviceSpec
from mijiaAPI_V2.repositories.home_repository import HomeRepositoryImpl
from mijiaAPI_V2.services.device_service import DeviceService


@pytest.fixture
def credential():
    return Credential(
        user_id="u",
        service_token="t",
        ssecurity="s",
        c_user_id="c",
        device_id="d",
        user_agent="test",
        expires_at=datetime(2099, 1, 1),
    )


@pytest.fixture
def layers(credential):
    http, cache, specs = Mock(), Mock(), Mock()
    repo = DeviceRepositoryImpl(http, cache)
    repo.get_by_id = Mock(return_value=Device(did="lamp", name="Lamp", model="m", home_id="h"))
    prop = DeviceProperty(siid=2, piid=1, name="power", type="bool", access="read_write")
    specs.get_spec.return_value = DeviceSpec(model="m", name="Lamp", properties=[prop], actions=[])
    service = DeviceService(repo, specs, cache)
    api = MijiaAPI(credential, service, Mock(), cache_manager=cache)
    http.post.return_value = {
        "code": 0,
        "result": [{"did": "lamp", "siid": 2, "piid": 1, "code": 0}],
    }
    return api, service, repo, specs, http


@pytest.mark.parametrize("field", ["did", "device_id"])
def test_public_batch_normalizes_wire_contract(layers, field):
    api, _, _, _, http = layers
    result = api.batch_control_devices(
        [{field: "lamp", "home_id": "h", "siid": 2, "piid": 1, "value": True}]
    )
    assert result[0]["code"] == 0
    http.post.assert_called_once()
    assert http.post.call_args.kwargs["json"] == {
        "params": [{"did": "lamp", "siid": 2, "piid": 1, "value": True}]
    }


def test_manual_refresh_reads_new_homes_instead_of_backfilling_l3(tmp_path, credential):
    cache = CacheManager(cache_dir=tmp_path)
    cache.set("homes", [{"id": "old", "name": "Old", "uid": "u"}], ttl=600, namespace="u")
    assert (tmp_path / cache._hash_key("u:homes")).exists()
    # Start with a new instance so the initial read comes from the file layer.
    cache = CacheManager(cache_dir=tmp_path)
    http = Mock()
    http.post.return_value = {
        "code": 0,
        "result": {"homelist": [{"id": "new", "name": "New", "uid": "u"}]},
    }
    api = MijiaAPI(
        credential,
        Mock(),
        Mock(),
        home_repository=HomeRepositoryImpl(http, cache),
        cache_manager=cache,
    )
    assert api.get_homes()[0].id == "old"
    http.post.assert_not_called()
    api.refresh_cache()
    assert api.get_homes()[0].id == "new"
    http.post.assert_called_once()
    assert not (tmp_path / cache._hash_key("u:homes")).exists()


def test_conflicting_batch_identifiers_are_rejected(layers):
    api, _, _, _, http = layers
    with pytest.raises(ValidationError):
        api.batch_control_devices(
            [{"did": "a", "device_id": "b", "siid": 2, "piid": 1, "value": True}]
        )
    http.post.assert_not_called()


@pytest.mark.parametrize("operation", ["property", "action", "batch"])
def test_cache_failures_preserve_completed_control(layers, operation):
    api, _, repo, specs, http = layers
    api._cache_manager.invalidate_pattern.side_effect = RuntimeError("cache unavailable")
    if operation == "property":
        assert api.control_device("lamp", 2, 1, True, home_id="h") is True
    elif operation == "action":
        specs.get_spec.return_value.actions = [DeviceAction(siid=2, aiid=1, name="act")]
        http.post.return_value = {"code": 0, "result": {"code": 0}}
        assert api.call_device_action("lamp", 2, 1, {}, home_id="h") == {"code": 0}
    else:
        assert (
            api.batch_control_devices(
                [{"did": "lamp", "home_id": "h", "siid": 2, "piid": 1, "value": True}]
            )[0]["code"]
            == 0
        )
    http.post.assert_called_once()


def invoke_repository_control(repo, credential, operation):
    if operation == "property":
        return repo.set_property("lamp", 2, 1, True, credential)
    if operation == "action":
        return repo.call_action("lamp", 2, 1, {}, credential)
    return repo.batch_set_properties(
        [
            {"did": "lamp", "siid": 2, "piid": 1, "value": True},
            {"did": "fan", "siid": 2, "piid": 1, "value": False},
        ],
        credential,
    )


@pytest.mark.parametrize(
    "operation,result",
    [
        ("property", None),
        ("property", []),
        ("property", {}),
        ("property", [None]),
        ("property", [{}]),
        ("property", [{"code": False}]),
        ("property", [{"code": "0"}]),
        ("property", [{"code": 0}, {"code": 0}]),
        ("action", None),
        ("action", []),
        ("action", {}),
        ("action", {"code": False}),
        ("action", {"code": "0"}),
        ("batch", None),
        ("batch", {}),
        ("batch", []),
        ("batch", [{"code": 0}]),
        ("batch", [{"code": 0}, None]),
        ("batch", [{"code": 0}, {}]),
        ("batch", [{"code": 0}, {"code": False}]),
        ("batch", [{"code": 0}, {"code": "0"}]),
        ("batch", [{"code": 0}, {"code": 0}, {"code": 0}]),
    ],
)
def test_repository_missing_or_malformed_ack_is_execution_unknown(
    layers, credential, operation, result
):
    _, _, repo, _, http = layers
    http.post.return_value = {"code": 0, "result": result}
    with pytest.raises(ExecutionUnknownError):
        invoke_repository_control(repo, credential, operation)
    http.post.assert_called_once()


@pytest.mark.parametrize("operation", ["property", "action", "batch"])
def test_repository_absent_result_is_execution_unknown(layers, credential, operation):
    _, _, repo, _, http = layers
    http.post.return_value = {"code": 0}
    with pytest.raises(ExecutionUnknownError):
        invoke_repository_control(repo, credential, operation)
    http.post.assert_called_once()


@pytest.mark.parametrize("operation", ["property", "action", "batch"])
def test_repository_mismatched_optional_identity_is_execution_unknown(
    layers, credential, operation
):
    _, _, repo, _, http = layers
    item = {"code": 0, "did": "other-device", "siid": 2}
    result = item if operation == "action" else [item]
    if operation == "batch":
        result.append({"code": 0, "did": "fan"})
    http.post.return_value = {"code": 0, "result": result}
    with pytest.raises(ExecutionUnknownError):
        invoke_repository_control(repo, credential, operation)


@pytest.mark.parametrize("operation", ["property", "action", "batch"])
def test_repository_explicit_miot_failure_stays_known(layers, credential, operation):
    _, _, repo, _, http = layers
    failed = {"code": -704042011}
    result = failed if operation == "action" else [failed]
    if operation == "batch":
        result.append({"code": 0})
    http.post.return_value = {"code": 0, "result": result}
    returned = invoke_repository_control(repo, credential, operation)
    assert returned == (False if operation == "property" else result)


def test_all_batches_are_validated_before_first_dispatch(layers, credential):
    _, service, _, _, http = layers
    requests = [{"did": "lamp", "siid": 2, "piid": 1, "value": True} for _ in range(20)]
    requests.append({"did": "lamp", "siid": 2, "piid": 1, "value": 1})
    with pytest.raises(ValidationError):
        service.batch_control_devices(requests, credential)
    http.post.assert_not_called()


@pytest.mark.parametrize("missing", ["spec", "property"])
def test_unavailable_property_contract_does_not_dispatch(layers, credential, missing):
    _, service, _, specs, http = layers
    if missing == "spec":
        specs.get_spec.return_value = None
    with pytest.raises(ValidationError):
        service.set_device_property("lamp", 2, 99 if missing == "property" else 1, True, credential)
    http.post.assert_not_called()


@pytest.mark.parametrize(
    "kind,bounds,choices,value,valid",
    [
        ("uint", [1, 100, 1], None, 1000, False),
        ("uint", [1, 100, 1], None, -1, False),
        ("uint", [1, 100, 1], None, True, False),
        ("uint", [0, 100, 5], None, 7, False),
        ("uint", [0, 100, 5], None, 10, True),
        ("float", [0, 1, 0.1], None, 0.3, True),
        ("float", [0, 1, 0.1], None, 0.35, False),
        ("float", None, None, float("nan"), False),
        ("float", None, None, float("inf"), False),
        ("int", None, [1, 2], True, False),
        ("int", None, [1, 2], 2, True),
        ("string", None, None, 1, False),
        ("bool", None, None, 1, False),
        ("uint", None, None, -1, False),
        ("int", [0, 10, 0], None, 1, False),
    ],
)
def test_strict_miot_values(kind, bounds, choices, value, valid):
    prop = DeviceProperty(
        siid=2,
        piid=1,
        name="p",
        type=kind,
        access="read_write",
        value_range=bounds,
        value_list=choices,
    )
    assert prop.validate_value(value) is valid


def action_spec():
    return DeviceAction(
        siid=2,
        aiid=1,
        name="set_mode",
        parameters=[
            ActionParameter(piid=2, name="level", type="uint", value_range=[0, 10, 2]),
            ActionParameter(piid=3, name="mode", type="string", value_list=["auto", "manual"]),
        ],
    )


def test_action_inputs_use_declared_order(layers, credential):
    _, service, _, specs, http = layers
    specs.get_spec.return_value.actions = [action_spec()]
    http.post.return_value = {"code": 0, "result": {"code": 0}}
    service.call_device_action("lamp", 2, 1, {"mode": "auto", "level": 4}, credential)
    assert http.post.call_args.kwargs["json"]["params"]["value"] == [4, "auto"]


@pytest.mark.parametrize(
    "params",
    [
        {"level": 4},
        {"level": True, "mode": "auto"},
        {"level": 3, "mode": "auto"},
        {"level": 4, "mode": "invalid"},
        {"level": 4, "mode": "auto", "extra": 1},
        {"level": 4, "2": 4, "mode": "auto"},
    ],
)
def test_invalid_action_inputs_do_not_dispatch(layers, credential, params):
    _, service, _, specs, http = layers
    specs.get_spec.return_value.actions = [action_spec()]
    with pytest.raises(ValidationError):
        service.call_device_action("lamp", 2, 1, params, credential)
    http.post.assert_not_called()


def test_action_piids_can_be_used_as_parameter_keys(layers, credential):
    _, service, _, specs, http = layers
    specs.get_spec.return_value.actions = [action_spec()]
    http.post.return_value = {"code": 0, "result": {"code": 0}}
    service.call_device_action("lamp", 2, 1, {"3": "auto", "2": 4}, credential)
    assert http.post.call_args.kwargs["json"]["params"]["value"] == [4, "auto"]


def test_undeclared_action_is_rejected(layers, credential):
    _, service, _, _, http = layers
    with pytest.raises(ValidationError):
        service.call_device_action("lamp", 2, 99, {}, credential)
    http.post.assert_not_called()


def test_later_batch_failure_preserves_partial_execution(layers, credential):
    _, service, repo, _, _ = layers
    repo.batch_set_properties = Mock(
        side_effect=[[{"code": 0}] * 20, RuntimeError("later failure")]
    )
    requests = [{"did": "lamp", "siid": 2, "piid": 1, "value": True} for _ in range(21)]
    with pytest.raises(ExecutionUnknownError) as raised:
        service.batch_control_devices(requests, credential)
    assert raised.value.context["completed_count"] == 20
    assert repo.batch_set_properties.call_count == 2


def test_action_parser_keeps_input_references_and_order():
    parser = DeviceSpecRepositoryImpl(Mock(), Mock())
    spec = parser._parse_spec_standard(
        "m",
        {
            "services": [
                {
                    "iid": 2,
                    "properties": [
                        {"iid": 1, "description": "power", "format": "bool", "access": ["write"]},
                        {
                            "iid": 2,
                            "description": "level",
                            "format": "uint8",
                            "value-range": [0, 10, 2],
                        },
                    ],
                    "actions": [{"iid": 1, "description": "act", "in": [2, 1]}],
                }
            ]
        },
    )
    assert [p.piid for p in spec.actions[0].parameters] == [2, 1]
    assert spec.actions[0].parameters[0].value_range == [0, 10, 2]
    assert all(p.required for p in spec.actions[0].parameters)


@pytest.mark.parametrize(
    "path",
    [
        "/miotspec/prop/set",
        "/miotspec/action",
        "/appgateway/miot/appsceneservice/AppSceneService/NewRunScene",
    ],
)
@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError])
def test_dispatched_control_with_lost_response_is_never_resent(credential, path, error):
    executions = []

    def upstream(request):
        executions.append(request)
        raise error("response lost after execution", request=request)

    transport = httpx.MockTransport(upstream)
    config, crypto = Mock(), Mock()
    config.get.side_effect = lambda key, default: default
    crypto.encrypt_params.return_value = {"_nonce": "nonce"}
    client = HttpClient(config, crypto)
    client._client.close()
    with httpx.Client(transport=transport) as connection:
        client._client = connection
        with pytest.raises(ExecutionUnknownError):
            client.post(path, {}, credential)
    assert len(executions) == 1


@pytest.mark.parametrize(
    "path,error",
    [
        ("/miotspec/prop/get", httpx.ReadTimeout),
        ("/miotspec/action", httpx.ConnectTimeout),
        ("/miotspec/action", httpx.ConnectError),
    ],
)
def test_queries_and_connection_before_dispatch_can_retry(credential, monkeypatch, path, error):
    calls = []

    def upstream(request):
        calls.append(request)
        if len(calls) < 3:
            raise error("temporary transport failure", request=request)
        return httpx.Response(200, text="encrypted", request=request)

    config, crypto = Mock(), Mock()
    config.get.side_effect = lambda key, default: default
    crypto.encrypt_params.return_value = {"_nonce": "nonce"}
    crypto.decrypt_response.return_value = '{"code":0}'
    monkeypatch.setattr(HttpClient._do_post.retry, "sleep", lambda _: None)
    client = HttpClient(config, crypto)
    client._client.close()
    with httpx.Client(transport=httpx.MockTransport(upstream)) as connection:
        client._client = connection
        assert client.post(path, {}, credential) == {"code": 0}
    assert len(calls) == 3


@pytest.mark.parametrize("body", ["not-json", "[]", '{"code":false}', "{}"])
def test_unreadable_control_response_is_unknown_without_retry(credential, body):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, text="encrypted", request=request)

    config, crypto = Mock(), Mock()
    config.get.side_effect = lambda key, default: default
    crypto.encrypt_params.return_value = {"_nonce": "nonce"}
    crypto.decrypt_response.return_value = body
    client = HttpClient(config, crypto)
    client._client.close()
    with httpx.Client(transport=httpx.MockTransport(upstream)) as connection:
        client._client = connection
        with pytest.raises(ExecutionUnknownError):
            client.post("/miotspec/action", {}, credential)
    assert len(calls) == 1


def test_server_error_after_control_dispatch_is_unknown(credential):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(503, request=request)

    config, crypto = Mock(), Mock()
    config.get.side_effect = lambda key, default: default
    crypto.encrypt_params.return_value = {"_nonce": "nonce"}
    client = HttpClient(config, crypto)
    client._client.close()
    with httpx.Client(transport=httpx.MockTransport(upstream)) as connection:
        client._client = connection
        with pytest.raises(ExecutionUnknownError):
            client.post("/miotspec/action", {}, credential)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/miotspec/prop/set",
        "/miotspec/action",
        "/appgateway/miot/appsceneservice/AppSceneService/NewRunScene",
    ],
)
@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError])
async def test_async_dispatched_control_is_never_resent(credential, path, error):
    executions = []

    async def upstream(request):
        executions.append(request)
        raise error("response lost after execution", request=request)

    config, crypto = Mock(), Mock()
    config.get.side_effect = lambda key, default: default
    crypto.encrypt_params.return_value = {"_nonce": "nonce"}
    client = AsyncHttpClient(config, crypto)
    await client._client.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as connection:
        client._client = connection
        with pytest.raises(ExecutionUnknownError):
            await client.post(path, {}, credential)
    assert len(executions) == 1


@pytest.mark.parametrize(
    "path,error",
    [
        ("/miotspec/prop/get", httpx.ReadTimeout),
        ("/miotspec/action", httpx.ConnectTimeout),
    ],
)
async def test_async_queries_and_pre_dispatch_connection_can_retry(
    credential, monkeypatch, path, error
):
    calls = []

    async def upstream(request):
        calls.append(request)
        if len(calls) < 3:
            raise error("temporary transport failure", request=request)
        return httpx.Response(200, text="encrypted", request=request)

    config, crypto = Mock(), Mock()
    config.get.side_effect = lambda key, default: default
    crypto.encrypt_params.return_value = {"_nonce": "nonce"}
    crypto.decrypt_response.return_value = '{"code":0}'
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    client = AsyncHttpClient(config, crypto)
    await client._client.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as connection:
        client._client = connection
        assert await client.post(path, {}, credential) == {"code": 0}
    assert len(calls) == 3
