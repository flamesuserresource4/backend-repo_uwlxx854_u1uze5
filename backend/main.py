import os
from datetime import datetime, date
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from bson import ObjectId

from database import create_document, get_documents, db
from schemas import (
    User as UserSchema,
    Subject as SubjectSchema,
    Enrollment as EnrollmentSchema,
    Attendance as AttendanceSchema,
    Bill as BillSchema,
)

app = FastAPI(title="Enrollment System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Enrollment System API running"}


# ---------- Auth (demo) ----------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@app.post("/auth/login")
def login(payload: LoginRequest):
    users = list(db["user"].find({"email": payload.email})) if db else []
    if not users:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user = users[0]
    if user.get("password") != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user["_id"] = str(user["_id"])  # stringify id for frontend
    return {"user": {k: v for k, v in user.items() if k != "password"}}


# ---------- Users (Admin) ----------
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    role: str
    password: str


@app.post("/users")
def create_user(payload: UserCreate):
    if db["user"].find_one({"email": payload.email}):
        raise HTTPException(status_code=400, detail="Email already in use")
    uid = create_document("user", payload.model_dump() | {"is_active": True})
    return {"id": uid}


@app.get("/users")
def list_users(role: Optional[str] = None):
    filt = {"role": role} if role else {}
    docs = get_documents("user", filt)
    for d in docs:
        d["_id"] = str(d["_id"])
        if "password" in d:
            del d["password"]
    return {"items": docs}


# ---------- Subjects ----------
@app.post("/subjects")
def create_subject(subject: SubjectSchema):
    sid = create_document("subject", subject)
    return {"id": sid}


@app.get("/subjects")
def list_subjects(faculty_id: Optional[str] = None):
    filt = {"faculty_id": faculty_id} if faculty_id else {}
    docs = get_documents("subject", filt)
    for d in docs:
        d["_id"] = str(d["_id"])  
    return {"items": docs}


@app.get("/subjects/{subject_id}")
def get_subject(subject_id: str):
    try:
        doc = db["subject"].find_one({"_id": ObjectId(subject_id)})
        if not doc:
            raise HTTPException(status_code=404, detail="Subject not found")
        doc["_id"] = str(doc["_id"]) 
        return doc
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid subject id")


# ---------- Enrollments ----------
@app.post("/enrollments")
def create_enrollment(enr: EnrollmentSchema):
    # prevent duplicate enrollment for same student/subject/semester
    existing = list(db["enrollment"].find({
        "student_id": enr.student_id,
        "subject_id": enr.subject_id,
        "semester": enr.semester,
    }))
    if existing:
        raise HTTPException(status_code=400, detail="Already enrolled")

    eid = create_document("enrollment", enr)

    # Billing: compute subject fee if available and upsert into student's bill
    fee = 0.0
    try:
        subject = db["subject"].find_one({"_id": ObjectId(enr.subject_id)})
        if subject:
            units = float(subject.get("units", 0))
            fee_per_unit = float(subject.get("fee_per_unit", 0))
            fee = units * fee_per_unit
    except Exception:
        subject = None

    bill = db["bill"].find_one({"student_id": enr.student_id, "semester": enr.semester})
    if not bill:
        bill_doc = BillSchema(student_id=enr.student_id, semester=enr.semester, lines=[], total=0, paid=0, status="unpaid")
        bill_id = create_document("bill", bill_doc)
        bill = db["bill"].find_one({"_id": ObjectId(bill_id)})

    # Add bill line and recompute totals
    line = {"subject_id": enr.subject_id, "description": "Tuition for subject", "amount": fee}
    db["bill"].update_one({"_id": bill["_id"]}, {"$push": {"lines": line}, "$set": {"updated_at": datetime.utcnow()}})
    bill = db["bill"].find_one({"_id": bill["_id"]})
    total = sum(float(l.get("amount", 0)) for l in bill.get("lines", []))
    status = "paid" if float(bill.get("paid", 0)) >= total and total > 0 else ("partial" if float(bill.get("paid", 0)) > 0 else "unpaid")
    db["bill"].update_one({"_id": bill["_id"]}, {"$set": {"total": total, "status": status}})

    return {"id": eid}


@app.get("/enrollments")
def list_enrollments(student_id: Optional[str] = None, subject_id: Optional[str] = None, semester: Optional[str] = None):
    filt = {}
    if student_id:
        filt["student_id"] = student_id
    if subject_id:
        filt["subject_id"] = subject_id
    if semester:
        filt["semester"] = semester
    docs = get_documents("enrollment", filt)
    for d in docs:
        d["_id"] = str(d["_id"]) 
    return {"items": docs}


# ---------- Attendance (Faculty) ----------
class AttendanceCreate(BaseModel):
    subject_id: str
    faculty_id: str
    session_date: date
    records: List[dict]


@app.post("/attendance")
def create_attendance(payload: AttendanceCreate):
    aid = create_document("attendance", payload.model_dump())
    return {"id": aid}


@app.get("/attendance")
def list_attendance(subject_id: Optional[str] = None, faculty_id: Optional[str] = None):
    filt = {}
    if subject_id:
        filt["subject_id"] = subject_id
    if faculty_id:
        filt["faculty_id"] = faculty_id
    docs = get_documents("attendance", filt)
    for d in docs:
        d["_id"] = str(d["_id"]) 
    return {"items": docs}


# ---------- Billing (Student/Cashier) ----------
@app.get("/bills")
def list_bills(student_id: Optional[str] = None, status: Optional[str] = None):
    filt = {}
    if student_id:
        filt["student_id"] = student_id
    if status:
        filt["status"] = status
    docs = get_documents("bill", filt)
    for d in docs:
        d["_id"] = str(d["_id"]) 
    return {"items": docs}


class PaymentCreate(BaseModel):
    bill_id: str
    amount: float
    cashier_id: str


@app.post("/payments")
def create_payment(payload: PaymentCreate):
    bill = db["bill"].find_one({"_id": ObjectId(payload.bill_id)})
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    pid = create_document("payment", {"bill_id": payload.bill_id, "amount": payload.amount, "cashier_id": payload.cashier_id, "paid_at": datetime.utcnow()})
    paid = float(bill.get("paid", 0)) + float(payload.amount)
    status = "paid" if paid >= float(bill.get("total", 0)) and float(bill.get("total", 0)) > 0 else ("partial" if paid > 0 else "unpaid")
    db["bill"].update_one({"_id": bill["_id"]}, {"$set": {"paid": paid, "status": status, "updated_at": datetime.utcnow()}})
    return {"id": pid}


# ---------- Utilities ----------
@app.get("/schema")
def get_schema():
    # Expose schemas to the database viewer if present
    return {"schemas": ["user", "subject", "enrollment", "attendance", "bill", "payment"]}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
