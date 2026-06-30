// Smart Queue System API Configuration
const CONFIG = {
    get API_BASE_URL() {
        // 1. Check if user configured a custom API URL in the UI
        const customUrl = localStorage.getItem('CUSTOM_API_URL');
        if (customUrl) {
            return customUrl.replace(/\/$/, '') + '/api';
        }
        
        // 2. Default to localhost for local development
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            return 'http://localhost:5000/api';
        }
        
        // 3. Fallback/Production URL (this will point to their backend deployment)
        // Users can easily customize this through the Settings gear on the Landing/Dashboard page.
        return 'https://smart-queue-system-ashen.vercel.app/api'; 
    }
};
