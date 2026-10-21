"""Static Rauthy 0.37.1 confidential-client contract for Core resource exchange.

Provisioning uses the provider's authenticated admin-session API. This module
holds public configuration only, never human credentials or client secrets.
"""
CLIENT_ID = "briareus-resource-broker"
CLIENT_NAME = "Briareus Resource Broker"
GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
HANDS = ("files", "terminal", "web", "svc", "infrastructure", "reverse", "serena")


def configuration(origin):
    if origin not in {"https://127.0.0.1", "https://briareus.koba-nexus.ru"}:
        raise ValueError("Approved Core realm required")
    return {"name":CLIENT_NAME,"confidential":True,"enabled":True,"redirect_uris":[],
        "post_logout_redirect_uris":None,"allowed_origins":None,"flows_enabled":[GRANT],
        "access_token_alg":"EdDSA","id_token_alg":"EdDSA","auth_code_lifetime":30,
        "access_token_lifetime":90,"scopes":["openid","profile","email"],
        "default_scopes":["openid","profile","email"],"challenges":None,"force_mfa":True,
        "client_uri":origin+"/panel/","contacts":None,"backchannel_logout_uri":None,
        "restrict_group_prefix":None,"claims":None,"claims_at_root":False,
        "allowed_resources":[origin+"/hands/"+hand+"/mcp" for hand in HANDS],"default_aud":None,"scim":None}


def verify_configuration(value, origin):
    expected=configuration(origin)
    if not isinstance(value,dict) or value.get("id")!=CLIENT_ID:
        raise ValueError("Wrong resource client identity")
    for key,wanted in expected.items():
        actual=value.get(key)
        if key in {"flows_enabled","allowed_resources","scopes","default_scopes"}:
            if not isinstance(actual,list) or sorted(actual)!=sorted(wanted):
                raise ValueError("Resource client scope differs from approved contract")
        elif wanted is None and key in {"post_logout_redirect_uris","allowed_origins","contacts","challenges","default_aud"} and actual in (None,[]):
            continue
        elif actual!=wanted:
            raise ValueError("Resource client configuration differs from approved contract")
