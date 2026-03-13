from fastapi import FastAPI, Request, Depends, Form, HTTPException, status, UploadFile, File
from fastapi.templating import Jinja2Templates # serve templates to the client
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware  
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import numpy as np
import os
import secrets
import string
import hashlib
import json
import pickle
import random
import uuid
import logging

from anthropic import Anthropic
from apscheduler.schedulers.background import BackgroundScheduler

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
import tensorflow as tf
import uvicorn
from schemas import SignupRequest, LoginRequest, TaskCreate, TaskUpdate, ProfileUpdate, MCIIMessage, PredictionRequest, PredictionResponse
from dotenv import load_dotenv


load_dotenv()
from database import Base, engine, SessionLocal, get_db
from models import Student, Admin, Task, WeeklyBundle, Prediction, MCIIIntervention, BehavioralLog, Survey
import tensorflow as tf
from datetime import datetime, timedelta


# ── Directory configuration 
BASE_DIR    = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR  = BASE_DIR / "static"
MODEL_DIR   = BASE_DIR / "models" / "saved_models"

templates = Jinja2Templates(directory=TEMPLATE_DIR) # templates directory
logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise ValueError("ANTHROPIC_API_KEY is not set")

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

scheduler = BackgroundScheduler(timezone="UTC")

# attention
class BahdanauAttention(tf.keras.layers.Layer):
    def __init__(self, units, **kwargs):
        super(BahdanauAttention, self).__init__(**kwargs)
        self.units = units
        self.W1 = tf.keras.layers.Dense(units, use_bias=False)
        self.V = tf.keras.layers.Dense(1, use_bias=False)

    def call(self, encoder_output):
        score = self.V(tf.nn.tanh(self.W1(encoder_output)))
        attention_weights = tf.nn.softmax(score, axis=1)
        context_vector = attention_weights * encoder_output
        context_vector = tf.reduce_sum(context_vector, axis=1)
        return context_vector, attention_weights

    def get_config(self):
        config = super().get_config()
        config.update({"units": self.units})
        return config

model_3window = None
model_7window = None
scaler_3window = None
scaler_7window = None
prior_profiles: Dict[str, Any] = {}
feature_config: Dict[str, Any] = {}

try:
    custom_objects = {
    'Orthogonal': tf.keras.initializers.Orthogonal,
    'BahdanauAttention': BahdanauAttention
    }

    model_3window = tf.keras.models.load_model(
        MODEL_DIR / "bilstm_3window.h5",
        custom_objects=custom_objects,
        compile=False
    )
    model_7window = tf.keras.models.load_model(
        MODEL_DIR / "bilstm_7window.h5",
        custom_objects=custom_objects,
        compile=False
    )
    with open(MODEL_DIR / "scaler_3window.pkl", "rb") as f:
        scaler_3window = pickle.load(f)
    with open(MODEL_DIR / "scaler_7window.pkl", "rb") as f:
        scaler_7window = pickle.load(f)
    with open(MODEL_DIR / "prior_profiles.json", "r") as f:
        prior_profiles = json.load(f)
    with open(MODEL_DIR / "feature_config.json", "r") as f:
        feature_config = json.load(f)

    print(" All ML artifacts loaded")

except Exception as e:
    print(f"Could not load ML artifacts: {e}")



def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── Auth helpers 

def require_login(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    return user

def require_student(request: Request) -> dict:
    user = require_login(request)
    if user["role"] != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student access only")
    return user

def require_admin(request: Request) -> dict:
    user = require_login(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access only")
    return user


# ── Bundle utilities and inference helper 


def create_initial_bundle(student_id: int, db: Session) -> Optional[WeeklyBundle]:
    """
    Create or return the current week's open WeeklyBundle row for a student.
    Ensures idempotency so repeated calls in the same week do not duplicate bundles.
    """
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    week_number = today.isocalendar().week

    existing = (
        db.query(WeeklyBundle)
        .filter(
            WeeklyBundle.student_id == student_id,
            WeeklyBundle.week_number == week_number,
        )
        .first()
    )
    if existing:
        return existing

    bundle = WeeklyBundle(
        student_id=student_id,
        week_number=week_number,
        start_date=start_of_week,
        end_date=end_of_week,
        tasks_total=0,
        tasks_completed=0,
        tasks_late=0,
        completion_rate=0.0,
        submitted_late=0,
        is_closed=0,
    )

    try:
        db.add(bundle)
        db.commit()
        db.refresh(bundle)
        return bundle
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to create initial bundle for student %s: %s", student_id, exc)
        return None


def collate_weekly_bundles(db: Session) -> None:
    """
    Close the current open bundle for each student, compute snapshot metrics, and
    provision the next week's bundle. Intended for use by a Sunday night scheduler.
    """
    students = db.query(Student).all()

    for student in students:
        try:
            open_bundle = (
                db.query(WeeklyBundle)
                .filter(
                    WeeklyBundle.student_id == student.student_id,
                    WeeklyBundle.is_closed == 0,
                )
                .order_by(WeeklyBundle.week_number.desc())
                .first()
            )
            if not open_bundle:
                continue

            tasks = (
                db.query(Task)
                .filter(
                    Task.student_id == student.student_id,
                    Task.due_date.isnot(None),
                    Task.due_date >= open_bundle.start_date,
                    Task.due_date <= open_bundle.end_date,
                )
                .all()
            )

            tasks_total = len(tasks)
            tasks_completed = sum(1 for t in tasks if t.status == "completed")
            tasks_late = sum(
                1
                for t in tasks
                if t.status == "overdue"
                or (t.completed_at is not None and t.due_date is not None and t.completed_at.date() > t.due_date)
            )
            completion_rate = (tasks_completed / tasks_total) if tasks_total > 0 else 0.0
            submitted_late = 1 if tasks_late > 0 else 0

            open_bundle.tasks_total = tasks_total
            open_bundle.tasks_completed = tasks_completed
            open_bundle.tasks_late = tasks_late
            open_bundle.completion_rate = float(completion_rate)
            open_bundle.submitted_late = submitted_late
            open_bundle.is_closed = 1
            open_bundle.closed_at = datetime.now()

            next_monday = open_bundle.start_date + timedelta(days=7)
            next_sunday = next_monday + timedelta(days=6)
            next_week_number = next_monday.isocalendar().week

            existing_next = (
                db.query(WeeklyBundle)
                .filter(
                    WeeklyBundle.student_id == student.student_id,
                    WeeklyBundle.week_number == next_week_number,
                )
                .first()
            )
            if not existing_next:
                next_bundle = WeeklyBundle(
                    student_id=student.student_id,
                    week_number=next_week_number,
                    start_date=next_monday,
                    end_date=next_sunday,
                    tasks_total=0,
                    tasks_completed=0,
                    tasks_late=0,
                    completion_rate=0.0,
                    submitted_late=0,
                    is_closed=0,
                )
                db.add(next_bundle)

            db.commit()
            logger.info("Collated bundle %s for student %s", open_bundle.bundle_id, student.student_id)
        except Exception as exc:
            db.rollback()
            logger.exception("Failed to collate bundles for student %s: %s", student.student_id, exc)


def assign_tasks_to_bundles(db: Session) -> None:
    """
    Attach tasks without a bundle_id to the correct WeeklyBundle based on due_date.
    Commits in small batches for efficiency and safety.
    """
    pending_tasks = (
        db.query(Task)
        .filter(Task.bundle_id.is_(None))
        .order_by(Task.due_date.asc())
        .all()
    )

    batch_size = 50
    counter = 0

    for task in pending_tasks:
        try:
            if task.due_date is None:
                continue
            task_date = task.due_date
            bundle = (
                db.query(WeeklyBundle)
                .filter(
                    WeeklyBundle.student_id == task.student_id,
                    WeeklyBundle.start_date <= task_date,
                    WeeklyBundle.end_date >= task_date,
                )
                .order_by(WeeklyBundle.week_number.desc())
                .first()
            )
            if bundle:
                task.bundle_id = bundle.bundle_id
                counter += 1

            if counter and counter % batch_size == 0:
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Failed assigning task %s to bundle: %s", task.task_id, exc)

    if counter % batch_size != 0:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception("Failed final commit while assigning tasks to bundles: %s", exc)
    logger.info("Assigned %s tasks to bundles", counter)


# ── Inference helper 

def _bundle_to_features(bundle: WeeklyBundle, today: date) -> list[float]:
    """
    Convert a closed WeeklyBundle row into the 5-feature vector.
    For a closed bundle: days_until_deadline is negative if tasks ran late.
    """
    days_until_deadline  = (bundle.end_date - today).days
    # For closed bundles we use the end_date vs today; negative = overdue
    return [
        float(days_until_deadline),
        0.0,   # days_since_last_sub — filled in by caller with proper gap
        1.0,   # submitted_today — 1 for closed bundles (snapshot day counts)
        float(bundle.completion_rate),
        0.0,   # overdue_count — filled in by caller as running total
    ]

# pipeline for model inference 
def compute_prediction(student: Student, db: Session) -> Optional[dict]:
    """
    Full inference pipeline as described in the pipeline doc.
    Returns a dict ready to store in Predictions, or None if models not loaded.
    """
    if not model_3window:
        return None

    today = date.today()

    # ── 1. Count closed bundles to decide which model to use 
    closed_bundles = (
        db.query(WeeklyBundle)
        .filter(WeeklyBundle.student_id == student.student_id, WeeklyBundle.is_closed == 1)
        .order_by(WeeklyBundle.week_number.asc())
        .all()
    )
    num_closed = len(closed_bundles)
    # Use normal 
    if num_closed >= 7 and model_7window:
        model      = model_7window
        scaler     = scaler_7window
        window     = 7
        model_name = "7window"
    else:
        model      = model_3window
        scaler     = scaler_3window
        window     = 3
        model_name = "3window"

    # ── 2. Get the current (live) bundle 
    current_bundle = (
        db.query(WeeklyBundle)
        .filter(WeeklyBundle.student_id == student.student_id, WeeklyBundle.is_closed == 0)
        .order_by(WeeklyBundle.week_number.desc())
        .first()
    )

    if not current_bundle:
        return None  # no active bundle yet — student hasn't set up their week

    # ── 3. Compute live features for current bundle (Row 7 / Row 3) 
    tasks_in_bundle = (
        db.query(Task)
        .filter(Task.bundle_id == current_bundle.bundle_id)
        .all()
    )
    tasks_total     = len(tasks_in_bundle)
    tasks_completed = sum(1 for t in tasks_in_bundle if t.status == 'completed')
    completion_rate = (tasks_completed / tasks_total) if tasks_total > 0 else 0.0

    overdue_count = sum(1 for b in closed_bundles if b.submitted_late == 1)

    submitted_today = 1 if any(
        t.completed_at and t.completed_at.date() == today
        for t in tasks_in_bundle
    ) else 0

    days_until_deadline = (current_bundle.end_date - today).days

    # days_since_last_sub: gap from previous bundle's last completed task
    if closed_bundles:
        prev_bundle = closed_bundles[-1]
        prev_tasks = (
            db.query(Task)
            .filter(Task.bundle_id == prev_bundle.bundle_id, Task.status == 'completed')
            .order_by(Task.completed_at.desc())
            .first()
        )
        if prev_tasks and prev_tasks.completed_at:
            days_since_last_sub = max(0, (today - prev_tasks.completed_at.date()).days)
        else:
            days_since_last_sub = 7  # default: assume last week
    else:
        days_since_last_sub = max(0, (today - student.enrollment_date).days)

    live_features = [
        float(days_until_deadline),
        float(days_since_last_sub),
        float(submitted_today),
        float(completion_rate),
        float(overdue_count),
    ]

    # ── 4. Build feature sequence, prepending priors for gaps
    # We need (window - 1) historical rows + 1 live row = window total
    real_history_needed = window - 1
    real_rows = []

    running_overdue = 0
    for i, bundle in enumerate(closed_bundles[-(real_history_needed):]):
        if bundle.submitted_late:
            running_overdue += 1
        prev_last_completed = None
        if i > 0:
            pb = closed_bundles[-(real_history_needed) + i - 1]
            prev_t = (
                db.query(Task)
                .filter(Task.bundle_id == pb.bundle_id, Task.status == 'completed')
                .order_by(Task.completed_at.desc())
                .first()
            )
            if prev_t and prev_t.completed_at:
                prev_last_completed = prev_t.completed_at.date()

        gap = (bundle.end_date - prev_last_completed).days if prev_last_completed else 7
        real_rows.append([
            float((bundle.end_date - bundle.end_date).days),  # 0 — submitted on deadline
            float(max(0, gap)),
            1.0,
            float(bundle.completion_rate),
            float(running_overdue),
        ])

    # Fill remaining slots with prior profile synthetic rows
    rows_needed = real_history_needed - len(real_rows)
    prior_key   = student.prior_profile if student.prior_profile else 'mixed'
    prior_rows  = prior_profiles.get(prior_key, [])[:rows_needed] if rows_needed > 0 else []

    sequence = prior_rows + real_rows + [live_features]

    if len(sequence) != window:
        # Safety check — should not happen with correct prior_profiles.json
        return None

    # ── 5. Scale 
    seq_array = np.array(sequence, dtype=np.float32)  # (window, 5)
    seq_scaled = scaler.transform(seq_array).reshape(1, window, 5)

    # ── 6. Inference 
    output = model.predict(seq_scaled, verbose=0)
    risk_score = float(output[0][0])  # sigmoid output — probability of late submission

    # ── 7. Map score to risk level 
    if risk_score < 0.40:
        risk_level = "low"
    elif risk_score < 0.65:
        risk_level = "medium"
    else:
        risk_level = "high"

    return {
        "risk_level":        risk_level,
        "confidence_score":  round(risk_score, 2),
        "model_used":        model_name,
        "bundle_id":         current_bundle.bundle_id,
        "features_json":     {
            "days_until_deadline":  days_until_deadline,
            "days_since_last_sub":  days_since_last_sub,
            "submitted_today":      submitted_today,
            "completion_rate":      round(completion_rate, 3),
            "overdue_count":        overdue_count,
        }
    }


# Daily rotating MCII implementation intention tips (deterministic by day of year)
MCII_DAILY_TIPS = [
    "If I feel like checking social media during study time, then I will put my phone in another room for 25 minutes first.",
    "If I sit down to study and feel overwhelmed, then I will write down just the first small step and do only that.",
    "If I notice myself opening a distraction app, then I will close it and set a 10-minute timer for one task.",
    "If it's my planned study block and I don't feel like starting, then I will tell myself I'll do just 5 minutes and then can stop.",
    "If I finish a small chunk of work, then I will take a 2-minute stretch break before deciding what's next.",
    "If I'm tempted to skip a study session, then I will at least open my notes and read one paragraph.",
    "If I catch myself saying 'I'll do it later', then I will do the very next physical action (e.g. open the file) right now.",
    "If my environment is noisy or distracting, then I will move to a quieter spot or put on focus music before continuing.",
    "If I'm avoiding a hard task, then I will spend 2 minutes writing down why it matters and one tiny first step.",
    "If I have multiple deadlines, then I will pick the single most urgent one and work on it for one Pomodoro before switching.",
    "If I feel tired and want to procrastinate, then I will do a 2-minute walk or splash water on my face, then try one 15-minute block.",
    "If I'm studying and my mind wanders, then I will write the distracting thought on a sticky note and return to the task.",
    "If a task feels too big, then I will break it into three smaller steps and do only the first one today.",
    "If I'm waiting for 'the right mood' to start, then I will start with the easiest part of the task for 5 minutes.",
    "If I complete a task before the deadline, then I will note what helped and reuse that condition next time.",
]


def generate_mcii_tip(risk_level: str, confidence_score: float) -> str:
    """
    Generate a concise MCII (Mental Contrasting and Implementation Intentions) tip using Claude
    for a given procrastination risk level and confidence score.
    """
    normalized_risk = (risk_level or "").lower()
    safe_confidence = max(0.0, min(float(confidence_score or 0.0), 1.0))

    base_prompt = (
        f"Generate a concise MCII tip under 100 words for a student "
        f"with {normalized_risk or 'unknown'} procrastination risk "
        f"(confidence: {safe_confidence:.2f}). "
        "Use the Mental Contrasting and Implementation Intentions framework."
    )

    low_risk_variants = [
        base_prompt
        + " Focus on positive reinforcement, maintaining momentum, and acknowledging recent wins. "
        "Keep the tone warm and encouraging, under 80 words.",
        base_prompt
        + " Emphasize how staying consistent this week will protect their current low-risk status. "
        "Highlight a clear if-then plan for keeping their good habits, under 80 words.",
        base_prompt
        + " Celebrate that the upcoming weekly bundle deadline looks manageable and encourage one small "
        "implementation intention that locks in their current study rhythm, under 80 words.",
    ]

    medium_risk_variants = [
        base_prompt
        + " Format the response exactly as:\n"
        "Goal: [specific academic goal linked to this week's bundle deadline].\n"
        "Obstacle: [concrete obstacle based on typical procrastination patterns].\n"
        "Plan: If [specific trigger situation before the deadline], then I will [precise study action].\n"
        "Be specific and mention that the bundle deadline is approaching soon. Stay under 120 words.",
        base_prompt
        + " The response must follow this structure:\n"
        "Goal: [clear goal tied to tasks due by the end of the current week].\n"
        "Obstacle: [realistic internal or external barrier, like phone distraction or fatigue].\n"
        "Plan: If [time or context near the deadline], then I will [focused behavior that moves one task forward].\n"
        "Keep it concrete, deadline-aware, and under 120 words.",
        base_prompt
        + " Use MCII to help the student close the gap before this week's bundle deadline. "
        "Write:\nGoal: ...\nObstacle: ...\nPlan: If ... then I will ....\n"
        "Refer explicitly to the remaining days before the deadline and keep it under 120 words.",
        base_prompt
        + " Assume the student still has several tasks due by Sunday. "
        "Structure the tip as Goal / Obstacle / Plan, with the plan being an if-then action they can execute "
        "today or tomorrow before the bundle closes. Under 120 words.",
    ]

    high_risk_variants = [
        base_prompt
        + " Write in an urgent but supportive tone. "
        "Assume many tasks are still unfinished and the bundle deadline is very close. "
        "Include a clear if-then implementation intention that can be acted on immediately, and stay under 150 words.",
        base_prompt
        + " Emphasize that time is almost up for this week's bundle and several tasks remain. "
        "Direct the student to pick one high-impact task and create a sharp if-then plan to start within the next hour. "
        "Keep it structured, concrete, and under 150 words.",
        base_prompt
        + " Treat this as a high-urgency situation. "
        "Highlight the cost of not acting before the weekly deadline, then provide one specific if-then plan "
        "for tackling the most overdue or risky task. Under 150 words.",
        base_prompt
        + " Assume the student has been postponing work until the last minute. "
        "Be direct: mention the urgent deadline, the number of tasks likely remaining, and give a firm if-then rule "
        "they can follow tonight to reduce risk. Under 150 words.",
    ]

    if normalized_risk == "low":
        prompt = random.choice(low_risk_variants)
    elif normalized_risk == "medium":
        prompt = random.choice(medium_risk_variants)
    elif normalized_risk == "high":
        prompt = random.choice(high_risk_variants)
    else:
        prompt = base_prompt + " Provide a balanced, supportive MCII tip suitable for an unknown risk level."

    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )
        if response and getattr(response, "content", None):
            first_block = response.content[0]
            text = getattr(first_block, "text", None) or getattr(first_block, "content", None)
            if isinstance(text, str) and text.strip():
                return text.strip()
    except Exception:
        pass

    if normalized_risk == "low":
        return (
            "You are on a strong path this week. Picture how it will feel to submit everything on time, "
            "then commit: if I start to drift or scroll my phone during my planned study block, "
            "then I will pause, take a breath, and return to the next small step on my task list."
        )
    if normalized_risk == "medium":
        return (
            "Goal: Finish this week’s key tasks before the bundle deadline.\n"
            "Obstacle: I tend to delay starting when studying feels overwhelming.\n"
            "Plan: If it is the next available 30-minute window today, then I will open my planner, pick one task "
            "due soonest, and work on it without checking my phone until the timer ends."
        )
    return (
        "Goal: Submit as many remaining tasks as possible before this week’s deadline.\n"
        "Obstacle: I keep putting tasks off until it feels too late to start.\n"
        "Plan: If it is the next hour, then I will choose the single most urgent task, silence notifications, "
        "and work on it in a focused 25-minute block, followed by a 5-minute break."
    )


# ── Scheduler jobs (use SessionLocal inside jobs, not get_db)

def nightly_inference() -> None:
    """Run prediction for all students; create Prediction rows and optional MCII interventions. Idempotent per student per day."""
    db = SessionLocal()
    try:
        today = date.today()
        students = db.query(Student).all()
        logger.info("nightly_inference started, total students=%s", len(students))
        written = 0
        errors = 0
        for student in students:
            try:
                existing = (
                    db.query(Prediction)
                    .filter(
                        Prediction.student_id == student.student_id,
                        Prediction.prediction_date == today,
                    )
                    .first()
                )
                if existing:
                    continue
                result = compute_prediction(student, db)
                if result is None:
                    logger.warning("compute_prediction returned None for student_id=%s", student.student_id)
                    continue
                pred = Prediction(
                    student_id=student.student_id,
                    bundle_id=result.get("bundle_id"),
                    prediction_date=today,
                    model_used=result["model_used"],
                    risk_level=result["risk_level"],
                    confidence_score=result["confidence_score"],
                    attention_weights_json=None,
                    features_json=result.get("features_json"),
                )
                db.add(pred)
                db.flush()
                student.current_risk_level = result["risk_level"]
                student.days_active = (student.days_active or 0) + 1
                if result["risk_level"] == "high":
                    cutoff = datetime.now() - timedelta(hours=24)
                    recent_mcii = (
                        db.query(MCIIIntervention)
                        .filter(
                            MCIIIntervention.student_id == student.student_id,
                            MCIIIntervention.delivery_time >= cutoff,
                        )
                        .first()
                    )
                    if not recent_mcii:
                        tip_text = generate_mcii_tip(result["risk_level"], result["confidence_score"])
                        intervention = MCIIIntervention(
                            prediction_id=pred.prediction_id,
                            student_id=student.student_id,
                            prompt_text=tip_text,
                            delivery_time=datetime.now(),
                        )
                        db.add(intervention)
                db.commit()
                written += 1
            except Exception as exc:
                db.rollback()
                errors += 1
                logger.exception("nightly_inference failed for student_id=%s: %s", student.student_id, exc)
        logger.info("nightly_inference finished, predictions_written=%s, errors=%s", written, errors)
    finally:
        db.close()


def _run_collate_weekly_bundles() -> None:
    db = SessionLocal()
    try:
        collate_weekly_bundles(db)
    finally:
        db.close()


def _run_assign_tasks_to_bundles() -> None:
    db = SessionLocal()
    try:
        assign_tasks_to_bundles(db)
    finally:
        db.close()


# ── FastAPI App 

app = FastAPI(title="ProActive")

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-in-production"),
    max_age=86400
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# upload_dir = BASE_DIR / "media" / "profile_pics"
app.mount("/media", StaticFiles(directory=BASE_DIR / "media"), name="media")


@app.on_event("startup")
def start_scheduler():
    scheduler.add_job(_run_collate_weekly_bundles, "cron", day_of_week="sun", hour=23, minute=59, timezone="UTC")
    scheduler.add_job(nightly_inference, "cron", hour=0, minute=5, timezone="UTC")
    scheduler.add_job(_run_assign_tasks_to_bundles, "cron", hour=0, minute=10, timezone="UTC")
    scheduler.start()


@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown()


@app.post("/admin/run-scheduler")
def run_scheduler_manual(
    current_user: dict = Depends(require_admin),
):
    """Manual trigger for nightly inference (admin only, for testing)."""
    nightly_inference()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"message": "Scheduler run complete", "timestamp": datetime.now().isoformat()},
    )


# ── Page Routes 

# login page 
@app.get("/", response_class=HTMLResponse)
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request): # request: Request required by Jinja 2 template rendering
    # redirect to admin dashboard if user is admin else redirect to student dashboard
    if request.session.get("user"):
        role = request.session["user"]["role"]
        return RedirectResponse(url="/admin/dashboard" if role == "admin" else "/student/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})


#  signup page 
@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

# student_dashboard
@app.get("/student/dashboard", response_class=HTMLResponse)
async def student_dashboard(
    request: Request,
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db)
):
    student = db.query(Student).filter(Student.student_id == current_user["user_id"]).first()

    today = date.today()
    tasks = (
        db.query(Task)
        .filter(Task.student_id == current_user["user_id"])
        .filter(
            (Task.due_date.is_(None)) | (Task.due_date >= today)
        )
        .order_by(Task.due_date.asc())
        .all()
    )

    latest_prediction = (
        db.query(Prediction)
        .filter(Prediction.student_id == current_user["user_id"])
        .order_by(Prediction.prediction_date.desc())
        .first()
    )

    # Daily MCII tip: same for the whole day, changes by day of year
    day_of_year = date.today().timetuple().tm_yday
    mcii_tip = MCII_DAILY_TIPS[day_of_year % len(MCII_DAILY_TIPS)]

    return templates.TemplateResponse("student_dashboard.html", {
        "request":          request,
        "current_user":     current_user,
        "student":          student,
        "student_id":       current_user["user_id"],
        "tasks":            tasks,
        "prediction":       latest_prediction,
        "mcii_tip":         mcii_tip,
    })


# student task manager 
@app.get("/student/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request,
    filter_status: Optional[str] = None,
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db)
):
    student = db.query(Student).filter(Student.student_id == current_user["user_id"]).first()
    query = db.query(Task).filter(Task.student_id == current_user["user_id"])
    if filter_status:
        query = query.filter(Task.status == filter_status)
    tasks = query.order_by(Task.due_date.asc()).all()

    return templates.TemplateResponse("tasks.html", {
        "request":       request,
        "current_user":  current_user,
        "student":       student,
        "tasks":         tasks,
        "filter_status": filter_status,
    })

# student profile page 
@app.get("/student/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db)
):
    student = db.query(Student).filter(Student.student_id == current_user["user_id"]).first()
    completed_count = db.query(Task).filter(
        Task.student_id == current_user["user_id"],
        Task.status == "completed"
    ).count()
    latest_prediction = (
        db.query(Prediction)
        .filter(Prediction.student_id == current_user["user_id"])
        .order_by(Prediction.prediction_date.desc())
        .first()
    )

    error = request.session.pop("flash_error", None)
    success = request.session.pop("flash_success", None)
    return templates.TemplateResponse("student_profile.html", {
        "request":          request,
        "current_user":     current_user,
        "student":          student,
        "completed_count":  completed_count,
        "prediction":       latest_prediction,
        "error":            error,
        "success":          success,
    })

# update student profile page 
@app.post("/student/profile/update")
async def update_profile(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(""),
    bio: str = Form(""),
    profile_pic: Optional[UploadFile] = File(None),
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db),
):
    """
    Handle profile updates for the logged-in student, including name, phone, bio, and
    optional profile picture upload with validation and safe database commit.
    """
    student = (
        db.query(Student)
        .filter(Student.student_id == current_user["user_id"])
        .first()
    )

    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student record not found for profile update",
        )

    name_clean = (full_name or "").strip()
    phone_clean = (phone or "").strip()
    bio_clean = (bio or "").strip()
    error_message: Optional[str] = None

    if len(name_clean) < 2 or len(name_clean) > 100:
        error_message = "Full name must be between 2 and 100 characters."
    elif len(phone_clean) > 20:
        error_message = "Phone must be at most 20 characters."
    elif phone_clean and not all(c in "0123456789 +-" for c in phone_clean):
        error_message = "Phone may only contain digits, spaces, + and -."
    elif len(bio_clean) > 500:
        error_message = "Bio must be at most 500 characters."

    image_path: Optional[str] = None

    if not error_message and profile_pic and profile_pic.filename:
        allowed_types = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }
        if profile_pic.content_type not in allowed_types:
            error_message = "Profile picture must be a JPG, PNG, or WEBP image."
        else:
            data = await profile_pic.read()
            if len(data) > 2 * 1024 * 1024:
                error_message = "Profile picture must be under 2MB."
            else:
                ext = allowed_types[profile_pic.content_type]
                upload_dir = BASE_DIR / "media" / "profile_pics"
                upload_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{student.student_id}_{uuid.uuid4().hex[:8]}{ext}"
                file_path = upload_dir / filename
                with open(file_path, "wb") as f:
                    f.write(data)
                image_path = f"/media/profile_pics/{filename}"

    if error_message:
        completed_count = db.query(Task).filter(
            Task.student_id == current_user["user_id"],
            Task.status == "completed",
        ).count()
        latest_prediction = (
            db.query(Prediction)
            .filter(Prediction.student_id == current_user["user_id"])
            .order_by(Prediction.prediction_date.desc())
            .first()
        )
        return templates.TemplateResponse(
            "student_profile.html",
            {
                "request": request,
                "current_user": current_user,
                "student": student,
                "completed_count": completed_count,
                "prediction": latest_prediction,
                "error": error_message,
                "success": None,
                "form_full_name": name_clean,
                "form_phone": phone_clean,
                "form_bio": bio_clean,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    old_profile_pic = student.profile_pic
    student.full_name = name_clean
    student.phone = phone_clean if phone_clean else None
    student.bio = bio_clean
    if image_path:
        student.profile_pic = image_path

    try:
        db.commit()
    except Exception:
        db.rollback()
        completed_count = db.query(Task).filter(
            Task.student_id == current_user["user_id"],
            Task.status == "completed",
        ).count()
        latest_prediction = (
            db.query(Prediction)
            .filter(Prediction.student_id == current_user["user_id"])
            .order_by(Prediction.prediction_date.desc())
            .first()
        )
        error = request.session.pop("flash_error", None)
        success = request.session.pop("flash_success", None)
        return templates.TemplateResponse(
            "student_profile.html",
            {
                "request": request,
                "current_user": current_user,
                "student": student,
                "completed_count": completed_count,
                "prediction": latest_prediction,
                "error": "Could not update profile. Please try again.",
                "success": success,
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if image_path and old_profile_pic:
        try:
            old_name = os.path.basename(old_profile_pic)
            old_path = BASE_DIR / "media" / "profile_pics" / old_name
            if old_path.exists():
                old_path.unlink()
        except FileNotFoundError:
            pass

    request.session["flash_success"] = "Profile updated successfully"
    return RedirectResponse(
        url="/student/profile",
        status_code=status.HTTP_303_SEE_OTHER,
    )


#  mcii chat endpoint 
@app.get("/student/mcii", response_class=HTMLResponse)
async def mcii_page(
    request: Request,
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db)
):
    student = db.query(Student).filter(Student.student_id == current_user["user_id"]).first()
    
    interventions = (
        db.query(MCIIIntervention)
        .filter(MCIIIntervention.student_id == current_user["user_id"])
        .order_by(MCIIIntervention.delivery_time.asc())
        .all()
    )

    # cutoff = datetime.now() - timedelta(hours=48)
    # recent_intervention = (
    #     db.query(MCIIIntervention)
    #     .filter(
    #         MCIIIntervention.student_id == current_user["user_id"],
    #         MCIIIntervention.delivery_time >= cutoff
    #     )
    #     .first()
    # )
    # is_fresh = recent_intervention is None

    if student.current_risk_level == "high":
        greeting = "Hey — I can see things are a bit intense right now. Let's talk about what's going on and build a plan together."
    elif student.current_risk_level == "medium":
        greeting = "Hey! You're doing okay but there's room to get ahead. What are you working on this week?"
    else:
        greeting = "Hey! You're in good shape right now — let's keep that momentum going. What's your focus this week?"

    return templates.TemplateResponse("mcii_chat.html", {
        "request": request,
        "current_user": current_user,
        "student": student,
        "interventions": interventions,
        "greeting": greeting,
    })


@app.post("/student/mcii/chat")
async def mcii_chat(
    message: MCIIMessage,
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db),
):
    if not message.message or not message.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message cannot be empty")
    
    student_id = current_user["user_id"]

    student = db.query(Student).filter(Student.student_id == student_id).first()

    latest_prediction = (
        db.query(Prediction)
        .filter(Prediction.student_id == student_id)
        .order_by(Prediction.prediction_date.desc())
        .first()
    )
    active_bundle = (
        db.query(WeeklyBundle)
        .filter(WeeklyBundle.student_id == student_id, WeeklyBundle.is_closed == 0)
        .order_by(WeeklyBundle.week_number.desc())
        .first()
    )
    tasks_remaining = (
        (active_bundle.tasks_total - active_bundle.tasks_completed)
        if active_bundle
        else "unknown"
    )
    days_until_deadline = (
        (active_bundle.end_date - date.today()).days
        if active_bundle
        else "unknown"
    )
    overdue_count = (
        db.query(WeeklyBundle)
        .filter(
            WeeklyBundle.student_id == student_id,
            WeeklyBundle.is_closed == 1,
            WeeklyBundle.submitted_late == 1,
        )
        .count()
    )
    risk_level = latest_prediction.risk_level if latest_prediction else "unknown"
    confidence_score = float(latest_prediction.confidence_score) if latest_prediction else 0.0

    system_prompt = (
        f"You are ProActive Coach — an AI academic coach and mental health-informed study companion for {student.full_name}.\n"
        "You are warm, direct, and knowledgeable. You genuinely care about student success and wellbeing.\n\n"
        "STUDENT CONTEXT:\n"
        f"- Risk level: {risk_level} (confidence: {confidence_score})\n"
        f"- Tasks remaining this week: {tasks_remaining}\n"
        f"- Days until weekly deadline: {days_until_deadline}\n"
        f"- Late bundles in history: {overdue_count}\n"
        f"- Days active on platform: {student.days_active}\n"
        f"- Prior procrastination profile: {student.prior_profile}\n\n"
        "YOUR PURPOSE:\n"
        "You are part of a research-backed intervention system exploring MCII (Mental Contrasting with "
        "Implementation Intentions) as an alternative to in-person CBT for academic procrastination. "
        "MCII is not optional — it is the core intervention you deliver. Every meaningful conversation "
        "should work toward a Mental Contrast and an Implementation Intention. Make this feel natural, not forced.\n\n"
        "YOUR PERSONALITY:\n"
        "- You talk like a smart, supportive friend who knows a lot about productivity and student psychology\n"
        "- You can be warm, funny, and casual when the moment calls for it\n"
        "- You can be clinical, structured, and direct when the situation requires it\n"
        "- You are comfortable sounding therapeutic — you are exploring this as an alternative to CBT\n"
        "- What you avoid is sounding like you are reading from a script\n"
        "- You listen before you coach — never jump to MCII before the student feels heard\n"
        "- You give direct answers first, MCII layer second when a student asks a practical question\n\n"
        "WHEN TO USE MCII:\n"
        "- When a student mentions a goal, struggle, or deadline → guide them through Mental Contrasting "
        "(visualize success, then name the obstacle) and build an Implementation Intention (if-then plan)\n"
        "- When they ask for a study plan → give the plan first, then anchor it with if-then intentions\n"
        "- When they are clearly procrastinating → acknowledge it, then apply MCII\n"
        "- When they vent or are stressed → listen and validate first, then transition to MCII naturally\n"
        "- Every session should end with or work toward a concrete if-then plan where possible\n\n"
        "HANDLING OFF-TOPIC CONVERSATIONS:\n"
        "- First time: engage briefly and genuinely with the off-topic thing, then redirect with light humour\n"
        "- Second time: acknowledge you've been off track, be warmer but firmer in redirecting\n"
        "- Third time and beyond: be firm and direct — no more engaging with the off-topic content, "
        "redirect fully to their academic context. Still warm, never rude.\n"
        "- Each redirect should feel natural and in-the-moment, not scripted\n\n"
        "THINGS YOU NEVER DO:\n"
        "- Never repeat your opening greeting if conversation history exists — pick up naturally\n"
        "- Never apply MCII so rigidly that it kills the conversation flow\n"
        "- Never ignore a casual question completely — engage briefly first\n"
        "- Never make a student jump through hoops to get a direct answer\n"
        "- Never say 'I need clarity' repeatedly — make a reasonable assumption and proceed\n"
        "- Never be preachy\n\n"
        "Keep responses under 200 words unless the student explicitly requests a detailed plan or "
        "breakdown, in which case be as thorough as needed.\n"
        "Do not be generic. Be direct and specific to this student's context."
    )

    # Load last 10 exchanges for conversation history
    cutoff = datetime.now() - timedelta(hours=48)
    history = (
        db.query(MCIIIntervention)
        .filter(
            MCIIIntervention.student_id == student_id,
            MCIIIntervention.delivery_time >= cutoff
        )
        .order_by(MCIIIntervention.intervention_id.desc())
        .limit(15)
        .all()
    )
    history.reverse()

    # Build messages array with history
    messages = []
    for h in history:
        messages.append({"role": "user", "content": h.prompt_text})
        if h.user_response:
            messages.append({"role": "assistant", "content": h.user_response})

    # Add current message
    messages.append({"role": "user", "content": message.message})

    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system_prompt,
            messages=messages,
        )
        claude_reply = response.content[0].text
    except Exception as exc:
        logger.exception("MCII chat Claude API error: %s", exc)
        err_name = type(exc).__name__
        error_str = str(exc)
        
        if "RateLimit" in err_name:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service temporarily unavailable. Please try again shortly.",
            )
        if "credit" in error_str.lower() or "billing" in error_str.lower() or "quota" in error_str.lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI coach is currently unavailable. Please contact your administrator.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI coach is temporarily unavailable. Please try again.",
        )


    intervention = MCIIIntervention(
        prediction_id=latest_prediction.prediction_id if latest_prediction else None,
        student_id=student_id,
        prompt_text=message.message,
        user_response=claude_reply,
        delivery_time=datetime.now(),
    )
    db.add(intervention)
    db.commit()
    db.refresh(intervention)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"response": claude_reply, "intervention_id": intervention.intervention_id},
    )


@app.get("/api/students/{student_id}/trend")
def get_student_trend(
    student_id: int,
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db),
):
    """Return last 14 days of predictions, one per day (latest only); 403 if not own student. Skips days with no prediction."""
    if current_user["user_id"] != student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    today = date.today()
    start = today - timedelta(days=14)
    rows = (
        db.query(Prediction)
        .filter(
            Prediction.student_id == student_id,
            Prediction.prediction_date >= start,
            Prediction.prediction_date <= today,
        )
        .order_by(Prediction.prediction_date.asc(), Prediction.prediction_id.asc())
        .all()
    )
    # One prediction per day: keep latest per prediction_date
    by_date: Dict[date, Any] = {}
    for r in rows:
        by_date[r.prediction_date] = r
    sorted_dates = sorted(by_date.keys())
    if len(sorted_dates) < 2:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "labels": [],
                "scores": [],
                "risk_levels": [],
                "trend": "insufficient_data",
                "trend_pct": 0,
            },
        )
    labels = [d.strftime("%b %d") for d in sorted_dates]
    scores = [float(by_date[d].confidence_score) for d in sorted_dates]
    risk_levels = [by_date[d].risk_level for d in sorted_dates]
    n = len(scores)
    if n >= 6:
        recent_avg = sum(scores[-3:]) / 3
        previous_avg = sum(scores[-6:-3]) / 3
    else:
        recent_avg = sum(scores[-2:]) / 2
        previous_avg = sum(scores[:2]) / 2
    diff = recent_avg - previous_avg
    if diff > 0.1:
        trend = "worsening"
    elif diff < -0.1:
        trend = "improving"
    else:
        trend = "stable"
    trend_pct = round(abs(diff) * 100, 1)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "labels": labels,
            "scores": scores,
            "risk_levels": risk_levels,
            "trend": trend,
            "trend_pct": trend_pct,
        },
    )


@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    page: int = 1,
    risk_filter: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db)
):
    per_page = 20
    admin_id = current_user["user_id"]

    # Cohort: only students linked to this admin
    cohort_base = db.query(Student).filter(Student.admin_id == admin_id)

    # ── Stats scoped to cohort ──
    total_students  = cohort_base.count()
    high_risk_count = cohort_base.filter(Student.current_risk_level == "high").count()

    cohort_student_ids = [r.student_id for r in cohort_base.with_entities(Student.student_id).all()]
    students_with_interventions = (
        db.query(MCIIIntervention.student_id)
        .filter(MCIIIntervention.student_id.in_(cohort_student_ids))
        .distinct()
        .count()
    ) if cohort_student_ids else 0
    mcii_engagement = round((students_with_interventions / total_students * 100), 1) if total_students > 0 else 0

    # Avg confidence: average of latest prediction per cohort student (Prompt 5)
    avg_confidence = 0.0
    if cohort_student_ids:
        latest_scores = []
        for sid in cohort_student_ids:
            p = (
                db.query(Prediction)
                .filter(Prediction.student_id == sid)
                .order_by(Prediction.prediction_date.desc())
                .first()
            )
            if p is not None:
                latest_scores.append(float(p.confidence_score))
        avg_confidence = round(sum(latest_scores) / len(latest_scores) * 100, 1) if latest_scores else 0.0

    # ── Student query with filters (cohort only) ──
    query = db.query(Student).filter(Student.admin_id == admin_id)

    if risk_filter:
        query = query.filter(Student.current_risk_level == risk_filter)

    if search:
        query = query.filter(
            or_(
                Student.email.ilike(f"%{search}%"),
                Student.full_name.ilike(f"%{search}%"),
            )
        )

    total_filtered = query.count()
    flash_success = request.session.pop("flash_success", None)
    total_pages    = max(1, (total_filtered + per_page - 1) // per_page)
    page           = max(1, min(page, total_pages))
    offset         = (page - 1) * per_page

    students = query.order_by(Student.created_at.desc()).offset(offset).limit(per_page).all()

    # ── Attach latest prediction to each student ──
    students_with_predictions = []
    for s in students:
        pred = (
            db.query(Prediction)
            .filter(Prediction.student_id == s.student_id)
            .order_by(Prediction.prediction_date.desc())
            .first()
        )
        students_with_predictions.append({"student": s, "prediction": pred})

    # Admin invite code for header badge
    admin_row = db.query(Admin).filter(Admin.admin_id == admin_id).first()
    invite_code = admin_row.invite_code if admin_row else None

    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "current_user": current_user,
        "stats": {
            "total_students": total_students,
            "high_risk_alerts": high_risk_count,
            "mcii_engagement": mcii_engagement,
            "avg_confidence": avg_confidence,
        },
        "students": students_with_predictions,
        "page": page,
        "total_pages": total_pages,
        "total_filtered": total_filtered,
        "risk_filter": risk_filter,
        "search": search,
        "flash_success": flash_success,
        "invite_code": invite_code,
    })


@app.get("/admin/profile", response_class=HTMLResponse)
async def admin_profile_page(
    request: Request,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Display admin profile with invite code for sharing with students."""
    admin = db.query(Admin).filter(Admin.admin_id == current_user["user_id"]).first()
    if not admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found")
    return templates.TemplateResponse(
        "admin_profile.html",
        {
            "request": request,
            "current_user": current_user,
            "admin": admin,
            "invite_code": admin.invite_code or "—",
        },
    )


@app.get("/admin/create-admin", response_class=HTMLResponse)
async def admin_create_page(
    request: Request,
    current_user: dict = Depends(require_admin),
):
    """Render the create admin account form."""
    return templates.TemplateResponse(
        "admin_create.html",
        {"request": request, "current_user": current_user, "error": None},
    )


@app.post("/admin/create-admin", response_class=HTMLResponse)
async def admin_create_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    department: str = Form("General"),
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new admin account. Auth: require_admin."""
    error = None
    email_clean = (email or "").strip().lower()
    department_clean = (department or "General").strip()[:100]
    if len(email_clean) > 255:
        error = "Email must be at most 255 characters."
    elif "@" not in email_clean or "." not in email_clean.split("@")[-1]:
        error = "Please enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    if not error and db.query(Admin).filter(Admin.email == email_clean).first():
        error = "An admin with this email already exists."
    if error:
        return templates.TemplateResponse(
            "admin_create.html",
            {"request": request, "current_user": current_user, "error": error},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    # Auto-generate 8-char alphanumeric invite code (ensure unique)
    for _ in range(10):
        invite_code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        if not db.query(Admin).filter(Admin.invite_code == invite_code).first():
            break
    else:
        invite_code = secrets.token_hex(4).upper()[:8]
    try:
        new_admin = Admin(
            email=email_clean,
            password_hash=hash_password(password),
            department=department_clean or "General",
            invite_code=invite_code,
        )
        db.add(new_admin)
        db.commit()
        request.session["flash_success"] = f"Admin account created for {email_clean}"
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    except Exception:
        db.rollback()
        return templates.TemplateResponse(
            "admin_create.html",
            {
                "request": request,
                "current_user": current_user,
                "error": "Could not create account. Try again.",
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@app.get("/admin/assign-task", response_class=HTMLResponse)
async def admin_assign_task_page(
    request: Request,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Render form to assign a task to all cohort students."""
    admin_id = current_user["user_id"]
    cohort_count = db.query(Student).filter(Student.admin_id == admin_id).count()
    return templates.TemplateResponse(
        "admin_assign_task.html",
        {
            "request": request,
            "current_user": current_user,
            "cohort_count": cohort_count,
            "error": None,
            "flash_success": None,
        },
    )


@app.post("/admin/assign-task", response_class=HTMLResponse)
async def admin_assign_task_submit(
    request: Request,
    title: str = Form(...),
    due_date: Optional[str] = Form(default=""),
    task_type: str = Form("assignment"),
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create the same task for every student in the admin's cohort. Safeguard: reject if already assigned."""
    admin_id = current_user["user_id"]
    cohort_students = db.query(Student).filter(Student.admin_id == admin_id).all()
    cohort_count = len(cohort_students)
    if cohort_count == 0:
        return templates.TemplateResponse(
            "admin_assign_task.html",
            {
                "request": request,
                "current_user": current_user,
                "cohort_count": 0,
                "error": "You have no students in your cohort yet. Share your invite code with students to add them.",
                "flash_success": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    due_date_val: Optional[date] = None
    if due_date and due_date.strip():
        try:
            due_date_val = datetime.strptime(due_date.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            pass

    # Safeguard: check if this exact task (same title, due_date, created_by_admin_id) already exists for any cohort student
    dup_query = (
        db.query(Task)
        .filter(
            Task.title == title.strip(),
            Task.created_by_admin_id == admin_id,
            Task.is_admin_assigned == True,
        )
        .join(Student, Task.student_id == Student.student_id)
        .filter(Student.admin_id == admin_id)
    )
    if due_date_val is None:
        existing = dup_query.filter(Task.due_date.is_(None)).first()
    else:
        existing = dup_query.filter(Task.due_date == due_date_val).first()
    if existing:
        return templates.TemplateResponse(
            "admin_assign_task.html",
            {
                "request": request,
                "current_user": current_user,
                "cohort_count": cohort_count,
                "error": "This task has already been assigned.",
                "flash_success": None,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    allowed_types = ("assignment", "quiz", "summative", "formative")
    task_type_clean = task_type if task_type in allowed_types else "assignment"

    try:
        for student in cohort_students:
            active_bundle = (
                db.query(WeeklyBundle)
                .filter(WeeklyBundle.student_id == student.student_id, WeeklyBundle.is_closed == 0)
                .order_by(WeeklyBundle.week_number.desc())
                .first()
            )
            task = Task(
                student_id=student.student_id,
                bundle_id=active_bundle.bundle_id if active_bundle else None,
                title=title.strip(),
                due_date=due_date_val,
                status="pending",
                task_type=task_type_clean,
                is_admin_assigned=True,
                created_by_admin_id=admin_id,
            )
            db.add(task)
        db.commit()
        request.session["flash_success"] = f"Task assigned to {cohort_count} student(s)."
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:
        db.rollback()
        logger.exception("admin_assign_task failed: %s", exc)
        return templates.TemplateResponse(
            "admin_assign_task.html",
            {
                "request": request,
                "current_user": current_user,
                "cohort_count": cohort_count,
                "error": "Could not assign task. Please try again.",
                "flash_success": None,
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@app.get("/admin/students/{student_id}", response_class=HTMLResponse)
async def admin_student_detail(
    student_id: int,
    request: Request,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Render a detailed view for a single student including predictions, tasks, bundles,
    latest MCII intervention, and high-level task statistics for admin review.
    """
    student = db.query(Student).filter(Student.student_id == student_id).first()

    if not student:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "status_code": status.HTTP_404_NOT_FOUND,
                "title": status.HTTP_404_NOT_FOUND,
                "detail": "Student not found",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )
    # Cohort scope: only view students in this admin's cohort
    if student.admin_id != current_user["user_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    predictions = (
        db.query(Prediction)
        .filter(Prediction.student_id == student_id)
        .order_by(Prediction.prediction_date.desc())
        .limit(14)
        .all()
    )

    tasks = (
        db.query(Task)
        .filter(Task.student_id == student_id)
        .order_by(Task.due_date.desc())
        .limit(10)
        .all()
    )

    bundles = (
        db.query(WeeklyBundle)
        .filter(WeeklyBundle.student_id == student_id)
        .order_by(WeeklyBundle.week_number.desc())
        .all()
    )

    total_tasks = db.query(Task).filter(Task.student_id == student_id).count()
    completed_tasks = (
        db.query(Task)
        .filter(Task.student_id == student_id, Task.status == "completed")
        .count()
    )
    overdue_tasks = (
        db.query(Task)
        .filter(Task.student_id == student_id, Task.status == "overdue")
        .count()
    )

    task_stats = {
        "total": total_tasks,
        "completed": completed_tasks,
        "overdue": overdue_tasks,
    }

    latest_prediction = predictions[0] if predictions else None

    return templates.TemplateResponse(
        "admin_student_detail.html",
        {
            "request": request,
            "current_user": current_user,
            "student": student,
            "predictions": predictions,
            "tasks": tasks,
            "bundles": bundles,
            "task_stats": task_stats,
            "latest_prediction": latest_prediction,
        },
    )


# ── Auth Form Handlers 

@app.post("/auth/login")
async def handle_login(
    request: Request,
    email:    str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    pw_hash = hash_password(password)

    student = db.query(Student).filter(Student.email == email).first()
    if student and student.password_hash == pw_hash:
        request.session["user"] = {
            "user_id": student.student_id,
            "email":   student.email,
            "role":    "student"
        }
        db.add(BehavioralLog(student_id=student.student_id, login_time=datetime.now()))
        db.commit()
        return RedirectResponse(url="/student/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    admin = db.query(Admin).filter(Admin.email == email).first()
    if admin and admin.password_hash == pw_hash:
        request.session["user"] = {
            "user_id": admin.admin_id,
            "email":   admin.email,
            "role":    "admin"
        }
        return RedirectResponse(url="/admin/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid email or password", "form_email": email},
        status_code=status.HTTP_400_BAD_REQUEST
    )


@app.post("/auth/signup")
async def handle_signup(
    request:       Request,
    name:          str = Form(...),
    email:         str = Form(...),
    password:      str = Form(...),
    prior_profile: str = Form(default="mixed"),
    invite_code:   str = Form(default=""),
    db: Session = Depends(get_db),
):
    if db.query(Student).filter(Student.email == email).first():
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "An account with this email already exists"},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    admin_id_val: Optional[int] = None
    if invite_code and (code_clean := invite_code.strip()):
        admin_by_code = db.query(Admin).filter(Admin.invite_code == code_clean).first()
        if not admin_by_code:
            return templates.TemplateResponse(
                "signup.html",
                {"request": request, "error": "Invalid invite code. Please check the code or leave it blank to sign up without a course."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        admin_id_val = admin_by_code.admin_id

    student = Student(
        email=email,
        full_name=name,
        password_hash=hash_password(password),
        enrollment_date=date.today(),
        current_risk_level="low",
        prior_profile=prior_profile,
        days_active=0,
        admin_id=admin_id_val,
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    create_initial_bundle(student.student_id, db)

    request.session["user"] = {
        "user_id": student.student_id,
        "email":   student.email,
        "role":    "student"
    }
    return RedirectResponse(url="/student/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/auth/logout")
async def handle_logout(
    request: Request,
    db: Session = Depends(get_db)
):
    user = request.session.get("user")
    if user and user["role"] == "student":
        recent_log = (
            db.query(BehavioralLog)
            .filter(BehavioralLog.student_id == user["user_id"], BehavioralLog.logout_time.is_(None))
            .order_by(BehavioralLog.login_time.desc())
            .first()
        )
        if recent_log:
            recent_log.logout_time = datetime.now()
            recent_log.session_duration = int(
                (recent_log.logout_time - recent_log.login_time).total_seconds()
            )
            db.commit()

    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


# ── Task Form Handlers 

@app.post("/student/tasks/create")
async def create_task(
    request: Request,
    title: str = Form(...),
    due_date: Optional[str] = Form(default=""),
    description: str = Form(default=""),
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db),
):
    due_date_val: Optional[date] = None
    if due_date and due_date.strip():
        try:
            due_date_val = datetime.strptime(due_date.strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    active_bundle = (
        db.query(WeeklyBundle)
        .filter(WeeklyBundle.student_id == current_user["user_id"], WeeklyBundle.is_closed == 0)
        .first()
    )
    task = Task(
        student_id=current_user["user_id"],
        bundle_id=active_bundle.bundle_id if active_bundle else None,
        title=title,
        description=description or None,
        due_date=due_date_val,
        status="pending",
        task_type="personal",
        is_admin_assigned=False,
    )
    db.add(task)
    db.commit()
    return RedirectResponse(url="/student/tasks", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/student/tasks/{task_id}/toggle")
async def toggle_task(
    task_id:     int,
    request:     Request,
    current_user: dict  = Depends(require_student),
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(
        Task.task_id == task_id,
        Task.student_id == current_user["user_id"]
    ).first()

    if task:
        if task.status == "completed":
            task.status = "pending"
            task.completed_at = None
        else:
            task.status = "completed"
            task.completed_at = datetime.now()
        db.commit()

    referer = request.headers.get("referer", "/student/dashboard")
    return RedirectResponse(url=referer, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/student/tasks/{task_id}/delete")
async def delete_task(
    task_id:     int,
    request:     Request,
    current_user: dict  = Depends(require_student),
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(
        Task.task_id    == task_id,
        Task.student_id == current_user["user_id"]
    ).first()
    if task:
        db.delete(task)
        db.commit()
    return RedirectResponse(url="/student/tasks", status_code=status.HTTP_303_SEE_OTHER)


# ── Prediction API 
# Kept as a JSON endpoint because it's compute-heavy and called on-demand.

# prediction endpoint 
@app.post("/api/predict/{student_id}", response_model=PredictionResponse)
async def generate_prediction(
    student_id:   int,
    request:      Request,
    current_user: dict    = Depends(require_student),
    db: Session           = Depends(get_db)
):
    """
    Runs the full inference pipeline for a student. Idempotent: if a prediction for today
    already exists, returns it without creating a duplicate.
    """
    if current_user["user_id"] != student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only generate predictions for yourself")

    student = db.query(Student).filter(Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    existing = (
        db.query(Prediction)
        .filter(
            Prediction.student_id == student_id,
            Prediction.prediction_date == date.today(),
        )
        .first()
    )
    if existing:
        return PredictionResponse.model_validate(existing)

    result = compute_prediction(student, db)
    if not result:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Model not available or no active bundle")

    pred = Prediction(
        student_id        = student_id,
        bundle_id         = result["bundle_id"],
        prediction_date   = date.today(),
        model_used        = result["model_used"],
        risk_level        = result["risk_level"],
        confidence_score  = result["confidence_score"],
        features_json     = result["features_json"],
    )
    db.add(pred)

    student.current_risk_level = result["risk_level"]
    db.commit()
    db.refresh(pred)

    return PredictionResponse.model_validate(pred)

    # return {
    #     "prediction_id":    pred.prediction_id,
    #     "risk_level":       result["risk_level"],
    #     "confidence_score": result["confidence_score"],
    #     "model_used":       result["model_used"],
    #     "features_used":    result["features_json"],
    # }


@app.get("/student/mcii/tip")
async def get_mcii_tip(
    request: Request,
    current_user: dict = Depends(require_student),
    db: Session = Depends(get_db),
):
    """
    Return a personalized MCII tip for the logged-in student based on today's prediction.
    Reuses any intervention already delivered today, otherwise generates, stores, and returns a new one.
    """
    try:
        today = date.today()

        existing = (
            db.query(MCIIIntervention)
            .filter(
                MCIIIntervention.student_id == current_user["user_id"],
                func.date(MCIIIntervention.delivery_time) == today,
            )
            .order_by(MCIIIntervention.delivery_time.desc())
            .first()
        )

        if existing:
            prediction = (
                db.query(Prediction)
                .filter(Prediction.prediction_id == existing.prediction_id)
                .first()
            )
            if prediction:
                return {
                    "tip": existing.prompt_text,
                    "risk_level": prediction.risk_level,
                    "confidence": float(prediction.confidence_score),
                }
            return {
                "tip": existing.prompt_text,
                "risk_level": "unknown",
                "confidence": 0.0,
            }

        latest_prediction = (
            db.query(Prediction)
            .filter(Prediction.student_id == current_user["user_id"])
            .order_by(Prediction.prediction_date.desc())
            .first()
        )

        if not latest_prediction:
            return {
                "tip": (
                    "We are still building your profile. "
                    "Add tasks to your weekly bundle and check back tomorrow for a personalized strategy."
                ),
                "risk_level": "unknown",
                "confidence": 0.0,
            }

        tip_text = generate_mcii_tip(
            risk_level=latest_prediction.risk_level,
            confidence_score=float(latest_prediction.confidence_score),
        )

        try:
            intervention = MCIIIntervention(
                prediction_id=latest_prediction.prediction_id,
                student_id=current_user["user_id"],
                prompt_text=tip_text,
            )
            db.add(intervention)
            db.commit()
        except Exception:
            db.rollback()

        return {
            "tip": tip_text,
            "risk_level": latest_prediction.risk_level,
            "confidence": float(latest_prediction.confidence_score),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate MCII tip at this time.",
        )


# ── Health Check 

@app.get("/api/health")
def health_check():
    return {
        "status":        "ok",
        "model_3window": "loaded" if model_3window else "not_loaded",
        "model_7window": "loaded" if model_7window else "not_loaded",
        "timestamp":     datetime.now().isoformat()
    }



# for HTTP exceptions
@app.exception_handler(StarletteHTTPException)
async def general_http_exception_handler(request: Request, exception: StarletteHTTPException):
    message = (
        exception.detail
        if exception.detail
        else "An error occurred. Please check your request and try again."
    )
    if exception.status_code in (401, 302):
        return RedirectResponse(url="/login", status_code=303)
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exception.status_code,
            content={"detail": message},
        )
    return templates.TemplateResponse("error.html", {
        "request": request,
        "status_code": exception.status_code,
        "title": exception.status_code,
        "detail": message
    }, status_code=exception.status_code)

# for unexpected crashes or errors
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc):
    return templates.TemplateResponse("error.html", {
        "request": request,
        "status_code": 500,
        "detail": "Something went wrong"
    }, status_code=500)

from fastapi.exceptions import RequestValidationError

# catches bad form data submitted
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exception):
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exception.errors()},
        )
    return templates.TemplateResponse("error.html", {
        "request": request,
        "status_code": 422,
        "detail": "Invalid form data submitted"
    }, status_code=422)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")