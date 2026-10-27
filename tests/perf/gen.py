"""Synthetic archive with realistic name statistics: Zipf-distributed first and
last names, companies with common legal-form words, relationship records by
name, ~10% cross-collection duplicates with spelling variants."""
import json, random, shutil, sys
from pathlib import Path

N, out = int(sys.argv[1]), Path(sys.argv[2])
rnd = random.Random(42)
FIRST = [f"Fn{i}" for i in range(300)]      # pools; Zipf weights make some very common
LAST = [f"Ln{i}" for i in range(2000)]
WORDS = [f"W{i}" for i in range(1500)]
FORMS = ["Ltd", "GmbH", "Inc", "LLC", "SA", "Holding", "Group", "Trading"]
zipf = lambda n: [1 / (k + 1) ** 1.1 for k in range(n)]
WF, WL, WW = zipf(len(FIRST)), zipf(len(LAST)), zipf(len(WORDS))
pick = lambda pool, w: rnd.choices(pool, w)[0]

n_people, n_cos = int(N * 0.45), int(N * 0.2)
n_rel = N - n_people - n_cos
cols = {c: [] for c in ("registry", "leaks", "press")}
people, cos = [], []
for i in range(n_people):
    name = f"{pick(FIRST, WF)} {pick(LAST, WL)}"
    p = {"id": f"p{i}", "schema": "Person", "properties": {
        "name": [name], "birthDate": [f"{rnd.randint(1940, 2000)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"],
        "nationality": [rnd.choice(["de", "fr", "gb", "us", "ru", "pl"])]}}
    people.append(p); cols["registry"].append(p)
for i in range(n_cos):
    name = f"{pick(WORDS, WW)} {pick(WORDS, WW)} {rnd.choice(FORMS)}"
    c = {"id": f"c{i}", "schema": "Company", "properties": {
        "name": [name], "jurisdiction": [rnd.choice(["de", "fr", "gb", "us", "ch"])],
        "registrationNumber": [f"R{i:07d}"]}}
    cos.append(c); cols["registry"].append(c)
schemas = [("Membership", "member", "organization"), ("Employment", "employee", "employer"),
           ("Directorship", "director", "organization")]
for i in range(n_rel):
    s, cp, pp = rnd.choice(schemas)
    a, b = rnd.choice(people), rnd.choice(cos)
    cols[rnd.choice(["registry", "leaks", "press"])].append({"id": f"r{i}", "schema": s, "properties": {
        cp: [a["properties"]["name"][0]], pp: [b["properties"]["name"][0]],
        "role": [rnd.choice(["Director", "Member", "Employee", "Officer", "Leader"])],
        "startDate": [str(rnd.randint(1990, 2020))]}})
for p in rnd.sample(people, len(people) // 10):           # duplicates in another source
    v = dict(p["properties"]); n = v["name"][0]
    v["name"] = [n.upper() if rnd.random() < .5 else n]
    cols["leaks"].append({"id": p["id"], "schema": "Person", "properties": v})
root = out
shutil.rmtree(root, ignore_errors=True)
shutil.copytree(sys.argv[3], root)
for c, recs in cols.items():
    (root / "collections" / f"{c}.json").write_text(json.dumps(recs))
print(N, "->", sum(len(v) for v in cols.values()), "records")
