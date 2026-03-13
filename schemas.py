# from pydantic import BaseModel, EmailStr, Field
# from typing import Optional
# from datetime import datetime, date


# # ── Auth 

# class SignupRequest(BaseModel):
#     name:          str   = Field(..., min_length=2, max_length=100)
#     email:         EmailStr
#     password:      str   = Field(..., min_length=5)
#     prior_profile: str   = Field(default="mixed")


# class LoginRequest(BaseModel):
#     email:    EmailStr
#     password: str = Field(..., min_length=5)


# # ── Tasks 

# class TaskCreate(BaseModel):
#     title:       str           = Field(..., min_length=1, max_length=200)
#     due_date:    datetime
#     description: Optional[str] = None


# class TaskUpdate(BaseModel):
#     title:       Optional[str]      = Field(None, max_length=200)
#     description: Optional[str]      = None
#     due_date:    Optional[datetime] = None
#     status:      Optional[str]      = None


# # ── Profile 

# class ProfileUpdate(BaseModel):
#     full_name: str      = Field(..., min_length=2, max_length=100)
#     email:     EmailStr
#     bio:       Optional[str] = Field(None, max_length=500)



# # ── MCII Chat 

# class MCIIMessage(BaseModel):
#     message: str = Field(..., min_length=1, max_length=1000)


# # ── Prediction 
# class PredictionRequest(BaseModel):
#     student_id: int


# class PredictionResponse(BaseModel):
#     prediction_id: int
#     risk_level: str
#     confidence_score: float
#     model_used: str
#     prediction_date: date
#     features_json: Optional[dict]

#     model_config = {'protected_namespaces': (), 'from_attributes': True}

# class BundleResponse(BaseModel):
#     bundle_id: int
#     week_number: int
#     completion_rate: float
#     submitted_late: int
#     is_closed: int

#     model_config = {"from_attributes": True}

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime, date


# ── Auth 

class SignupRequest(BaseModel):
    name:          str   = Field(..., min_length=2, max_length=100)
    email:         EmailStr
    password:      str   = Field(..., min_length=5)
    prior_profile: str   = Field(default="mixed")


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str = Field(..., min_length=5)


# ── Tasks 

class TaskCreate(BaseModel):
    title:       str           = Field(..., min_length=1, max_length=200)
    due_date:    datetime
    description: Optional[str] = None


class TaskUpdate(BaseModel):
    title:       Optional[str]      = Field(None, max_length=200)
    description: Optional[str]      = None
    due_date:    Optional[datetime] = None
    status:      Optional[str]      = None


# ── Profile 

class ProfileUpdate(BaseModel):
    full_name: str      = Field(..., min_length=2, max_length=100)
    email:     EmailStr
    bio:       Optional[str] = Field(None, max_length=500)



# ── MCII Chat 

class MCIIMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)


# ── Prediction 
class PredictionRequest(BaseModel):
    student_id: int


class PredictionResponse(BaseModel):
    prediction_id: int
    risk_level: str
    confidence_score: float
    model_used: str
    prediction_date: date
    features_json: Optional[dict]

    model_config = {'protected_namespaces': (), 'from_attributes': True}

class BundleResponse(BaseModel):
    bundle_id: int
    week_number: int
    completion_rate: float
    submitted_late: int
    is_closed: int

    model_config = {"from_attributes": True}