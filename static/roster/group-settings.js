/**
 * Group Settings Page JavaScript
 */

// Get group ID from URL
const urlParams = new URLSearchParams(window.location.search);
const groupId = window.location.pathname.split('/').pop().split('?')[0];
const serverId = parseInt(urlParams.get('server_id'));
const ROSTER_TOKEN = urlParams.get('token');

// Save basic settings
async function saveBasicSettings() {
    try {
        const maxAccounts = document.getElementById('group-max-accounts').value;

        const data = {};
        if (maxAccounts && maxAccounts.trim() !== '') {
            data.max_accounts_per_user = parseInt(maxAccounts);
        } else {
            data.max_accounts_per_user = null;
        }

        await apiCall(`${API_BASE}/roster-group/${groupId}?server_id=${serverId}`, 'PATCH', data);
        showAlert('Settings saved successfully!');

        // Refresh after a short delay to show the alert
        setTimeout(() => window.location.reload(), 1000);
    } catch (error) {
        console.error('Error saving settings:', error);
        showAlert('Failed to save settings: ' + error.message, 'error');
    }
}

// Group reminder functions
function showAddGroupReminder() {
    showAlert('Group reminders coming soon!', 'info');
    // TODO: Implement group reminder creation
}

async function loadGroupReminders() {
    const remindersList = document.getElementById('group-reminders-list');
    if (!remindersList) return;

    try {
        // TODO: Load group automations/reminders
        // const reminders = await apiCall(`${API_BASE}/roster-automation?group_id=${groupId}&server_id=${serverId}`);

        remindersList.innerHTML = `
            <div class="text-center py-8 text-muted-foreground">
                <i data-lucide="bell-off" class="w-12 h-12 mx-auto mb-3 opacity-50"></i>
                <p class="text-sm">No group reminders configured</p>
                <p class="text-xs mt-1">Click "Add Reminder" to create one</p>
            </div>
        `;

        // Re-render icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    } catch (error) {
        console.error('Error loading group reminders:', error);
        remindersList.innerHTML = `
            <div class="text-center py-4 text-sm text-destructive">
                Failed to load reminders
            </div>
        `;
    }
}

// Initialize page
document.addEventListener('DOMContentLoaded', () => {
    loadGroupReminders();
});
