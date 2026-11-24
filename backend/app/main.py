"""NetraCare clinic API. Roles are enforced HERE on every request, not in the frontend."""
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import config, db, rules, service
from .rules import Refusal

VisitType = Literal["new", "follow_up"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Appointments start empty (data pack README). NETRACARE_SEED_APPOINTMENTS=1 loads stretch/appointments_seed.csv.
    db.init_db(with_seed_appointments=os.environ.get("NETRACARE_SEED_APPOINTMENTS") == "1")
    yield


app = FastAPI(title="NetraCare Clinic API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Refusal)
async def refusal_handler(request: Request, exc: Refusal):
    return JSONResponse(status_code=exc.http_status, content={"detail": exc.as_dict()})


# ---------- dependencies ----------
def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


class User(BaseModel):
    role: Literal["patient", "staff", "doctor"]
    name: str
    patient_id: Optional[str] = None
    doctor_id: Optional[str] = None


def current_user(authorization: str = Header(default=""), conn: sqlite3.Connection = Depends(get_conn)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    row = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone() if token else None
    if row is None:
        raise Refusal("NOT_LOGGED_IN", "Please log in first.", http_status=401)
    return User(role=row["role"], name=row["name"], patient_id=row["patient_id"], doctor_id=row["doctor_id"])


def require(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise Refusal("FORBIDDEN", f"This action is not available to the {user.role} role.", http_status=403)
        return user
    return dep


# ---------- schemas ----------
class LoginIn(BaseModel):
    role: Literal["patient", "staff", "doctor"]
    name: Optional[str] = None
    mobile: Optional[str] = None
    doctor_id: Optional[str] = None


class BookIn(BaseModel):
    patient_id: Optional[str] = None  # staff only; a patient always books for themselves
    doctor_id: str
    speciality: str
    visit_type: VisitType = "new"
    date: str
    start_time: str


class RescheduleIn(BaseModel):
    doctor_id: str
    speciality: str
    visit_type: VisitType = "new"
    date: str
    start_time: str


# ---------- routes ----------
@app.get("/health")
def health():
    return {"ok": True, "clinic_now": config.clinic_now().isoformat(timespec="minutes")}


@app.post("/login")
def login(body: LoginIn, conn: sqlite3.Connection = Depends(get_conn)):
    if body.role == "patient":
        token, p = service.login_patient(conn, body.mobile or "", body.name or "")
        user = {"role": "patient", "name": p["name"], "patient_id": p["patient_id"]}
    elif body.role == "doctor":
        token, d = service.login_doctor(conn, body.doctor_id or "")
        user = {"role": "doctor", "name": d["name"], "doctor_id": d["doctor_id"]}
    else:
        token, name = service.login_staff(conn, body.name or "")
        user = {"role": "staff", "name": name}
    return {"token": token, "user": user}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return user


@app.get("/doctors")
def doctors(conn: sqlite3.Connection = Depends(get_conn)):
    """Public: the doctor list is also what the doctor login screen shows."""
    return [{"doctor_id": r["doctor_id"], "name": r["name"], "specialities": r["specialities"].split(";")}
            for r in conn.execute("SELECT * FROM doctors ORDER BY doctor_id")]


@app.get("/schedule")
def schedule(user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
    return [dict(r) for r in conn.execute("SELECT * FROM weekly_schedule ORDER BY doctor_id")]


@app.get("/holidays")
def holidays(user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
    return [dict(r) for r in conn.execute("SELECT * FROM holidays ORDER BY date")]


@app.get("/patients")
def patients(user: User = Depends(require("staff")), conn: sqlite3.Connection = Depends(get_conn)):
    """Staff only: needed to book for a walk-in."""
    return [dict(r) for r in conn.execute("SELECT patient_id, name, mobile FROM patients ORDER BY patient_id")]


class NewPatientIn(BaseModel):
    name: str
    mobile: str


@app.post("/patients", status_code=201)
def create_patient(body: NewPatientIn, user: User = Depends(require("staff")),
                   conn: sqlite3.Connection = Depends(get_conn)):
    """Staff only: register a brand-new walk-in so they can be booked."""
    p = service.create_patient(conn, body.mobile, body.name)
    return {"patient_id": p["patient_id"], "name": p["name"], "mobile": p["mobile"]}


@app.get("/slots")
def slots(doctor_id: str, date: str, speciality: str, visit_type: VisitType = "new",
          user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
    times = rules.free_slots(conn, doctor_id, speciality, visit_type, date)
    return {"doctor_id": doctor_id, "date": date, "speciality": speciality, "visit_type": visit_type,
            "duration_minutes": config.DURATION[visit_type], "slots": times}


APPT_SELECT = ("SELECT a.*, d.name AS doctor_name, p.name AS patient_name, p.mobile AS patient_mobile, "
               "(SELECT status FROM approvals ap WHERE ap.appointment_id = a.appointment_id ORDER BY approval_id DESC LIMIT 1) AS approval_status, "
               "(SELECT action FROM approvals ap WHERE ap.appointment_id = a.appointment_id ORDER BY approval_id DESC LIMIT 1) AS approval_action "
               "FROM appointments a JOIN doctors d USING(doctor_id) JOIN patients p USING(patient_id)")


def _appt_out(r: sqlite3.Row, user: User) -> dict:
    out = dict(r)
    if user.role == "patient":
        out.pop("patient_mobile", None)
    return out


@app.get("/appointments")
def list_appointments(date: Optional[str] = None, doctor_id: Optional[str] = None, status: Optional[str] = None,
                      user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)):
    where, args = [], []
    if user.role == "patient":  # forced by the backend: a patient can only ever list their own
        where.append("a.patient_id = ?"); args.append(user.patient_id)
    elif user.role == "doctor":
        where.append("a.doctor_id = ?"); args.append(user.doctor_id)
    elif doctor_id:
        where.append("a.doctor_id = ?"); args.append(doctor_id)
    if date:
        where.append("a.date = ?"); args.append(date)
    if status:
        where.append("a.status = ?"); args.append(status)
    sql = APPT_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY a.date, a.start_time"
    return [_appt_out(r, user) for r in conn.execute(sql, args)]


def _one(conn, appointment_id, user):
    r = conn.execute(APPT_SELECT + " WHERE a.appointment_id = ?", (appointment_id,)).fetchone()
    return _appt_out(r, user)


@app.post("/appointments", status_code=201)
def create_appointment(body: BookIn, user: User = Depends(require("patient", "staff")),
                       conn: sqlite3.Connection = Depends(get_conn)):
    if user.role == "patient":
        patient_id = user.patient_id  # any patient_id in the body is ignored
    else:
        if not body.patient_id:
            raise Refusal("PATIENT_REQUIRED", "Staff must choose which patient the booking is for.", http_status=422)
        patient_id = body.patient_id
    appt_id = service.book(conn, patient_id, body.doctor_id, body.speciality, body.visit_type, body.date, body.start_time)
    return _one(conn, appt_id, user)


@app.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: str, user: User = Depends(require("patient", "staff")),
                       conn: sqlite3.Connection = Depends(get_conn)):
    service.cancel(conn, appointment_id, user.role, user.patient_id)
    return _one(conn, appointment_id, user)


@app.post("/appointments/{appointment_id}/reschedule")
def reschedule_appointment(appointment_id: str, body: RescheduleIn, user: User = Depends(require("patient", "staff")),
                           conn: sqlite3.Connection = Depends(get_conn)):
    new_id = service.reschedule(conn, appointment_id, user.role, user.patient_id, body.doctor_id,
                                body.speciality, body.visit_type, body.date, body.start_time)
    return _one(conn, new_id, user)


@app.post("/appointments/{appointment_id}/complete")
def complete_appointment(appointment_id: str, user: User = Depends(require("doctor")),
                         conn: sqlite3.Connection = Depends(get_conn)):
    service.complete(conn, appointment_id, user.doctor_id)
    return _one(conn, appointment_id, user)


# ---------- stretch: Staff approval queue ----------
@app.get("/staff/approvals")
def staff_approvals(include_decided: bool = False, user: User = Depends(require("staff")), conn: sqlite3.Connection = Depends(get_conn)):
    return service.list_approvals(conn, include_decided)


@app.post("/staff/approvals/{approval_id}/approve")
def staff_approve(approval_id: int, user: User = Depends(require("staff")), conn: sqlite3.Connection = Depends(get_conn)):
    return service.approve_request(conn, approval_id, user.name)


@app.post("/staff/approvals/{approval_id}/reject")
def staff_reject(approval_id: int, user: User = Depends(require("staff")), conn: sqlite3.Connection = Depends(get_conn)):
    return service.reject_request(conn, approval_id, user.name)


# ---------- stretch: Staff can add holidays and edit a doctor's weekly schedule ----------
class HolidayIn(BaseModel):
    date: str
    name: str


class ScheduleIn(BaseModel):
    doctor_id: str
    day: Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    session: Literal["AM", "PM"]
    status: Literal["OPD", "SURGERY", "OFF"]


@app.post("/holidays", status_code=201)
def add_holiday(body: HolidayIn, user: User = Depends(require("staff")), conn: sqlite3.Connection = Depends(get_conn)):
    return service.add_holiday(conn, body.date, body.name)


@app.delete("/holidays/{date}")
def remove_holiday(date: str, user: User = Depends(require("staff")), conn: sqlite3.Connection = Depends(get_conn)):
    service.remove_holiday(conn, date)
    return {"removed": date}


@app.put("/schedule")
def edit_schedule(body: ScheduleIn, user: User = Depends(require("staff")), conn: sqlite3.Connection = Depends(get_conn)):
    return service.set_schedule(conn, body.doctor_id, body.day, body.session, body.status)


# ---------- stretch: week view calendar for each doctor ----------
@app.get("/calendar")
def calendar(doctor_id: Optional[str] = None, date: Optional[str] = None, user: User = Depends(require("staff", "doctor")),
             conn: sqlite3.Connection = Depends(get_conn)):
    """Staff may open any doctor's week; a doctor only their own (any doctor_id they send is ignored)."""
    target = user.doctor_id if user.role == "doctor" else doctor_id
    if not target:
        raise Refusal("DOCTOR_REQUIRED", "Choose a doctor.", http_status=422)
    return service.week_calendar(conn, target, date or config.clinic_now().date().isoformat(), show_patients=True)
