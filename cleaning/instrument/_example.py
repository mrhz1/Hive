COUNTRIES = {"CAN": "Canada", "CA": "Canada", "USA": "United States", "US": "United States"}


def clean(table, rows):
    for row in rows:
        country = (row.get("country") or "").strip()
        row["country"] = COUNTRIES.get(country.upper(), country)
    return rows
