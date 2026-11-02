"""The provider adapter fixes its destination and never follows redirects."""

import unittest
from email.message import Message
from types import TracebackType
from typing import ClassVar
from unittest.mock import patch

import projects._rauthy_user_status as provider
from pydantic import SecretStr


class ResponseFixture:
    def __init__(
        self, status: int = 200, body: bytes = b"{}", content_type: str = "application/json"
    ) -> None:
        self.status, self.body = status, body
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self) -> "ResponseFixture":
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _error: BaseException | None,
        _trace: TracebackType | None,
    ) -> None:
        pass

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class ConnectionFixture:
    instances: ClassVar[list["ConnectionFixture"]] = []
    response: ClassVar[ResponseFixture] = ResponseFixture()

    def __init__(self, host: str, port: int, *, timeout: int) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.target: str | None = None
        self.closed = False
        self.instances.append(self)

    def request(self, method: str, target: str, *, headers: dict[str, str]) -> None:
        if method != "GET" or set(headers) != {"Authorization", "Accept"}:
            raise AssertionError("Unexpected provider request")
        self.target = target

    def getresponse(self) -> ResponseFixture:
        return self.response

    def close(self) -> None:
        self.closed = True


class ProviderTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        ConnectionFixture.instances = []
        ConnectionFixture.response = ResponseFixture()
        self.transport = provider.FixedRauthyUsersTransport(
            users_read_api_key=SecretStr("test-only-key")
        )

    def test_subject_read_uses_only_fixed_private_host_and_bounded_response(self) -> None:
        with patch.object(provider, "HTTPConnection", ConnectionFixture):
            response = self.transport._read_sync("R" * 24)
        connection = ConnectionFixture.instances[0]
        self.assertEqual(
            (connection.host, connection.port, connection.timeout), ("briareus-rauthy", 8080, 3)
        )
        self.assertEqual(connection.target, "/auth/v1/users/" + "R" * 24)
        self.assertTrue(connection.closed)
        self.assertEqual(response.body, b"{}")

    def test_email_selector_is_encoded_in_a_fixed_path(self) -> None:
        with patch.object(provider, "HTTPConnection", ConnectionFixture):
            self.transport._read_sync("person+test@example.invalid", by_email=True)
        self.assertEqual(
            ConnectionFixture.instances[0].target,
            "/auth/v1/users/email/person%2Btest%40example.invalid",
        )

    def test_redirect_is_returned_without_contacting_another_destination(self) -> None:
        ConnectionFixture.response = ResponseFixture(302)
        with patch.object(provider, "HTTPConnection", ConnectionFixture):
            response = self.transport._read_sync("R" * 24)
        self.assertEqual(response.status, 302)
        self.assertEqual(len(ConnectionFixture.instances), 1)
        self.assertTrue(ConnectionFixture.instances[0].closed)

    def test_oversized_and_non_json_bodies_fail_closed_and_close_connection(self) -> None:
        for response in (
            ResponseFixture(body=b"x" * 65537),
            ResponseFixture(content_type="text/plain"),
        ):
            with (
                self.subTest(response=response),
                patch.object(provider, "HTTPConnection", ConnectionFixture),
            ):
                ConnectionFixture.response = response
                with self.assertRaises(provider.RauthyUserStatusUnavailable):
                    self.transport._read_sync("R" * 24)
                self.assertTrue(ConnectionFixture.instances[-1].closed)
