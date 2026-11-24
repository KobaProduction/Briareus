from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock, patch

from briareus_git.downloads import DownloadError, _public_connection, download_public_https
from briareus_git.files import content_fields, encode_content


class SharedGitDownloadContracts(unittest.TestCase):
    def test_private_mixed_multicast_and_insecure_redirects_denied(self) -> None:
        for url in (
            "http://example.org/file",
            "https://user@example.org/file",
            "https://example.org:444/file",
        ):
            with self.subTest(url=url), self.assertRaises(DownloadError):
                _public_connection(url)
        for addresses in (["127.0.0.1"], ["8.8.8.8", "10.0.0.1"], ["224.0.0.1"]):
            results = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses]
            with (
                patch("briareus_git.downloads.socket.getaddrinfo", return_value=results),
                self.assertRaises(DownloadError),
            ):
                _public_connection("https://example.org/file")

    def test_validated_ip_is_pinned_with_original_tls_hostname(self) -> None:
        address = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        with patch("briareus_git.downloads.socket.getaddrinfo", return_value=[address]):
            conn, target = _public_connection("https://example.org/file?signature=x")
        self.assertEqual(conn.host, "example.org")
        self.assertEqual(conn.address, "8.8.8.8")
        self.assertEqual(target, "/file?signature=x")

    def test_follow_redirect_without_auth_and_bounded_read(self) -> None:
        first, second = MagicMock(), MagicMock()
        first.getresponse.return_value.status = 302
        first.getresponse.return_value.getheader.return_value = "https://second.example.org/data"
        second.getresponse.return_value.status = 200
        second.getresponse.return_value.read.return_value = b"abc"
        with patch(
            "briareus_git.downloads._public_connection",
            side_effect=[
                (first, "/signed"),
                (second, "/data"),
            ],
        ):
            self.assertEqual(download_public_https("https://first.example.org/signed", 3), b"abc")
        for conn in (first, second):
            self.assertEqual(conn.request.call_args.kwargs["headers"], {"User-Agent": "briareus"})
            conn.close.assert_called_once()
        second.getresponse.return_value.read.assert_called_once_with(4)
        second.getresponse.return_value.read.return_value = b"abcd"
        with (
            patch("briareus_git.downloads._public_connection", return_value=(second, "/data")),
            self.assertRaisesRegex(DownloadError, "exceeds"),
        ):
            download_public_https("https://second.example.org/data", 3)

    def test_common_codec_preserves_binary_and_text(self) -> None:
        self.assertEqual(encode_content("hello", "utf-8"), "aGVsbG8=")
        self.assertEqual(encode_content("/wA=", "base64"), "/wA=")
        self.assertEqual(content_fields(b"\xff\x00", "base64"), {"content_base64": "/wA="})
        with self.assertRaises(ValueError):
            encode_content("!invalid", "base64")
