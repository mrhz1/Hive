"""Example rule (ignored: the name starts with "_"). Copy it to
instrument/patients.py to use it.

Countries are typed in many ways by the sites; one spelling makes counting
by country possible.
"""

COUNTRIES = {"CAN": "Canada", "CA": "Canada", "USA": "United States", "US": "United States"}


def clean(table, rows):
    for row in rows:
        country = (row.get("country") or "").strip()
        row["country"] = COUNTRIES.get(country.upper(), country)
    return rows
