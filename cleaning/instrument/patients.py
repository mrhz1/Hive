COUNTRIES = {"CAN": "Canada", "CA": "Canada", "USA": "United States", "US": "United States"}


def clean(table, rows):
    for row in rows:
        for key, value in row.items():
            if isinstance(value, str):
                row[key] = " ".join(value.split())
        country = row.get("country") or ""
        row["country"] = COUNTRIES.get(country.upper(), country)
    return rows
