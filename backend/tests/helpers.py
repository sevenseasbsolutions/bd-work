"""Set-up shared by the test modules: make a BD, make a profile, log a find."""


def make_bd(client, manager, name, email):
    reply = client.post("/users", headers=manager, json={
        "name": name, "email": email, "password": "secret", "role": "bd"})
    assert reply.status_code == 201, reply.text
    return reply.json()


def make_profile(client, manager, name, user_id=None, **extra):
    reply = client.post("/profiles", headers=manager,
                        json={"name": name, "user_id": user_id, **extra})
    assert reply.status_code == 201, reply.text
    return reply.json()


def log(client, headers, profile_id, **job):
    """One line of the entry grid, filed."""
    reply = client.post(f"/profiles/{profile_id}/own", headers=headers,
                        json={"jobs": [job]})
    assert reply.status_code == 200, reply.text
    return reply.json()
