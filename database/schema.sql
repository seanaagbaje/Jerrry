-- Students Table (modified)
CREATE TABLE Students (
    student_id          INT AUTO_INCREMENT PRIMARY KEY,
    email               VARCHAR(255) UNIQUE NOT NULL,
    password_hash       VARCHAR(255) NOT NULL,
    enrollment_date     DATE NOT NULL,
    current_risk_level  ENUM('low', 'medium', 'high') DEFAULT 'low',
    prior_profile       ENUM('early', 'mixed', 'lastminute') DEFAULT 'mixed',
    -- prior_profile set at signup from study habits question
    -- used to prepend synthetic bundle history for cold start
    days_active         INT DEFAULT 0,
    -- tracks how long student has been on platform
    -- determines which model to use: <4=baseline, 4-6=3window, 7+=7window
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- Admins Table (unchanged)
CREATE TABLE Admins (
    admin_id        INT AUTO_INCREMENT PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    department      VARCHAR(100) NULL,
    access_level    INT DEFAULT 1,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- Surveys Table (unchanged)
CREATE TABLE Surveys (
    survey_id       INT AUTO_INCREMENT PRIMARY KEY,
    student_id      INT UNIQUE NOT NULL,
    responses_json  JSON NOT NULL,
    completion_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (student_id) REFERENCES Students(student_id) ON DELETE CASCADE
);


-- Tasks Table (modified)
CREATE TABLE Tasks (
    task_id         INT AUTO_INCREMENT PRIMARY KEY,
    student_id      INT NOT NULL,
    bundle_id       INT NULL,
    -- which weekly bundle this task belongs to
    -- NULL means task not yet assigned to a bundle
    title           VARCHAR(200) NOT NULL,
    description     TEXT NULL,
    due_date        DATETIME NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP NULL,
    status          ENUM('pending', 'in_progress', 'completed', 'overdue') DEFAULT 'pending',

    FOREIGN KEY (student_id) REFERENCES Students(student_id) ON DELETE CASCADE,
    -- bundle_id foreign key added after WeeklyBundles table is created below

    INDEX idx_tasks_student_status (student_id, status),
    INDEX idx_tasks_bundle (bundle_id)
);


-- WeeklyBundles Table (NEW)
CREATE TABLE WeeklyBundles (
    bundle_id           INT AUTO_INCREMENT PRIMARY KEY,
    student_id          INT NOT NULL,
    week_number         INT NOT NULL,
    -- week 1, 2, 3... since student joined platform
    start_date          DATE NOT NULL,
    -- Monday of that week
    end_date            DATE NOT NULL,
    -- Sunday of that week (bundle deadline)
    tasks_total         INT DEFAULT 0,
    -- total tasks in bundle at snapshot time
    tasks_completed     INT DEFAULT 0,
    -- tasks completed by end_date
    tasks_late          INT DEFAULT 0,
    -- tasks not completed by end_date
    completion_rate     DECIMAL(4,3) DEFAULT 0.000,
    -- tasks_completed / tasks_total (0.000 to 1.000)
    submitted_late      TINYINT(1) DEFAULT 0,
    -- 1 if completion_rate < 1.0 at bundle close, 0 if all done
    -- this is the label equivalent to OULAD submitted_late
    is_closed           TINYINT(1) DEFAULT 0,
    -- 0 = bundle still in progress, 1 = snapshot taken (Sunday midnight)
    closed_at           TIMESTAMP NULL,
    -- when the background job ran and froze this bundle
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (student_id) REFERENCES Students(student_id) ON DELETE CASCADE,
    UNIQUE KEY uk_bundle_student_week (student_id, week_number),
    INDEX idx_bundle_student_closed (student_id, is_closed),
    INDEX idx_bundle_end_date (end_date)
);


-- Add foreign key to Tasks now that WeeklyBundles exists
ALTER TABLE Tasks
    ADD CONSTRAINT fk_tasks_bundle
    FOREIGN KEY (bundle_id) REFERENCES WeeklyBundles(bundle_id) ON DELETE SET NULL;


-- BehavioralLogs Table (unchanged)
CREATE TABLE BehavioralLogs (
    log_id           INT AUTO_INCREMENT PRIMARY KEY,
    student_id       INT NOT NULL,
    login_time       TIMESTAMP NOT NULL,
    logout_time      TIMESTAMP NULL,
    pages_visited    INT DEFAULT 0,
    session_duration INT NULL,

    FOREIGN KEY (student_id) REFERENCES Students(student_id) ON DELETE CASCADE,

    INDEX idx_logs_student_time (student_id, login_time)
);


-- Predictions Table (modified)
CREATE TABLE Predictions (
    prediction_id        INT AUTO_INCREMENT PRIMARY KEY,
    student_id           INT NOT NULL,
    bundle_id            INT NULL,
    -- which bundle this prediction is for
    -- NULL for day 1-3 baseline predictions
    prediction_date      DATE NOT NULL,
    model_used           ENUM('baseline', '3window', '7window') NOT NULL,
    -- which model generated this prediction
    -- baseline = days 1-3, 3window = days 4-6, 7window = day 7+
    risk_level           ENUM('low', 'medium', 'high') NOT NULL,
    confidence_score     DECIMAL(3,2) NOT NULL,
    attention_weights_json JSON NULL,
    -- attention weights from Bahdanau layer
    -- shows which of the 7 bundles the model focused on
    features_json        JSON NULL,
    -- snapshot of the 5 features used for this prediction
    -- useful for debugging and for displaying to student

    FOREIGN KEY (student_id) REFERENCES Students(student_id) ON DELETE CASCADE,
    FOREIGN KEY (bundle_id)  REFERENCES WeeklyBundles(bundle_id) ON DELETE SET NULL,

    INDEX idx_predictions_student_date (student_id, prediction_date)
);


-- MCIIInterventions Table (unchanged)
CREATE TABLE MCIIInterventions (
    intervention_id  INT AUTO_INCREMENT PRIMARY KEY,
    prediction_id    INT NOT NULL,
    student_id       INT NOT NULL,
    prompt_text      TEXT NOT NULL,
    delivery_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_response    TEXT NULL,
    was_helpful      BOOLEAN NULL,

    FOREIGN KEY (prediction_id) REFERENCES Predictions(prediction_id) ON DELETE CASCADE,
    FOREIGN KEY (student_id)    REFERENCES Students(student_id) ON DELETE CASCADE,

    INDEX idx_mcii_student_time (student_id, delivery_time)
);

-- Add full_name if not already done
ALTER TABLE Students 
ADD COLUMN IF NOT EXISTS full_name VARCHAR(100) NULL AFTER email;

-- Add phone, profile_pic, bio for profile editing
ALTER TABLE Students ADD COLUMN phone VARCHAR(20) NULL;
ALTER TABLE Students ADD COLUMN profile_pic VARCHAR(255) NULL;
ALTER TABLE Students ADD COLUMN bio TEXT NULL;