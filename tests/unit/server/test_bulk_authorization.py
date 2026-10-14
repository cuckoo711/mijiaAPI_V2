"""Batch authorization is authenticated, atomic, and changes only permission fields."""

import pytest

from tests.unit.server.test_app import admin_cookie_session, make_client_with_store


@pytest.fixture
def inventory(tmp_path):
    client, store = make_client_with_store(tmp_path)
    _, csrf = admin_cookie_session(client)
    store.upsert_devices(
        [
            {"did": "a", "slug": "a", "name": "A"},
            {"did": "b", "slug": "b", "name": "B"},
        ]
    )
    store.upsert_scenes([{"scene_id": "a", "name": "A"}, {"scene_id": "b", "name": "B"}])
    return client, store, {"X-CSRF-Token": csrf}


@pytest.mark.parametrize("kind", ["devices", "scenes"])
def test_batch_authorization_defaults_and_atomic_toggle(inventory, kind):
    client, store, headers = inventory
    items = store.list_devices() if kind == "devices" else store.list_scenes()
    field, off, on = (
        ("access_mode", "read", "write") if kind == "devices" else ("executable", False, True)
    )
    get = store.get_device if kind == "devices" else store.get_scene
    update = store.update_device if kind == "devices" else store.update_scene
    assert all(item[field] == off for item in items)
    ids = [item["id"] for item in items]
    update(ids[0], {"hidden": True})
    before = [get(resource_id) for resource_id in ids]
    # Resources synced after the user confirmed the list must keep their defaults.
    if kind == "devices":
        store.upsert_devices([{"did": "new", "slug": "new", "name": "New"}])
    else:
        store.upsert_scenes([{"scene_id": "new", "name": "New"}])
    path = f"/api/admin/{kind}/authorization/batch"
    for enabled, expected in [(True, on), (False, off)]:
        response = client.post(path, json={"ids": ids + ids, "enabled": enabled}, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"ids": ids, "enabled": enabled, "count": 2}
        assert get("new")[field] == off
        for old, resource_id in zip(before, ids):
            current = get(resource_id)
            assert current[field] == expected
            assert {k: v for k, v in current.items() if k != field} == {
                k: v for k, v in old.items() if k != field
            }
    event = store.list_audit(action="resource.authorization.batch")[0]
    assert event["metadata"]["count"] == 2
    assert event["metadata"]["kind"] == kind


@pytest.mark.parametrize("kind", ["devices", "scenes"])
def test_batch_rejects_stale_ids_without_partial_update(inventory, kind):
    client, store, headers = inventory
    item = (store.list_devices() if kind == "devices" else store.list_scenes())[0]
    response = client.post(
        f"/api/admin/{kind}/authorization/batch",
        headers=headers,
        json={"ids": [item["id"], "deleted-id"], "enabled": True},
    )
    assert response.status_code == 404
    if kind == "devices":
        assert store.get_device(item["id"])["access_mode"] == "read"
    else:
        assert not store.get_scene(item["id"])["executable"]


@pytest.mark.parametrize("kind", ["devices", "scenes"])
def test_batch_requires_auth_csrf_and_valid_payload(inventory, kind):
    client, store, headers = inventory
    path = f"/api/admin/{kind}/authorization/batch"
    item = (store.list_devices() if kind == "devices" else store.list_scenes())[0]
    body = {"ids": [item["id"]], "enabled": True}
    assert client.post(path, json=body).status_code == 403
    for invalid in [
        {"ids": [], "enabled": True},
        {"ids": [" "], "enabled": True},
        {"ids": [item["id"]], "enabled": "false"},
    ]:
        assert client.post(path, headers=headers, json=invalid).status_code == 422
    client.cookies.clear()
    assert client.post(path, json=body, headers=headers).status_code == 401
