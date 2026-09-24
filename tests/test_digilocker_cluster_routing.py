"""Synthetic, loopback-only Redis tests executing the real transaction Lua."""

import asyncio
import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from digilocker_helpers import settings
from redis.asyncio import Redis
from redis.crc import key_slot
from redis.exceptions import ClusterCrossSlotError, RedisError, TimeoutError

from app.config import get_settings
from app.integrations.digilocker.transactions import (
    _CLEAR,
    _CONSUME,
    _CREATE,
    StateError,
    TransactionStore,
)


class RecordedRedis:
    """Check declared key slots before executing real Lua; never retain payload arguments."""

    def __init__(self, client):
        self.client = client
        self.calls = []

    async def set(self, key, value, **kwargs):
        self.calls.append(("set", key, kwargs))
        return await self.client.set(key, value, **kwargs)

    async def get(self, key):
        self.calls.append(("get", key))
        return await self.client.get(key)

    async def eval(self, script, count, *args):
        keys = args[:count]
        assert len({key_slot(key.encode()) for key in keys}) == 1
        self.calls.append(("eval", script, keys))
        return await self.client.eval(script, count, *args)


@pytest.fixture
async def routing():
    runtime = get_settings()
    if runtime.app_env.value != "test" or urlsplit(runtime.redis_url).hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError("Routing tests require loopback-only test Redis")
    client = Redis.from_url(runtime.redis_url, decode_responses=False)
    prefix = "digilocker-routing-test:" + uuid4().hex
    recorded = RecordedRedis(client)
    store = TransactionStore(recorded, settings(redis_key_prefix=prefix))
    yield SimpleNamespace(
        client=client, recorded=recorded, store=store, now=datetime.now(UTC), owner=uuid4()
    )
    # Only this disposable test namespace; application cleanup never scans.
    async for key in client.scan_iter(match=prefix + ":*"):
        await client.delete(key)
    await client.aclose()


async def create(h, owner=None):
    return await h.store.create(owner or h.owner, uuid4(), uuid4(), h.now)


def keys(h, tx):
    fingerprint = h.store._fingerprint(tx.state.get_secret_value())
    tag = h.store._routing_tag(tx.user_id)
    return (
        h.store._locator_key(fingerprint),
        h.store._owner_key(tag),
        h.store._state_key(tag, fingerprint),
    )


def test_exact_derivation_slots_distribution_and_private_keys():
    store = TransactionStore(None, settings(redis_key_prefix="kairo:test"))
    other = TransactionStore(None, settings(redis_key_prefix="kairo:other"))
    slots, all_states, old_mismatches = set(), set(), 0
    for n in range(1, 1025):
        owner = UUID(int=n)
        tag = store._routing_tag(owner)
        expected = hashlib.sha256(
            b"kairoid:digilocker:owner-route:v1\0kairo:test:cache:digilocker-tx-v1:\0" + owner.bytes
        ).hexdigest()
        assert tag == expected == store._routing_tag(owner)
        assert tag != other._routing_tag(owner)
        assert re.fullmatch("[0-9a-f]{64}", tag)
        owner_key = store._owner_key(tag)
        assert owner_key == f"kairo:test:cache:digilocker-tx-v1:{{{tag}}}:owner"
        slots.add(key_slot(owner_key.encode()))
        for attempt in range(4):
            state = hashlib.sha256(f"synthetic-{n}-{attempt}".encode()).hexdigest()[:43]
            fingerprint = store._fingerprint(state)
            previous = store._fingerprint("previous-" + state)
            state_key = store._state_key(tag, fingerprint)
            group = [owner_key, state_key, store._state_key(tag, previous)]
            assert len({key_slot(key.encode()) for key in group}) == 1
            assert all(state not in key and str(owner) not in key for key in group)
            assert store._locator_key(fingerprint) == (
                "kairo:test:cache:digilocker-route-v1:" + fingerprint
            )
            all_states.add(state_key)
            old_mismatches += key_slot(
                f"kairo:test:cache:digilocker-owner:{owner}".encode()
            ) != key_slot(f"kairo:test:cache:digilocker-state:{fingerprint}".encode())
    assert len(slots) > 900
    assert len(all_states) == 4096
    assert old_mismatches > 4000


@pytest.mark.parametrize(
    "bad", [None, "", "A" * 64, "f" * 63, "f" * 65, "{" * 64, b"\xff" * 64, 42, [], "f" * 63 + "\n"]
)
def test_invalid_routing_tags_rejected(bad):
    store = TransactionStore(None, settings())
    with pytest.raises(ValueError):
        store._owner_key(bad)
    with pytest.raises(ValueError):
        store._state_key(bad, "a" * 64)


@pytest.mark.parametrize("prefix", ["prefix{tag}", "prefix}", "{prefix"])
def test_namespace_cannot_override_owner_hash_tag(prefix):
    with pytest.raises(RedisError, match="namespace"):
        TransactionStore(None, settings(redis_key_prefix=prefix))


@pytest.mark.parametrize("script", [_CREATE, _CLEAR, _CONSUME])
def test_every_lua_key_access_is_explicit(script):
    accesses = re.findall(r"redis.call\('[A-Z]+',\s*([^,\n)]+)", script)
    assert accesses
    assert all(re.fullmatch(r"KEYS\[\d\]", key) for key in accesses)
    assert ".." not in script


async def test_real_lua_command_order_explicit_keys_and_replacement(routing):
    h = routing
    first = await create(h)
    locator1, owner, state1 = keys(h, first)
    assert [call[0] for call in h.recorded.calls] == ["set", "get", "eval"]
    assert h.recorded.calls[0] == ("set", locator1, {"nx": True, "ex": 600})
    assert h.recorded.calls[-1] == ("eval", _CREATE, (owner, state1))
    second = await create(h)
    locator2, _, state2 = keys(h, second)
    assert h.recorded.calls[-1] == ("eval", _CREATE, (owner, state2, state1))
    assert await h.client.exists(state1) == 0
    assert (
        await h.client.get(owner) == h.store._fingerprint(second.state.get_secret_value()).encode()
    )
    assert await h.client.get(locator2) == h.store._routing_tag(h.owner).encode()
    with pytest.raises(StateError):
        await h.store.consume(first.state.get_secret_value(), h.now)
    await h.store.clear(h.owner)
    assert h.recorded.calls[-1] == ("eval", _CLEAR, (owner, state2))
    assert await h.client.exists(owner, state2) == 0
    assert all([await h.client.exists(key) == 1 for key in (locator1, locator2)])
    await h.store.clear(h.owner)
    assert h.recorded.calls[-1] == ("eval", _CLEAR, (owner,))


async def test_callback_race_replay_and_locator_ttl_not_renewed(routing):
    h = routing
    tx = await create(h)
    locator, _, state_key = keys(h, tx)
    assert 0 < await h.client.ttl(locator) <= 600
    await h.client.pexpire(locator, 100_000)
    before = await h.client.pttl(locator)
    h.recorded.calls.clear()
    results = await asyncio.gather(
        *(h.store.consume(tx.state.get_secret_value(), h.now) for _ in range(8)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, StateError) for result in results) == 7
    assert sum(getattr(result, "user_id", None) == h.owner for result in results) == 1
    assert all(call[0] in {"get", "eval"} for call in h.recorded.calls)
    assert all(
        call == ("eval", _CONSUME, (state_key,)) for call in h.recorded.calls if call[0] == "eval"
    )
    assert 0 < await h.client.pttl(locator) <= before
    assert await h.client.exists(state_key) == 0
    with pytest.raises(StateError):
        await h.store.consume(tx.state.get_secret_value(), h.now)


async def test_server_enforces_old_crossslot_when_running_local_cluster(routing):
    h = routing
    key1 = h.store.prefix + "old-owner"
    key2 = h.store.prefix + "old-state"
    assert key_slot(key1.encode()) != key_slot(key2.encode())
    script = "return redis.call('EXISTS', KEYS[1], KEYS[2])"
    if (await h.client.info("cluster"))["cluster_enabled"]:
        with pytest.raises(ClusterCrossSlotError):
            await h.client.eval(script, 2, key1, key2)
    else:
        assert await h.client.eval(script, 2, key1, key2) == 0


@pytest.mark.parametrize(
    "mode",
    ["missing_locator", "expired_locator", "missing_payload", "expired_payload", "missing_both"],
)
async def test_orphans_and_expiry_fail_closed(routing, mode):
    h = routing
    tx = await create(h)
    locator, _, payload = keys(h, tx)
    if mode in {"missing_locator", "missing_both"}:
        await h.client.delete(locator)
    if mode in {"missing_payload", "missing_both"}:
        await h.client.delete(payload)
    if mode == "expired_locator":
        await h.client.pexpireat(locator, 1)
    if mode == "expired_payload":
        await h.client.pexpireat(payload, 1)
    with pytest.raises(StateError):
        await h.store.consume(tx.state.get_secret_value(), h.now)
    if mode in {"missing_locator", "expired_locator"}:
        assert await h.client.exists(payload) == 1


@pytest.mark.parametrize(
    "value",
    [b"\xff", b"A" * 64, b"{}", b"f" * 63, b"f" * 65, b"", b'{"route":"x"}', b"f" * 63 + b"\n"],
)
async def test_malformed_locator_fails_before_consume(routing, value):
    h = routing
    tx = await create(h)
    locator, _, payload = keys(h, tx)
    await h.client.set(locator, value, keepttl=True)
    h.recorded.calls.clear()
    with pytest.raises(StateError):
        await h.store.consume(tx.state.get_secret_value(), h.now)
    assert [call[0] for call in h.recorded.calls] == ["get"]
    assert await h.client.exists(payload) == 1


async def test_locator_collision_does_not_overwrite_or_replace(routing, monkeypatch):
    h = routing
    first = await create(h)
    locator, owner, payload = keys(h, first)
    before = await h.client.get(locator)
    monkeypatch.setattr(secrets, "token_urlsafe", lambda n: first.state.get_secret_value())
    h.recorded.calls.clear()
    with pytest.raises(RedisError, match="locator"):
        await create(h)
    assert [call[0] for call in h.recorded.calls] == ["set"]
    assert await h.client.get(locator) == before
    assert await h.client.exists(owner, payload) == 2
    assert (await h.store.consume(first.state.get_secret_value(), h.now)).user_id == h.owner


@pytest.mark.parametrize("stage", ["set_before", "set_after", "get", "eval_before", "eval_after"])
async def test_create_transport_failure_is_not_retried(routing, monkeypatch, stage):
    h = routing
    first = await create(h)
    first_payload = keys(h, first)[2]
    method = "set" if stage.startswith("set") else "eval" if stage.startswith("eval") else "get"
    original = getattr(h.recorded, method)
    calls = 0

    async def fail(*args, **kwargs):
        nonlocal calls
        calls += 1
        if stage.endswith("after"):
            await original(*args, **kwargs)
        raise TimeoutError("synthetic failure")

    monkeypatch.setattr(h.recorded, method, fail)
    with pytest.raises(TimeoutError):
        await create(h)
    assert calls == 1
    assert await h.client.exists(first_payload) == (stage != "eval_after")


@pytest.mark.parametrize("operation", ["create", "clear"])
@pytest.mark.parametrize("change", ["replaced", "expired"])
async def test_stale_pointer_compare_fails_before_mutation(routing, monkeypatch, operation, change):
    h = routing
    first = await create(h)
    _, owner, payload = keys(h, first)
    original = h.recorded.eval

    async def changed_pointer(*args):
        if change == "expired":
            await h.client.delete(owner)
        else:
            await h.client.set(owner, "a" * 64, ex=600)
        return await original(*args)

    monkeypatch.setattr(h.recorded, "eval", changed_pointer)
    with pytest.raises(RedisError, match="pointer changed"):
        if operation == "clear":
            await h.store.clear(h.owner)
        else:
            await create(h)
    assert await h.client.exists(payload) == 1
    assert await h.client.get(owner) == (None if change == "expired" else b"a" * 64)


@pytest.mark.parametrize("operation", ["create", "clear"])
async def test_corrupt_owner_pointer_never_reaches_lua(routing, operation):
    h = routing
    owner = h.store._owner_key(h.store._routing_tag(h.owner))
    await h.client.set(owner, b"\xff", ex=600)
    h.recorded.calls.clear()
    with pytest.raises(RedisError, match="pointer"):
        if operation == "clear":
            await h.store.clear(h.owner)
        else:
            await create(h)
    assert not any(call[0] == "eval" for call in h.recorded.calls)


async def test_cross_owner_routing_and_payload_tag_binding(routing):
    h = routing
    first, second = await create(h), await create(h, uuid4())
    locator, _, first_payload = keys(h, first)
    tag2 = h.store._routing_tag(second.user_id)
    await h.client.set(locator, tag2, keepttl=True)
    with pytest.raises(StateError):
        await h.store.consume(first.state.get_secret_value(), h.now)
    assert await h.client.exists(first_payload) == 1
    misplaced = h.store._state_key(tag2, h.store._fingerprint(first.state.get_secret_value()))
    await h.client.set(misplaced, await h.client.get(first_payload), ex=600)
    with pytest.raises(StateError):
        await h.store.consume(first.state.get_secret_value(), h.now)
    assert (await h.store.consume(second.state.get_secret_value(), h.now)).user_id == second.user_id


async def test_clear_keeps_only_bounded_locator_and_no_renewal(routing):
    h = routing
    tx = await create(h)
    locator, owner, payload = keys(h, tx)
    await h.client.pexpire(locator, 100_000)
    before = await h.client.pttl(locator)
    await h.store.clear(h.owner)
    assert await h.client.exists(owner, payload) == 0
    assert 0 < await h.client.pttl(locator) <= before <= 600_000
    with pytest.raises(StateError):
        await h.store.consume(tx.state.get_secret_value(), h.now)


async def test_payload_without_pointer_can_be_consumed_once(routing):
    h = routing
    tx = await create(h)
    await h.client.delete(keys(h, tx)[1])
    assert (await h.store.consume(tx.state.get_secret_value(), h.now)).user_id == h.owner
    with pytest.raises(StateError):
        await h.store.consume(tx.state.get_secret_value(), h.now)


@pytest.mark.parametrize(
    "mode", ["expired", "future", "wrong_lifetime", "wrong_owner", "bad_verifier", "invalid_json"]
)
async def test_payload_validation_still_authoritative(routing, mode):
    h = routing
    tx = await create(h)
    payload_key = keys(h, tx)[2]
    data = json.loads(await h.client.get(payload_key))
    if mode == "future":
        data["created_at"] += 1
        data["expires_at"] += 1
    if mode == "wrong_lifetime":
        data["expires_at"] += 1
    if mode == "wrong_owner":
        data["user_id"] = str(uuid4())
    if mode == "bad_verifier":
        data["verifier"] = "invalid"
    await h.client.set(
        payload_key, "not-json" if mode == "invalid_json" else json.dumps(data), keepttl=True
    )
    with pytest.raises(StateError):
        await h.store.consume(
            tx.state.get_secret_value(),
            h.now + timedelta(seconds=600) if mode == "expired" else h.now,
        )
    assert await h.client.exists(payload_key) == 0


async def test_forged_state_and_old_format_no_fallback(routing):
    h = routing
    state = secrets.token_urlsafe(32)
    old = "old-format:" + h.store._fingerprint(state)
    await h.client.set(old, "synthetic", ex=600)
    try:
        with pytest.raises(StateError):
            await h.store.consume(state, h.now)
        assert await h.client.get(old) == b"synthetic"
    finally:
        await h.client.delete(old)


async def test_callback_transport_failure_propagates_without_consume():
    redis = SimpleNamespace(get=AsyncMock(side_effect=RedisError()), eval=AsyncMock())
    store = TransactionStore(redis, settings())
    with pytest.raises(RedisError):
        await store.consume(secrets.token_urlsafe(32), datetime.now(UTC))
    redis.eval.assert_not_awaited()


async def test_text_decoding_client_corrupt_locator_and_pointer_fail_safely(routing):
    h = routing
    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    store = TransactionStore(client, settings(redis_key_prefix=h.store.prefix.split(":cache:")[0]))
    try:
        tx = await create(h)
        locator, owner, payload = keys(h, tx)
        await h.client.set(locator, b"\xff", keepttl=True)
        with pytest.raises(StateError):
            await store.consume(tx.state.get_secret_value(), h.now)
        assert await h.client.exists(payload) == 1
        await h.client.set(owner, b"\xff", keepttl=True)
        with pytest.raises(RedisError, match="pointer"):
            await store.clear(h.owner)
        with pytest.raises(RedisError, match="pointer"):
            await store.create(h.owner, uuid4(), uuid4(), h.now)
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "script,count,argv", [(_CREATE, 2, ("a" * 64, "b" * 64, "{}", 600)), (_CLEAR, 1, ("a" * 64,))]
)
async def test_lua_bad_declared_key_count_fails_before_writes(routing, script, count, argv):
    h = routing
    tx = await create(h)
    _, owner, payload = keys(h, tx)
    before = await h.client.get(owner), await h.client.get(payload)
    declared = [owner, payload][:count]
    assert await h.recorded.eval(script, count, *declared, *argv) == 0
    assert (await h.client.get(owner), await h.client.get(payload)) == before
