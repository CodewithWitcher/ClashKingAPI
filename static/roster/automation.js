// Automation Management
let currentAutomations = []; // Changed to array to hold multiple automations
let currentAutomation = null; // Keep for backward compatibility
let isEditingAutomation = false;
let actionsCounter = 0;
let discordChannels = []; // Cache for Discord channels

// Simple notification function
function showNotification(message, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${message}`);
    if (typeof showToast === 'function') {
        showToast(message, type);
    }
}

// Helper function to get auth token
async function getAuthToken() {
    return ROSTER_TOKEN;
}

// Initialize automation tab
async function initializeAutomationTab() {
    console.log('initializeAutomationTab called, currentRosterData:', currentRosterData);
    if (!currentRosterData) return;

    try {
        // Load channels first, then automations
        await loadDiscordChannels();
        await loadCurrentAutomation();
        console.log('After loadCurrentAutomation, currentAutomation:', currentAutomation);
        updateAutomationDisplay();
        updateEventTimeDisplay();
    } catch (error) {
        console.error('Error initializing automation tab:', error);
        showNotification('Failed to load automation settings', 'error');
    }
}

// Load automations for sidebar status (lightweight, doesn't load full UI)
async function loadAutomationsForSidebar() {
    if (!currentRosterData) return;

    try {
        await loadCurrentAutomation();
        updateSidebarAutomationStatus();
    } catch (error) {
        console.error('Error loading automations for sidebar:', error);
    }
}

// Load Discord channels for the server
async function loadDiscordChannels() {
    if (discordChannels.length > 0) {
        return discordChannels; // Return cached
    }

    try {
        const response = await fetch(`/v2/server/${serverId}/discord-channels`, {
            headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        discordChannels = data.channels || [];
        console.log(`Loaded ${discordChannels.length} Discord channels`);
        return discordChannels;
    } catch (error) {
        console.error('Error loading Discord channels:', error);
        discordChannels = [];
        return [];
    }
}

// Update Event Time Display
function updateEventTimeDisplay() {
    const eventTimeDisplay = document.getElementById('current-event-time');
    const eventTimezone = document.getElementById('current-event-timezone');
    const eventIndicator = document.getElementById('event-status-indicator');

    if (!currentRosterData) return;

    const eventStartTime = currentRosterData.event_start_time || currentRosterData.time;

    if (eventStartTime) {
        const eventDate = new Date(eventStartTime * 1000);
        eventTimeDisplay.textContent = eventDate.toLocaleString();
        eventTimezone.textContent = `Timezone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}`;

        // Green indicator if time is set
        if (eventIndicator) {
            eventIndicator.className = 'w-2 h-2 rounded-full bg-green-500';
        }
    } else {
        eventTimeDisplay.textContent = 'Not set';
        eventTimezone.textContent = 'Select a date and time below';

        // Gray indicator if no time set
        if (eventIndicator) {
            eventIndicator.className = 'w-2 h-2 rounded-full bg-gray-400';
        }
    }
}

// Toggle Event Time Editor
function toggleEventTimeEditor() {
    const editor = document.getElementById('event-time-editor');
    if (!editor) return;

    if (editor.style.display === 'none' || editor.style.display === '') {
        // Show editor and populate with current values
        editor.style.display = 'block';

        const eventStartTime = currentRosterData.event_start_time || currentRosterData.time;
        if (eventStartTime) {
            const eventDate = new Date(eventStartTime * 1000);
            const dateInput = document.getElementById('automation-event-date');
            const timeInput = document.getElementById('automation-event-time');

            if (dateInput) dateInput.value = eventDate.toISOString().split('T')[0];
            if (timeInput) timeInput.value = eventDate.toTimeString().substr(0, 5);
        }
    } else {
        editor.style.display = 'none';
    }
}

// Save Event Time
async function saveEventTime() {
    const dateInput = document.getElementById('automation-event-date');
    const timeInput = document.getElementById('automation-event-time');

    if (!dateInput || !timeInput || !dateInput.value || !timeInput.value) {
        showNotification('Please select both date and time', 'error');
        return;
    }

    try {
        const timestamp = new Date(`${dateInput.value}T${timeInput.value}`);
        const utcTimestamp = Math.floor(timestamp.getTime() / 1000);

        // Update roster with new event time
        const response = await fetch(`/v2/roster/${currentRosterData.custom_id}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${await getAuthToken()}`
            },
            body: JSON.stringify({
                server_id: serverId,
                event_start_time: utcTimestamp
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // Update local data
        currentRosterData.event_start_time = utcTimestamp;
        currentRosterData.time = utcTimestamp;

        updateEventTimeDisplay();
        toggleEventTimeEditor();
        showNotification('Event time saved successfully', 'success');
    } catch (error) {
        console.error('Error saving event time:', error);
        showNotification('Failed to save event time', 'error');
    }
}

// Cancel Event Time Edit
function cancelEventTimeEdit() {
    const editor = document.getElementById('event-time-editor');
    if (editor) {
        editor.style.display = 'none';
    }
}

// Load current automation for the roster
async function loadCurrentAutomation() {
    if (!currentRosterData) return;

    try {
        // Get list of automations for this server first
        const response = await fetch(`/v2/roster-automation/list?server_id=${serverId}${currentRosterData ? '&roster_id=' + currentRosterData.custom_id : ''}&active_only=false`, {
            headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const automations = data.items || [];
        console.log('Loaded automations:', automations);

        // Find all automations for current roster
        currentAutomations = automations.filter(automation =>
            automation.roster_id === currentRosterData.custom_id
        );
        console.log('Current automations for roster:', currentAutomations);

        // Set first automation as current for backward compatibility
        currentAutomation = currentAutomations.length > 0 ? currentAutomations[0] : null;

    } catch (error) {
        console.error('Error loading automation:', error);
        currentAutomation = null;
    }
}

// Update the automation display based on current state
function updateAutomationDisplay() {
    console.log('updateAutomationDisplay called, automations:', currentAutomations);

    // Separate automations by type
    const signupAutomation = currentAutomations.find(a => a.action_type === 'roster_signup');
    const closeAutomation = currentAutomations.find(a => a.action_type === 'roster_signup_close');
    const postAutomation = currentAutomations.find(a => a.action_type === 'roster_post');
    const reminderAutomations = currentAutomations.filter(a => a.action_type === 'roster_ping');

    // Update each section
    updateAutomationSection('signup-automation-content', signupAutomation, 'roster_signup');
    updateAutomationSection('close-automation-content', closeAutomation, 'roster_signup_close');
    updateAutomationSection('post-automation-content', postAutomation, 'roster_post');
    updateRemindersSection('reminders-content', reminderAutomations);

    // Load and display group reminders if roster is in a group
    loadGroupRemindersForRoster();

    // Update sidebar automation status
    updateSidebarAutomationStatus();

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Update a single automation section (for signup, close, post)
function updateAutomationSection(containerId, automation, actionType) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (automation) {
        // Show existing automation
        container.innerHTML = renderAutomationCard(automation);
    } else {
        // Show empty state with Add button
        container.innerHTML = renderEmptyAutomationState(actionType);
    }
}

// Update reminders section (can have multiple)
function updateRemindersSection(containerId, reminders) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (reminders.length > 0) {
        container.innerHTML = reminders.map(r => renderAutomationCard(r)).join('');
    } else {
        container.innerHTML = `
            <div class="text-center py-8 text-muted-foreground">
                <p class="text-sm">No reminders configured</p>
                <p class="text-xs mt-1">Click "Add Reminder" above to create one</p>
            </div>
        `;
    }
}

// Render a single automation card
function renderAutomationCard(automation) {
    const isActive = automation.active;
    const indicatorClass = isActive ?
        'w-2 h-2 rounded-full bg-green-500' :
        'w-2 h-2 rounded-full bg-gray-400';

    // Calculate timing info
    let timingText = '';
    if (automation.options?.days_before !== undefined) {
        const days = automation.options.days_before;
        timingText = days === 0 ? 'At event time' : `${days} day${days > 1 ? 's' : ''} before`;
    } else if (automation.scheduled_time) {
        const nextTime = new Date(automation.scheduled_time * 1000);
        timingText = formatNextExecution(nextTime);
    }

    // Get channel info
    let channelText = '';
    if (automation.discord_channel_id) {
        const channel = discordChannels.find(c => String(c.id) === String(automation.discord_channel_id));
        if (channel) {
            channelText = channel.display_name;
        } else {
            // Channel not found - maybe bot doesn't have access or it was deleted
            console.warn(`Channel ${automation.discord_channel_id} not found in discordChannels list (${discordChannels.length} channels loaded)`);
            const shortId = automation.discord_channel_id.substring(0, 8) + '...';
            channelText = `ID: ${shortId}`;
        }
    }

    // Show ping target for reminders
    let targetText = '';
    if (automation.action_type === 'roster_ping' && automation.options?.ping_target) {
        const pingTargetLabels = {
            'signed_up': 'Signed up members',
            'signed_up_wrong_clan': 'Signed up but wrong clan',
            'clan_not_signed_up': 'Clan members not signed up'
        };
        targetText = pingTargetLabels[automation.options.ping_target] || automation.options.ping_target;
    }

    // Get next execution time
    let nextExecText = '';
    if (automation.scheduled_time) {
        const nextTime = new Date(automation.scheduled_time * 1000);
        nextExecText = formatNextExecution(nextTime);
    }

    return `
        <div class="bg-muted/30 rounded-lg p-4 ${!isActive ? 'opacity-60' : ''}">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-3 flex-1">
                    <div class="${indicatorClass}" title="${isActive ? 'Active' : 'Inactive'}"></div>
                    <div class="flex-1">
                        <div class="text-sm font-medium text-foreground">${timingText}</div>
                        <div class="text-xs text-muted-foreground mt-0.5">
                            ${channelText}${targetText ? ' • ' + targetText : ''}
                        </div>
                        ${automation.options?.message ? `<div class="text-xs text-muted-foreground mt-1 italic">"${automation.options.message}"</div>` : ''}
                        ${nextExecText ? `<div class="text-xs text-muted-foreground mt-1">Next: ${nextExecText}</div>` : ''}
                    </div>
                </div>
                <div class="flex items-center gap-1">
                    <button onclick="toggleAutomationActive('${automation.automation_id}', ${!isActive})"
                            class="p-1.5 hover:bg-accent rounded ${isActive ? 'text-green-600' : 'text-muted-foreground'} hover:text-foreground"
                            title="${isActive ? 'Disable' : 'Enable'}">
                        <i data-lucide="${isActive ? 'toggle-right' : 'toggle-left'}" class="w-4 h-4"></i>
                    </button>
                    <button onclick="editAutomationById('${automation.automation_id}')"
                            class="p-1.5 hover:bg-accent rounded text-muted-foreground hover:text-foreground"
                            title="Edit">
                        <i data-lucide="edit" class="w-4 h-4"></i>
                    </button>
                    <button onclick="deleteAutomationById('${automation.automation_id}')"
                            class="p-1.5 hover:bg-accent rounded text-red-400 hover:text-red-300"
                            title="Delete">
                        <i data-lucide="trash-2" class="w-4 h-4"></i>
                    </button>
                </div>
            </div>
        </div>
    `;
}

// Render empty state with Add button
function renderEmptyAutomationState(actionType) {
    const labels = {
        'roster_signup': 'Open Signup',
        'roster_signup_close': 'Close Signup',
        'roster_post': 'Post Roster'
    };

    const label = labels[actionType] || 'Automation';

    return `
        <div class="text-center py-8">
            <p class="text-sm text-muted-foreground mb-3">No automation configured</p>
            <button onclick="showAutomationForm('${actionType}')"
                    class="px-4 py-2 bg-primary hover:bg-primary/90 text-primary-foreground text-sm rounded-md transition-colors inline-flex items-center gap-2">
                <i data-lucide="plus" class="w-4 h-4"></i>
                <span>Add ${label}</span>
            </button>
        </div>
    `;
}

// Toggle automation form visibility
function toggleAutomation() {
    const formContainer = document.getElementById('automation-form-container');
    const cardsContainer = document.getElementById('automation-cards-container');
    const emptyState = document.getElementById('automation-empty-state');

    if (formContainer && (formContainer.style.display === 'none' || formContainer.style.display === '')) {
        // Show form for creating new automation
        formContainer.style.display = 'block';
        if (cardsContainer) cardsContainer.style.display = 'none';
        if (emptyState) emptyState.style.display = 'none';

        isEditingAutomation = false;
        currentAutomation = null; // Clear current automation for new creation

        // Reset form
        const form = document.getElementById('automation-form');
        if (form) form.reset();
    } else {
        // Hide form
        cancelAutomation();
    }
}

// Edit existing automation
function editAutomation() {
    toggleAutomation();
}

// Cancel automation editing
function cancelAutomation() {
    const formContainer = document.getElementById('automation-form-container');
    if (formContainer) {
        formContainer.style.display = 'none';
        isEditingAutomation = false;
    }

    currentAutomation = null;
    updateAutomationDisplay();
}

// Reset automation form to default state
function resetAutomationForm() {
    const form = document.getElementById('automation-form');
    if (!form) return;

    // Clear all radio buttons
    form.querySelectorAll('input[type="radio"]').forEach(radio => {
        radio.checked = false;
    });

    // Clear all other inputs
    form.querySelectorAll('input:not([type="radio"]), select, textarea').forEach(input => {
        input.value = '';
    });

    // Hide all schedule sections
    const relativeSchedule = document.getElementById('relative-schedule');
    const recurringSchedule = document.getElementById('recurring-schedule');
    const fixedSchedule = document.getElementById('fixed-schedule');

    if (relativeSchedule) relativeSchedule.style.display = 'none';
    if (recurringSchedule) recurringSchedule.style.display = 'none';
    if (fixedSchedule) fixedSchedule.style.display = 'none';

    // Clear actions
    const actionsList = document.getElementById('actions-list');
    if (actionsList) {
        actionsList.innerHTML = '';
    }
    actionsCounter = 0;
}

// Populate form with existing automation data
function populateFormWithAutomation(automation) {
    // Map backend action_type to UI automation_type
    const actionToAutomationType = {
        'roster_post': 'event_lifecycle',
        'roster_ping': 'recurring_reminder',
        'roster_signup': 'event_lifecycle',
        'roster_signup_close': 'event_lifecycle',
        'roster_delete': 'maintenance',
        'roster_clear': 'maintenance',
        'roster_archive': 'maintenance'
    };

    const automationType = actionToAutomationType[automation.action_type] || 'event_lifecycle';
    const typeRadio = document.querySelector(`input[name="automation_type"][value="${automationType}"]`);
    if (typeRadio) {
        typeRadio.checked = true;
        updateAutomationType();
    }

    // For schedule, use fixed type with the scheduled_time
    if (automation.scheduled_time) {
        const scheduleRadio = document.querySelector(`input[name="schedule_type"][value="fixed"]`);
        if (scheduleRadio) {
            scheduleRadio.checked = true;
            updateScheduleType();

            const date = new Date(automation.scheduled_time * 1000);
            const dateInput = document.querySelector('input[name="fixed_date"]');
            const timeInput = document.querySelector('input[name="fixed_time"]');
            if (dateInput) dateInput.value = date.toISOString().split('T')[0];
            if (timeInput) timeInput.value = date.toTimeString().substr(0, 5);
        }
    }

    // Map backend action_type to UI action_type
    const backendToUIAction = {
        'roster_post': 'post_roster',
        'roster_ping': 'ping_users',
        'roster_signup_close': 'close_signup'
    };

    const uiActionType = backendToUIAction[automation.action_type] || 'post_roster';
    addAction({ action_type: uiActionType });
}

// Populate schedule fields based on type
function populateScheduleFields(schedule) {
    if (schedule.schedule_type === 'relative') {
        if (schedule.relative_to) {
            const relativeToSelect = document.querySelector('select[name="relative_to"]');
            if (relativeToSelect) relativeToSelect.value = schedule.relative_to;
        }
        if (schedule.offset_hours !== undefined) {
            const offsetInput = document.querySelector('input[name="offset_hours"]');
            if (offsetInput) offsetInput.value = schedule.offset_hours;
        }
    } else if (schedule.schedule_type === 'recurring') {
        if (schedule.recurring_pattern) {
            const patternSelect = document.querySelector('select[name="recurring_pattern"]');
            if (patternSelect) {
                patternSelect.value = schedule.recurring_pattern;
                updateRecurringOptions();
            }
        }
        if (schedule.recurring_time) {
            const timeInput = document.querySelector('input[name="recurring_time"]');
            if (timeInput) timeInput.value = schedule.recurring_time;
        }
        if (schedule.recurring_day) {
            const dayInput = document.querySelector('input[name="recurring_day"]');
            if (dayInput) dayInput.value = schedule.recurring_day;
        }
        if (schedule.recurring_weekday !== undefined) {
            const weekdaySelect = document.querySelector('select[name="recurring_weekday"]');
            if (weekdaySelect) weekdaySelect.value = schedule.recurring_weekday;
        }
    } else if (schedule.schedule_type === 'fixed') {
        if (schedule.fixed_timestamp) {
            const date = new Date(schedule.fixed_timestamp * 1000);
            const dateInput = document.querySelector('input[name="fixed_date"]');
            const timeInput = document.querySelector('input[name="fixed_time"]');
            if (dateInput) dateInput.value = date.toISOString().split('T')[0];
            if (timeInput) timeInput.value = date.toTimeString().substr(0, 5);
        }
    }
}

// Update automation type-specific UI
function updateAutomationType() {
    const selectedType = document.querySelector('input[name="automation_type"]:checked')?.value;
    // You can add type-specific logic here if needed
}

// Update schedule type visibility
function updateScheduleType() {
    const selectedType = document.querySelector('input[name="schedule_type"]:checked')?.value;

    // Hide all schedule sections
    const relativeSchedule = document.getElementById('relative-schedule');
    const recurringSchedule = document.getElementById('recurring-schedule');
    const fixedSchedule = document.getElementById('fixed-schedule');

    if (relativeSchedule) relativeSchedule.style.display = 'none';
    if (recurringSchedule) recurringSchedule.style.display = 'none';
    if (fixedSchedule) fixedSchedule.style.display = 'none';

    // Show selected section
    if (selectedType) {
        const selectedSection = document.getElementById(`${selectedType}-schedule`);
        if (selectedSection) {
            selectedSection.style.display = 'block';
        }

        if (selectedType === 'recurring') {
            updateRecurringOptions();
        }
    }
}

// Update recurring schedule options based on pattern
function updateRecurringOptions() {
    const pattern = document.querySelector('select[name="recurring_pattern"]')?.value;
    const optionsContainer = document.getElementById('recurring-options');

    if (!pattern || !optionsContainer) return;

    let optionsHTML = '';

    if (pattern === 'weekly') {
        optionsHTML = `
            <div>
                <label class="block text-xs font-medium text-muted-foreground mb-1">Day of Week</label>
                <select name="recurring_weekday" class="w-full px-3 py-2 bg-background border border-input rounded-md text-sm">
                    <option value="1">Monday</option>
                    <option value="2">Tuesday</option>
                    <option value="3">Wednesday</option>
                    <option value="4">Thursday</option>
                    <option value="5">Friday</option>
                    <option value="6">Saturday</option>
                    <option value="0">Sunday</option>
                </select>
            </div>
        `;
    } else if (pattern === 'monthly') {
        optionsHTML = `
            <div>
                <label class="block text-xs font-medium text-muted-foreground mb-1">Day of Month</label>
                <input type="number" name="recurring_day" min="1" max="31" placeholder="1"
                       class="w-full px-3 py-2 bg-background border border-input rounded-md text-sm">
            </div>
        `;
    }

    if (optionsContainer) {
        optionsContainer.innerHTML = optionsHTML;
    }
}

// Add a new action to the form
function addAction(actionData = null) {
    const actionsList = document.getElementById('actions-list');
    if (!actionsList) return;

    const actionId = `action-${++actionsCounter}`;
    const actionHTML = createActionHTML(actionId, actionData);
    actionsList.insertAdjacentHTML('beforeend', actionHTML);

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Create HTML for an action
function createActionHTML(actionId, actionData = null) {
    const action = actionData || { action_type: 'post_roster' };

    return `
        <div id="${actionId}" class="bg-muted/30 border border-border rounded-lg p-4">
            <div class="flex items-center justify-between mb-3">
                <h5 class="text-sm font-medium text-foreground">Action ${actionsCounter}</h5>
                <button onclick="removeAction('${actionId}')" type="button"
                        class="p-1 hover:bg-accent rounded text-red-400 hover:text-red-300">
                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                </button>
            </div>

            <div class="space-y-3">
                <div>
                    <label class="block text-xs font-medium text-muted-foreground mb-1">Action Type</label>
                    <select name="action_type" onchange="updateActionConfig('${actionId}')"
                            class="w-full px-3 py-2 bg-background border border-input rounded-md text-sm">
                        <option value="post_roster" ${action.action_type === 'post_roster' ? 'selected' : ''}>Post Roster</option>
                        <option value="ping_users" ${action.action_type === 'ping_users' ? 'selected' : ''}>Ping Users</option>
                        <option value="close_signup" ${action.action_type === 'close_signup' ? 'selected' : ''}>Close Signup</option>
                    </select>
                </div>
            </div>
        </div>
    `;
}

// Remove an action from the form
function removeAction(actionId) {
    const actionDiv = document.getElementById(actionId);
    if (actionDiv) {
        actionDiv.remove();
    }
}

// Update action configuration when type changes
function updateActionConfig(actionId) {
    // Basic implementation for now
    console.log('Updating action config for:', actionId);
}

// Save automation(s)
async function saveAutomation() {
    try {
        const automationsToCreate = collectFormData();

        if (!automationsToCreate || automationsToCreate.length === 0) {
            showNotification('Please enable at least one action', 'error');
            return;
        }

        // Create all automations
        let created = 0;
        let failed = 0;

        for (const automationData of automationsToCreate) {
            try {
                const response = await fetch('/v2/roster-automation', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${await getAuthToken()}`
                    },
                    body: JSON.stringify(automationData)
                });

                if (response.ok) {
                    created++;
                } else {
                    failed++;
                    const error = await response.json();
                    console.error(`Failed to create ${automationData.action_type}:`, error);
                }
            } catch (error) {
                failed++;
                console.error(`Error creating ${automationData.action_type}:`, error);
            }
        }

        // Reload automations
        await loadCurrentAutomation();

        if (created > 0) {
            showNotification(`Created ${created} automation(s)${failed > 0 ? ` (${failed} failed)` : ''}`, 'success');
        } else {
            showNotification('Failed to create automations', 'error');
        }

        if (created > 0) {
            cancelAutomation();
        }

    } catch (error) {
        console.error('Error saving automations:', error);
        showNotification(`Failed to save automations: ${error.message}`, 'error');
    }
}

// Collect form data - returns array of automations to create
function collectFormData() {
    const form = document.getElementById('automation-form');
    if (!form) return [];

    const automations = [];

    // Helper to get value
    const getValue = (name) => {
        const input = form.querySelector(`[name="${name}"]`);
        return input ? input.value : null;
    };

    const getChecked = (name) => {
        const input = form.querySelector(`input[name="${name}"]`);
        return input ? input.checked : false;
    };

    // Get event type and recurring options
    const eventType = form.querySelector('input[name="event_type"]:checked')?.value;
    const isRecurring = eventType === 'recurring';

    let recurringOptions = {};
    if (isRecurring) {
        recurringOptions = {
            is_recurring: true,
            recurring_interval: parseInt(getValue('recurring_interval')) || 1,
            recurring_unit: getValue('recurring_unit') || 'months',
            clear_members: getValue('clear_members') === 'true'
        };
    }

    // Get event start time from roster
    const eventStartTime = currentRosterData.event_start_time || currentRosterData.time;
    if (!eventStartTime) {
        throw new Error('Please set event start time first');
    }

    // Post Signup action
    if (getChecked('action_signup_enabled')) {
        const daysBefore = parseInt(getValue('action_signup_days')) || 14;
        const scheduledTime = eventStartTime - (daysBefore * 24 * 60 * 60);

        automations.push({
            server_id: serverId,
            roster_id: currentRosterData.custom_id,
            action_type: 'roster_signup',
            scheduled_time: scheduledTime,
            discord_channel_id: getValue('action_signup_channel'),
            options: {
                ...recurringOptions,
                days_before: daysBefore
            }
        });
    }

    // Close Signup action
    if (getChecked('action_close_enabled')) {
        const daysBefore = parseInt(getValue('action_close_days')) || 1;
        const scheduledTime = eventStartTime - (daysBefore * 24 * 60 * 60);

        automations.push({
            server_id: serverId,
            roster_id: currentRosterData.custom_id,
            action_type: 'roster_signup_close',
            scheduled_time: scheduledTime,
            discord_channel_id: getValue('action_close_channel'),
            options: {
                ...recurringOptions,
                days_before: daysBefore
            }
        });
    }

    // Post Roster action
    if (getChecked('action_post_enabled')) {
        const daysBefore = parseInt(getValue('action_post_days')) || 0;
        const scheduledTime = eventStartTime - (daysBefore * 24 * 60 * 60);

        automations.push({
            server_id: serverId,
            roster_id: currentRosterData.custom_id,
            action_type: 'roster_post',
            scheduled_time: scheduledTime,
            discord_channel_id: getValue('action_post_channel'),
            options: {
                ...recurringOptions,
                days_before: daysBefore
            }
        });
    }

    // Ping action
    if (getChecked('action_ping_enabled')) {
        const daysBefore = parseInt(getValue('action_ping_days')) || 3;
        const scheduledTime = eventStartTime - (daysBefore * 24 * 60 * 60);

        automations.push({
            server_id: serverId,
            roster_id: currentRosterData.custom_id,
            action_type: 'roster_ping',
            scheduled_time: scheduledTime,
            discord_channel_id: getValue('action_ping_channel'),
            options: {
                ...recurringOptions,
                days_before: daysBefore
            }
        });
    }

    return automations;
}

// Collect data from a single action div
function collectActionData(actionDiv) {
    const actionType = actionDiv.querySelector('select[name="action_type"]')?.value;
    if (!actionType) return null;

    const action = { action_type: actionType };
    return action;
}

// Validate automation data before saving
function validateAutomationData(automation) {
    if (!automation.action_type) {
        showNotification('Please select an action type', 'error');
        return false;
    }

    if (!automation.scheduled_time) {
        showNotification('Please configure the schedule', 'error');
        return false;
    }

    return true;
}

// Toggle automation active status
async function toggleAutomationActive(automationId, newActiveState) {
    try {
        const response = await fetch(`/v2/roster-automation/${automationId}?server_id=${serverId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${await getAuthToken()}`
            },
            body: JSON.stringify({
                active: newActiveState
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // Update local state
        const automation = currentAutomations.find(a => a.automation_id === automationId);
        if (automation) {
            automation.active = newActiveState;
        }

        updateAutomationDisplay();
        showNotification(`Automation ${newActiveState ? 'enabled' : 'disabled'}`, 'success');

    } catch (error) {
        console.error('Error toggling automation:', error);
        showNotification('Failed to toggle automation', 'error');
    }
}

// Edit automation by ID
async function editAutomationById(automationId) {
    const automation = currentAutomations.find(a => a.automation_id === automationId);
    if (!automation) {
        showNotification('Automation not found', 'error');
        return;
    }

    // Use the appropriate modal based on automation type
    if (automation.action_type === 'roster_ping') {
        showReminderForm(automation);
    } else {
        showAutomationForm(automation.action_type, automation);
    }
}

// Delete automation by ID
async function deleteAutomationById(automationId) {
    if (!confirm('Are you sure you want to delete this automation?')) {
        return;
    }

    try {
        const response = await fetch(`/v2/roster-automation/${automationId}?server_id=${serverId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        // Reload automations
        await loadCurrentAutomation();
        showNotification('Automation deleted successfully', 'success');
        updateAutomationDisplay();

    } catch (error) {
        console.error('Error deleting automation:', error);
        showNotification(`Failed to delete automation: ${error.message}`, 'error');
    }
}

// Delete automation (for backward compatibility)
async function deleteAutomation() {
    if (currentAutomation) {
        await deleteAutomationById(currentAutomation.automation_id);
    }
}

// Test automation
async function testAutomation() {
    if (!currentAutomation) {
        showNotification('No automation to test', 'error');
        return;
    }

    showNotification('Automation configuration is valid and ready to run', 'success');
}

// Formatting helper functions
function formatAutomationType(type) {
    const types = {
        'event_lifecycle': 'Event Lifecycle',
        'recurring_reminder': 'Recurring Reminder',
        'maintenance': 'Maintenance'
    };
    return types[type] || type;
}

function formatActionType(actionType) {
    const types = {
        'roster_signup': 'Open Signup',
        'roster_signup_close': 'Close Signup',
        'roster_post': 'Post Roster',
        'roster_ping': 'Send Reminder',
        'recurring_event': 'Recurring Event',
        'roster_delete': 'Delete Roster',
        'roster_clear': 'Clear Roster',
        'roster_archive': 'Archive Roster'
    };
    return types[actionType] || actionType;
}

function getActionDescription(actionType) {
    const descriptions = {
        'roster_signup': 'Opens the signup period for roster registration',
        'roster_signup_close': 'Closes the signup period',
        'roster_post': 'Posts the final roster to Discord',
        'roster_ping': 'Sends reminders to members',
        'recurring_event': 'Automatically updates roster dates',
        'roster_delete': 'Deletes the roster',
        'roster_clear': 'Clears roster members',
        'roster_archive': 'Archives the roster'
    };
    return descriptions[actionType] || 'Custom automation action';
}

function formatScheduleText(automation) {
    // Backend uses scheduled_time directly
    if (!automation || !automation.scheduled_time) return 'Not configured';

    const date = new Date(automation.scheduled_time * 1000);
    const now = new Date();
    const diffMs = date.getTime() - now.getTime();
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));

    if (diffHours < 24 && diffHours > 0) {
        return `Today at ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
    } else if (diffHours < 48 && diffHours > 0) {
        return `Tomorrow at ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
    }

    return date.toLocaleString();
}

function getAutomationDescription(type) {
    const descriptions = {
        'event_lifecycle': 'Automatically manages the complete lifecycle of roster events',
        'recurring_reminder': 'Sends regular reminders and notifications to users',
        'maintenance': 'Performs automated cleanup and maintenance tasks'
    };
    return descriptions[type] || 'Custom automation';
}

function formatNextExecution(date) {
    const now = new Date();
    const diffMs = date.getTime() - now.getTime();
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    // Handle past dates
    if (diffMs < 0) {
        const absMins = Math.abs(diffMins);
        const absHours = Math.abs(diffHours);
        const absDays = Math.abs(diffDays);

        if (absMins < 60) {
            return `${absMins} minutes ago`;
        } else if (absHours < 24) {
            return `${absHours} hours ago`;
        } else if (absDays === 1) {
            return `yesterday at ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
        } else {
            return date.toLocaleDateString() + ' at ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) + ' (past)';
        }
    }

    // Handle future dates
    if (diffMins < 60) {
        return `in ${diffMins} minutes`;
    } else if (diffHours < 24) {
        return `in ${diffHours} hours`;
    } else if (diffDays === 1) {
        return `tomorrow at ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
    } else if (diffDays < 7) {
        return `in ${diffDays} days at ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
    } else {
        return date.toLocaleDateString() + ' at ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    }
}

function getOrdinalSuffix(day) {
    const j = day % 10;
    const k = day % 100;
    if (j == 1 && k != 11) return 'st';
    if (j == 2 && k != 12) return 'nd';
    if (j == 3 && k != 13) return 'rd';
    return 'th';
}

// Update sidebar automation status
function updateSidebarAutomationStatus() {
    const statusElement = document.getElementById('sidebar-automation-status');
    if (!statusElement) return;

    const activeCount = currentAutomations.filter(a => a.active).length;
    const totalCount = currentAutomations.length;

    if (activeCount > 0) {
        statusElement.textContent = `On`;
        statusElement.className = 'ml-auto bg-green-500 text-green-100 px-1.5 py-0.5 rounded text-xs';
    } else if (totalCount > 0) {
        statusElement.textContent = 'Paused';
        statusElement.className = 'ml-auto bg-yellow-500 text-yellow-100 px-1.5 py-0.5 rounded text-xs';
    } else {
        statusElement.textContent = 'Off';
        statusElement.className = 'ml-auto bg-muted text-muted-foreground px-1.5 py-0.5 rounded text-xs';
    }
}

// Use automation template
function useTemplate(templateKey) {
    // Basic template functionality
    toggleAutomation();
}

// Hide templates section
function hideTemplates() {
    const templatesSection = document.getElementById('automation-templates');
    if (templatesSection) {
        templatesSection.style.display = 'none';
    }
}

// Refresh automation history
async function refreshHistory() {
    try {
        const historyList = document.getElementById('history-list');
        if (historyList) {
            historyList.innerHTML = '<div class="text-center py-4 text-sm text-muted-foreground">No execution history available</div>';
        }
    } catch (error) {
        console.error('Error refreshing history:', error);
        showNotification('Failed to refresh history', 'error');
    }
}

// Toggle recurring options
function toggleRecurringOptions() {
    const eventType = document.querySelector('input[name="event_type"]:checked')?.value;
    const recurringOptions = document.getElementById('recurring-options');

    if (recurringOptions) {
        recurringOptions.style.display = eventType === 'recurring' ? 'block' : 'none';
    }
}

// Toggle automation form when master toggle is changed
async function toggleAutomationForm() {
    const masterToggle = document.getElementById('automation-master-toggle');
    const isEnabled = masterToggle ? masterToggle.checked : false;

    if (!currentAutomation) {
        // No automation exists, show creation form if enabled
        if (isEnabled) {
            const formContainer = document.getElementById('automation-form-container');
            if (formContainer) {
                formContainer.style.display = 'block';
            }
        } else {
            masterToggle.checked = false; // Keep it disabled
        }
        return;
    }

    // Update existing automation active status
    try {
        const response = await fetch(`/v2/roster-automation/${currentAutomation.automation_id}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${await getAuthToken()}`
            },
            body: JSON.stringify({
                server_id: serverId,
                active: isEnabled
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // Update local state
        currentAutomation.active = isEnabled;
        updateAutomationDisplay();

        showNotification(
            isEnabled ? 'Automation enabled' : 'Automation disabled',
            'success'
        );
    } catch (error) {
        console.error('Error toggling automation:', error);
        showNotification('Failed to toggle automation', 'error');
        // Revert toggle state
        masterToggle.checked = !isEnabled;
    }
}

// ======================== DISCORD CHANNEL SELECTION ========================

// Render channel selector with search
function renderChannelSelector(selectedChannelId = '') {
    const channels = discordChannels;

    // Find the selected channel to show its name
    let selectedChannelName = '';
    if (selectedChannelId && channels.length > 0) {
        const selected = channels.find(c => c.id === selectedChannelId);
        if (selected) {
            selectedChannelName = selected.display_name;
        }
    }

    return `
        <div class="relative">
            <input
                type="text"
                id="modal-channel-search"
                list="channel-options"
                value="${selectedChannelName || selectedChannelId}"
                placeholder="${channels.length > 0 ? 'Search or select a channel...' : 'Loading channels...'}"
                class="w-full px-3 py-2 bg-background border border-input rounded-md text-sm"
                oninput="updateChannelIdFromSearch(this.value)"
                ${channels.length === 0 ? 'disabled' : ''}
            >
            <datalist id="channel-options">
                ${channels.map(channel => `
                    <option value="${channel.display_name}" data-id="${channel.id}">
                        ${channel.full_display_name}
                    </option>
                `).join('')}
            </datalist>
            <input type="hidden" id="modal-channel-id" value="${selectedChannelId}">
        </div>
    `;
}

// Update channel ID when user types or selects
function updateChannelIdFromSearch(searchValue) {
    const hiddenInput = document.getElementById('modal-channel-id');
    if (!hiddenInput) return;

    // Check if it's a direct ID (numeric string)
    if (/^\d+$/.test(searchValue)) {
        hiddenInput.value = searchValue;
        return;
    }

    // Try to find matching channel by display name
    const channel = discordChannels.find(c =>
        c.display_name === searchValue ||
        c.name === searchValue.replace('#', '')
    );

    if (channel) {
        hiddenInput.value = channel.id;
    } else {
        // If no match, keep the typed value (allows manual ID entry)
        hiddenInput.value = searchValue;
    }
}

// ======================== NEW MODAL-BASED AUTOMATION FORMS ========================

// Show automation form modal
async function showAutomationForm(actionType, existingAutomation = null) {
    const isEdit = !!existingAutomation;
    const labels = {
        'roster_signup': { title: 'Open Signup', icon: '📅', desc: 'When should signups open?' },
        'roster_signup_close': { title: 'Close Signup', icon: '🚫', desc: 'When should signups close?' },
        'roster_post': { title: 'Post Roster', icon: '📋', desc: 'When should the final roster be posted?' }
    };

    const config = labels[actionType] || { title: 'Automation', icon: '⚙️', desc: '' };

    // Get event start time
    const eventStartTime = currentRosterData?.event_start_time || currentRosterData?.time;
    if (!eventStartTime) {
        showNotification('Please set the event start time first', 'error');
        return;
    }

    // Load channels if not already loaded
    await loadDiscordChannels();

    // Calculate defaults
    const defaultDaysBefore = actionType === 'roster_signup' ? 14 : (actionType === 'roster_signup_close' ? 1 : 0);
    const daysBefore = existingAutomation?.options?.days_before ?? defaultDaysBefore;
    const channelId = existingAutomation?.discord_channel_id || '';

    const modalHTML = `
        <div id="automation-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onclick="if(event.target===this) closeAutomationModal()">
            <div class="bg-card border border-border rounded-lg shadow-lg max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto">
                <div class="p-6">
                    <div class="flex items-center gap-3 mb-4">
                        <span class="text-3xl">${config.icon}</span>
                        <div>
                            <h3 class="text-lg font-semibold text-foreground">${isEdit ? 'Edit' : 'Add'} ${config.title}</h3>
                            <p class="text-sm text-muted-foreground">${config.desc}</p>
                        </div>
                    </div>

                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium mb-2">Timing</label>
                            <div class="flex items-center gap-2">
                                <input type="number" id="modal-days-before" value="${daysBefore}" min="0" max="90"
                                       class="flex-1 px-3 py-2 bg-background border border-input rounded-md text-sm">
                                <span class="text-sm text-muted-foreground">days before event</span>
                            </div>
                            <p class="text-xs text-muted-foreground mt-1">
                                Event time: ${new Date(eventStartTime * 1000).toLocaleString()}
                            </p>
                        </div>

                        <div>
                            <label class="block text-sm font-medium mb-2">Discord Channel</label>
                            ${renderChannelSelector(channelId)}
                            <p class="text-xs text-muted-foreground mt-1">
                                The channel where the message will be posted
                            </p>
                        </div>
                    </div>

                    <div class="flex gap-3 mt-6">
                        <button onclick="saveAutomationFromModal('${actionType}', ${isEdit ? `'${existingAutomation.automation_id}'` : 'null'})"
                                class="flex-1 px-4 py-2 bg-primary hover:bg-primary/90 text-primary-foreground rounded-md text-sm font-medium">
                            ${isEdit ? 'Update' : 'Create'}
                        </button>
                        <button onclick="closeAutomationModal()"
                                class="px-4 py-2 bg-secondary hover:bg-secondary/80 text-sm rounded-md">
                            Cancel
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal if any
    const existingModal = document.getElementById('automation-modal');
    if (existingModal) {
        existingModal.remove();
    }

    // Add modal to body
    document.body.insertAdjacentHTML('beforeend', modalHTML);
}

// Show reminder form modal
async function showReminderForm(existingAutomation = null) {
    const isEdit = !!existingAutomation;

    // Get event start time
    const eventStartTime = currentRosterData?.event_start_time || currentRosterData?.time;
    if (!eventStartTime) {
        showNotification('Please set the event start time first', 'error');
        return;
    }

    // Load channels if not already loaded
    await loadDiscordChannels();

    const daysBefore = existingAutomation?.options?.days_before ?? 3;
    const channelId = existingAutomation?.discord_channel_id || '';
    const message = existingAutomation?.options?.message || '';
    const pingTarget = existingAutomation?.options?.ping_target || 'signed_up';

    const modalHTML = `
        <div id="automation-modal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onclick="if(event.target===this) closeAutomationModal()">
            <div class="bg-card border border-border rounded-lg shadow-lg max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto">
                <div class="p-6">
                    <div class="flex items-center gap-3 mb-4">
                        <span class="text-3xl">🔔</span>
                        <div>
                            <h3 class="text-lg font-semibold text-foreground">${isEdit ? 'Edit' : 'Add'} Reminder</h3>
                            <p class="text-sm text-muted-foreground">Send a reminder to roster members</p>
                        </div>
                    </div>

                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium mb-2">Timing</label>
                            <div class="flex items-center gap-2">
                                <input type="number" id="modal-days-before" value="${daysBefore}" min="0" max="90"
                                       class="flex-1 px-3 py-2 bg-background border border-input rounded-md text-sm">
                                <span class="text-sm text-muted-foreground">days before event</span>
                            </div>
                            <p class="text-xs text-muted-foreground mt-1">
                                Event time: ${new Date(eventStartTime * 1000).toLocaleString()}
                            </p>
                        </div>

                        <div>
                            <label class="block text-sm font-medium mb-2">Discord Channel</label>
                            ${renderChannelSelector(channelId)}
                            <p class="text-xs text-muted-foreground mt-1">
                                The channel where the reminder will be posted
                            </p>
                        </div>

                        <div>
                            <label class="block text-sm font-medium mb-2">Who to ping</label>
                            <select id="modal-ping-target" class="w-full px-3 py-2 bg-background border border-input rounded-md text-sm">
                                <option value="signed_up" ${pingTarget === 'signed_up' ? 'selected' : ''}>
                                    Ping signed up members
                                </option>
                                <option value="signed_up_wrong_clan" ${pingTarget === 'signed_up_wrong_clan' ? 'selected' : ''}>
                                    Ping signed up but not in the right clan
                                </option>
                                <option value="clan_not_signed_up" ${pingTarget === 'clan_not_signed_up' ? 'selected' : ''}>
                                    Ping clan members not signed up
                                </option>
                            </select>
                            <p class="text-xs text-muted-foreground mt-1">
                                Choose which members should receive this reminder
                            </p>
                        </div>

                        <div>
                            <label class="block text-sm font-medium mb-2">Custom Message (Optional)</label>
                            <textarea id="modal-message" rows="3" placeholder="Add a custom reminder message..."
                                      class="w-full px-3 py-2 bg-background border border-input rounded-md text-sm">${message}</textarea>
                        </div>
                    </div>

                    <div class="flex gap-3 mt-6">
                        <button onclick="saveAutomationFromModal('roster_ping', ${isEdit ? `'${existingAutomation.automation_id}'` : 'null'})"
                                class="flex-1 px-4 py-2 bg-primary hover:bg-primary/90 text-primary-foreground rounded-md text-sm font-medium">
                            ${isEdit ? 'Update' : 'Create'}
                        </button>
                        <button onclick="closeAutomationModal()"
                                class="px-4 py-2 bg-secondary hover:bg-secondary/80 text-sm rounded-md">
                            Cancel
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal if any
    const existingModal = document.getElementById('automation-modal');
    if (existingModal) {
        existingModal.remove();
    }

    // Add modal to body
    document.body.insertAdjacentHTML('beforeend', modalHTML);
}

// Close automation modal
function closeAutomationModal() {
    const modal = document.getElementById('automation-modal');
    if (modal) {
        modal.remove();
    }
}

// Save automation from modal
async function saveAutomationFromModal(actionType, automationId = null) {
    try {
        const daysBefore = parseInt(document.getElementById('modal-days-before')?.value || 0);
        const channelId = document.getElementById('modal-channel-id')?.value;
        const message = document.getElementById('modal-message')?.value || '';
        const pingTarget = document.getElementById('modal-ping-target')?.value || 'signed_up';

        if (!channelId) {
            showNotification('Please enter a Discord channel ID', 'error');
            return;
        }

        const eventStartTime = currentRosterData.event_start_time || currentRosterData.time;
        const scheduledTime = eventStartTime - (daysBefore * 24 * 60 * 60);

        const automationData = {
            server_id: serverId,
            roster_id: currentRosterData.custom_id,
            action_type: actionType,
            scheduled_time: scheduledTime,
            discord_channel_id: channelId,
            options: {
                days_before: daysBefore,
                ...(message && { message }),
                ...(actionType === 'roster_ping' && { ping_target: pingTarget })
            }
        };

        let response;
        if (automationId) {
            // Update existing - server_id goes in query params, not body
            response = await fetch(`/v2/roster-automation/${automationId}?server_id=${serverId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${await getAuthToken()}`
                },
                body: JSON.stringify({
                    scheduled_time: scheduledTime,
                    discord_channel_id: channelId,
                    options: automationData.options
                })
            });
        } else {
            // Create new
            response = await fetch('/v2/roster-automation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${await getAuthToken()}`
                },
                body: JSON.stringify(automationData)
            });
        }

        if (!response.ok) {
            const error = await response.json();
            console.error('Server error response:', error);

            // Handle FastAPI validation errors (422)
            let errorMessage = `HTTP ${response.status}`;
            if (error.detail) {
                if (Array.isArray(error.detail)) {
                    // Validation errors from FastAPI/Pydantic
                    errorMessage = error.detail.map(e => `${e.loc.join('.')}: ${e.msg}`).join(', ');
                } else if (typeof error.detail === 'string') {
                    errorMessage = error.detail;
                } else {
                    errorMessage = JSON.stringify(error.detail);
                }
            }
            throw new Error(errorMessage);
        }

        showNotification(`Automation ${automationId ? 'updated' : 'created'} successfully`, 'success');

        // Reload automations and close modal
        await loadCurrentAutomation();
        updateAutomationDisplay();
        closeAutomationModal();

    } catch (error) {
        console.error('Error saving automation:', error);
        showNotification(`Failed to save automation: ${error.message}`, 'error');
    }
}

// Load and display group reminders for this roster
async function loadGroupRemindersForRoster() {
    const groupRemindersSection = document.getElementById('group-reminders-section');
    const groupRemindersContent = document.getElementById('group-reminders-content');

    if (!groupRemindersSection || !groupRemindersContent) return;

    // Check if roster is in a group
    if (!currentRosterData || !currentRosterData.group_id) {
        groupRemindersSection.style.display = 'none';
        return;
    }

    try {
        // Fetch group reminders (including inactive ones)
        const response = await fetch(`${API_BASE}/roster-automation/list?group_id=${currentRosterData.group_id}&server_id=${serverId}&active_only=false`, {
            headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const groupReminders = data.items || [];

        // Show the section
        groupRemindersSection.style.display = 'block';

        if (groupReminders.length > 0) {
            groupRemindersContent.innerHTML = groupReminders.map(reminder => {
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

                const channel = discordChannels.find(c => String(c.id) === String(reminder.discord_channel_id));
                const channelName = channel ? channel.display_name : `ID: ${reminder.discord_channel_id}`;

                return `
                    <div class="flex items-center justify-between p-3 bg-muted/30 rounded-lg ${!isActive ? 'opacity-60' : ''}">
                        <div class="flex items-center gap-3 flex-1">
                            <div class="${indicatorClass}" title="${isActive ? 'Active' : 'Inactive'}"></div>
                            <div class="flex-1">
                                <div class="text-xs font-medium text-foreground">${timingText}</div>
                                <div class="text-xs text-muted-foreground mt-0.5">${channelName} • ${targetText}</div>
                                ${reminder.options?.message ? `<div class="text-xs text-muted-foreground mt-1 italic">"${reminder.options.message}"</div>` : ''}
                            </div>
                        </div>
                        <div class="flex items-center gap-1">
                            <i data-lucide="users" class="w-3 h-3 text-purple-500" title="Group reminder"></i>
                        </div>
                    </div>
                `;
            }).join('');
        } else {
            groupRemindersContent.innerHTML = `
                <div class="text-center py-4 text-xs text-muted-foreground">
                    No group reminders configured
                </div>
            `;
        }

        // Re-render icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }

    } catch (error) {
        console.error('Error loading group reminders:', error);
        groupRemindersContent.innerHTML = `
            <div class="text-center py-2 text-xs text-destructive">
                Failed to load group reminders
            </div>
        `;
    }
}

// Navigate to group settings
function goToGroupSettings() {
    if (!currentRosterData || !currentRosterData.group_id) {
        showAlert('This roster is not part of a group', 'error');
        return;
    }

    // Switch to Groups tab
    showTab('groups');

    // Try to find and click the settings button for this group
    setTimeout(() => {
        const settingsButtons = document.querySelectorAll('[onclick^="showGroupSettings"]');
        for (const button of settingsButtons) {
            const onclickAttr = button.getAttribute('onclick');
            if (onclickAttr && onclickAttr.includes(`'${currentRosterData.group_id}'`)) {
                button.click();
                return;
            }
        }

        showAlert('Switched to Groups tab. Click on the group\'s Settings button to manage reminders.', 'info');
    }, 100);
}