"""Filter für die Einrichtung der Servarr-Apps über ihre APIs."""


def arr_from_schema(schema, implementation, values, **extra):
    """Eintrag aus einem *arr-Schema (z. B. /api/v3/downloadclient/schema) übernehmen
    und nur die genannten Felder setzen. So bleiben neue oder umbenannte Felder der
    App bei ihren Standardwerten, statt dass wir ein festes Format nachbauen."""
    item = next((s for s in schema if s.get("implementation") == implementation), None)
    if item is None:
        raise ValueError(f"Implementierung {implementation} nicht im Schema")
    item = dict(item)
    item["fields"] = [
        dict(f, value=values[f["name"]]) if f["name"] in values else f
        for f in item.get("fields", [])
    ]
    missing = set(values) - {f["name"] for f in item["fields"]}
    if missing:
        raise ValueError(f"Felder {sorted(missing)} nicht im Schema von {implementation}")
    item.update(extra)
    return item


class FilterModule:
    def filters(self):
        return {"arr_from_schema": arr_from_schema}
