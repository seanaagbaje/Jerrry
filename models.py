from __future__ import annotations
from pydoc import text
from sqlalchemy import String, Integer, Date, DateTime, Enum, JSON, Text, Boolean, DECIMAL, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.mysql import TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, date, UTC
from database import Base


class Student(Base):
    __tablename__ = "Students"
    student_id:Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    enrollment_date:Mapped[Date] = mapped_column(Date)
    current_risk_level:Mapped[str | None] = mapped_column(Enum('low', 'medium', 'high'), default='low')
    prior_profile:Mapped[str | None]= mapped_column(Enum('early', 'mixed', 'lastminute'), default='mixed')
    days_active:Mapped[int] = mapped_column(Integer, default=0)
    created_at:Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    phone:Mapped[str | None] = mapped_column(String(20))
    profile_pic: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    bio: Mapped[str | None] = mapped_column(Text)
    admin_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("Admins.admin_id"), nullable=True, index=True)

    # Student
    tasks: Mapped[list["Task"]] = relationship(back_populates="student")

# Task


    @property
    def image_path(self) -> str:
        if self.profile_pic:
            if self.profile_pic.startswith("/") or self.profile_pic.startswith("http"):
                return self.profile_pic
            return f"/media/profile_pics/{self.profile_pic}"
        return "https://ui-avatars.com/api/?name=User&background=136dec&color=fff"


class Admin(Base):
    __tablename__ = "Admins"
    admin_id: Mapped[int]= mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash:Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None]= mapped_column(String(100))
    invite_code: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True, index=True)
    access_level: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime | None]= mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class WeeklyBundle(Base):
    __tablename__ = "WeeklyBundles"
    bundle_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("Students.student_id"), index=True)
    week_number:Mapped[int]  = mapped_column(Integer)
    start_date: Mapped[Date] = mapped_column(Date)
    end_date: Mapped[Date] = mapped_column(Date)
    tasks_total:Mapped[int]  = mapped_column(Integer, default=0)
    tasks_completed:Mapped[int]  = mapped_column(Integer, default=0)
    tasks_late:Mapped[int]  = mapped_column(Integer, default=0)
    completion_rate:Mapped[float]= mapped_column(DECIMAL(4, 3), default=0.000)
    submitted_late: Mapped[int]  = mapped_column(TINYINT, default=0)
    is_closed: Mapped[int]  = mapped_column(TINYINT, default=0)
    closed_at: Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    created_at:Mapped[datetime | None]= mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Task(Base):
    __tablename__ = "Tasks"
    task_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("Students.student_id"), index=True)
    bundle_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("WeeklyBundles.bundle_id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at:Mapped[datetime | None]= mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    status:Mapped[str] = mapped_column(Enum('pending', 'in_progress', 'completed', 'overdue'), default='pending')
    task_type: Mapped[str] = mapped_column(String(20), default="personal")
    is_admin_assigned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_admin_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("Admins.admin_id"), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="tasks")


class Prediction(Base):
    __tablename__ = "Predictions"
    prediction_id:Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("Students.student_id"), index=True)
    bundle_id:  Mapped[int | None] = mapped_column(Integer, ForeignKey("WeeklyBundles.bundle_id"), nullable=True, index=True)
    prediction_date:Mapped[Date] = mapped_column(Date)
    model_used: Mapped[str]  = mapped_column(Enum('3window', '7window'))
    risk_level: Mapped[str]  = mapped_column(Enum('low', 'medium', 'high'))
    confidence_score: Mapped[float]= mapped_column(DECIMAL(3, 2))
    attention_weights_json: Mapped[dict | None]    = mapped_column(JSON, nullable=True)
    features_json: Mapped[dict | None]    = mapped_column(JSON, nullable=True)


class Survey(Base):
    __tablename__ = "Surveys"
    survey_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("Students.student_id"), index=True)
    responses_json: Mapped[dict] = mapped_column(JSON)
    completion_date:Mapped[datetime | None]= mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class BehavioralLog(Base):
    __tablename__ = "BehavioralLogs"
    log_id:Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("Students.student_id"), index=True)
    login_time: Mapped[datetime]= mapped_column(DateTime(timezone=True))
    logout_time: Mapped[datetime | None]= mapped_column(DateTime(timezone=True), nullable=True)
    pages_visited: Mapped[int] = mapped_column(Integer, default=0)
    session_duration: Mapped[int | None]     = mapped_column(Integer, nullable=True)


class MCIIIntervention(Base):
    __tablename__ = "MCIIInterventions"
    intervention_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("Predictions.prediction_id"), index=True, nullable=True)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("Students.student_id"),index=True)
    prompt_text: Mapped[str] = mapped_column(Text)
    delivery_time: Mapped[datetime | None]= mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    user_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    was_helpful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


    