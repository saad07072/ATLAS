from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWKClientError
from jwt.exceptions import InvalidTokenError

from backend.app.config.settings import settings
from backend.app.core.exceptions import ApplicationError

_bearer_scheme = HTTPBearer(auto_error=False)
_MAX_ACCESS_TOKEN_LENGTH = 8192
_SUPPORTED_JWKS_ALGORITHMS = ("ES256", "RS256", "EdDSA")


class SupabaseAccessTokenVerifier:
    def __init__(
        self,
        supabase_url: str | None,
        jwt_secret: str | None = None,
    ) -> None:
        self._issuer = (
            f"{supabase_url.rstrip('/')}/auth/v1" if supabase_url else None
        )
        self._jwt_secret = jwt_secret
        self._jwks_client = (
            PyJWKClient(
                f"{self._issuer}/.well-known/jwks.json",
                cache_keys=True,
                timeout=5,
            )
            if self._issuer
            else None
        )

    def verify(self, access_token: str) -> UUID:
        if (
            not access_token
            or len(access_token) > _MAX_ACCESS_TOKEN_LENGTH
            or not self._issuer
        ):
            if not self._issuer:
                raise _authentication_unavailable()
            raise _invalid_credentials()

        try:
            header = jwt.get_unverified_header(access_token)
            algorithm = header.get("alg")
            if algorithm == "HS256" and self._jwt_secret:
                signing_key = self._jwt_secret
                algorithms = ["HS256"]
            elif (
                algorithm in _SUPPORTED_JWKS_ALGORITHMS
                and self._jwks_client is not None
            ):
                signing_key = self._jwks_client.get_signing_key_from_jwt(
                    access_token
                ).key
                algorithms = [algorithm]
            else:
                raise _invalid_credentials()

            claims = jwt.decode(
                access_token,
                signing_key,
                algorithms=algorithms,
                audience="authenticated",
                issuer=self._issuer,
                options={
                    "require": ["aud", "exp", "iat", "iss", "sub"],
                },
            )
        except PyJWKClientConnectionError as exc:
            raise _authentication_unavailable() from exc
        except (PyJWKClientError, InvalidTokenError, TypeError, ValueError) as exc:
            raise _invalid_credentials() from exc
        except OSError as exc:
            raise _authentication_unavailable() from exc

        if claims.get("role") != "authenticated":
            raise ApplicationError(
                "This account is not authorized to access ATLAS.",
                code="authentication_forbidden",
                status_code=403,
            )

        try:
            return UUID(claims["sub"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid_credentials() from exc


@lru_cache(maxsize=1)
def get_access_token_verifier() -> SupabaseAccessTokenVerifier:
    return SupabaseAccessTokenVerifier(
        settings.supabase_url,
        settings.supabase_jwt_secret,
    )


def get_optional_authenticated_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    verifier: SupabaseAccessTokenVerifier = Depends(get_access_token_verifier),
) -> UUID | None:
    if credentials is None:
        return None
    return verifier.verify(credentials.credentials)


def get_authenticated_user_id(
    user_id: UUID | None = Depends(get_optional_authenticated_user_id),
) -> UUID:
    if user_id is None:
        raise ApplicationError(
            "Authentication is required.",
            code="authentication_required",
            status_code=401,
        )
    return user_id


def require_authenticated_user_id(
    user_id: UUID = Depends(get_authenticated_user_id),
) -> UUID:
    if user_id is None:
        raise ApplicationError(
            "Authentication is required.",
            code="authentication_required",
            status_code=401,
        )
    return user_id


def _invalid_credentials() -> ApplicationError:
    return ApplicationError(
        "The access token is missing, invalid, or expired.",
        code="invalid_authentication",
        status_code=401,
    )


def _authentication_unavailable() -> ApplicationError:
    return ApplicationError(
        "Authentication is temporarily unavailable.",
        code="authentication_unavailable",
        status_code=503,
    )
