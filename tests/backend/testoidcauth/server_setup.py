import writer.auth
import writer.serve

oidc = writer.auth.Oidc(
    client_id="client-id",
    client_secret="client-secret",
    host_url="http://localhost",
    url_authorize="https://idp.example.com/authorize",
    url_oauthtoken="https://idp.example.com/token",
)

writer.serve.register_auth(oidc)
