from datetime import datetime, date
from typing import Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class RegisterIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: Literal["patient", "caregiver", "clinician"] = "patient"
    accept_terms: bool
    locale: str = Field(default="en", max_length=16)
    timezone: str = Field(default="UTC", max_length=64)

class LoginIn(Strict):
    email: EmailStr
    password: str = Field(max_length=128)
    totp: str | None = Field(default=None, max_length=10)

class RefreshIn(Strict):
    refresh_token: str = Field(max_length=200)

class MfaCodeIn(Strict):
    code: str = Field(min_length=6, max_length=10)

class PatientIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    date_of_birth: date | None = None
    sex: str = Field(default="", max_length=20)
    notes: str = Field(default="", max_length=5000)
    emergency_contact: str = Field(default="", max_length=500)

class PatientUpdate(Strict):
    name: str | None = Field(default=None, max_length=120)
    date_of_birth: date | None = None
    sex: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=5000)
    emergency_contact: str | None = Field(default=None, max_length=500)

class GrantIn(Strict):
    grantee_email: EmailStr
    relationship: Literal["caregiver", "clinician", "family"]
    scopes: list[str] | None = None
    expires_at: datetime | None = None

class ConsentIn(Strict):
    kind: Literal["data_sharing", "ai_processing", "notifications", "research"]
    granted: bool
    policy_version: str = Field(max_length=20)
    detail: str = Field(default="", max_length=1000)

class AllergyIn(Strict):
    substance: str = Field(min_length=1, max_length=160)
    reaction: str = Field(default="", max_length=1000)
    severity: Literal["mild", "moderate", "severe", "unknown"] = "unknown"

class ConditionIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(default="", max_length=40)
    status: Literal["active", "resolved"] = "active"
    onset_date: date | None = None

class MedicationIn(Strict):
    patient_id: int
    name: str = Field(min_length=1, max_length=160)
    dose: str = Field(min_length=1, max_length=100)
    route: str = Field(default="oral", max_length=40)
    frequency: str = Field(min_length=1, max_length=100)
    schedule_times: str = Field(default="", max_length=200, pattern=r"^(\d{2}:\d{2})?(,\d{2}:\d{2})*$")
    instructions: str = Field(default="", max_length=2000)
    prescriber: str = Field(default="", max_length=160)
    start_date: date | None = None
    end_date: date | None = None

class MedicationUpdate(Strict):
    dose: str | None = Field(default=None, max_length=100)
    frequency: str | None = Field(default=None, max_length=100)
    schedule_times: str | None = Field(default=None, max_length=200, pattern=r"^(\d{2}:\d{2})?(,\d{2}:\d{2})*$")
    instructions: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "paused", "stopped"] | None = None
    end_date: date | None = None

class DoseIn(Strict):
    status: Literal["taken", "missed", "skipped", "delayed"]
    scheduled_at: datetime
    note: str = Field(default="", max_length=500)

class AppointmentIn(Strict):
    patient_id: int
    clinician: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=255)
    location: str = Field(default="", max_length=255)
    mode: Literal["in_person", "video", "phone"] = "in_person"
    scheduled_at: datetime
    duration_min: int = Field(default=30, ge=5, le=480)
    notes: str = Field(default="", max_length=2000)

class AppointmentUpdate(Strict):
    scheduled_at: datetime | None = None
    status: Literal["scheduled", "completed", "cancelled", "no_show"] | None = None
    notes: str | None = Field(default=None, max_length=2000)

READING_KINDS = Literal["heart_rate", "spo2", "temperature_c", "blood_pressure_systolic",
                        "blood_pressure_diastolic", "blood_glucose_mmol", "blood_glucose_mgdl",
                        "weight_kg", "respiratory_rate", "pain_score"]

class ReadingIn(Strict):
    patient_id: int
    kind: READING_KINDS
    value: float = Field(ge=-50, le=1000)
    unit: str = Field(max_length=30)
    context: str = Field(default="", max_length=40)
    recorded_at: datetime | None = None

class ThresholdIn(Strict):
    kind: READING_KINDS
    low: float | None = None
    high: float | None = None

class NoteIn(Strict):
    kind: Literal["progress", "soap", "discharge", "care_plan"] = "progress"
    body: str = Field(min_length=1, max_length=20000)
    appointment_id: int | None = None

class TaskIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    assignee_id: int | None = None
    due_at: datetime | None = None

class TaskUpdate(Strict):
    status: Literal["open", "done", "cancelled"]

class AIRequest(Strict):
    patient_id: int
    question: str = Field(min_length=1, max_length=1500)

class AdminUserUpdate(Strict):
    is_active: bool | None = None
    is_verified_clinician: bool | None = None
    role: Literal["patient", "caregiver", "clinician", "admin"] | None = None

class BreakGlassIn(Strict):
    patient_id: int
    reason: str = Field(min_length=20, max_length=1000)
