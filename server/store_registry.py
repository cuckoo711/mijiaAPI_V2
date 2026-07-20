"""Homes / devices / scenes registry operations for ServerStore."""

from __future__ import annotations

import json
import uuid
from typing import Any

from server.store import isoformat, utc_now


class RegistryMixin:
    """Mixin providing synced home/device/scene registry helpers."""

    def clear_synced_registries(self) -> dict[str, int]:
        """删除所有从米家同步来的家庭 / 设备 / 场景。

        用于凭据被删除或切换到另一个米家账号时，避免遗留孤儿数据。
        审计日志、API Key、runtime_config 等本地状态保持不变。
        返回受影响的行数（便于审计）。
        """
        with self._database.connect() as conn:
            devices = conn.execute("DELETE FROM device_registry").rowcount
            scenes = conn.execute("DELETE FROM scene_registry").rowcount
            homes = conn.execute("DELETE FROM home_registry").rowcount
        return {
            "homes": int(homes or 0),
            "devices": int(devices or 0),
            "scenes": int(scenes or 0),
        }

    def replace_home_registry(self, homes: list[dict[str, Any]]) -> None:
        """Persist synced homes."""

        now = isoformat(utc_now())
        with self._database.connect() as conn:
            for home in homes:
                conn.execute(
                    """
                    INSERT INTO home_registry(id, name, uid, rooms_json, last_synced_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        uid = excluded.uid,
                        rooms_json = excluded.rooms_json,
                        last_synced_at = excluded.last_synced_at
                    """,
                    (
                        str(home["id"]),
                        str(home.get("name", "")),
                        str(home.get("uid", "")),
                        json.dumps(home.get("rooms", []), ensure_ascii=False),
                        now,
                    ),
                )

    def upsert_devices(self, devices: list[dict[str, Any]]) -> None:
        """Persist synced devices while preserving local aliases and permissions."""

        now = isoformat(utc_now())
        with self._database.connect() as conn:
            for device in devices:
                miot_did = str(device["did"])
                slug = self._unique_slug(
                    conn,
                    base=device.get("slug") or self._slugify(device.get("name") or miot_did),
                    current_did=miot_did,
                )
                conn.execute(
                    """
                    INSERT INTO device_registry(
                        id, miot_did, slug, name, alias, model, home_id, room_id,
                        tags_json, group_name, hidden, access_mode, status,
                        raw_json, spec_json, last_synced_at
                    )
                    VALUES (?, ?, ?, ?, NULL, ?, ?, ?, '[]', NULL, 0, 'read',
                            ?, ?, ?, ?)
                    ON CONFLICT(miot_did) DO UPDATE SET
                        name = excluded.name,
                        model = excluded.model,
                        home_id = excluded.home_id,
                        room_id = excluded.room_id,
                        status = excluded.status,
                        raw_json = excluded.raw_json,
                        spec_json = COALESCE(excluded.spec_json, device_registry.spec_json),
                        last_synced_at = excluded.last_synced_at
                    """,
                    (
                        str(device.get("id") or uuid.uuid4()),
                        miot_did,
                        slug,
                        str(device.get("name", "")),
                        str(device.get("model", "")),
                        str(device.get("home_id", "")),
                        device.get("room_id"),
                        str(device.get("status", "unknown")),
                        json.dumps(device, ensure_ascii=False, default=str),
                        (
                            json.dumps(device.get("spec"), ensure_ascii=False, default=str)
                            if device.get("spec") is not None
                            else None
                        ),
                        now,
                    ),
                )

    def upsert_scenes(self, scenes: list[dict[str, Any]]) -> None:
        """Persist synced scenes while preserving local executable flags."""

        now = isoformat(utc_now())
        with self._database.connect() as conn:
            for scene in scenes:
                scene_id = str(scene["scene_id"])
                conn.execute(
                    """
                    INSERT INTO scene_registry(
                        id, miot_scene_id, name, home_id, hidden, executable,
                        raw_json, last_synced_at
                    )
                    VALUES (?, ?, ?, ?, 0, 0, ?, ?)
                    ON CONFLICT(miot_scene_id) DO UPDATE SET
                        name = excluded.name,
                        home_id = excluded.home_id,
                        raw_json = excluded.raw_json,
                        last_synced_at = excluded.last_synced_at
                    """,
                    (
                        str(scene.get("id") or uuid.uuid4()),
                        scene_id,
                        str(scene.get("name", "")),
                        str(scene.get("home_id", "")),
                        json.dumps(scene, ensure_ascii=False, default=str),
                        now,
                    ),
                )

    def list_homes(self) -> list[dict[str, Any]]:
        """List locally synced homes."""

        with self._database.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, uid, rooms_json, last_synced_at FROM home_registry ORDER BY name"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "uid": row["uid"],
                "rooms": json.loads(row["rooms_json"]),
                "last_synced_at": row["last_synced_at"],
            }
            for row in rows
        ]

    def list_devices(
        self,
        include_hidden: bool = False,
        include_spec: bool = False,
        include_raw: bool = False,
    ) -> list[dict[str, Any]]:
        """List locally synced devices.

        默认不返回 ``spec`` / ``raw`` 字段（每台设备的 JSON 可能达几十 KB，
        全量列表反序列化开销累积可观）。需要时显式传参，或改用
        :meth:`get_device` 单点查询。
        """

        where = "" if include_hidden else "WHERE hidden = 0"
        columns = (
            "id, miot_did, slug, name, alias, model, home_id, room_id, "
            "tags_json, group_name, hidden, access_mode, status, last_synced_at"
        )
        if include_raw:
            columns += ", raw_json"
        if include_spec:
            columns += ", spec_json"
        with self._database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT {columns} FROM device_registry
                {where}
                ORDER BY home_id, group_name, COALESCE(alias, name), name
                """
            ).fetchall()
        return [
            self._device_from_row(
                row, include_spec=include_spec, include_raw=include_raw
            )
            for row in rows
        ]

    def get_device(self, device_slug_or_id: str) -> dict[str, Any]:
        """Get a device by slug, internal id, or original did."""

        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM device_registry
                WHERE slug = ? OR id = ? OR miot_did = ?
                """,
                (device_slug_or_id, device_slug_or_id, device_slug_or_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Device not found: {device_slug_or_id}")
        return self._device_from_row(row, include_spec=True, include_raw=True)

    def update_device(self, device_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update local device presentation and authorization metadata."""

        current = self.get_device(device_id)
        allowed = {"slug", "alias", "tags", "group_name", "hidden", "access_mode"}
        values = {key: value for key, value in updates.items() if key in allowed}
        if "tags" in values:
            values["tags_json"] = json.dumps(values.pop("tags"), ensure_ascii=False)
        if not values:
            return current

        assignments = ", ".join(f"{key} = ?" for key in values)
        params = list(values.values()) + [current["id"]]
        with self._database.connect() as conn:
            conn.execute(f"UPDATE device_registry SET {assignments} WHERE id = ?", params)
        return self.get_device(current["id"])

    def list_scenes(self, include_hidden: bool = False) -> list[dict[str, Any]]:
        """List locally synced scenes."""

        where = "" if include_hidden else "WHERE hidden = 0"
        with self._database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM scene_registry {where} ORDER BY home_id, name"
            ).fetchall()
        return [
            {
                "id": row["id"],
                "scene_id": row["miot_scene_id"],
                "name": row["name"],
                "home_id": row["home_id"],
                "hidden": bool(row["hidden"]),
                "executable": bool(row["executable"]),
                "raw": json.loads(row["raw_json"]),
                "last_synced_at": row["last_synced_at"],
            }
            for row in rows
        ]

    def get_scene(self, scene_id: str) -> dict[str, Any]:
        """Get a scene by internal id or original scene id."""

        with self._database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM scene_registry
                WHERE id = ? OR miot_scene_id = ?
                """,
                (scene_id, scene_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Scene not found: {scene_id}")
        return {
            "id": row["id"],
            "scene_id": row["miot_scene_id"],
            "name": row["name"],
            "home_id": row["home_id"],
            "hidden": bool(row["hidden"]),
            "executable": bool(row["executable"]),
            "raw": json.loads(row["raw_json"]),
            "last_synced_at": row["last_synced_at"],
        }

    def update_scene(self, scene_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update local scene presentation and authorization metadata."""

        current = self.get_scene(scene_id)
        allowed = {"hidden", "executable"}
        values = {key: value for key, value in updates.items() if key in allowed}
        if not values:
            return current
        assignments = ", ".join(f"{key} = ?" for key in values)
        params = [
            1 if value is True else 0 if value is False else value for value in values.values()
        ]
        params.append(current["id"])
        with self._database.connect() as conn:
            conn.execute(f"UPDATE scene_registry SET {assignments} WHERE id = ?", params)
        return self.get_scene(current["id"])

    def _device_from_row(
        self,
        row: Any,
        include_spec: bool = True,
        include_raw: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "id": row["id"],
            "did": row["miot_did"],
            "did_masked": self._mask_secret(row["miot_did"]),
            "slug": row["slug"],
            "name": row["name"],
            "alias": row["alias"],
            "display_name": row["alias"] or row["name"],
            "model": row["model"],
            "home_id": row["home_id"],
            "room_id": row["room_id"],
            "tags": json.loads(row["tags_json"]),
            "group_name": row["group_name"],
            "hidden": bool(row["hidden"]),
            "access_mode": row["access_mode"],
            "status": row["status"],
            "last_synced_at": row["last_synced_at"],
        }
        if include_raw:
            payload["raw"] = json.loads(row["raw_json"]) if row["raw_json"] else {}
        if include_spec:
            payload["spec"] = (
                json.loads(row["spec_json"]) if row["spec_json"] else None
            )
        return payload

    def _unique_slug(self, conn: Any, base: str, current_did: str) -> str:
        slug = self._slugify(base)
        candidate = slug
        index = 2
        while True:
            row = conn.execute(
                "SELECT miot_did FROM device_registry WHERE slug = ?",
                (candidate,),
            ).fetchone()
            if row is None or row["miot_did"] == current_did:
                return candidate
            candidate = f"{slug}-{index}"
            index += 1

    def _slugify(self, value: str) -> str:
        chars = []
        for char in value.lower().strip():
            if char.isalnum():
                chars.append(char)
            elif char in {" ", "_", "-", ".", "/"}:
                chars.append("-")
        slug = "".join(chars).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        return slug or f"device-{uuid.uuid4().hex[:8]}"
