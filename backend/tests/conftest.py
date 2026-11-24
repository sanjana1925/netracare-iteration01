import csv
import os
import shutil
import pytest
from fastapi.testclient import TestClient

from helpers import CLINIC_NOW, DATA


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    """One database loaded from the data pack + seed appointments. Each test gets a fresh copy."""
    path = tmp_path_factory.mktemp("tpl") / "template.db"
    os.environ["NETRACARE_DB"] = str(path)
    os.environ["CLINIC_NOW"] = CLINIC_NOW
    from app import db
    db.init_db(with_seed_appointments=True)
    return path


@pytest.fixture()
def client(template_db, tmp_path, monkeypatch):
    fresh = tmp_path / "test.db"
    shutil.copy(template_db, fresh)
    monkeypatch.setenv("NETRACARE_DB", str(fresh))
    monkeypatch.setenv("CLINIC_NOW", CLINIC_NOW)
    from app.main import app
    return TestClient(app)  # no `with`: lifespan is skipped, the DB is already loaded


@pytest.fixture(scope="session")
def patients():
    with open(DATA / "patients.csv", newline="", encoding="utf-8") as f:
        return {r["patient_id"]: r for r in csv.DictReader(f)}
