def clean(table, rows):
    for row in rows:
        for key, value in row.items():
            if isinstance(value, str):
                row[key] = value.strip()
        row["modality"] = (row.get("modality") or "").upper()
    return rows
