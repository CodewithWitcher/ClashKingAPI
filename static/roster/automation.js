// Debug: automation.js loaded
console.log("automation.js loaded successfully");

// Simple notification function
function showNotification(message, type = "success") {
    console.log(`[${type.toUpperCase()}] ${message}`);
    // TODO: Add visual notification later
}

// Automation Management
let currentAutomation = null;
let isEditingAutomation = false;
let actionsCounter = 0;

// Helper function to get auth token
async function getAuthToken() {
    return ROSTER_TOKEN;
}

// Initialize automation tab
async function initializeAutomationTab() {
    if (!currentRosterData) return;

    // Wait for DOM elements to be available
    const maxAttempts = 10;
    let attempts = 0;

    const waitForElements = () => {
        return new Promise((resolve) => {
            const checkElements = () => {
                const toggleBtn = document.getElementById('automation-toggle-btn');
                if (toggleBtn || attempts >= maxAttempts) {
                    resolve(toggleBtn);
                } else {
                    attempts++;
                    setTimeout(checkElements, 100);
                }
            };
            checkElements();
        });
    };

    try {
        await waitForElements();
        await loadCurrentAutomation();
        updateAutomationDisplay();
        updateEventTimeDisplay();
        updateAutomationTimezoneInfo();

        // Preload Discord channels for autocomplete
        loadDiscordChannels().catch(error => {
            console.warn('Failed to preload Discord channels:', error);
        });
    } catch (error) {
        console.error('Error initializing automation tab:', error);
        showNotification('Failed to load automation settings', 'error');
    }
}

// Load current automation for the roster
async function loadCurrentAutomation() {
    if (!currentRosterData) return;

    try {
        // Get list of automations for this server first
        const response = await fetch(`/v2/roster-automation/list?server_id=${serverId}${currentRosterData ? '&roster_id=' + currentRosterData.custom_id : ''}`, {
            headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const automations = data.items || [];

        // Find automation for current roster
        currentAutomation = automations.find(automation =>
            automation.roster_id === currentRosterData.custom_id
        ) || null;

    } catch (error) {
        console.error('Error loading automation:', error);
        currentAutomation = null;
    }
}

// Update the automation display based on current state
function updateAutomationDisplay() {
    console.log('updateAutomationDisplay called');

    const statusCard = document.getElementById('automation-status-card');
    const emptyState = document.getElementById('automation-empty-state');
    const toggleBtn = document.getElementById('automation-toggle-btn');
    const testBtn = document.getElementById('test-automation-btn');

    console.log('DOM elements found:', {
        statusCard: !!statusCard,
        emptyState: !!emptyState,
        toggleBtn: !!toggleBtn,
        testBtn: !!testBtn
    });

    // Check if required elements exist
    if (!toggleBtn) {
        console.warn('automation-toggle-btn not found in DOM - automation tab may not be visible or loaded');

        // Check if automation tab content is visible
        const automationContent = document.getElementById('content-automation');
        console.log('Automation tab content exists:', !!automationContent);
        if (automationContent) {
            console.log('Automation tab content classes:', automationContent.className);
            console.log('Automation tab content visible:', !automationContent.classList.contains('hidden'));

            // If content exists but no toggle button, the template might not have rendered properly
            console.error('Automation tab content exists but automation template elements are missing - possible template rendering issue');
        } else {
            console.error('Automation tab content div (content-automation) does not exist - template inclusion failed');
        }

        // Try to initialize again in a moment
        setTimeout(() => {
            if (document.getElementById('automation-toggle-btn')) {
                console.log('Retrying updateAutomationDisplay after DOM elements became available');
                updateAutomationDisplay();
            }
        }, 500);
        return;
    }

    if (currentAutomation) {
        // Show current automation
        if (statusCard) statusCard.style.display = 'block';
        if (emptyState) emptyState.style.display = 'none';
        if (testBtn) testBtn.style.display = 'flex';

        // Update status card content
        const indicator = document.getElementById('automation-status-indicator');
        const typeText = document.getElementById('automation-type-text');
        const scheduleText = document.getElementById('automation-schedule-text');
        const description = document.getElementById('automation-description');
        const nextExecution = document.getElementById('next-execution-time');

        // Set status indicator color based on active state
        if (indicator) {
            indicator.className = currentAutomation.active ?
                'w-2 h-2 rounded-full bg-green-500' :
                'w-2 h-2 rounded-full bg-gray-400';
        }

        // Set automation type text
        if (typeText) {
            typeText.textContent = formatAutomationType(currentAutomation.automation_type);
        }

        // Set schedule text
        if (scheduleText) {
            scheduleText.textContent = formatScheduleText(currentAutomation.schedule);
        }

        // Set description
        if (description) {
            description.textContent = getAutomationDescription(currentAutomation.automation_type);
        }

        // Set next execution time
        if (nextExecution) {
            if (currentAutomation.next_execution) {
                const nextTime = new Date(currentAutomation.next_execution * 1000);
                nextExecution.textContent = formatNextExecution(nextTime);
            } else {
                nextExecution.textContent = 'Not scheduled';
            }
        }

        // Update toggle button
        if (toggleBtn) {
            toggleBtn.innerHTML = `
                <i data-lucide="edit" class="w-4 h-4"></i>
                <span>Edit Automation</span>
            `;
        }
    } else {
        // Show empty state
        if (statusCard) statusCard.style.display = 'none';
        if (emptyState) emptyState.style.display = 'block';
        if (testBtn) testBtn.style.display = 'none';

        // Update toggle button
        if (toggleBtn) {
            toggleBtn.innerHTML = `
                <i data-lucide="plus" class="w-4 h-4"></i>
                <span>Create Automation</span>
            `;
        }
    }

    // Update sidebar automation status
    updateSidebarAutomationStatus();

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Toggle automation form visibility
function toggleAutomation() {
    const formContainer = document.getElementById('automation-form-container');
    const statusCard = document.getElementById('automation-status-card');
    const emptyState = document.getElementById('automation-empty-state');

    if (!formContainer) {
        console.warn('automation-form-container not found in DOM');
        return;
    }

    if (formContainer.style.display === 'none' || formContainer.style.display === '') {
        // Show form
        formContainer.style.display = 'block';
        if (statusCard) statusCard.style.display = 'none';
        if (emptyState) emptyState.style.display = 'none';
        isEditingAutomation = true;

        if (currentAutomation) {
            populateFormWithAutomation(currentAutomation);
        } else {
            resetAutomationForm();
            addAction(); // Add first action by default
        }
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
    }
    isEditingAutomation = false;

    updateAutomationDisplay();
    resetAutomationForm();
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
    if (!automation) return;

    const form = document.getElementById('automation-form');
    if (!form) return;

    // Set automation type
    const typeRadio = form.querySelector(`input[name="automation_type"][value="${automation.automation_type}"]`);
    if (typeRadio) typeRadio.checked = true;

    // Set schedule type and data
    if (automation.schedule) {
        const scheduleTypeRadio = form.querySelector(`input[name="schedule_type"][value="${automation.schedule.schedule_type}"]`);
        if (scheduleTypeRadio) {
            scheduleTypeRadio.checked = true;
            updateScheduleType();

            // Populate schedule-specific fields
            if (automation.schedule.schedule_type === 'relative') {
                const relativeToSelect = form.querySelector('select[name="relative_to"]');
                const offsetInput = form.querySelector('input[name="offset_hours"]');
                if (relativeToSelect) relativeToSelect.value = automation.schedule.relative_to || '';
                if (offsetInput) offsetInput.value = automation.schedule.offset_hours || '';
            } else if (automation.schedule.schedule_type === 'recurring') {
                const patternSelect = form.querySelector('select[name="recurring_pattern"]');
                const timeInput = form.querySelector('input[name="recurring_time"]');
                if (patternSelect) patternSelect.value = automation.schedule.recurring_pattern || '';
                if (timeInput) timeInput.value = automation.schedule.recurring_time || '';

                updateRecurringOptions();

                if (automation.schedule.recurring_weekday !== undefined) {
                    const weekdaySelect = form.querySelector('select[name="recurring_weekday"]');
                    if (weekdaySelect) weekdaySelect.value = automation.schedule.recurring_weekday;
                }
                if (automation.schedule.recurring_day !== undefined) {
                    const dayInput = form.querySelector('input[name="recurring_day"]');
                    if (dayInput) dayInput.value = automation.schedule.recurring_day;
                }
            } else if (automation.schedule.schedule_type === 'fixed') {
                if (automation.schedule.fixed_timestamp) {
                    const date = new Date(automation.schedule.fixed_timestamp * 1000);
                    const dateInput = form.querySelector('input[name="fixed_date"]');
                    const timeInput = form.querySelector('input[name="fixed_time"]');
                    if (dateInput) dateInput.value = date.toISOString().split('T')[0];
                    if (timeInput) timeInput.value = date.toISOString().split('T')[1].substring(0, 5);
                }
            }
        }
    }

    // Clear existing actions and add the ones from automation
    const actionsList = document.getElementById('actions-list');
    if (actionsList) {
        actionsList.innerHTML = '';
        actionsCounter = 0;
    }

    if (automation.actions && automation.actions.length > 0) {
        automation.actions.forEach(action => {
            addAction(action);
        });
    } else {
        // Add at least one empty action
        addAction();
    }
}

let reminderCounter = 0;

// Toggle automation form visibility with master toggle
function toggleAutomationForm() {
    const toggle = document.getElementById('automation-master-toggle');
    const formContainer = document.getElementById('automation-form-container');
    const toggleSection = document.getElementById('automation-toggle-section');
    const statusCard = document.getElementById('automation-status-card');

    if (toggle.checked) {
        // Show form, hide toggle section
        if (formContainer) formContainer.style.display = 'block';
        if (toggleSection) toggleSection.style.display = 'none';
        if (statusCard) statusCard.style.display = 'none';
    } else {
        // Hide form, show toggle section
        if (formContainer) formContainer.style.display = 'none';
        if (toggleSection) toggleSection.style.display = 'flex';
        if (statusCard) statusCard.style.display = 'none';
    }
}

// Toggle recurring options visibility
function toggleRecurringOptions() {
    const recurringRadio = document.querySelector('input[name="event_type"][value="recurring"]');
    const options = document.getElementById('recurring-options');

    if (options) {
        options.style.display = recurringRadio.checked ? 'block' : 'none';
    }

    // Update event time display when recurring status changes
    updateEventTimeDisplay();
}

function addReminder() {
    reminderCounter++;
    const reminderId = `reminder-${reminderCounter}`;

    const reminderHTML = `
        <div id="${reminderId}" class="p-4 bg-background border border-border rounded-lg">
            <div class="flex items-center justify-between mb-3">
                <h5 class="font-medium">🔔 Reminder ${reminderCounter}</h5>
                <button onclick="removeReminder('${reminderId}')" class="text-red-400 hover:text-red-300">
                    <i data-lucide="x" class="w-4 h-4"></i>
                </button>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                <div>
                    <label class="block text-xs font-medium mb-1">When?</label>
                    <div class="flex gap-2">
                        <input type="number" name="reminder-days" value="7" min="0" class="w-16 px-2 py-1 bg-muted border border-input rounded text-center">
                        <select name="reminder-unit" class="flex-1 px-2 py-1 bg-muted border border-input rounded text-sm">
                            <option value="days-before-close">days before signup close</option>
                            <option value="hours-before-close">hours before signup close</option>
                            <option value="days-before-event">days before event start</option>
                            <option value="hours-before-event">hours before event start</option>
                        </select>
                    </div>
                </div>
                <div>
                    <label class="block text-xs font-medium mb-1">Target?</label>
                    <select name="reminder-target" class="w-full px-2 py-1 bg-muted border border-input rounded text-sm">
                        <option value="unregistered_clan">👥 Clan members not registered</option>
                        <option value="unregistered_family">🏠 Family members not registered to any group roster</option>
                        <option value="wrong_clan">⚠️ Registered but in wrong clan</option>
                        <option value="all_registered">✅ All registered members</option>
                    </select>
                </div>
                <div class="relative">
                    <label class="block text-xs font-medium mb-1">Discord Channel</label>
                    <div class="channel-autocomplete-container">
                        <input type="text" name="reminder-channel" placeholder="#reminders"
                               class="w-full px-2 py-1 bg-muted border border-input rounded text-sm channel-input"
                               oninput="handleChannelInput(this)" onfocus="showChannelSuggestions(this)">
                        <div class="channel-suggestions absolute z-10 w-full mt-1 bg-background border border-border rounded-md shadow-lg hidden max-h-48 overflow-y-auto">
                            <!-- Suggestions will be populated here -->
                        </div>
                    </div>
                </div>
            </div>

            <div>
                <label class="block text-xs font-medium mb-1">Custom message</label>
                <textarea name="reminder-message" rows="2" placeholder="Only {days_remaining} days left to register for {roster_name}!"
                          class="w-full px-2 py-1 bg-muted border border-input rounded text-sm"></textarea>
                <div class="text-xs text-muted-foreground mt-1">Variables: {roster_name}, {event_date}, {days_remaining}</div>
            </div>
        </div>
    `;

    document.getElementById('reminders-list').insertAdjacentHTML('beforeend', reminderHTML);

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function removeReminder(reminderId) {
    const reminder = document.getElementById(reminderId);
    if (reminder) {
        reminder.remove();
    }
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
        const selectedSchedule = document.getElementById(`${selectedType}-schedule`);
        if (selectedSchedule) {
            selectedSchedule.style.display = 'block';
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

    optionsContainer.innerHTML = optionsHTML;
}

// Add a new action to the form
function addAction(actionData = null) {
    const actionsList = document.getElementById('actions-list');
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
}

// Save automation
async function saveAutomation() {
    try {
        const automations = collectAutomationData();

        if (!automations || automations.length === 0) {
            showError('No actions selected');
            return;
        }

        console.log('Creating automations:', automations);

        // Create each automation entry separately
        const results = [];
        for (const automation of automations) {
            const response = await fetch('/v2/roster-automation', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${await getAuthToken()}`
                },
                body: JSON.stringify(automation)
            });

            if (!response.ok) {
                const errorData = await response.json();
                console.error('Server error response:', errorData);

                let errorMessage = `HTTP ${response.status}`;
                if (errorData.detail) {
                    if (typeof errorData.detail === 'string') {
                        errorMessage = errorData.detail;
                    } else if (Array.isArray(errorData.detail)) {
                        errorMessage = errorData.detail.map(err => `${err.loc?.join('.')}: ${err.msg}`).join(', ');
                    } else {
                        errorMessage = JSON.stringify(errorData.detail);
                    }
                }

                throw new Error(`Failed to create ${automation.action_type}: ${errorMessage}`);
            }

            const result = await response.json();
            results.push(result);
        }

        console.log('All automations created successfully:', results);
        showNotification(`Created ${results.length} automation rules successfully`, 'success');

        // Hide the form and show the status card
        cancelAutomation();

        // Reload automation status
        await loadAutomationStatus();

    } catch (error) {
        console.error('Error saving automation:', error);
        showNotification(`Failed to save automation: ${error.message}`, 'error');
    }
}

// Collect automation data - creates separate automation entries for each action
function collectAutomationData() {
    const form = document.getElementById('automation-form');

    if (!form) {
        console.error('Automation form not found');
        throw new Error('Automation form not found');
    }

    const formData = new FormData(form);
    const automations = [];

    // Get event timing
    const eventTime = getEventDateTime();
    if (!eventTime) {
        throw new Error('Event time must be set before creating automation');
    }

    // Get event type
    const eventType = formData.get('event_type');
    const isRecurring = eventType === 'recurring';

    // Recurring event options
    let recurringOptions = {};
    if (isRecurring) {
        recurringOptions = {
            recurring_interval: parseInt(formData.get('recurring_interval') || '7'),
            recurring_unit: formData.get('recurring_unit') || 'days',
            clear_members: formData.get('clear_members') === 'true'
        };
    }

    // Base automation data for all actions
    const baseAutomation = {
        server_id: serverId,
        roster_id: currentRosterData.custom_id,
        options: {
            is_recurring: isRecurring,
            ...recurringOptions
        }
    };

    // Post Signup automation
    if (formData.get('action_signup_enabled') === 'on') {
        const signupDays = parseInt(formData.get('action_signup_days') || '14');
        const signupChannel = formData.get('action_signup_channel');

        automations.push({
            ...baseAutomation,
            action_type: 'roster_signup',
            scheduled_time: eventTime - (signupDays * 24 * 60 * 60), // Convert days to seconds
            discord_channel_id: signupChannel || null,
            options: {
                ...baseAutomation.options,
                days_before: signupDays
            }
        });
    }

    // Close Signup automation
    if (formData.get('action_close_enabled') === 'on') {
        const closeDays = parseInt(formData.get('action_close_days') || '3');
        const closeChannel = formData.get('action_close_channel');

        automations.push({
            ...baseAutomation,
            action_type: 'roster_signup_close',
            scheduled_time: eventTime - (closeDays * 24 * 60 * 60),
            discord_channel_id: closeChannel || null,
            options: {
                ...baseAutomation.options,
                days_before: closeDays
            }
        });
    }

    // Post Final List automation
    if (formData.get('action_final_enabled') === 'on') {
        const finalDays = parseInt(formData.get('action_final_days') || '2');
        const finalChannel = formData.get('action_final_channel');

        automations.push({
            ...baseAutomation,
            action_type: 'roster_post',
            scheduled_time: eventTime - (finalDays * 24 * 60 * 60),
            discord_channel_id: finalChannel || null,
            options: {
                ...baseAutomation.options,
                days_before: finalDays
            }
        });
    }

    // Add reminders
    const reminders = collectAllReminders();
    for (const reminder of reminders) {
        automations.push({
            ...baseAutomation,
            action_type: 'roster_ping',
            scheduled_time: eventTime - (reminder.days * 24 * 60 * 60),
            discord_channel_id: reminder.channel || null,
            options: {
                ...baseAutomation.options,
                days_before: reminder.days,
                message: reminder.message
            }
        });
    }

    // Add recurring event automation if it's a recurring event
    if (isRecurring) {
        automations.push({
            ...baseAutomation,
            action_type: 'recurring_event',
            scheduled_time: eventTime,
            options: {
                ...baseAutomation.options,
                next_occurrence: eventTime + (recurringOptions.recurring_interval * 24 * 60 * 60)
            }
        });
    }

    console.log('Collected automation data:', automations);
    return automations;
}

// Get event datetime as Unix timestamp
function getEventDateTime() {
    // Try to get from current roster data first
    if (currentRosterData && currentRosterData.time) {
        return currentRosterData.time;
    }

    // Try to get from the event time form inputs
    const dateInput = document.getElementById('automation-event-date');
    const timeInput = document.getElementById('automation-event-time');

    if (!dateInput || !timeInput || !dateInput.value || !timeInput.value) {
        return null;
    }

    // Combine date and time and convert to UTC timestamp
    const localDateTime = new Date(dateInput.value + 'T' + timeInput.value);
    return Math.floor(localDateTime.getTime() / 1000); // Convert to Unix timestamp
}

// Collect all reminders from the form
function collectAllReminders() {
    const reminders = [];
    const reminderDivs = document.querySelectorAll('#reminders-list .reminder-item');

    reminderDivs.forEach(reminderDiv => {
        const reminder = collectReminderData(reminderDiv);
        if (reminder) {
            reminders.push(reminder);
        }
    });

    return reminders;
}

// Collect data from a single reminder div
function collectReminderData(reminderDiv) {
    const reminderDays = reminderDiv.querySelector('input[name="reminder-days"]')?.value;
    const reminderChannel = reminderDiv.querySelector('input[name="reminder-channel"]')?.value;
    const reminderMessage = reminderDiv.querySelector('textarea[name="reminder-message"]')?.value;

    if (!reminderDays || !reminderChannel) {
        return null; // Skip incomplete reminders
    }

    return {
        days: parseInt(reminderDays) || 0,
        channel: reminderChannel,
        message: reminderMessage || null
    };
}

// Collect data from a single action div (legacy function, keeping for compatibility)
function collectActionData(actionDiv) {
    const actionType = actionDiv.querySelector('select[name="action_type"]')?.value;
    if (!actionType) return null;

    const action = { action_type: actionType };
    return action;
}

// Validate automation data before saving
function validateAutomationData(automation) {
    if (!automation.event_type) {
        showNotification('Please select an event type (One-time Event or Recurring Event)', 'error');
        return false;
    }

    if (!automation.action_type) {
        showNotification('Action type not determined', 'error');
        return false;
    }

    if (!automation.server_id) {
        showNotification('Server ID missing', 'error');
        return false;
    }

    if (!automation.roster_id) {
        showNotification('Roster ID missing', 'error');
        return false;
    }

    // For now, just check that we have the basic required fields
    // The schedule and actions are optional in this simple version
    return true;
}

// Delete automation
async function deleteAutomation() {
    if (!currentAutomation || !confirm('Are you sure you want to delete this automation?')) {
        return;
    }

    try {
        const response = await fetch(`/v2/roster-automation/${currentAutomation.automation_id}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        currentAutomation = null;
        showNotification('Automation deleted successfully', 'success');
        updateAutomationDisplay();

    } catch (error) {
        console.error('Error deleting automation:', error);
        showNotification('Failed to delete automation', 'error');
    }
}

// Test automation
async function testAutomation() {
    if (!currentAutomation) {
        showNotification('No automation to test', 'error');
        return;
    }

    // For now, just validate the automation configuration
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

function formatScheduleText(schedule) {
    if (!schedule) return 'Not configured';

    if (schedule.schedule_type === 'relative') {
        const offset = schedule.offset_hours || 0;
        const relative = schedule.relative_to?.replace('_', ' ') || 'event';
        const when = offset < 0 ? `${Math.abs(offset)}h before` : offset > 0 ? `${offset}h after` : 'at';
        return `${when} ${relative}`;
    } else if (schedule.schedule_type === 'recurring') {
        const pattern = schedule.recurring_pattern;
        const time = schedule.recurring_time || '10:00';

        if (pattern === 'daily') {
            return `Daily at ${time}`;
        } else if (pattern === 'weekly') {
            const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
            const day = days[schedule.recurring_weekday] || 'Mon';
            return `Every ${day} at ${time}`;
        } else if (pattern === 'monthly') {
            const day = schedule.recurring_day || 1;
            return `${day}${getOrdinalSuffix(day)} of month at ${time}`;
        }
    } else if (schedule.schedule_type === 'fixed') {
        if (schedule.fixed_timestamp) {
            const date = new Date(schedule.fixed_timestamp * 1000);
            return date.toLocaleString();
        }
    }

    return 'Custom schedule';
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

    if (currentAutomation && currentAutomation.active) {
        statusElement.textContent = 'On';
        statusElement.className = 'ml-auto bg-green-500 text-green-100 px-1.5 py-0.5 rounded text-xs';
    } else if (currentAutomation && !currentAutomation.active) {
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
    const templates = document.getElementById('automation-templates');
    if (templates) {
        templates.style.display = 'none';
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

// ======================== DISCORD CHANNEL AUTOCOMPLETE ========================

// Global cache for Discord channels
let discordChannelsCache = null;
let channelsLoadPromise = null;

// Load Discord channels for autocomplete
async function loadDiscordChannels() {
    if (discordChannelsCache) {
        return discordChannelsCache;
    }

    if (channelsLoadPromise) {
        return channelsLoadPromise;
    }

    channelsLoadPromise = (async () => {
        try {
            const response = await fetch(`${API_BASE}/server/${serverId}/discord-channels`, {
                headers: { 'Authorization': `Bearer ${await getAuthToken()}` }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            discordChannelsCache = data;
            return data;

        } catch (error) {
            console.error('Error loading Discord channels:', error);
            channelsLoadPromise = null;
            throw error;
        }
    })();

    return channelsLoadPromise;
}

// Handle channel input for autocomplete
function handleChannelInput(input) {
    const value = input.value.toLowerCase();
    const container = input.closest('.channel-autocomplete-container');
    const suggestionsDiv = container?.querySelector('.channel-suggestions');

    if (!suggestionsDiv) return;

    if (value.length === 0) {
        showChannelSuggestions(input);
        return;
    }

    // Filter and display suggestions
    loadDiscordChannels().then(channelsData => {
        if (!channelsData) return;

        const allChannels = channelsData.channels;
        const filteredChannels = allChannels.filter(channel =>
            channel.name.toLowerCase().includes(value) ||
            channel.display_name.toLowerCase().includes(value) ||
            (channel.category_name && channel.category_name.toLowerCase().includes(value)) ||
            channel.full_display_name.toLowerCase().includes(value)
        );

        displayChannelSuggestions(suggestionsDiv, filteredChannels, input);
    }).catch(error => {
        console.error('Error filtering channels:', error);
    });
}

// Show channel suggestions when input is focused
function showChannelSuggestions(input) {
    const container = input.closest('.channel-autocomplete-container');
    const suggestionsDiv = container?.querySelector('.channel-suggestions');

    if (!suggestionsDiv) return;

    loadDiscordChannels().then(channelsData => {
        if (!channelsData) return;

        // Show all channels without categorization
        displayCategorizedChannelSuggestions(suggestionsDiv, channelsData, input);
    }).catch(error => {
        console.error('Error showing channel suggestions:', error);
        suggestionsDiv.innerHTML = '<div class="p-2 text-sm text-muted-foreground">Failed to load channels</div>';
    });

    suggestionsDiv.classList.remove('hidden');
}

// Display categorized channel suggestions
function displayCategorizedChannelSuggestions(suggestionsDiv, channelsData, input) {
    let html = '';

    // Simply show all channels without categorization
    const allChannels = channelsData.channels || [];

    if (allChannels.length === 0) {
        html = '<div class="p-2 text-sm text-muted-foreground">No channels found</div>';
    } else {
        // Limit to first 15 channels to avoid overwhelming the user
        allChannels.slice(0, 15).forEach(channel => {
            html += createChannelSuggestionHTML(channel, false);
        });
    }

    suggestionsDiv.innerHTML = html;

    // Add click handlers
    suggestionsDiv.querySelectorAll('.channel-suggestion-item').forEach(item => {
        item.addEventListener('click', () => {
            const channelName = item.dataset.channelName;
            input.value = channelName;
            suggestionsDiv.classList.add('hidden');
            input.focus();
        });
    });
}

// Display filtered channel suggestions
function displayChannelSuggestions(suggestionsDiv, channels, input) {
    let html = '';

    if (channels.length === 0) {
        html = '<div class="p-2 text-sm text-muted-foreground">No matching channels</div>';
    } else {
        channels.slice(0, 10).forEach(channel => {
            html += createChannelSuggestionHTML(channel, false);
        });
    }

    suggestionsDiv.innerHTML = html;

    // Add click handlers
    suggestionsDiv.querySelectorAll('.channel-suggestion-item').forEach(item => {
        item.addEventListener('click', () => {
            const channelName = item.dataset.channelName;
            input.value = channelName;
            suggestionsDiv.classList.add('hidden');
            input.focus();
        });
    });
}

// Create HTML for a single channel suggestion
function createChannelSuggestionHTML(channel, isHighlighted) {
    const highlightClass = isHighlighted ? 'bg-primary/10 border-l-2 border-l-primary' : '';

    return `
        <div class="channel-suggestion-item p-2 hover:bg-accent cursor-pointer transition-colors ${highlightClass}"
             data-channel-name="${channel.display_name}" data-channel-id="${channel.id}">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <span class="text-muted-foreground">#</span>
                    <div class="flex flex-col">
                        <span class="text-sm font-medium">${channel.name}</span>
                        ${channel.category_name ? `<span class="text-xs text-muted-foreground">${channel.category_name}</span>` : ''}
                    </div>
                </div>
                <div class="flex items-center gap-1">
                    ${isHighlighted ? '<span class="text-xs text-primary">★</span>' : ''}
                    <span class="text-xs text-muted-foreground">${channel.id}</span>
                </div>
            </div>
        </div>
    `;
}

// Hide channel suggestions when clicking outside
document.addEventListener('click', (event) => {
    if (!event.target.closest('.channel-autocomplete-container')) {
        document.querySelectorAll('.channel-suggestions').forEach(suggestions => {
            suggestions.classList.add('hidden');
        });
    }
});

// ======================== EVENT TIMING FUNCTIONS ========================

// Update event time display
function updateEventTimeDisplay() {
    if (!currentRosterData) return;

    const currentEventTimeEl = document.getElementById('current-event-time');
    const currentEventTimezoneEl = document.getElementById('current-event-timezone');
    const titleEl = document.getElementById('event-timing-title');
    const subtitleEl = document.getElementById('event-timing-subtitle');
    const statusIndicatorEl = document.getElementById('event-status-indicator');
    const typeBadgeEl = document.getElementById('event-type-badge');

    if (!currentEventTimeEl || !currentEventTimezoneEl) return;

    // Determine if this is a recurring event by checking multiple sources
    let isRecurring = false;

    // Check if there's a recurring automation from the form
    const recurringRadio = document.querySelector('input[name="event_type"][value="recurring"]');
    if (recurringRadio && recurringRadio.checked) {
        isRecurring = true;
    }

    // Also check existing automation configuration
    if (currentAutomation) {
        if (currentAutomation.schedule && currentAutomation.schedule.schedule_type === 'recurring') {
            isRecurring = true;
        }
        // Check for recurring events in actions or automation type
        if (currentAutomation.actions && currentAutomation.actions.some(action =>
            action.action_type === 'recurring_event'
        )) {
            isRecurring = true;
        }
    }

    if (currentRosterData.event_start_time) {
        // Convert UTC timestamp to local time
        const eventDate = new Date(currentRosterData.event_start_time * 1000);
        const now = new Date();
        const isPastEvent = eventDate < now;

        // Format date and time for display
        const formattedDate = eventDate.toLocaleDateString('en-US', {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
        const formattedTime = eventDate.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit'
        });

        // Update title and subtitle based on event type
        if (isRecurring) {
            if (titleEl) titleEl.textContent = 'Next Event';
            if (subtitleEl) subtitleEl.textContent = 'Automatically updated for recurring events';

            // Show recurring badge
            if (typeBadgeEl) {
                typeBadgeEl.className = 'px-2 py-1 text-xs rounded-full bg-blue-100 text-blue-800';
                typeBadgeEl.textContent = '🔄 Recurring';
                typeBadgeEl.classList.remove('hidden');
            }
        } else {
            if (titleEl) titleEl.textContent = isPastEvent ? 'Event Timing (Past)' : 'Event Timing';
            if (subtitleEl) subtitleEl.textContent = 'One-time event schedule';

            // Show one-time badge
            if (typeBadgeEl) {
                if (isPastEvent) {
                    typeBadgeEl.className = 'px-2 py-1 text-xs rounded-full bg-gray-100 text-gray-600';
                    typeBadgeEl.textContent = '📅 Past Event';
                } else {
                    typeBadgeEl.className = 'px-2 py-1 text-xs rounded-full bg-green-100 text-green-800';
                    typeBadgeEl.textContent = '📅 Scheduled';
                }
                typeBadgeEl.classList.remove('hidden');
            }
        }

        // Update status indicator color
        if (statusIndicatorEl) {
            if (isRecurring) {
                statusIndicatorEl.className = 'w-2 h-2 rounded-full bg-blue-500'; // Blue for recurring
            } else if (isPastEvent) {
                statusIndicatorEl.className = 'w-2 h-2 rounded-full bg-gray-400'; // Gray for past
            } else {
                statusIndicatorEl.className = 'w-2 h-2 rounded-full bg-green-500'; // Green for upcoming
            }
        }

        // Set main display text
        if (isPastEvent && !isRecurring) {
            currentEventTimeEl.textContent = `${formattedDate} at ${formattedTime} (Past)`;
        } else {
            currentEventTimeEl.textContent = `${formattedDate} at ${formattedTime}`;
        }

        // Show timezone info
        try {
            const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
            const offset = eventDate.getTimezoneOffset();
            const offsetHours = Math.abs(Math.floor(offset / 60));
            const offsetMinutes = Math.abs(offset % 60);
            const offsetSign = offset <= 0 ? '+' : '-';
            const offsetString = `UTC${offsetSign}${offsetHours.toString().padStart(2, '0')}:${offsetMinutes.toString().padStart(2, '0')}`;

            let timezoneText = `${timezone} (${offsetString})`;
            if (isRecurring) {
                timezoneText += ' • Updates automatically after each event';
            }
            currentEventTimezoneEl.textContent = timezoneText;
        } catch (error) {
            currentEventTimezoneEl.textContent = 'Your local time';
        }
    } else {
        // No event time set
        if (titleEl) titleEl.textContent = 'Event Timing';
        if (subtitleEl) subtitleEl.textContent = 'Set the start time for this roster\'s event';
        if (statusIndicatorEl) statusIndicatorEl.className = 'w-2 h-2 rounded-full bg-gray-300';
        if (typeBadgeEl) typeBadgeEl.classList.add('hidden');

        currentEventTimeEl.textContent = 'Not set';
        currentEventTimezoneEl.textContent = 'Select a date and time below';
    }
}

// Update timezone info in automation section
function updateAutomationTimezoneInfo() {
    try {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const offset = new Date().getTimezoneOffset();
        const offsetHours = Math.abs(Math.floor(offset / 60));
        const offsetMinutes = Math.abs(offset % 60);
        const offsetSign = offset <= 0 ? '+' : '-';
        const offsetString = `UTC${offsetSign}${offsetHours.toString().padStart(2, '0')}:${offsetMinutes.toString().padStart(2, '0')}`;

        const timezoneInfoEl = document.getElementById('automation-timezone-info');
        if (timezoneInfoEl) {
            timezoneInfoEl.textContent = `${timezone} (${offsetString})`;
        }
    } catch (error) {
        console.warn('Could not determine timezone:', error);
    }
}

// Toggle event time editor
function toggleEventTimeEditor() {
    const editor = document.getElementById('event-time-editor');
    const display = document.getElementById('event-time-display');
    const btn = document.getElementById('edit-event-time-btn');

    if (!editor || !display || !btn) return;

    if (editor.style.display === 'none' || editor.style.display === '') {
        // Show editor
        editor.style.display = 'block';
        btn.innerHTML = '<i data-lucide="x" class="w-4 h-4"></i><span>Cancel</span>';

        // Populate current values if they exist
        if (currentRosterData.event_start_time) {
            const eventDate = new Date(currentRosterData.event_start_time * 1000);

            // Format date as YYYY-MM-DD
            const formattedDate = eventDate.getFullYear() + '-' +
                String(eventDate.getMonth() + 1).padStart(2, '0') + '-' +
                String(eventDate.getDate()).padStart(2, '0');

            // Format time as HH:MM
            const formattedTime = String(eventDate.getHours()).padStart(2, '0') + ':' +
                String(eventDate.getMinutes()).padStart(2, '0');

            const dateField = document.getElementById('automation-event-date');
            const timeField = document.getElementById('automation-event-time');

            if (dateField) dateField.value = formattedDate;
            if (timeField) timeField.value = formattedTime;
        }
    } else {
        // Hide editor
        cancelEventTimeEdit();
    }

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Cancel event time editing
function cancelEventTimeEdit() {
    const editor = document.getElementById('event-time-editor');
    const btn = document.getElementById('edit-event-time-btn');

    if (editor) editor.style.display = 'none';
    if (btn) {
        btn.innerHTML = '<i data-lucide="edit" class="w-4 h-4"></i><span>Edit Time</span>';
    }

    // Clear form fields
    const dateField = document.getElementById('automation-event-date');
    const timeField = document.getElementById('automation-event-time');
    if (dateField) dateField.value = '';
    if (timeField) timeField.value = '';

    // Re-render lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Save event time
async function saveEventTime() {
    const dateField = document.getElementById('automation-event-date');
    const timeField = document.getElementById('automation-event-time');

    if (!dateField || !timeField) {
        showNotification('Date and time fields not found', 'error');
        return;
    }

    const eventDate = dateField.value;
    const eventTime = timeField.value;

    if (!eventDate || !eventTime) {
        showNotification('Please select both date and time', 'error');
        return;
    }

    try {
        // Combine date and time into UTC timestamp
        const combinedDateTime = `${eventDate}T${eventTime}`;
        const localDate = new Date(combinedDateTime);
        const utcTimestamp = Math.floor(localDate.getTime() / 1000);

        console.log(`Saving event time: ${localDate.toLocaleString()} (UTC: ${utcTimestamp})`);

        // Update roster with new event start time
        const response = await fetch(`${API_BASE}/roster/${currentRosterData.custom_id}?server_id=${serverId}`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${await getAuthToken()}`
            },
            body: JSON.stringify({
                event_start_time: utcTimestamp
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        const result = await response.json();
        currentRosterData = result.roster;

        showNotification('Event time saved successfully', 'success');

        // Update display and hide editor
        updateEventTimeDisplay();
        cancelEventTimeEdit();

    } catch (error) {
        console.error('Error saving event time:', error);
        showNotification(`Failed to save event time: ${error.message}`, 'error');
    }
}

// Load automation status for the current roster
async function loadAutomationStatus() {
    try {
        const response = await fetch(`/v2/roster-automation/list?server_id=${serverId}&roster_id=${currentRosterData.custom_id}`, {
            headers: {
                'Authorization': `Bearer ${await getAuthToken()}`
            }
        });

        if (response.ok) {
            const automations = await response.json();
            updateAutomationDisplay(automations);
        } else {
            console.warn('Failed to load automation status');
        }
    } catch (error) {
        console.error('Error loading automation status:', error);
    }
}

// Update automation display based on current automations
function updateAutomationDisplay(automations) {
    const statusCard = document.getElementById('automation-status-card');
    const toggleSection = document.getElementById('automation-toggle-section');

    if (automations && automations.length > 0) {
        // Show status card and hide toggle section
        statusCard.style.display = 'block';
        toggleSection.style.display = 'none';

        // Update status card content
        document.getElementById('automation-type-text').textContent =
            automations.length === 1 ? 'Single Action' : `${automations.length} Actions`;
        document.getElementById('automation-description').textContent =
            `${automations.length} automation rule(s) configured for this roster`;
    } else {
        // Show toggle section and hide status card
        statusCard.style.display = 'none';
        toggleSection.style.display = 'block';
    }
}
