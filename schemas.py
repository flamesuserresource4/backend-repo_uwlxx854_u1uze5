"""
Database Schemas for Enrollment System

Each Pydantic model corresponds to a MongoDB collection:
- User -> "user"
- Subject -> "subject"
- Enrollment -> "enrollment"
- Attendance -> "attendance"
- Bill -> "bill"
- Payment -> "payment"

These models are used for validation and to power the database viewer.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Literal
from datetime import date, datetime

# User and Auth
class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Unique email address")
    role: Literal["admin", "student", "faculty", "cashier"] = Field(..., description="User role")
    password: str = Field(..., description="Hashed or demo password (do not store plain in production)")
    is_active: bool = Field(True, description="Whether the user is active")

# Academic domain
class Subject(BaseModel):
    code: str = Field(..., description="Subject code e.g., CS101")
    title: str = Field(..., description="Subject title")
    units: float = Field(..., ge=0, description="Number of units")
    fee_per_unit: float = Field(0, ge=0, description="Fee per unit for billing")
    faculty_id: Optional[str] = Field(None, description="Assigned faculty user id")

class Enrollment(BaseModel):
    student_id: str = Field(..., description="Student user id")
    subject_id: str = Field(..., description="Subject id")
    semester: str = Field(..., description="e.g., 2025-1")
    status: Literal["enrolled", "dropped", "completed"] = Field("enrolled")

class AttendanceRecord(BaseModel):
    student_id: str
    status: Literal["present", "absent", "late"] = "present"

class Attendance(BaseModel):
    subject_id: str
    faculty_id: str
    session_date: date
    records: List[AttendanceRecord]

class BillLine(BaseModel):
    subject_id: str
    description: str
    amount: float

class Bill(BaseModel):
    student_id: str
    semester: str
    lines: List[BillLine]
    total: float
    paid: float = 0
    status: Literal["unpaid", "partial", "paid"] = "unpaid"

class Payment(BaseModel):
    bill_id: str
    amount: float
    cashier_id: str
    paid_at: datetime
