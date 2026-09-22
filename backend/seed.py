"""Fill an empty MBS with a workspace you can actually look at.

    python seed.py            add the demo data if it is not already there
    python seed.py --reset    delete the database file first

Everybody signs in with the password `mbs`, except the manager, who uses
`manager`. Change both before this is anywhere but a laptop.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import dispatch                                  # noqa: E402
from app.db import Base, SessionLocal, engine             # noqa: E402
from app.models import Profile, User                      # noqa: E402
from app.security import hash_password                    # noqa: E402

PEOPLE = [
    ("Manager", "manager@mbs.co", "manager", "manager"),
    ("Ayesha Raza", "ayesha@mbs.co", "mbs", "bd"),
    ("Bilal Khan", "bilal@mbs.co", "mbs", "bd"),
    ("Sana Iqbal", "sana@mbs.co", "mbs", "bd"),
]

PROFILES = [
    ("Khuram — AI Engineer", "AI / LLM Engineer", "Upwork",
     "python, pytorch, rag, llm, langchain", "ayesha@mbs.co"),
    ("Zahid — ML Engineer", "Machine Learning Engineer", "Upwork",
     "python, tensorflow, nlp, llm", "ayesha@mbs.co"),
    ("Hamza — Full Stack", "Full Stack Developer", "LinkedIn",
     "react, node, postgres, typescript", "bilal@mbs.co"),
    ("Noor — Frontend", "Frontend Engineer", "LinkedIn",
     "react, next.js, tailwind, typescript", "sana@mbs.co"),
    ("Imran — Backend", "Backend Engineer", "Indeed",
     "django, fastapi, postgres, aws", ""),
]

# One line of the entry grid each:
# (profile, company, job title, url, platform, email, date)
FINDS = [
    ("Khuram — AI Engineer", "Northwind Labs", "Senior RAG Engineer",
     "https://www.upwork.com/jobs/~017acdef99120abc44", "Upwork",
     "khuram.apply@mbs.co", "2026-09-14"),
    ("Khuram — AI Engineer", "Bluepeak AI", "LLM Fine-tuning Specialist",
     "https://www.upwork.com/jobs/~011bb2299ffee33001", "Upwork",
     "khuram.apply@mbs.co", "2026-09-15"),
    ("Zahid — ML Engineer", "Corvid Analytics", "NLP Engineer, Contract",
     "https://www.upwork.com/jobs/~01ccdd4411aa99bb22", "Upwork",
     "zahid.apply@mbs.co", "2026-09-15"),
    ("Hamza — Full Stack", "Halcyon Systems", "Full Stack Developer (React/Node)",
     "https://www.linkedin.com/jobs/view/4123998877", "LinkedIn",
     "hamza.apply@mbs.co", "2026-09-14"),
    ("Hamza — Full Stack", "Marlow Digital", "Senior TypeScript Engineer",
     "https://www.linkedin.com/jobs/view/4088112233", "LinkedIn",
     "hamza.apply@mbs.co", "2026-09-16"),
    ("Noor — Frontend", "Tidewater Studio", "Next.js Developer",
     "https://www.linkedin.com/jobs/view/4155667788", "LinkedIn",
     "noor.apply@mbs.co", "2026-09-15"),
    ("Noor — Frontend", "Aperture Retail", "Frontend Engineer, Design Systems",
     "https://www.indeed.com/viewjob?jk=9f3a7c21b8e4d055", "Indeed",
     "noor.apply@mbs.co", "2026-09-16"),
]


def main() -> None:
    if "--reset" in sys.argv:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "mbs.db")
        if os.path.exists(path):
            os.remove(path)
            print(f"removed {path}")

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(User).count():
            print("Already seeded. Run with --reset to start over.")
            return

        users: dict[str, User] = {}
        for name, email, password, role in PEOPLE:
            user = User(name=name, email=email, role=role,
                        password_hash=hash_password(password))
            db.add(user)
            users[email] = user
        db.flush()

        profiles: dict[str, Profile] = {}
        for name, headline, platform, skills, holder in PROFILES:
            profile = Profile(name=name, headline=headline, platform=platform,
                              skills=skills,
                              user_id=users[holder].id if holder else None)
            db.add(profile)
            db.flush()
            # Each new identity picks up whatever the earlier ones have already
            # found, exactly as it would on a real Tuesday.
            dispatch.backfill(db, profile)
            profiles[name] = profile

        for owner, company, title, url, platform, email, date in FINDS:
            dispatch.log_find(db, profiles[owner], {
                "company": company, "title": title, "url": url,
                "platform": platform, "email": email, "applied_on": date,
            })

        # One profile works through some of what it was handed, so the screens
        # open with all three states on them rather than a wall of "waiting".
        worked = profiles["Noor — Frontend"]
        handed = dispatch.others_jobs(db, worked.id, "pending")
        from app.models import Assignment  # local: only this block needs it
        for index, row in enumerate(handed[:4]):
            assignment = db.get(Assignment, row["assignment_id"])
            dispatch.set_status(db, assignment,
                                "applied" if index % 2 == 0 else "skipped")

        db.commit()

    print("Seeded MBS.")
    print("  manager@mbs.co / manager")
    print("  ayesha@mbs.co  / mbs   (2 profiles)")
    print("  bilal@mbs.co   / mbs   (1 profile)")
    print("  sana@mbs.co    / mbs   (1 profile)")


if __name__ == "__main__":
    main()
