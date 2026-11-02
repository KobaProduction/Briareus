"""Strict issuer models consume nested JSON after duplicate and nonfinite checks."""

import unittest

from authorization.domain.rauthy import RauthyKeysUnavailable
from authorization.infrastructure.issuer_documents import authority_document
from runtime_peer.oidc_wire import IssuerSigningKeys, RsaSigningKey


class NestedIssuerDocumentTests(unittest.TestCase):
    def test_nested_signing_key_is_a_typed_record(self) -> None:
        document = authority_document(
            b'{"keys":[{"kty":"RSA","kid":"provider-key","alg":"RS256",'
            b'"use":"sig","n":"modulus","e":"AQAB"}]}',
            IssuerSigningKeys,
        )
        key = document.keys[0]
        self.assertIsInstance(key, RsaSigningKey)
        self.assertEqual(key.kid, "provider-key")

    def test_nested_duplicate_private_and_nonfinite_material_stays_rejected(self) -> None:
        for payload in (
            b'{"keys":[{"kty":"RSA","kid":"first","kid":"last","alg":"RS256","n":"n","e":"e"}]}',
            b'{"keys":[{"kty":"RSA","kid":"key","alg":"RS256","n":"n","e":"e","d":"private"}]}',
            b'{"keys":[{"kty":"RSA","kid":"key","alg":"RS256","n":"n","e":"e","extra":NaN}]}',
            b'[]',
        ):
            with self.subTest(payload=payload), self.assertRaises(RauthyKeysUnavailable):
                authority_document(payload, IssuerSigningKeys)
