// API base URL configuration
const API_BASE_URL = 'http://localhost:8000';

// Get auth headers from auth.js TokenManager
function getAuthHeaders() {
    const token = localStorage.getItem('access_token');
    return {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
    };
}

// Display error message to user
function showError(message, elementId = 'error-message') {
    const errorElement = document.getElementById(elementId);
    if (errorElement) {
        errorElement.textContent = message;
        errorElement.style.display = 'block';
        
        // Auto-hide after 5 seconds
        setTimeout(() => {
            errorElement.style.display = 'none';
        }, 5000);
    }
}

// Display success message to user
function showSuccess(message, elementId = 'success-message') {
    const successElement = document.getElementById(elementId);
    if (successElement) {
        successElement.textContent = message;
        successElement.style.display = 'block';
        
        // Auto-hide after 3 seconds
        setTimeout(() => {
            successElement.style.display = 'none';
        }, 3000);
    }
}

// Student Dashboard Functions

// Load student dashboard data
async function loadStudentDashboard() {
    const userId = localStorage.getItem('user_id');
    if (!userId) {
        window.location.href = '/';
        return;
    }
    
    try {
        // Load student profile data
        const profileResponse = await fetch(`${API_BASE_URL}/api/students/${userId}`, {
            headers: getAuthHeaders()
        });
        
        if (profileResponse.ok) {
            const profileData = await profileResponse.json();
            updateDashboardUI(profileData);
        }
        
        // Load recent tasks
        await loadTasks();
        
        // Load recent predictions
        await loadPredictions(userId);
        
    } catch (error) {
        console.error('Error loading dashboard:', error);
        showError('Failed to load dashboard data');
    }
}

// Update dashboard UI with student data
function updateDashboardUI(data) {
    // Update student name/email
    const userNameElement = document.getElementById('user-name');
    if (userNameElement) {
        userNameElement.textContent = data.email.split('@')[0]; // Use email prefix as name
    }
    
    // Update risk level indicator
    const riskLevelElement = document.getElementById('risk-level');
    if (riskLevelElement && data.latest_prediction) {
        riskLevelElement.textContent = data.latest_prediction.risk_level.toUpperCase();
        riskLevelElement.className = `risk-${data.latest_prediction.risk_level}`;
    }
    
    // Update confidence score
    const confidenceElement = document.getElementById('confidence-score');
    if (confidenceElement && data.latest_prediction) {
        confidenceElement.textContent = `${Math.round(data.latest_prediction.confidence_score * 100)}%`;
    }
    
    // Update task completion stats
    const completionRateElement = document.getElementById('completion-rate');
    if (completionRateElement && data.task_stats) {
        completionRateElement.textContent = `${Math.round(data.task_stats.completion_rate)}%`;
    }
    
    const tasksCompletedElement = document.getElementById('tasks-completed');
    if (tasksCompletedElement && data.task_stats) {
        tasksCompletedElement.textContent = `${data.task_stats.completed}/${data.task_stats.total}`;
    }
}

// Task Management Functions

// Load tasks for current student
async function loadTasks(statusFilter = null) {
    const userId = localStorage.getItem('user_id');
    if (!userId) return;
    
    try {
        let url = `${API_BASE_URL}/api/tasks/${userId}`;
        if (statusFilter) {
            url += `?status_filter=${statusFilter}`;
        }
        
        const response = await fetch(url, {
            headers: getAuthHeaders()
        });
        
        if (response.ok) {
            const data = await response.json();
            displayTasks(data.tasks);
        } else {
            showError('Failed to load tasks');
        }
    } catch (error) {
        console.error('Error loading tasks:', error);
        showError('Failed to load tasks');
    }
}

// Display tasks in the UI
function displayTasks(tasks) {
    const tasksContainer = document.getElementById('tasks-container');
    if (!tasksContainer) return;
    
    if (tasks.length === 0) {
        tasksContainer.innerHTML = '<p class="no-tasks">No tasks found. Add your first task!</p>';
        return;
    }
    
    tasksContainer.innerHTML = tasks.map(task => `
        <div class="task-item ${task.status}" data-task-id="${task.task_id}">
            <div class="task-header">
                <input type="checkbox" 
                       class="task-checkbox" 
                       ${task.status === 'completed' ? 'checked' : ''} 
                       onchange="toggleTaskStatus(${task.task_id}, this.checked)">
                <h3 class="task-title">${escapeHtml(task.title)}</h3>
                <span class="task-status ${task.status}">${task.status}</span>
            </div>
            ${task.description ? `<p class="task-description">${escapeHtml(task.description)}</p>` : ''}
            <div class="task-footer">
                <span class="task-due-date">Due: ${formatDate(task.due_date)}</span>
                <div class="task-actions">
                    <button onclick="editTask(${task.task_id})" class="btn-edit">Edit</button>
                    <button onclick="deleteTask(${task.task_id})" class="btn-delete">Delete</button>
                </div>
            </div>
        </div>
    `).join('');
}

// Create a new task
async function createTask(event) {
    event.preventDefault();
    
    const userId = localStorage.getItem('user_id');
    const title = document.getElementById('task-title').value;
    const description = document.getElementById('task-description')?.value || '';
    const dueDate = document.getElementById('task-due-date').value;
    
    if (!title || !dueDate) {
        showError('Please fill in all required fields');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/tasks`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                student_id: parseInt(userId),
                title: title,
                description: description,
                due_date: dueDate,
                status: 'pending'
            })
        });
        
        if (response.ok) {
            showSuccess('Task created successfully');
            
            // Clear form
            document.getElementById('task-form').reset();
            
            // Close modal if exists
            const modal = document.getElementById('task-modal');
            if (modal) modal.style.display = 'none';
            
            // Reload tasks
            await loadTasks();
        } else {
            const error = await response.json();
            showError(error.detail || 'Failed to create task');
        }
    } catch (error) {
        console.error('Error creating task:', error);
        showError('Failed to create task');
    }
}

// Toggle task completion status
async function toggleTaskStatus(taskId, isCompleted) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                status: isCompleted ? 'completed' : 'pending',
                completed_at: isCompleted ? new Date().toISOString() : null
            })
        });
        
        if (response.ok) {
            showSuccess('Task updated');
            await loadTasks();
        } else {
            showError('Failed to update task');
        }
    } catch (error) {
        console.error('Error updating task:', error);
        showError('Failed to update task');
    }
}

// Delete a task
async function deleteTask(taskId) {
    if (!confirm('Are you sure you want to delete this task?')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}`, {
            method: 'DELETE',
            headers: getAuthHeaders()
        });
        
        if (response.ok) {
            showSuccess('Task deleted');
            await loadTasks();
        } else {
            showError('Failed to delete task');
        }
    } catch (error) {
        console.error('Error deleting task:', error);
        showError('Failed to delete task');
    }
}

// Edit task (you can expand this to show an edit modal)
function editTask(taskId) {
    // This is a placeholder - implement edit modal based on your UI
    console.log('Edit task:', taskId);
    showError('Edit functionality coming soon');
}

// Prediction Functions

// Load prediction history
async function loadPredictions(studentId) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/predictions/${studentId}?limit=5`, {
            headers: getAuthHeaders()
        });
        
        if (response.ok) {
            const data = await response.json();
            displayPredictionHistory(data.predictions);
        }
    } catch (error) {
        console.error('Error loading predictions:', error);
    }
}

// Display prediction history
function displayPredictionHistory(predictions) {
    const container = document.getElementById('prediction-history');
    if (!container) return;
    
    if (predictions.length === 0) {
        container.innerHTML = '<p>No predictions yet</p>';
        return;
    }
    
    container.innerHTML = predictions.map(pred => `
        <div class="prediction-item">
            <span class="prediction-date">${formatDate(pred.prediction_date)}</span>
            <span class="prediction-risk ${pred.risk_level}">${pred.risk_level.toUpperCase()}</span>
            <span class="prediction-confidence">${Math.round(pred.confidence_score * 100)}%</span>
        </div>
    `).join('');
}

// Generate new prediction
async function generatePrediction() {
    const userId = localStorage.getItem('user_id');
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/predict`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                student_id: parseInt(userId),
                behavioral_data: {
                    late_rate: 0.3,
                    irregularity: 0.25,
                    last_min_ratio: 0.4,
                    avg_gap: 2.5
                }
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            showSuccess('Prediction generated successfully');
            await loadStudentDashboard();
        } else {
            showError('Failed to generate prediction');
        }
    } catch (error) {
        console.error('Error generating prediction:', error);
        showError('Failed to generate prediction');
    }
}

// Admin Dashboard Functions

// Load admin dashboard stats
async function loadAdminDashboard() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/admin/dashboard/stats`, {
            headers: getAuthHeaders()
        });
        
        if (response.ok) {
            const data = await response.json();
            updateAdminDashboardUI(data);
        }
        
        // Load all students
        await loadAllStudents();
        
    } catch (error) {
        console.error('Error loading admin dashboard:', error);
        showError('Failed to load dashboard data');
    }
}

// Update admin dashboard UI
function updateAdminDashboardUI(stats) {
    const elements = {
        'total-students': stats.total_students,
        'high-risk-alerts': stats.high_risk_alerts,
        'mcii-engagement': `${stats.mcii_engagement}%`,
        'avg-progress': `${stats.avg_progress}%`
    };
    
    Object.entries(elements).forEach(([id, value]) => {
        const element = document.getElementById(id);
        if (element) element.textContent = value;
    });
}

// Load all students for admin view
async function loadAllStudents() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/admin/students`, {
            headers: getAuthHeaders()
        });
        
        if (response.ok) {
            const data = await response.json();
            displayStudentsList(data.students);
        }
    } catch (error) {
        console.error('Error loading students:', error);
        showError('Failed to load students');
    }
}

// Display students list in admin dashboard
function displayStudentsList(students) {
    const container = document.getElementById('students-list');
    if (!container) return;
    
    if (students.length === 0) {
        container.innerHTML = '<p>No students found</p>';
        return;
    }
    
    container.innerHTML = students.map(student => `
        <div class="student-item">
            <div class="student-info">
                <span class="student-email">${escapeHtml(student.email)}</span>
                <span class="student-date">Enrolled: ${formatDate(student.enrollment_date)}</span>
            </div>
            <span class="student-risk ${student.current_risk_level}">${student.current_risk_level.toUpperCase()}</span>
            ${student.latest_prediction ? `
                <span class="student-confidence">${Math.round(student.latest_prediction.confidence_score * 100)}%</span>
            ` : ''}
            <button onclick="viewStudentDetail(${student.student_id})" class="btn-view">View Detail</button>
        </div>
    `).join('');
}

// View individual student details (admin)
function viewStudentDetail(studentId) {
    // Navigate to student detail page or show modal
    console.log('View student:', studentId);
    showError('Student detail view coming soon');
}

// Utility Functions

// Escape HTML to prevent XSS
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Format date for display
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Initialize dashboard based on page
document.addEventListener('DOMContentLoaded', function() {
    // Check authentication
    const token = localStorage.getItem('access_token');
    const role = localStorage.getItem('user_role');
    
    if (!token) {
        window.location.href = '/';
        return;
    }
    
    // Load appropriate dashboard
    if (window.location.pathname.includes('/student/dashboard')) {
        if (role !== 'student') {
            window.location.href = '/admin/dashboard';
            return;
        }
        loadStudentDashboard();
    } else if (window.location.pathname.includes('/admin/dashboard')) {
        if (role !== 'admin') {
            window.location.href = '/student/dashboard';
            return;
        }
        loadAdminDashboard();
    } else if (window.location.pathname.includes('/student/tasks')) {
        if (role !== 'student') {
            window.location.href = '/';
            return;
        }
        loadTasks();
    }
    
    // Attach task form handler
    const taskForm = document.getElementById('task-form');
    if (taskForm) {
        taskForm.addEventListener('submit', createTask);
    }
    
    // Attach filter handlers
    const filterButtons = document.querySelectorAll('[data-filter]');
    filterButtons.forEach(button => {
        button.addEventListener('click', function() {
            const filter = this.dataset.filter;
            loadTasks(filter === 'all' ? null : filter);
        });
    });
});