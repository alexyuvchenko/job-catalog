"""Helpers shared by the catalog tests."""

from web.auth import AccountError


def sign_in(client, catalog, username: str = "ada", password: str = "password-1"):
    try:
        catalog.create_user(username, password)
    except AccountError as exc:
        if exc.code != "username_taken":
            raise
    response = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    if response.status_code != 303:
        raise RuntimeError(f"login failed: {response.status_code} {response.text[:500]}")
    return response
