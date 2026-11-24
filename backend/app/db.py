"""SQLite schema, connection helper and CSV loader (requirement R1)."""
import csv
import sqlite3
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS doctors (
  doctor_id TEXT PRIMARY KEY, name TEXT NOT NULL, specialities TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS weekly_schedule (
  doctor_id TEXT NOT NULL REFERENCES doctors(doctor_id),
  day TEXT NOT NULL, session TEXT NOT NULL, status TEXT NOT NULL,
  PRIMARY KEY (doctor_id, day, session));
CREATE TABLE IF NOT EXISTS holidays (date TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS patients (
  patient_id TEXT PRIMARY KEY, name TEXT NOT NULL,
  mobile TEXT NOT NULL UNIQUE, year_of_birth INTEGER);
CREATE TABLE IF NOT EXISTS appointments (
  appointment_id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  doctor_id TEXT NOT NULL REFERENCES doctors(doctor_id),
  speciality TEXT NOT NULL, visit_type TEXT NOT NULL,
  date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('booked','cancelled','completed')));
CREATE INDEX IF NOT EXISTS idx_appt_doctor_date ON appointments(doctor_id, date);
CREATE INDEX IF NOT EXISTS idx_appt_patient ON appointments(patient_id);
CREATE TABLE IF NOT EXISTS approvals (              -- stretch goal: Staff approval queue for a patient's late cancel / reschedule
  approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
  appointment_id TEXT NOT NULL REFERENCES appointments(appointment_id),
  patient_id TEXT NOT NULL REFERENCES patients(patient_id),
  action TEXT NOT NULL CHECK (action IN ('cancel','reschedule')),
  new_doctor_id TEXT, new_speciality TEXT, new_visit_type TEXT, new_date TEXT, new_start_time TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  created_at TEXT NOT NULL, decided_at TEXT, decided_by TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, role TEXT NOT NULL, patient_id TEXT, doctor_id TEXT, name TEXT NOT NULL);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path(), isolation_level=None, timeout=10,
                           check_same_thread=False)  # manual transactions. FastAPI may create the per-request connection in one worker thread and use it in another; each request has its OWN connection and uses it one step at a time, so this is safe
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _rows(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def init_db(with_seed_appointments: bool = False) -> None:
    """Create tables and load the data pack if the database is empty. Safe to call on every startup."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0:
            d = config.DATA_DIR
            conn.execute("BEGIN")
            conn.executemany("INSERT INTO doctors VALUES (:doctor_id,:name,:specialities)", _rows(d / "doctors.csv"))
            conn.executemany("INSERT INTO weekly_schedule VALUES (:doctor_id,:day,:session,:status)", _rows(d / "weekly_schedule.csv"))
            conn.executemany("INSERT INTO holidays VALUES (:date,:name)", _rows(d / "holidays.csv"))
            conn.executemany("INSERT INTO patients VALUES (:patient_id,:name,:mobile,:year_of_birth)", _rows(d / "patients.csv"))
            conn.execute("COMMIT")
        if with_seed_appointments and conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0:
            conn.execute("BEGIN")
            conn.executemany(
                "INSERT INTO appointments VALUES (:appointment_id,:patient_id,:doctor_id,:speciality,:visit_type,"
                ":date,:start_time,:end_time,:status)",
                _rows(config.DATA_DIR / "stretch" / "appointments_seed.csv"))
            conn.execute("COMMIT")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("Database ready at", config.db_path())
