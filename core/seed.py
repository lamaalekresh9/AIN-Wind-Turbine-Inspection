from .extensions import db
from .models import Blade, Turbine, User

DEMO_USERS = [
    ("Admin User", "admin@ain.local", "Admin@123", "admin"),
    ("Sara Reviewer", "reviewer@ain.local", "Review@123", "reviewer"),
    ("Omar Inspector", "inspector@ain.local", "Inspect@123", "inspector"),
]

DEMO_TURBINES = [
    dict(code="DJ-WTG-07", name="Unit 7", site="Dumat Al Jandal Wind Farm", region="Al Jouf",
         latitude=29.81, longitude=39.87, manufacturer="Vestas", model="V150-4.2 MW",
         hub_height_m=105, rotor_diameter_m=150, commission_year=2021, status="operational"),
    dict(code="DJ-WTG-12", name="Unit 12", site="Dumat Al Jandal Wind Farm", region="Al Jouf",
         latitude=29.83, longitude=39.90, manufacturer="Vestas", model="V150-4.2 MW",
         hub_height_m=105, rotor_diameter_m=150, commission_year=2021, status="maintenance"),
    dict(code="YB-WTG-03", name="Unit 3", site="Yanbu Wind Project", region="Madinah",
         latitude=24.09, longitude=38.06, manufacturer="Siemens Gamesa", model="SG 5.0-145",
         hub_height_m=110, rotor_diameter_m=145, commission_year=2025, status="operational"),
]


def seed_if_empty(app, force=False):
    if not force and (not app.config.get("SEED_DEMO_DATA") or User.query.first()):
        return
    for name, email, pw, role in DEMO_USERS:
        if not User.query.filter_by(email=email).first():
            u = User(name=name, email=email, role=role, organization="Ain Demo")
            u.set_password(pw)
            db.session.add(u)
    for t in DEMO_TURBINES:
        if Turbine.query.filter_by(code=t["code"]).first():
            continue
        tb = Turbine(**t)
        L = round(t["rotor_diameter_m"] / 2 - 2, 1)
        for pos in "ABC":
            tb.blades.append(Blade(position=pos, serial=f"{t['code']}-{pos}", length_m=L,
                                   material="Glass-fibre reinforced epoxy", manufacturer=t["manufacturer"],
                                   install_year=t["commission_year"]))
        db.session.add(tb)
    db.session.commit()
