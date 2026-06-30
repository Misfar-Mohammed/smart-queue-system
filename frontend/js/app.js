// Helper utilities for the Smart Queue App

// 1. Toast Notification Utility
const Toast = {
    show(message, type = 'info') {
        // Remove existing toast container if any
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'fixed bottom-5 right-5 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `p-4 rounded-xl shadow-xl backdrop-blur-md text-white font-medium transform translate-y-2 opacity-0 transition-all duration-300 pointer-events-auto flex items-center gap-2 `;
        
        // Colors & Icons based on type
        if (type === 'success') {
            toast.className += ' bg-emerald-500/90 border border-emerald-400/20';
            toast.innerHTML = `
                <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                <span>${message}</span>
            `;
        } else if (type === 'error') {
            toast.className += ' bg-rose-500/90 border border-rose-400/20';
            toast.innerHTML = `
                <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                <span>${message}</span>
            `;
        } else if (type === 'warning') {
            toast.className += ' bg-amber-500/90 border border-amber-400/20';
            toast.innerHTML = `
                <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                <span>${message}</span>
            `;
        } else {
            toast.className += ' bg-blue-600/90 border border-blue-500/20';
            toast.innerHTML = `
                <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                <span>${message}</span>
            `;
        }

        container.appendChild(toast);

        // Animate Entry
        setTimeout(() => {
            toast.classList.remove('translate-y-2', 'opacity-0');
        }, 10);

        // Animate Dismissal
        setTimeout(() => {
            toast.classList.add('translate-y-2', 'opacity-0');
            setTimeout(() => {
                toast.remove();
            }, 300);
        }, 3500);
    }
};

// 2. Auth Helper Methods
const Auth = {
    getToken() {
        return localStorage.getItem('shop_token');
    },
    
    setToken(token) {
        localStorage.setItem('shop_token', token);
    },
    
    setShop(shop) {
        localStorage.setItem('shop_data', JSON.stringify(shop));
    },
    
    getShop() {
        const data = localStorage.getItem('shop_data');
        return data ? JSON.parse(data) : null;
    },
    
    logout() {
        localStorage.removeItem('shop_token');
        localStorage.removeItem('shop_data');
        Toast.show('Logged out successfully', 'info');
        setTimeout(() => {
            window.location.href = 'login.html';
        }, 800);
    },
    
    isAuthenticated() {
        return !!this.getToken();
    },
    
    // Authenticated API request wrapper
    async fetch(endpoint, options = {}) {
        const token = this.getToken();
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        const config = {
            ...options,
            headers
        };
        
        try {
            const response = await fetch(`${CONFIG.API_BASE_URL}${endpoint}`, config);
            
            if (response.status === 401) {
                // Token expired or unauthorized
                localStorage.removeItem('shop_token');
                localStorage.removeItem('shop_data');
                window.location.href = 'login.html';
                throw new Error('Session expired. Please log in again.');
            }
            
            return response;
        } catch (error) {
            console.error('API Fetch Error:', error);
            throw error;
        }
    }
};

// 3. Time formatting utility
function formatTime(isoString) {
    if (!isoString) return '-';
    try {
        const date = new Date(isoString);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        return isoString;
    }
}

// 4. Custom API Base URL Modal setup (for local/testing setups)
function initApiConfigSettings() {
    const configBtn = document.getElementById('api-config-btn');
    if (!configBtn) return;
    
    configBtn.addEventListener('click', () => {
        const currentUrl = localStorage.getItem('CUSTOM_API_URL') || CONFIG.API_BASE_URL.replace(/\/api$/, '');
        const newUrl = prompt('Enter your Backend API base URL (e.g. https://your-backend.vercel.app):', currentUrl);
        
        if (newUrl !== null) {
            if (newUrl.trim() === '') {
                localStorage.removeItem('CUSTOM_API_URL');
                Toast.show('Resetting to default API connection', 'info');
            } else {
                try {
                    new URL(newUrl); // Validate format
                    localStorage.setItem('CUSTOM_API_URL', newUrl.trim());
                    Toast.show(`Connected backend API endpoint to: ${newUrl}`, 'success');
                } catch (e) {
                    alert('Invalid URL format! Please include http:// or https://');
                    return;
                }
            }
            setTimeout(() => window.location.reload(), 1000);
        }
    });
}

// Load config settings dynamically when DOM finishes loading
document.addEventListener('DOMContentLoaded', () => {
    initApiConfigSettings();
});
