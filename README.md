# ProActive - AI-Powered Student Productivity Platform

**Master your time with AI-driven predictive tracking**

ProActive uses BiLSTM neural networks and Mental Contrasting Implementation Intentions (MCII) to help students identify procrastination patterns before they become missed deadlines.

## 🎥 Video Demo

[https://drive.google.com/file/d/19wgmgCOhaH6As0hXxTeW66HzxtqUESZx/view?usp=sharing]

---

## 🚀 Features

### Student Features
- **AI Procrastination Prediction**: BiLSTM model analyzes engagement patterns to predict task delays
- **MCII Intervention Assistant**: Chat-based cognitive behavioral intervention using proven psychological frameworks
- **Smart Task Management**: Priority-based task organization with AI-driven recommendations
- **Personalized Dashboard**: Real-time insights on study velocity, weekly activity, and productivity metrics
- **Risk Alerts**: Proactive notifications for assignments at risk of delay

### Admin Features
- **Student Monitoring Dashboard**: Track student performance across courses
- **High-Risk Alert System**: Identify students requiring immediate attention (42 high-risk alerts)
- **MCII Engagement Tracking**: Monitor platform engagement (86% current rate)
- **Performance Analytics**: View average progress (74.2%) and trends
- **Detailed Activity Logs**: Individual risk levels, courses, and last active timestamps

---

## 🏗️ Tech Stack

### Backend
- **FastAPI** - High-performance Python web framework
- **MySQL** - Relational database for user and task management
- **TensorFlow/Keras** - BiLSTM model training and serving
- **Scikit-learn** - Feature preprocessing and encoding

### Frontend
- **HTML/CSS/JavaScript** - Responsive UI components
- **Fetch API** - RESTful communication with backend

### Machine Learning
- **BiLSTM Neural Network** - Sequential pattern recognition for procrastination prediction
- **Label Encoding** - Categorical feature transformation
- **Standard Scaling** - Feature normalization
- **Training Data**: Open University Learning Analytics Dataset (OULAD)

---

## 📁 Project Structure

```
ProActive/
├── backend/
│   ├── main.py                    # FastAPI server & endpoints
│   ├── database/
│   │   └── schema.sql            # MySQL database schema
│   └── models/
│       └── saved_models/
│           ├── procrastination_bilstm.h5
│           ├── label_encoder.pkl
│           └── scaler.pkl
├── frontend/
│   ├── student_dashboard.html
│   ├── admin_dashboard.html
│   ├── mcii_chat.html
│   ├── tasks.html
│   ├── login.html
│   ├── signup.html
│   └── js/
│       ├── auth.js
│       └── dashboard.js
├── data/
│   ├── oulad/                    # Raw OULAD dataset
│   └── processed/                # Preprocessed features
├── ml_notebooks/
│   └── oulad_analysis_v2.ipynb  # Model training notebook
└── requirements.txt
```

---

## 🛠️ Installation & Setup

### Prerequisites
```bash
Python 3.8+
MySQL 8.0+
pip package manager
```

### 1. Clone Repository
```bash
git clone https://github.com/yourusername/proactive.git
cd proactive
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Database Setup
```bash
# Create database
mysql -u root -p
CREATE DATABASE proactive_db;
USE proactive_db;
SOURCE backend/database/schema.sql;
exit;
```

### 4. Run Backend Server
```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Access Application
Open browser to `http://localhost:8000`

---

## 🗄️ Database Schema

### Core Tables
- **Students**: User authentication, enrollment data, risk levels
- **Admins**: Admin authentication and access control
- **Tasks**: Student task management with status tracking
- **Predictions**: AI-generated risk predictions with confidence scores
- **MCIIInterventions**: MCII prompts and student responses
- **BehavioralLogs**: Session tracking and engagement metrics
- **Surveys**: Student survey responses (JSON format)

### Key Relationships
- Students ← Tasks (1:N)
- Students ← Predictions (1:N)
- Predictions ← MCIIInterventions (1:N)
- Students ← BehavioralLogs (1:N)

---

## 🧠 ML Model Architecture

### BiLSTM Procrastination Predictor

**Input Features:**
- VLE interaction counts
- Assignment submission timing
- Assessment scores
- Study session duration
- Task completion velocity

**Architecture:**
- Bidirectional LSTM layers
- Dropout for regularization
- Dense layers with softmax activation
- Output: Risk classification (Low/Medium/High) + confidence score

**Training:**
- Dataset: OULAD (32,593 students, 22 courses)
- Validation split: 80/20
- Loss: Categorical crossentropy
- Optimizer: Adam

**Model Artifacts:**
```
backend/models/saved_models/
├── procrastination_bilstm.h5  # Trained model weights
├── label_encoder.pkl           # Risk level encoder
└── scaler.pkl                  # Feature scaler
```

---

## 🔌 API Endpoints

### Authentication
```
POST   /api/auth/signup       # Create student account
POST   /api/auth/login        # User login
POST   /api/auth/logout       # End session
```

### Student Operations
```
GET    /api/student/profile   # Get student data
PUT    /api/student/profile   # Update profile
GET    /api/student/tasks     # Fetch tasks
POST   /api/student/tasks     # Create task
PATCH  /api/student/tasks/:id # Update task status
```

### AI Predictions
```
GET    /api/predictions/:student_id  # Get risk predictions
POST   /api/predict                  # Generate new prediction
```

### MCII Interventions
```
GET    /api/mcii/interventions       # Get intervention history
POST   /api/mcii/chat                # MCII conversation endpoint
```

### Admin Dashboard
```
GET    /api/admin/dashboard          # Analytics overview
GET    /api/admin/students           # Student list with risk levels
GET    /api/admin/reports            # Export reports
```

---

## ✅ Implementation Status

### Completed
- ✅ FastAPI backend server with routing
- ✅ User authentication (signup/login)
- ✅ MySQL database schema
- ✅ BiLSTM model training pipeline
- ✅ Model serialization (H5, PKL files)
- ✅ Frontend UI for all views
- ✅ Navigation between pages
- ✅ MCII intervention interface

### In Progress
- ⚠️ Model inference API integration
- ⚠️ Real-time prediction endpoint
- ⚠️ Task CRUD operations backend
- ⚠️ Admin dashboard live data

---

## 📊 MCII Framework

**Mental Contrasting and Implementation Intentions** - Evidence-based behavioral intervention:

1. **Goal Identification**: Student defines academic objective
2. **Obstacle Recognition**: AI guides identification of barriers
3. **Implementation Intention**: Creates "if-then" action plans
4. **Continuous Support**: 24/7 conversational assistance

**Example:**
- **Goal**: "Finish calculus assignment on time"
- **Obstacle**: "I keep checking social media"
- **Implementation**: "If I feel like browsing social media, then I will close my phone and focus for 10 minutes first"

---

## 📱 Screenshots

### Login & Signup
![Login Page](designs/screenshots/login.png)
*Secure authentication with email and password*

![Sign Up Page](designs/screenshots/sign_up.png)
*Student registration with AI-powered insights included*

### Student Dashboard
![Student Dashboard](designs/screenshots/student_dashboard.png)
*Real-time AI predictions, weekly activity graphs, and task prioritization*

### MCII Chat Interface
![MCII Intervention](designs/screenshots/mcii_intervention.png)
*Interactive intervention assistant using Mental Contrasting and Implementation Intentions framework*

### Task Management
![Tasks View](designs/screenshots/tasks.png)
*Priority-based task list with AI-driven scheduling recommendations*

### Student Profile
![Student Profile](designs/screenshots/student_profile.png)
*Personalized productivity insights and procrastination risk assessment*

### Admin Dashboard
![Admin Dashboard](designs/screenshots/admin_dashboard.png)
*Monitor 1,284 students, track 42 high-risk alerts, 86% MCII engagement*

---

## 🔬 Model Training Process

See `ml_notebooks/oulad_analysis_v2.ipynb` for complete training pipeline:

1. **Data Loading**: OULAD dataset ingestion
2. **Feature Engineering**: Extract engagement metrics
3. **Preprocessing**: Scaling, encoding, sequence padding
4. **Model Training**: BiLSTM architecture
5. **Evaluation**: Accuracy, precision, recall metrics
6. **Serialization**: Save model artifacts

---

## 🚀 Future Enhancements

- Real-time WebSocket notifications
- Mobile application (React Native)
- Advanced visualization dashboards
- Integration with LMS platforms (Canvas, Moodle)
- Multilingual MCII support
- Improved model accuracy with transfer learning

---

## 📄 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

- **OULAD Dataset**: Open University for learning analytics data
- **MCII Framework**: Research by Gabriele Oettingen and Peter Gollwitzer
- **Evidence-Based Design**: Educational psychology research

---

## 📧 Contact

For questions or feedback, please open an issue or contact the development team.

---

**Built with ❤️ for students struggling with procrastination**
