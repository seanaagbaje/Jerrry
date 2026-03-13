// API base URL configuration
const API_BASE_URL = 'http://localhost:8000';

// Token management utilities
const TokenManager = {
    // Store JWT token in localStorage
    setToken(token) {
        localStorage.setItem('access_token', token);
    },
    
    // Retrieve JWT token from localStorage
    getToken() {
        return localStorage.getItem('access_token');
    },
    
    // Remove token from localStorage
    removeToken() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user_id');
        localStorage.removeItem('user_role');
        localStorage.removeItem('user_email');
    },
    
    // Check if user is authenticated
    isAuthenticated() {
        return !!this.getToken();
    },
    
    // Get authorization header for API requests
    getAuthHeader() {
        const token = this.getToken();
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }
};

// User data management
const UserManager = {
    // Store user information
    setUser(userId, role, email) {
        localStorage.setItem('user_id', userId);
        localStorage.setItem('user_role', role);
        localStorage.setItem('user_email', email);
    },
    
    // Get current user ID
    getUserId() {
        return localStorage.getItem('user_id');
    },
    
    // Get current user role
    getUserRole() {
        return localStorage.getItem('user_role');
    },
    
    // Get current user email
    getUserEmail() {
        return localStorage.getItem('user_email');
    },
    
    // Clear all user data
    clearUser() {
        TokenManager.removeToken();
    }
};

// Login form handler
async function handleLogin(event) {
    event.preventDefault();
    
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const errorMessage = document.getElementById('error-message');
    const loginButton = document.getElementById('login-button');
    
    // Clear previous error messages
    if (errorMessage) {
        errorMessage.textContent = '';
        errorMessage.style.display = 'none';
    }
    
    // Disable button during request
    if (loginButton) {
        loginButton.disabled = true;
        loginButton.textContent = 'Signing in...';
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email, password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Store authentication data
            TokenManager.setToken(data.access_token);
            UserManager.setUser(data.user_id, data.role, data.email);
            
            // Redirect based on user role
            if (data.role === 'student') {
                window.location.href = '/student/dashboard';
            } else if (data.role === 'admin') {
                window.location.href = '/admin/dashboard';
            }
        } else {
            // Show error message
            if (errorMessage) {
                errorMessage.textContent = data.detail || 'Invalid email or password';
                errorMessage.style.display = 'block';
            }
        }
    } catch (error) {
        console.error('Login error:', error);
        if (errorMessage) {
            errorMessage.textContent = 'Network error. Please check your connection and try again.';
            errorMessage.style.display = 'block';
        }
    } finally {
        // Re-enable button
        if (loginButton) {
            loginButton.disabled = false;
            loginButton.textContent = 'Sign In';
        }
    }
}

// Signup form handler
async function handleSignup(event) {
    event.preventDefault();
    
    const name = document.getElementById('name').value;
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirm-password')?.value;
    const errorMessage = document.getElementById('error-message');
    const signupButton = document.getElementById('signup-button');
    
    // Clear previous error messages
    if (errorMessage) {
        errorMessage.textContent = '';
        errorMessage.style.display = 'none';
    }
    
    // Client-side validation
    if (password.length < 6) {
        if (errorMessage) {
            errorMessage.textContent = 'Password must be at least 6 characters long';
            errorMessage.style.display = 'block';
        }
        return;
    }
    
    if (confirmPassword && password !== confirmPassword) {
        if (errorMessage) {
            errorMessage.textContent = 'Passwords do not match';
            errorMessage.style.display = 'block';
        }
        return;
    }
    
    // Disable button during request
    if (signupButton) {
        signupButton.disabled = true;
        signupButton.textContent = 'Creating account...';
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/auth/signup`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ name, email, password })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Store authentication data
            TokenManager.setToken(data.access_token);
            UserManager.setUser(data.user_id, data.role, data.email);
            
            // Redirect to student dashboard
            window.location.href = '/student/dashboard';
        } else {
            // Show error message
            if (errorMessage) {
                errorMessage.textContent = data.detail || 'Signup failed. Please try again.';
                errorMessage.style.display = 'block';
            }
        }
    } catch (error) {
        console.error('Signup error:', error);
        if (errorMessage) {
            errorMessage.textContent = 'Network error. Please check your connection and try again.';
            errorMessage.style.display = 'block';
        }
    } finally {
        // Re-enable button
        if (signupButton) {
            signupButton.disabled = false;
            signupButton.textContent = 'Create Account';
        }
    }
}

// Logout handler
async function handleLogout() {
    try {
        // Call logout endpoint
        await fetch(`${API_BASE_URL}/api/auth/logout`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...TokenManager.getAuthHeader()
            }
        });
    } catch (error) {
        console.error('Logout error:', error);
    } finally {
        // Clear local storage and redirect regardless of API call result
        UserManager.clearUser();
        window.location.href = '/';
    }
}

// Check authentication status and redirect if needed
function requireAuth() {
    if (!TokenManager.isAuthenticated()) {
        window.location.href = '/';
        return false;
    }
    return true;
}

// Check if user has required role
function requireRole(requiredRole) {
    if (!requireAuth()) return false;
    
    const userRole = UserManager.getUserRole();
    if (userRole !== requiredRole) {
        // Redirect to appropriate dashboard
        if (userRole === 'student') {
            window.location.href = '/student/dashboard';
        } else if (userRole === 'admin') {
            window.location.href = '/admin/dashboard';
        } else {
            window.location.href = '/';
        }
        return false;
    }
    return true;
}

// Redirect to login if already authenticated
function redirectIfAuthenticated() {
    if (TokenManager.isAuthenticated()) {
        const role = UserManager.getUserRole();
        if (role === 'student') {
            window.location.href = '/student/dashboard';
        } else if (role === 'admin') {
            window.location.href = '/admin/dashboard';
        }
    }
}

// Initialize authentication on page load
document.addEventListener('DOMContentLoaded', function() {
    // Attach event listeners for login form
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        redirectIfAuthenticated();
        loginForm.addEventListener('submit', handleLogin);
    }
    
    // Attach event listeners for signup form
    const signupForm = document.getElementById('signup-form');
    if (signupForm) {
        redirectIfAuthenticated();
        signupForm.addEventListener('submit', handleSignup);
    }
    
    // Attach event listeners for logout buttons
    const logoutButtons = document.querySelectorAll('[data-logout]');
    logoutButtons.forEach(button => {
        button.addEventListener('click', handleLogout);
    });
});