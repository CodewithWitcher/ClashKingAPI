/**
 * Groups and Categories Management Functions
 */

// Switch to a specific roster
function switchToRoster(rosterId) {
    // Force the Settings tab to be shown when switching to a roster
    localStorage.setItem('roster-current-tab', 'settings');

    // Build the roster dashboard URL with proper parameters
    const url = new URL('/ui/roster/dashboard', window.location.origin);
    url.searchParams.set('server_id', serverId);
    url.searchParams.set('token', ROSTER_TOKEN);
    url.searchParams.set('roster_id', rosterId);
    window.location.href = url.toString();
}

// Modal management
function showCreateGroupModal() {
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.getElementById('create-group-modal').classList.remove('hidden');
}

function showCreateCategoryModal() {
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.getElementById('create-category-modal').classList.remove('hidden');
}

function closeModals() {
    document.getElementById('modal-overlay').classList.add('hidden');
    document.getElementById('create-group-modal').classList.add('hidden');
    document.getElementById('create-category-modal').classList.add('hidden');
    document.getElementById('group-settings-modal').classList.add('hidden');
}

// Group settings management
let currentGroupId = null;
let currentGroupName = '';

function showGroupSettings(groupId, groupName, maxAccounts) {
    currentGroupId = groupId;
    currentGroupName = groupName;

    // Hide list view, show settings view
    document.getElementById('groups-list-view').classList.add('hidden');
    document.getElementById('group-settings-view').classList.remove('hidden');

    // Set group name
    const nameElement = document.getElementById('group-settings-name');
    if (nameElement) {
        nameElement.textContent = groupName;
    }

    // Set max accounts value
    const maxAccountsInput = document.getElementById('group-max-accounts');
    if (maxAccountsInput) {
        maxAccountsInput.value = maxAccounts || '';
    }

    // Load group data
    loadGroupRosters(groupId);
    loadGroupReminders(groupId);

    // Re-render icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function hideGroupSettings() {
    // Show list view, hide settings view
    document.getElementById('groups-list-view').classList.remove('hidden');
    document.getElementById('group-settings-view').classList.add('hidden');

    currentGroupId = null;
    currentGroupName = '';
}

function closeGroupSettingsModal() {
    const modalOverlay = document.getElementById('group-settings-modal-overlay');
    if (modalOverlay) {
        modalOverlay.classList.add('hidden');
    }
}

async function saveGroupSettings() {
    if (!currentGroupId) return;

    try {
        const maxAccounts = document.getElementById('group-max-accounts').value;

        const data = {};
        if (maxAccounts && maxAccounts.trim() !== '') {
            data.max_accounts_per_user = parseInt(maxAccounts);
        } else {
            data.max_accounts_per_user = null;
        }

        await apiCall(`${API_BASE}/roster-group/${currentGroupId}?server_id=${serverId}`, 'PATCH', data);
        showAlert('Group settings saved successfully!');

        // Stay on the settings page - no reload needed
    } catch (error) {
        console.error('Error saving group settings:', error);
        showAlert('Failed to save group settings: ' + error.message, 'error');
    }
}

async function loadGroupRosters(groupId) {
    const rostersList = document.getElementById('group-rosters-list');
    if (!rostersList) return;

    try {
        // Use the rosters already loaded in the page
        const allRostersData = typeof allRosters !== 'undefined' ? allRosters : [];

        // Filter rosters by group_id
        const groupRosters = allRostersData.filter(r => r.group_id === groupId);

        if (groupRosters.length > 0) {
            rostersList.innerHTML = groupRosters.map(roster => {
                const memberCount = roster.members ? roster.members.length : 0;
                const clanInfo = roster.clan_tag ? roster.clan_tag : 'No clan';

                return `
                    <div class="flex items-center justify-between p-3 bg-muted/30 rounded-lg hover:bg-muted/50 transition-colors">
                        <div class="flex items-center gap-3 flex-1">
                            <div class="w-2 h-2 rounded-full bg-primary"></div>
                            <div class="flex-1">
                                <div class="font-medium text-sm">${roster.alias}</div>
                                <div class="text-xs text-muted-foreground">
                                    ${memberCount} member${memberCount !== 1 ? 's' : ''} • ${clanInfo}
                                </div>
                            </div>
                        </div>
                        <button onclick="switchToRoster('${roster.custom_id}')"
                                class="px-3 py-1 bg-secondary hover:bg-secondary/80 rounded text-xs transition-colors">
                            View
                        </button>
                    </div>
                `;
            }).join('');
        } else {
            rostersList.innerHTML = `
                <div class="text-center py-8 text-muted-foreground">
                    <i data-lucide="folder-open" class="w-12 h-12 mx-auto mb-3 opacity-50"></i>
                    <p class="text-sm">No rosters in this group yet</p>
                </div>
            `;
        }

        // Re-render icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    } catch (error) {
        console.error('Error loading group rosters:', error);
        rostersList.innerHTML = `
            <div class="text-center py-4 text-sm text-destructive">
                Failed to load rosters: ${error.message}
            </div>
        `;
    }
}

async function loadGroupReminders(groupId) {
    const remindersList = document.getElementById('group-reminders-list');
    if (!remindersList) return;

    try {
        // Load automations for this group (including inactive ones)
        const response = await fetch(`${API_BASE}/roster-automation/list?group_id=${groupId}&server_id=${serverId}&active_only=false`, {
            headers: { 'Authorization': `Bearer ${ROSTER_TOKEN}` }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const reminders = data.items || [];

        if (reminders && reminders.length > 0) {
            remindersList.innerHTML = reminders.map(reminder => {
                const isActive = reminder.active;
                const indicatorClass = isActive ?
                    'w-2 h-2 rounded-full bg-green-500' :
                    'w-2 h-2 rounded-full bg-gray-400';

                const targetLabels = {
                    'not_signed_up_any': 'Not signed up in any roster',
                    'signed_up_any': 'Signed up in any roster'
                };

                const targetText = targetLabels[reminder.options?.ping_target] || reminder.options?.ping_target || 'Unknown';

                // Handle both days_before and days_after
                let timingText = '';
                if (reminder.options?.days_after !== undefined) {
                    const days = reminder.options.days_after;
                    timingText = days === 0 ? 'At event time' : `${days} day${days > 1 ? 's' : ''} after`;
                } else {
                    const days = reminder.options?.days_before || 0;
                    timingText = days === 0 ? 'At event time' : `${days} day${days > 1 ? 's' : ''} before`;
                }

                return `
                    <div class="bg-muted/30 rounded-lg p-4 ${!isActive ? 'opacity-60' : ''}">
                        <div class="flex items-center justify-between">
                            <div class="flex items-center gap-3 flex-1">
                                <div class="${indicatorClass}" title="${isActive ? 'Active' : 'Inactive'}"></div>
                                <div class="flex-1">
                                    <div class="text-sm font-medium text-foreground">${timingText}</div>
                                    <div class="text-xs text-muted-foreground mt-0.5">
                                        ${targetText}
                                    </div>
                                    ${reminder.options?.message ? `<div class="text-xs text-muted-foreground mt-1 italic">"${reminder.options.message}"</div>` : ''}
                                </div>
                            </div>
                            <div class="flex items-center gap-1">
                                <button onclick="toggleGroupReminderActive('${reminder.automation_id}', ${!isActive})"
                                        class="p-1.5 hover:bg-accent rounded ${isActive ? 'text-green-600' : 'text-muted-foreground'} hover:text-foreground"
                                        title="${isActive ? 'Disable' : 'Enable'}">
                                    <i data-lucide="${isActive ? 'toggle-right' : 'toggle-left'}" class="w-4 h-4"></i>
                                </button>
                                <button onclick="editGroupReminder('${reminder.automation_id}')"
                                        class="p-1.5 hover:bg-accent rounded text-muted-foreground hover:text-foreground"
                                        title="Edit">
                                    <i data-lucide="edit" class="w-4 h-4"></i>
                                </button>
                                <button onclick="deleteGroupReminder('${reminder.automation_id}')"
                                        class="p-1.5 hover:bg-accent rounded text-red-400 hover:text-red-300"
                                        title="Delete">
                                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        } else {
            remindersList.innerHTML = `
                <div class="text-center py-8 text-muted-foreground">
                    <i data-lucide="bell-off" class="w-12 h-12 mx-auto mb-3 opacity-50"></i>
                    <p class="text-sm">No group reminders configured</p>
                    <p class="text-xs mt-1">Click "Add Reminder" to create one</p>
                </div>
            `;
        }

        // Re-render icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    } catch (error) {
        console.error('Error loading group reminders:', error);
        remindersList.innerHTML = `
            <div class="text-center py-4 text-sm text-destructive">
                Failed to load reminders: ${error.message}
            </div>
        `;
    }
}

async function showAddGroupReminder() {
    // Load Discord channels if not already loaded
    if (typeof loadDiscordChannels === 'function') {
        await loadDiscordChannels();
    }

    // Show the modal
    const modal = document.getElementById('group-reminder-modal');
    if (modal) {
        modal.classList.remove('hidden');

        // Clear editing state
        delete modal.dataset.editingAutomationId;

        // Reset modal title
        const titleElement = document.getElementById('group-reminder-modal-title');
        if (titleElement) {
            titleElement.textContent = 'Add Group Reminder';
        }

        // Reset button text to "Create"
        const saveButton = document.getElementById('group-reminder-save-btn');
        if (saveButton) {
            saveButton.textContent = 'Create Reminder';
        }

        // Reset form values
        const daysInput = document.getElementById('group-reminder-days');
        if (daysInput) {
            daysInput.value = 3;
        }

        const timingSelect = document.getElementById('group-reminder-timing');
        if (timingSelect) {
            timingSelect.value = 'before';
        }

        const targetSelect = document.getElementById('group-reminder-target');
        if (targetSelect) {
            targetSelect.value = 'not_signed_up_any';
        }

        const messageInput = document.getElementById('group-reminder-message');
        if (messageInput) {
            messageInput.value = '';
        }

        // Populate channel selector
        const channelContainer = document.getElementById('group-reminder-channel-selector');
        if (channelContainer && typeof renderChannelSelector === 'function') {
            channelContainer.innerHTML = renderChannelSelector('');
        }

        // Re-render icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

function closeGroupReminderModal() {
    const modal = document.getElementById('group-reminder-modal');
    if (modal) {
        modal.classList.add('hidden');
        // Clear editing state
        delete modal.dataset.editingAutomationId;
    }
}

async function saveGroupReminder() {
    if (!currentGroupId) {
        showAlert('No group selected', 'error');
        return;
    }

    try {
        const days = parseInt(document.getElementById('group-reminder-days').value || 3);
        const timing = document.getElementById('group-reminder-timing').value; // 'before' or 'after'
        const channelId = document.getElementById('modal-channel-id')?.value;
        const target = document.getElementById('group-reminder-target').value;
        const message = document.getElementById('group-reminder-message').value;

        if (!channelId) {
            showAlert('Please select a Discord channel', 'error');
            return;
        }

        // Check if we're editing an existing reminder
        const modal = document.getElementById('group-reminder-modal');
        const editingAutomationId = modal?.dataset.editingAutomationId;

        // For group reminders, we need the earliest event time from all rosters in the group
        // For now, we'll use a placeholder - this should be calculated server-side
        const scheduledTime = Math.floor(Date.now() / 1000) + (days * 24 * 60 * 60);

        const options = {
            ping_target: target,
            ...(message && { message })
        };

        // Set either days_before or days_after
        if (timing === 'after') {
            options.days_after = days;
        } else {
            options.days_before = days;
        }

        let response;
        if (editingAutomationId) {
            // Update existing reminder - only send updatable fields
            const updateData = {
                scheduled_time: scheduledTime,
                discord_channel_id: channelId,
                options: options
            };

            response = await fetch(`${API_BASE}/roster-automation/${editingAutomationId}?server_id=${serverId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${ROSTER_TOKEN}`
                },
                body: JSON.stringify(updateData)
            });
        } else {
            // Create new reminder - include all required fields
            const createData = {
                server_id: serverId,
                group_id: currentGroupId,
                action_type: 'roster_ping',
                scheduled_time: scheduledTime,
                discord_channel_id: channelId,
                options: options
            };

            response = await fetch(`${API_BASE}/roster-automation`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${ROSTER_TOKEN}`
                },
                body: JSON.stringify(createData)
            });
        }

        if (!response.ok) {
            const error = await response.json();
            console.error('Validation error response:', error);

            // Handle Pydantic validation errors (array of objects)
            let errorMessage = `HTTP ${response.status}`;
            if (error.detail) {
                if (Array.isArray(error.detail)) {
                    // Format validation errors
                    errorMessage = error.detail.map(err => {
                        const field = err.loc ? err.loc.join('.') : 'unknown';
                        return `${field}: ${err.msg}`;
                    }).join(', ');
                } else if (typeof error.detail === 'string') {
                    errorMessage = error.detail;
                } else {
                    errorMessage = JSON.stringify(error.detail);
                }
            }
            throw new Error(errorMessage);
        }

        showAlert(editingAutomationId ? 'Group reminder updated successfully!' : 'Group reminder created successfully!');
        closeGroupReminderModal();
        loadGroupReminders(currentGroupId);

    } catch (error) {
        console.error('Error saving group reminder:', error);
        showAlert(`Failed to save reminder: ${error.message}`, 'error');
    }
}

async function toggleGroupReminderActive(automationId, newState) {
    try {
        const response = await fetch(`${API_BASE}/roster-automation/${automationId}?server_id=${serverId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${ROSTER_TOKEN}`
            },
            body: JSON.stringify({
                active: newState
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        showAlert(`Reminder ${newState ? 'enabled' : 'disabled'} successfully!`);
        loadGroupReminders(currentGroupId);

    } catch (error) {
        console.error('Error toggling reminder:', error);
        showAlert(`Failed to toggle reminder: ${error.message}`, 'error');
    }
}

async function deleteGroupReminder(automationId) {
    if (!confirm('Are you sure you want to delete this reminder?')) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/roster-automation/${automationId}?server_id=${serverId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${ROSTER_TOKEN}` }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        showAlert('Reminder deleted successfully!');
        loadGroupReminders(currentGroupId);

    } catch (error) {
        console.error('Error deleting reminder:', error);
        showAlert(`Failed to delete reminder: ${error.message}`, 'error');
    }
}

async function editGroupReminder(automationId) {
    // Find the reminder to edit (including inactive ones)
    const response = await fetch(`${API_BASE}/roster-automation/list?group_id=${currentGroupId}&server_id=${serverId}&active_only=false`, {
        headers: { 'Authorization': `Bearer ${ROSTER_TOKEN}` }
    });
    const data = await response.json();
    const reminders = data.items || [];
    const reminder = reminders.find(r => r.automation_id === automationId);

    if (!reminder) {
        showAlert('Reminder not found', 'error');
        return;
    }

    // Load Discord channels if not already loaded
    if (typeof loadDiscordChannels === 'function') {
        await loadDiscordChannels();
    }

    // Show the modal with pre-filled values
    const modal = document.getElementById('group-reminder-modal');
    if (modal) {
        modal.classList.remove('hidden');

        // Set the modal title to indicate editing
        const titleElement = document.getElementById('group-reminder-modal-title');
        if (titleElement) {
            titleElement.textContent = 'Edit Group Reminder';
        }

        // Set button text to "Update"
        const saveButton = document.getElementById('group-reminder-save-btn');
        if (saveButton) {
            saveButton.textContent = 'Update Reminder';
        }

        // Pre-fill form values
        const daysInput = document.getElementById('group-reminder-days');
        const timingSelect = document.getElementById('group-reminder-timing');

        if (reminder.options?.days_after !== undefined) {
            if (daysInput) daysInput.value = reminder.options.days_after;
            if (timingSelect) timingSelect.value = 'after';
        } else {
            if (daysInput) daysInput.value = reminder.options?.days_before || 3;
            if (timingSelect) timingSelect.value = 'before';
        }

        const targetSelect = document.getElementById('group-reminder-target');
        if (targetSelect) {
            targetSelect.value = reminder.options?.ping_target || 'not_signed_up_any';
        }

        const messageInput = document.getElementById('group-reminder-message');
        if (messageInput) {
            messageInput.value = reminder.options?.message || '';
        }

        // Populate channel selector
        const channelContainer = document.getElementById('group-reminder-channel-selector');
        if (channelContainer && typeof renderChannelSelector === 'function') {
            channelContainer.innerHTML = renderChannelSelector(reminder.discord_channel_id || '');
        }

        // Store the automation ID for updating
        modal.dataset.editingAutomationId = automationId;

        // Re-render icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

// Create new group
async function createGroup(event) {
    event.preventDefault();

    const formData = new FormData(event.target);
    const data = {
        alias: formData.get('alias')
        // server_id goes in query params, not body
    };

    try {
        await apiCall(`${API_BASE}/roster-group?server_id=${serverId}`, 'POST', data);
        showAlert('Group created successfully!');
        closeModals();

        // Refresh the page to show the new group
        window.location.reload();
    } catch (error) {
        console.error('Error creating group:', error);
        showAlert('Failed to create group: ' + error.message, 'error');
    }
}

// Create new category
async function createCategory(event) {
    event.preventDefault();

    const formData = new FormData(event.target);
    const data = {
        alias: formData.get('alias')
        // server_id goes in query params, not body
    };

    try {
        await apiCall(`${API_BASE}/roster-signup-category?server_id=${serverId}`, 'POST', data);
        showAlert('Category created successfully!');
        closeModals();

        // Refresh the page to show the new category
        window.location.reload();
    } catch (error) {
        console.error('Error creating category:', error);
        showAlert('Failed to create category: ' + error.message, 'error');
    }
}

// Delete group
async function deleteGroup(groupId) {
    if (!confirm('Are you sure you want to delete this group? This action cannot be undone.')) {
        return;
    }
    
    try {
        await apiCall(`${API_BASE}/roster-group/${groupId}?server_id=${serverId}`, 'DELETE');
        showAlert('Group deleted successfully!');
        
        // Refresh the page to reflect changes
        window.location.reload();
    } catch (error) {
        console.error('Error deleting group:', error);
        showAlert('Failed to delete group: ' + error.message, 'error');
    }
}

// Delete category
async function deleteCategory(customId) {
    if (!confirm('Are you sure you want to delete this category? This action cannot be undone.')) {
        return;
    }
    
    try {
        await apiCall(`${API_BASE}/roster-signup-category/${customId}?server_id=${serverId}`, 'DELETE');
        showAlert('Category deleted successfully!');
        
        // Refresh the page to reflect changes
        window.location.reload();
    } catch (error) {
        console.error('Error deleting category:', error);
        showAlert('Failed to delete category: ' + error.message, 'error');
    }
}

// Close modals on Escape key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        closeModals();
    }
});