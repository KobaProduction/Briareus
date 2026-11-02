"""Keep the existing account TLS policy on public SSLContext APIs."""

import os
import ssl
import sys


def provider_ssl_context(*, verify_tls: bool, ca_cert_pem: str | None) -> ssl.SSLContext:
    if verify_tls:
        if ca_cert_pem:
            return ssl.create_default_context(cadata=ca_cert_pem.replace("\\n", "\n"))
        return ssl.create_default_context()

    # Match CPython 3.13's former private factory for this explicit account policy.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    if hasattr(context, "keylog_filename"):
        keylog_file = os.environ.get("SSLKEYLOGFILE")
        if keylog_file and not sys.flags.ignore_environment:
            context.keylog_filename = keylog_file
    return context
