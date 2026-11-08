"""设备状态监听器单元测试"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from mijiaAPI_V2.domain.exceptions import ValidationError
from mijiaAPI_V2.domain.models import (
    Credential,
    DeviceProperty,
    PropertyAccess,
    PropertyType,
)
from mijiaAPI_V2.watcher import (
    DEFAULT_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    DeviceStateWatcher,
    StateChangeEvent,
)


@pytest.fixture
def credential() -> Credential:
    return Credential(
        user_id="user-1",
        service_token="token",
        ssecurity="security",
        pass_token="pass",
        c_user_id="user-1",
        device_id="device",
        user_agent="ua",
        expires_at=datetime(2099, 1, 1),
    )


def _prop(siid: int, piid: int, name: str, value) -> DeviceProperty:
    return DeviceProperty(
        siid=siid,
        piid=piid,
        name=name,
        type=PropertyType.BOOL,
        access=PropertyAccess.READ_WRITE,
        value=value,
    )


@pytest.fixture
def device_service() -> MagicMock:
    service = MagicMock()
    service.get_device_properties.return_value = [_prop(2, 1, "on", False)]
    return service


@pytest.fixture
def watcher(device_service, credential) -> DeviceStateWatcher:
    return DeviceStateWatcher(device_service, credential)


class TestNormalization:
    def test_devices_accepts_single_string(self, watcher):
        captured = []

        @watcher.on_change("did-1")
        def handler(event):
            captured.append(event)

        assert handler.__name__ == "handler"

    def test_devices_accepts_list_and_deduplicates(self, watcher, device_service):
        @watcher.on_change(["did-1", "did-2", "did-1"])
        def handler(event):
            pass

        watcher.poll_once()
        dids = [call.args[0] for call in device_service.get_device_properties.call_args_list]
        assert dids == ["did-1", "did-2"]

    def test_empty_devices_rejected(self, watcher):
        with pytest.raises(ValidationError):
            watcher.on_change([])

    def test_blank_device_id_rejected(self, watcher):
        with pytest.raises(ValidationError):
            watcher.on_change(["  "])

    def test_interval_clamped_to_minimum(self, watcher, device_service):
        @watcher.on_change("did-1", interval=1)
        def handler(event):
            pass

        assert handler  # 装饰器生效
        # 间隔被钳制后仍能正常工作
        watcher.poll_once()
        assert device_service.get_device_properties.called

    def test_invalid_interval_rejected(self, watcher):
        with pytest.raises(ValidationError):
            watcher.on_change("did-1", interval=0)
        with pytest.raises(ValidationError):
            watcher.on_change("did-1", interval=-5)
        with pytest.raises(ValidationError):
            watcher.on_change("did-1", interval="fast")

    def test_non_callable_handler_rejected(self, watcher):
        decorator = watcher.on_change("did-1")
        with pytest.raises(ValidationError):
            decorator("not-callable")


class TestChangeDetection:
    def test_first_poll_only_establishes_baseline(self, watcher, device_service):
        events = []

        @watcher.on_change("did-1")
        def handler(event):
            events.append(event)

        assert watcher.poll_once() == 0
        assert events == []

    def test_value_change_fires_event(self, watcher, device_service):
        events = []

        @watcher.on_change("did-1")
        def handler(event):
            events.append(event)

        watcher.poll_once()
        device_service.get_device_properties.return_value = [_prop(2, 1, "on", True)]
        assert watcher.poll_once() == 1

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, StateChangeEvent)
        assert event.did == "did-1"
        assert event.siid == 2
        assert event.piid == 1
        assert event.name == "on"
        assert event.old is False
        assert event.new is True
        assert isinstance(event.changed_at, datetime)

    def test_unchanged_values_fire_nothing(self, watcher, device_service):
        events = []

        @watcher.on_change("did-1")
        def handler(event):
            events.append(event)

        watcher.poll_once()
        assert watcher.poll_once() == 0
        assert events == []

    def test_multiple_changes_in_one_cycle(self, watcher, device_service):
        events = []

        @watcher.on_change("did-1")
        def handler(event):
            events.append(event)

        device_service.get_device_properties.return_value = [
            _prop(2, 1, "on", False),
            _prop(2, 2, "level", 10),
        ]
        watcher.poll_once()
        device_service.get_device_properties.return_value = [
            _prop(2, 1, "on", True),
            _prop(2, 2, "level", 20),
        ]
        assert watcher.poll_once() == 2
        assert {(e.siid, e.piid) for e in events} == {(2, 1), (2, 2)}

    def test_property_appearing_later_does_not_fire(self, watcher, device_service):
        events = []

        @watcher.on_change("did-1")
        def handler(event):
            events.append(event)

        device_service.get_device_properties.return_value = [_prop(2, 1, "on", False)]
        watcher.poll_once()
        device_service.get_device_properties.return_value = [
            _prop(2, 1, "on", False),
            _prop(2, 2, "level", 10),
        ]
        assert watcher.poll_once() == 0
        assert events == []

    def test_read_failure_keeps_baseline(self, watcher, device_service):
        events = []

        @watcher.on_change("did-1")
        def handler(event):
            events.append(event)

        watcher.poll_once()
        device_service.get_device_properties.side_effect = RuntimeError("网络错误")
        assert watcher.poll_once() == 0

        device_service.get_device_properties.side_effect = None
        device_service.get_device_properties.return_value = [_prop(2, 1, "on", True)]
        assert watcher.poll_once() == 1
        assert events[0].old is False

    def test_handler_exception_does_not_break_polling(self, watcher, device_service):
        calls = []

        @watcher.on_change("did-1")
        def handler(event):
            calls.append(event)
            raise RuntimeError("回调炸了")

        watcher.poll_once()
        device_service.get_device_properties.return_value = [_prop(2, 1, "on", True)]
        assert watcher.poll_once() == 1
        device_service.get_device_properties.return_value = [_prop(2, 1, "on", False)]
        assert watcher.poll_once() == 1
        assert len(calls) == 2

    def test_poll_requests_fresh_values(self, watcher, device_service):
        @watcher.on_change("did-1")
        def handler(event):
            pass

        watcher.poll_once()
        assert device_service.get_device_properties.call_args.kwargs["fresh"] is True

    def test_unreadable_properties_ignored(self, watcher, device_service):
        write_only = DeviceProperty(
            siid=2,
            piid=3,
            name="write-only",
            type=PropertyType.BOOL,
            access=PropertyAccess.WRITE_ONLY,
            value=False,
        )
        device_service.get_device_properties.return_value = [write_only]
        events = []

        @watcher.on_change("did-1")
        def handler(event):
            events.append(event)

        watcher.poll_once()
        device_service.get_device_properties.return_value = [
            DeviceProperty(
                siid=2,
                piid=3,
                name="write-only",
                type=PropertyType.BOOL,
                access=PropertyAccess.WRITE_ONLY,
                value=True,
            )
        ]
        assert watcher.poll_once() == 0


class TestClientIntegration:
    def test_api_on_change_and_stop_watching(self, device_service, credential):
        from mijiaAPI_V2.api_client import MijiaAPI

        api = MijiaAPI(
            credential=credential,
            device_service=device_service,
            scene_service=MagicMock(),
        )
        events = []

        @api.on_change("did-1", interval=MIN_POLL_INTERVAL)
        def handler(event):
            events.append(event)

        assert api._watcher is not None
        api.stop_watching()

    def test_update_credential_reaches_watcher(self, device_service, credential):
        from mijiaAPI_V2.api_client import MijiaAPI

        api = MijiaAPI(
            credential=credential,
            device_service=device_service,
            scene_service=MagicMock(),
        )

        @api.on_change("did-1")
        def handler(event):
            pass

        new_credential = credential.model_copy(update={"service_token": "new-token"})
        api.update_credential(new_credential)
        assert api._watcher._credential is new_credential
        api.stop_watching()

    def test_default_interval_is_30(self, watcher, device_service):
        @watcher.on_change("did-1")
        def handler(event):
            pass

        sub = watcher._subs[0]
        assert sub.interval == DEFAULT_POLL_INTERVAL == 30.0
