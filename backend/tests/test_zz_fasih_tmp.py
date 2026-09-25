from test_imports import workspace, upload

def test_fasih(client, manager):
    (mine, ayesha), (theirs, bilal) = workspace(client, manager)
    data = open("../Old Data/Fasih Sultan AR-Rehaan (1).xlsx", "rb").read()
    r = upload(client, mine, ayesha["id"], data)
    print("\nREPORT", {k: r[k] for k in ("rows","added","known","duplicate","repeated","clashing","not_applied","unusable","undated","left_over","finished")})
    own = client.get(f"/profiles/{ayesha['id']}/own", headers=mine).json()
    pool = client.get(f"/profiles/{ayesha['id']}/all", headers=mine).json()
    pend = client.get(f"/profiles/{bilal['id']}/others", headers=theirs, params={"status":"pending"}).json()
    print("own", len(own), "all jobs", len(pool), "standing", {s for s in (p["standing"] for p in pool)}, "bilal pending", len(pend))
    again = upload(client, mine, ayesha["id"], data)
    print("AGAIN", {k: again[k] for k in ("added","duplicate","repeated","clashing","unusable")})
