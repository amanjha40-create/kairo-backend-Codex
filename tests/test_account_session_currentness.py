from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.deps import CurrentUser, get_current_user, get_optional_current_user
from app.auth.service import AuthService
from app.auth.tokens import create_access_token, decode_token
from app.config import Settings
from app.exceptions import ConflictError, UnauthorizedError
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.account_settings_service import AccountSettingsService


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeUsers:
    def __init__(self, user: User | None) -> None:
        self.user = user

    async def get_by_id(self, user_id):  # noqa: ANN001
        if (
            self.user is not None
            and self.user.id == user_id
            and self.user.deleted_at is None
        ):
            return self.user
        return None


class FakeRefreshRepo:
    def __init__(
        self,
        existing: RefreshToken | None = None,
        *,
        active_family_ids: set[UUID] | None = None,
    ) -> None:
        self.existing = existing
        self.active_family_ids = active_family_ids or set()
        self.revoked_ids: list[UUID] = []
        self.revoke_all_calls: list[UUID] = []
        self.revoke_all_except_calls: list[tuple[UUID, UUID]] = []

    async def get_by_hash_any(self, _token_hash: str) -> RefreshToken | None:
        return self.existing

    async def revoke(self, token_id: UUID) -> None:
        self.revoked_ids.append(token_id)

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        self.revoke_all_calls.append(user_id)

    async def revoke_all_for_user_except_family(self, user_id: UUID, family_id: UUID) -> None:
        self.revoke_all_except_calls.append((user_id, family_id))

    async def has_active_family(self, _user_id: UUID, family_id: UUID) -> bool:
        return family_id in self.active_family_ids


class FakeResult:
    def __init__(self, rows: list[RefreshToken]) -> None:
        self._rows = rows

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[RefreshToken]:
        return self._rows


class FakeQuerySession(FakeSession):
    def __init__(
        self,
        rows: list[RefreshToken] | None = None,
        scalar_row: RefreshToken | None = None,
    ) -> None:
        super().__init__()
        self._rows = rows or []
        self._scalar_row = scalar_row

    async def execute(self, _stmt) -> FakeResult:  # noqa: ANN001
        return FakeResult(self._rows)

    async def scalar(self, _stmt):  # noqa: ANN001
        return self._scalar_row


def make_settings() -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://kairo:kairo@localhost:5432/kairo",
        JWT_SECRET_KEY="test-jwt-secret-key-32-chars-minimum!!",
        REDIS_URL="redis://localhost:6379/0",
        APP_ENV="test",
    )


def make_user() -> User:
    user = User(
        email="candidate@example.com",
        password_hash="hashed-password",
        full_name="Candidate User",
        role="user",
        is_active=True,
        email_verified_at=datetime.now(tz=UTC),
    )
    user.id = uuid4()
    return user


def make_refresh_token(
    *,
    user_id: UUID,
    family_id: UUID,
    revoked_at: datetime | None = None,
    expires_delta_days: int = 7,
) -> RefreshToken:
    row = RefreshToken(
        user_id=user_id,
        token_hash=uuid4().hex,
        expires_at=datetime.now(tz=UTC) + timedelta(days=expires_delta_days),
        family_id=family_id,
        replaced_by_id=None,
    )
    row.id = uuid4()
    row.created_at = datetime.now(tz=UTC) - timedelta(hours=1)
    row.updated_at = datetime.now(tz=UTC)
    row.revoked_at = revoked_at
    return row


@pytest.mark.asyncio
async def test_issue_tokens_embeds_logical_session_family_claim() -> None:
    settings = make_settings()
    session = FakeSession()
    auth = AuthService(session, settings, SimpleNamespace())
    user = make_user()

    tokens = await auth._issue_tokens(user)

    assert len(session.added) == 1
    refresh_row = session.added[0]
    assert isinstance(refresh_row, RefreshToken)
    payload = decode_token(settings, tokens.access_token)
    assert payload["sid"] == str(refresh_row.family_id)


@pytest.mark.asyncio
async def test_refresh_rotation_preserves_logical_session_family_claim() -> None:
    settings = make_settings()
    session = FakeSession()
    auth = AuthService(session, settings, SimpleNamespace())
    user = make_user()
    family_id = uuid4()
    existing = make_refresh_token(user_id=user.id, family_id=family_id)
    auth._users = FakeUsers(user)
    auth._refresh = FakeRefreshRepo(existing)

    tokens = await auth.refresh(SimpleNamespace(refresh_token="refresh-token-value"))

    assert auth._refresh.revoked_ids == [existing.id]
    assert len(session.added) == 1
    new_row = session.added[0]
    assert isinstance(new_row, RefreshToken)
    assert new_row.family_id == family_id
    payload = decode_token(settings, tokens.access_token)
    assert payload["sid"] == str(family_id)


@pytest.mark.asyncio
async def test_list_sessions_marks_only_requesting_session_current() -> None:
    settings = make_settings()
    user = make_user()
    current_family_id = uuid4()
    current_row = make_refresh_token(user_id=user.id, family_id=current_family_id)
    other_row = make_refresh_token(user_id=user.id, family_id=uuid4())
    session = FakeQuerySession(rows=[current_row, other_row])
    service = AccountSettingsService(session, settings)
    service._users = FakeUsers(user)

    rows = await service.list_sessions(user.id, current_family_id)

    assert len(rows) == 2
    assert rows[0].id == current_row.id
    assert rows[0].current is True
    assert rows[1].id == other_row.id
    assert rows[1].current is False


@pytest.mark.asyncio
async def test_revoke_non_current_session_succeeds_but_current_session_is_blocked() -> None:
    settings = make_settings()
    user = make_user()
    current_family_id = uuid4()
    current_row = make_refresh_token(user_id=user.id, family_id=current_family_id)
    other_row = make_refresh_token(user_id=user.id, family_id=uuid4())

    service = AccountSettingsService(FakeQuerySession(scalar_row=current_row), settings)
    service._users = FakeUsers(user)
    service._refresh = FakeRefreshRepo()

    with pytest.raises(ConflictError, match="Current session cannot be revoked"):
        await service.revoke_session(user.id, current_row.id, current_family_id)
    assert service._refresh.revoked_ids == []

    other_service = AccountSettingsService(FakeQuerySession(scalar_row=other_row), settings)
    other_service._users = FakeUsers(user)
    other_service._refresh = FakeRefreshRepo()

    await other_service.revoke_session(user.id, other_row.id, current_family_id)

    assert other_service._refresh.revoked_ids == [other_row.id]
    assert other_service._session.commits == 1


@pytest.mark.asyncio
async def test_revoke_all_other_sessions_preserves_current_family() -> None:
    settings = make_settings()
    user = make_user()
    current_family_id = uuid4()
    service = AccountSettingsService(FakeQuerySession(), settings)
    service._users = FakeUsers(user)
    service._refresh = FakeRefreshRepo()

    await service.revoke_all_sessions(user.id, current_family_id)

    assert service._refresh.revoke_all_calls == []
    assert service._refresh.revoke_all_except_calls == [(user.id, current_family_id)]
    assert service._session.commits == 1


def test_current_user_carries_optional_session_family_identity() -> None:
    family_id = uuid4()
    current = CurrentUser(
        id=uuid4(),
        email="candidate@example.com",
        role="user",
        session_family_id=family_id,
    )

    assert current.session_family_id == family_id


@pytest.mark.asyncio
async def test_get_current_user_accepts_active_session_family_after_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = make_user()
    family_id = uuid4()
    token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
        extra_claims={"sid": str(family_id)},
    )

    monkeypatch.setattr("app.auth.deps.UserRepository", lambda _session: FakeUsers(user))
    monkeypatch.setattr(
        "app.auth.deps.RefreshTokenRepository",
        lambda _session: FakeRefreshRepo(active_family_ids={family_id}),
    )

    current = await get_current_user(
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        session=object(),
        settings=settings,
    )

    assert current.id == user.id
    assert current.session_family_id == family_id


@pytest.mark.asyncio
async def test_get_current_user_rejects_revoked_session_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = make_user()
    family_id = uuid4()
    token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
        extra_claims={"sid": str(family_id)},
    )

    monkeypatch.setattr("app.auth.deps.UserRepository", lambda _session: FakeUsers(user))
    monkeypatch.setattr(
        "app.auth.deps.RefreshTokenRepository",
        lambda _session: FakeRefreshRepo(active_family_ids=set()),
    )

    with pytest.raises(UnauthorizedError, match="Session not found or inactive"):
        await get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            session=object(),
            settings=settings,
        )


@pytest.mark.asyncio
async def test_get_current_user_rejects_missing_session_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = make_user()
    token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
    )

    monkeypatch.setattr("app.auth.deps.UserRepository", lambda _session: FakeUsers(user))
    monkeypatch.setattr(
        "app.auth.deps.RefreshTokenRepository",
        lambda _session: FakeRefreshRepo(active_family_ids=set()),
    )

    with pytest.raises(UnauthorizedError, match="Session not found or inactive"):
        await get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            session=object(),
            settings=settings,
        )


@pytest.mark.asyncio
async def test_get_current_user_rejects_invalid_session_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = make_user()
    token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
        extra_claims={"sid": "not-a-uuid"},
    )

    monkeypatch.setattr("app.auth.deps.UserRepository", lambda _session: FakeUsers(user))
    monkeypatch.setattr(
        "app.auth.deps.RefreshTokenRepository",
        lambda _session: FakeRefreshRepo(active_family_ids=set()),
    )

    with pytest.raises(UnauthorizedError, match="Invalid session"):
        await get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            session=object(),
            settings=settings,
        )


@pytest.mark.asyncio
async def test_get_optional_current_user_returns_none_for_revoked_session_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = make_user()
    family_id = uuid4()
    token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
        extra_claims={"sid": str(family_id)},
    )

    monkeypatch.setattr("app.auth.deps.UserRepository", lambda _session: FakeUsers(user))
    monkeypatch.setattr(
        "app.auth.deps.RefreshTokenRepository",
        lambda _session: FakeRefreshRepo(active_family_ids=set()),
    )

    current = await get_optional_current_user(
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        session=object(),
        settings=settings,
    )

    assert current is None


@pytest.mark.asyncio
async def test_get_current_user_rejects_one_revoked_session_family_but_accepts_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = make_user()
    active_family_id = uuid4()
    revoked_family_id = uuid4()
    active_token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
        extra_claims={"sid": str(active_family_id)},
    )
    revoked_token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
        extra_claims={"sid": str(revoked_family_id)},
    )

    monkeypatch.setattr("app.auth.deps.UserRepository", lambda _session: FakeUsers(user))
    monkeypatch.setattr(
        "app.auth.deps.RefreshTokenRepository",
        lambda _session: FakeRefreshRepo(active_family_ids={active_family_id}),
    )

    current = await get_current_user(
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=active_token),
        session=object(),
        settings=settings,
    )

    assert current.session_family_id == active_family_id

    with pytest.raises(UnauthorizedError, match="Session not found or inactive"):
        await get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=revoked_token),
            session=object(),
            settings=settings,
        )


@pytest.mark.asyncio
async def test_get_current_user_rejects_suspended_user_even_with_active_session_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = make_user()
    user.is_active = False
    family_id = uuid4()
    token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
        extra_claims={"sid": str(family_id)},
    )

    monkeypatch.setattr("app.auth.deps.UserRepository", lambda _session: FakeUsers(user))
    monkeypatch.setattr(
        "app.auth.deps.RefreshTokenRepository",
        lambda _session: FakeRefreshRepo(active_family_ids={family_id}),
    )

    with pytest.raises(UnauthorizedError, match="User not found or inactive"):
        await get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            session=object(),
            settings=settings,
        )


@pytest.mark.asyncio
async def test_get_current_user_rejects_deleted_user_bearer_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    user = make_user()
    user.deleted_at = datetime.now(tz=UTC)
    family_id = uuid4()
    token = create_access_token(
        settings,
        subject=user.id,
        role=user.role,
        extra_claims={"sid": str(family_id)},
    )

    monkeypatch.setattr("app.auth.deps.UserRepository", lambda _session: FakeUsers(user))
    monkeypatch.setattr(
        "app.auth.deps.RefreshTokenRepository",
        lambda _session: FakeRefreshRepo(active_family_ids={family_id}),
    )

    with pytest.raises(UnauthorizedError, match="User not found or inactive"):
        await get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
            session=object(),
            settings=settings,
        )
