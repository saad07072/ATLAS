import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from jwt import PyJWKClientConnectionError

from backend.app.core.error_handlers import register_exception_handlers
from backend.app.core.exceptions import ApplicationError
from backend.app.memory.models import (
    MemoryCandidate,
    MemoryRecord,
    MemorySource,
    MemoryType,
    MemoryUpdate,
)
from backend.app.memory.service import MemoryService
from backend.app.security.identity import (
    SupabaseAccessTokenVerifier,
    get_access_token_verifier,
    get_optional_authenticated_user_id,
    require_authenticated_user_id,
)
from backend.app.api.v1.memory import router as memory_router
from backend.app.memory.runtime import get_memory_service

SUPABASE_URL = "https://atlas-test.supabase.co"
USER_A = UUID("ef3e7347-a8e9-4d63-90cf-a21d5c855515")
USER_B = UUID("43ad3973-5d96-4608-8b7b-3e774106429a")


class InMemoryOwnerRepository:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, MemoryRecord]] = {}

    def list(self, user_id: str, *, memory_type: str | None, limit: int):
        return [
            record
            for owner, record in self.records.values()
            if owner == user_id
            and (memory_type is None or record.type.value == memory_type)
        ][:limit]

    def create(self, user_id: str, candidate: MemoryCandidate, *, source: str):
        now = datetime.now(timezone.utc)
        record = MemoryRecord(
            id=str(uuid4()),
            type=candidate.type,
            memory_key=candidate.memory_key,
            content=candidate.content,
            source=MemorySource(source),
            created_at=now,
            updated_at=now,
        )
        self.records[record.id] = (user_id, record)
        return record

    def update(self, user_id: str, memory_id: str, changes: MemoryUpdate):
        stored = self.records.get(memory_id)
        if stored is None or stored[0] != user_id:
            return None
        record = stored[1].model_copy(
            update={
                **changes.model_dump(exclude_unset=True),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.records[memory_id] = (user_id, record)
        return record

    def delete(self, user_id: str, memory_id: str):
        stored = self.records.get(memory_id)
        if stored is None or stored[0] != user_id:
            return False
        del self.records[memory_id]
        return True

    def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        memory_type: str | None,
        limit: int,
    ):
        return [
            record
            for owner, record in self.records.values()
            if owner == user_id
            and query.lower() in record.content.lower()
            and (memory_type is None or record.type.value == memory_type)
        ][:limit]


def make_token(
    private_key: rsa.RSAPrivateKey,
    *,
    subject: str = str(USER_A),
    audience: str | list[str] = "authenticated",
    issuer: str = f"{SUPABASE_URL}/auth/v1",
    role: str = "authenticated",
    expires_at: datetime | None = None,
    include_iat: bool = True,
) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, object] = {
        "aud": audience,
        "exp": expires_at or now + timedelta(minutes=5),
        "iss": issuer,
        "role": role,
        "sub": subject,
    }
    if include_iat:
        claims["iat"] = now
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-signing-key"},
    )


class SupabaseAccessTokenVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

    def setUp(self) -> None:
        self.verifier = SupabaseAccessTokenVerifier(SUPABASE_URL)
        self.signing_key = SimpleNamespace(
            key=self.private_key.public_key(),
            algorithm_name="RS256",
        )
        self.jwks_patch = patch.object(
            self.verifier._jwks_client,
            "get_signing_key_from_jwt",
            return_value=self.signing_key,
        )
        self.jwks_patch.start()
        self.addCleanup(self.jwks_patch.stop)

    def test_accepts_valid_supabase_access_token_and_returns_trusted_uuid(self) -> None:
        token = make_token(self.private_key)

        self.assertEqual(self.verifier.verify(token), USER_A)

    def test_rejects_expired_token_and_requires_claims(self) -> None:
        expired = make_token(
            self.private_key,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        missing_iat = make_token(self.private_key, include_iat=False)

        for token in (expired, missing_iat):
            with self.subTest(token=token[:12]), self.assertRaises(ApplicationError) as error:
                self.verifier.verify(token)
            self.assertEqual(error.exception.status_code, 401)

    def test_rejects_invalid_signature_audience_issuer_and_malformed_subject(self) -> None:
        valid_token = make_token(self.private_key)
        header, payload, signature = valid_token.split(".")
        replacement = "A" if signature[0] != "A" else "B"
        invalid_signature = ".".join((header, payload, replacement + signature[1:]))
        wrong_audience = make_token(self.private_key, audience="anon")
        wrong_issuer = make_token(
            self.private_key,
            issuer="https://other.supabase.co/auth/v1",
        )
        malformed_subject = make_token(self.private_key, subject="not-a-uuid")

        for token in (
            invalid_signature,
            wrong_audience,
            wrong_issuer,
            malformed_subject,
        ):
            with self.subTest(token=token[:12]):
                with self.assertRaises(ApplicationError) as error:
                    self.verifier.verify(token)
                self.assertEqual(error.exception.status_code, 401)

    def test_rejects_non_authenticated_role_with_forbidden(self) -> None:
        token = make_token(self.private_key, role="anon")

        with self.assertRaises(ApplicationError) as error:
            self.verifier.verify(token)

        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(error.exception.code, "authentication_forbidden")

    def test_rejects_unsupported_algorithm_without_jwks_lookup(self) -> None:
        token = jwt.encode(
            {
                "aud": "authenticated",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                "iat": datetime.now(timezone.utc),
                "iss": f"{SUPABASE_URL}/auth/v1",
                "role": "authenticated",
                "sub": str(USER_A),
            },
            "shared-secret",
            algorithm="HS384",
        )
        self.verifier._jwks_client.get_signing_key_from_jwt = Mock()

        with self.assertRaises(ApplicationError) as error:
            self.verifier.verify(token)

        self.assertEqual(error.exception.status_code, 401)
        self.verifier._jwks_client.get_signing_key_from_jwt.assert_not_called()

    def test_uses_configured_hs256_secret_only_for_legacy_signing_keys(self) -> None:
        verifier = SupabaseAccessTokenVerifier(SUPABASE_URL, "legacy-signing-secret")
        token = jwt.encode(
            {
                "aud": "authenticated",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                "iat": datetime.now(timezone.utc),
                "iss": f"{SUPABASE_URL}/auth/v1",
                "role": "authenticated",
                "sub": str(USER_A),
            },
            "legacy-signing-secret",
            algorithm="HS256",
        )

        self.assertEqual(verifier.verify(token), USER_A)

    def test_missing_configuration_and_unavailable_jwks_fail_safely(self) -> None:
        unconfigured = SupabaseAccessTokenVerifier(None)
        token = make_token(self.private_key)
        with self.assertRaises(ApplicationError) as error:
            unconfigured.verify(token)
        self.assertEqual(error.exception.status_code, 503)

        self.verifier._jwks_client.get_signing_key_from_jwt.side_effect = (
            PyJWKClientConnectionError("sensitive network details")
        )
        with self.assertRaises(ApplicationError) as error:
            self.verifier.verify(token)
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("sensitive", error.exception.message)


class AuthenticationDependencyTests(unittest.TestCase):
    def test_optional_identity_accepts_missing_credentials_only_for_optional_routes(self) -> None:
        self.assertIsNone(
            get_optional_authenticated_user_id(
                credentials=None,
                verifier=Mock(),
            )
        )
        with self.assertRaises(ApplicationError) as error:
            require_authenticated_user_id(user_id=None)
        self.assertEqual(error.exception.status_code, 401)

    def test_invalid_bearer_is_rejected_instead_of_becoming_anonymous(self) -> None:
        verifier = Mock()
        verifier.verify.side_effect = ApplicationError(
            "The access token is missing, invalid, or expired.",
            code="invalid_authentication",
            status_code=401,
        )

        with self.assertRaises(ApplicationError) as error:
            get_optional_authenticated_user_id(
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials="invalid-token",
                ),
                verifier=verifier,
            )
        self.assertEqual(error.exception.status_code, 401)


class MemoryOwnershipApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryOwnerRepository()
        self.service = MemoryService(self.repository)
        self.app = FastAPI()
        register_exception_handlers(self.app)
        self.app.include_router(memory_router, prefix="/api/v1")
        self.app.dependency_overrides[get_access_token_verifier] = lambda: self.verifier
        self.app.dependency_overrides[get_memory_service] = lambda: self.service
        self.verifier = Mock(spec=SupabaseAccessTokenVerifier)
        self.verifier.verify.side_effect = self._verify_test_token

    @staticmethod
    def _verify_test_token(token: str) -> UUID:
        if token == "user-a-token":
            return USER_A
        if token == "user-b-token":
            return USER_B
        raise ApplicationError(
            "The access token is missing, invalid, or expired.",
            code="invalid_authentication",
            status_code=401,
        )

    def test_valid_and_missing_tokens_are_authenticated_or_rejected(self) -> None:
        from fastapi.testclient import TestClient

        with TestClient(self.app) as client:
            response = client.get(
                "/api/v1/memory",
                headers={"Authorization": "Bearer user-a-token"},
            )
            missing = client.get("/api/v1/memory")
            invalid = client.get(
                "/api/v1/memory",
                headers={"Authorization": "Bearer invalid-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)

    def test_user_b_cannot_list_update_or_delete_user_a_memory(self) -> None:
        from fastapi.testclient import TestClient

        memory = self.service.create(
            str(USER_A),
            MemoryCandidate(
                type=MemoryType.DURABLE_FACT,
                memory_key="private-fact",
                content="This is user A private memory.",
            ),
        )
        with TestClient(self.app) as client:
            headers = {"Authorization": "Bearer user-b-token"}
            listing = client.get("/api/v1/memory", headers=headers)
            update = client.put(
                f"/api/v1/memory/{memory.id}",
                headers=headers,
                json={"content": "User B cannot change this."},
            )
            delete = client.delete(
                f"/api/v1/memory/{memory.id}",
                headers=headers,
            )

        self.assertEqual(listing.json(), {"memories": []})
        self.assertEqual(update.status_code, 404)
        self.assertEqual(delete.json(), {"deleted": False})
        self.assertEqual(
            self.service.list(str(USER_A))[0].content,
            "This is user A private memory.",
        )

    def test_user_id_in_request_body_cannot_override_token_identity(self) -> None:
        from fastapi.testclient import TestClient

        with TestClient(self.app) as client:
            response = client.post(
                "/api/v1/memory",
                headers={"Authorization": "Bearer user-a-token"},
                json={
                    "user_id": str(USER_B),
                    "type": "durable_fact",
                    "memory_key": "my-fact",
                    "content": "Owned by the identity from the token.",
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.list(str(USER_A)), [])


if __name__ == "__main__":
    unittest.main()
