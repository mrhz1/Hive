"""Patient endpoints, end to end through permissions -> router -> CRUD."""
from conftest import NOBODY_ID, VIEWER_ID, minimal_patient, patient_columns


# ------------------------------------------------------------ the shape

def test_model_exposes_every_requested_field(as_admin):
    """The full column set, verified through an actual response body."""
    created = as_admin.post("/patients", json=minimal_patient()).json()

    expected = {
        # provider / institution
        "instcode", "pname", "pemail", "phone1", "phone2", "wphone1", "wphone2",
        "street", "street2", "street3", "city", "state", "zip", "country",
        # patient
        "fstname", "lstname", "ptemail", "ptphone", "ptphone2", "ptwphone",
        "ptwphone2", "ptstreet", "ptstreet2", "ptstreet3", "ptcity", "ptstate",
        "ptzip", "ptcountry",
        # dates
        "dt_reg", "dt_b", "dt_d",
        # source documents
        "original_file_path", "de_identified_file_path",
        # lifecycle
        "id", "status", "is_active", "created_at",
    }
    assert set(created) == expected
    assert set(patient_columns()) == expected


def test_round_trips_every_field(as_admin):
    """Every one of the 37 columns survives write -> read unchanged.

    Not a column-order check -- see the KNOWN LIMIT in conftest.
    """
    payload = minimal_patient(
        instcode="INST001", pname="Springfield Clinic",
        pemail="clinic@example.com", phone1="+1 555 100 0001",
        phone2="+1 555 100 0002", wphone1="+1 555 200 0001",
        wphone2="+1 555 200 0002", street="1 Medical Plaza",
        street2="Suite 4", street3="Wing B", city="Springfield",
        state="IL", zip="62701", country="US",
        ptemail="jane@example.com", ptphone="+1 555 300 0001",
        ptphone2="+1 555 300 0002", ptwphone="+1 555 400 0001",
        ptwphone2="+1 555 400 0002", ptstreet="1 Elm St",
        ptstreet2="Apt 2", ptstreet3="Rear", ptcity="Shelbyville",
        ptstate="IL", ptzip="62702", ptcountry="US",
        dt_reg="2026-07-01", dt_b="1990-01-02", dt_d="2026-08-01",
        original_file_path="/data/in.pdf",
        de_identified_file_path="/data/in_deid.pdf",
        status="active", is_active=True,
    )
    created = as_admin.post("/patients", json=payload)
    assert created.status_code == 201, created.text

    fetched = as_admin.get(f"/patients/{created.json()['id']}").json()
    for field, value in payload.items():
        assert fetched[field] == value, f"{field} did not round-trip"


def test_provider_and_patient_blocks_stay_distinct(as_admin):
    """`street` and `ptstreet` are different columns -- a sed-style rename
    could easily collapse one onto the other."""
    created = as_admin.post(
        "/patients",
        json=minimal_patient(
            street="1 Provider Way", city="Springfield", zip="11111",
            ptstreet="1 Patient Way", ptcity="Shelbyville", ptzip="22222",
            phone1="+1111", ptphone="+2222",
            pemail="provider@example.com", ptemail="patient@example.com",
        ),
    ).json()

    assert created["street"] == "1 Provider Way"
    assert created["ptstreet"] == "1 Patient Way"
    assert created["city"] == "Springfield"
    assert created["ptcity"] == "Shelbyville"
    assert created["phone1"] == "+1111"
    assert created["ptphone"] == "+2222"
    assert created["pemail"] == "provider@example.com"
    assert created["ptemail"] == "patient@example.com"


# ------------------------------------------------------------- optional

def test_only_the_document_and_one_identifier_are_required(as_admin):
    response = as_admin.post("/patients", json=minimal_patient())
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["fstname"] == "Jane"
    # Everything else is unknown, and unknown is null -- including
    # lstname, which minimal_patient does not send.
    for field in ("lstname", "instcode", "pemail", "ptphone", "dt_b", "city", "ptcity"):
        assert body[field] is None


def test_any_one_identifier_satisfies_the_rule(as_admin):
    """fstname, lstname or ptemail -- the ingested systems disagree about
    which of them they populate, so any one has to be enough."""
    for identifier in (
        {"fstname": "Jane"},
        {"lstname": "Doe"},
        {"ptemail": "jane@example.com"},
    ):
        response = as_admin.post(
            "/patients", json={"original_file_path": "/data/x.pdf", **identifier}
        )
        assert response.status_code == 201, (identifier, response.text)


def test_a_patient_with_no_identifier_at_all_is_rejected(as_admin):
    response = as_admin.post(
        "/patients", json={"original_file_path": "/data/x.pdf", "ptcity": "Springfield"}
    )
    assert response.status_code == 422
    detail = str(response.json()["error"]["fields"])
    assert "fstname, lstname or ptemail" in detail, detail


def test_blank_identifiers_do_not_count_as_present(as_admin):
    """'' normalises to NULL, so a form submitted with the name fields
    cleared must be rejected rather than stored as a nameless row."""
    response = as_admin.post(
        "/patients",
        json={"original_file_path": "/data/x.pdf", "fstname": "  ", "lstname": ""},
    )
    assert response.status_code == 422


def test_missing_source_document_is_a_422_naming_the_field(as_admin):
    for payload in (
        {"fstname": "Jane"},
        {"fstname": "Jane", "original_file_path": ""},
        # Whitespace is not a path, and must not slip past a length check.
        {"fstname": "Jane", "original_file_path": "   "},
    ):
        response = as_admin.post("/patients", json=payload)
        assert response.status_code == 422, response.text
        fields = response.json()["error"]["fields"]
        assert any(f["loc"][-1] == "original_file_path" for f in fields), fields


def test_blank_strings_are_stored_as_null(as_admin):
    """A cleared HTML input submits ''. Storing that would make "unknown"
    two different values in Hive."""
    created = as_admin.post(
        "/patients",
        json=minimal_patient(instcode="   ", dt_b="", ptemail="", ptcity=""),
    ).json()

    assert created["instcode"] is None
    assert created["dt_b"] is None
    assert created["ptemail"] is None
    assert created["ptcity"] is None


# ---------------------------------------------------------------- dates

def test_dates_round_trip_as_iso_strings(as_admin):
    created = as_admin.post(
        "/patients",
        json=minimal_patient(dt_reg="2026-07-01", dt_b="1990-01-02", dt_d="2026-08-01"),
    ).json()

    assert created["dt_reg"] == "2026-07-01"
    assert created["dt_b"] == "1990-01-02"
    assert created["dt_d"] == "2026-08-01"


def test_date_columns_are_cast_in_sql(as_admin, cursor):
    """Hive will not coerce a bound STRING into a DATE column."""
    as_admin.post("/patients", json=minimal_patient(dt_b="1990-01-02"))

    insert = next(s for s, _ in cursor.statements if s.startswith("INSERT INTO `patients`"))
    assert "CAST(%s AS DATE)" in insert

    patient_id = as_admin.get("/patients").json()[0]["id"]
    as_admin.put(f"/patients/{patient_id}", json={"dt_d": "2026-08-01"})

    update = next(s for s, _ in cursor.statements if s.startswith("UPDATE `patients`"))
    assert "`dt_d` = CAST(%s AS DATE)" in update


def test_a_malformed_date_is_rejected(as_admin):
    response = as_admin.post("/patients", json=minimal_patient(dt_b="01/02/1990"))
    assert response.status_code == 422


# ------------------------------------------------------------ uniqueness

def test_patient_email_and_phone_stay_unique(as_admin):
    as_admin.post(
        "/patients", json=minimal_patient(ptemail="dup@example.com", ptphone="+1555")
    )

    clash = as_admin.post(
        "/patients", json=minimal_patient(fstname="Other", ptemail="dup@example.com")
    )
    assert clash.status_code == 409

    clash = as_admin.post(
        "/patients", json=minimal_patient(fstname="Other", ptphone="+1555")
    )
    assert clash.status_code == 409


def test_absent_contact_details_never_collide(as_admin):
    """Two patients with no email are not duplicates of each other."""
    assert as_admin.post("/patients", json=minimal_patient()).status_code == 201
    assert (
        as_admin.post("/patients", json=minimal_patient(fstname="John")).status_code
        == 201
    )


def test_saving_a_record_unchanged_does_not_conflict_with_itself(as_admin):
    created = as_admin.post(
        "/patients", json=minimal_patient(ptemail="jane@example.com", ptphone="+1555")
    ).json()

    response = as_admin.put(
        f"/patients/{created['id']}",
        json={"ptemail": "jane@example.com", "ptphone": "+1555", "ptcity": "Shelbyville"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["ptcity"] == "Shelbyville"


# ---------------------------------------------------------------- update

def test_update_touches_only_the_fields_sent(as_admin):
    created = as_admin.post(
        "/patients", json=minimal_patient(instcode="INST001", ptcity="Springfield")
    ).json()

    updated = as_admin.put(
        f"/patients/{created['id']}", json={"ptcity": "Shelbyville"}
    ).json()

    assert updated["ptcity"] == "Shelbyville"
    assert updated["instcode"] == "INST001"
    assert updated["fstname"] == "Jane"


def test_update_cannot_clear_the_last_identifier(as_admin):
    """The rule holds over the row the update leaves behind, not over the
    patch -- a patch clearing fstname is only invalid because nothing
    already stored would identify the row afterwards."""
    created = as_admin.post("/patients", json=minimal_patient()).json()

    response = as_admin.put(f"/patients/{created['id']}", json={"fstname": ""})
    assert response.status_code == 422
    assert "fstname, lstname or ptemail" in response.json()["error"]["detail"]

    # ... and the stored row is untouched.
    assert as_admin.get(f"/patients/{created['id']}").json()["fstname"] == "Jane"


def test_update_can_clear_an_identifier_while_another_remains(as_admin):
    created = as_admin.post(
        "/patients", json=minimal_patient(lstname="Doe")
    ).json()

    updated = as_admin.put(f"/patients/{created['id']}", json={"fstname": ""})
    assert updated.status_code == 200, updated.text
    assert updated.json()["fstname"] is None
    assert updated.json()["lstname"] == "Doe"


def test_update_cannot_clear_the_source_document(as_admin):
    created = as_admin.post("/patients", json=minimal_patient()).json()

    # Blank is refused by the field constraint, null by the merged check.
    assert (
        as_admin.put(
            f"/patients/{created['id']}", json={"original_file_path": ""}
        ).status_code
        == 422
    )
    response = as_admin.put(
        f"/patients/{created['id']}", json={"original_file_path": None}
    )
    assert response.status_code == 422
    assert "original_file_path" in response.json()["error"]["detail"]


def test_unknown_patient_is_a_404(as_admin):
    assert as_admin.get("/patients/nope").status_code == 404
    assert as_admin.put("/patients/nope", json={"ptcity": "X"}).status_code == 404
    assert as_admin.delete("/patients/nope").status_code == 404


def test_list_and_delete(as_admin):
    first = as_admin.post("/patients", json=minimal_patient()).json()
    as_admin.post("/patients", json=minimal_patient(fstname="John"))

    assert len(as_admin.get("/patients").json()) == 2

    assert as_admin.delete(f"/patients/{first['id']}").status_code == 204
    assert len(as_admin.get("/patients").json()) == 1


# ----------------------------------------------------------- permissions

def test_permissions_are_named_patients(as_admin):
    granted = as_admin.get("/me/permissions").json()
    assert "patient:view" in granted
    assert not any(p.startswith("customers:") for p in granted)


def test_reader_cannot_write(client):
    client.headers.update({"X-User-Id": VIEWER_ID})
    assert client.get("/patients").status_code == 200
    assert client.post("/patients", json=minimal_patient()).status_code == 403
    assert client.put("/patients/x", json={"ptcity": "X"}).status_code == 403
    assert client.delete("/patients/x").status_code == 403


def test_a_role_with_no_grants_is_locked_out(client):
    client.headers.update({"X-User-Id": NOBODY_ID})
    response = client.get("/patients")
    assert response.status_code == 403
    assert "patient:view" in response.json()["error"]["detail"]


def test_identity_is_required(client):
    assert client.get("/patients").status_code == 401


# ---------------------------------------------------------------- audit

def test_writes_are_audited_as_patient(as_admin, store):
    created = as_admin.post("/patients", json=minimal_patient()).json()
    as_admin.put(f"/patients/{created['id']}", json={"ptcity": "Shelbyville"})
    as_admin.delete(f"/patients/{created['id']}")

    entries = [e for e in store["audit_log"] if e["entity_type"] == "patient"]
    assert [e["action"] for e in entries] == ["CREATE", "UPDATE", "DELETE"]
    assert all(e["entity_id"] == created["id"] for e in entries)


def test_the_audit_snapshot_serialises_dates(as_admin, store):
    """model_dump(mode='json') has to run before the row hits Hive --
    a date object would not survive the JSON-in-STRING column."""
    import json

    as_admin.post("/patients", json=minimal_patient(dt_b="1990-01-02"))

    entry = store["audit_log"][0]
    assert json.loads(entry["new_values"])["dt_b"] == "1990-01-02"
