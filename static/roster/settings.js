/**
 * Settings Management Functions
 */

// Save roster settings
async function saveRosterSettings(event) {
    event.preventDefault();
    
    const form = event.target;
    const formData = new FormData(form);
    
    // Build update data
    const updateData = {};
    
    // Basic fields
    if (formData.get('alias')) updateData.alias = formData.get('alias');
    if (formData.get('roster_size')) updateData.roster_size = parseInt(formData.get('roster_size'));
    if (formData.get('description') !== null) updateData.description = formData.get('description') || null;

    // Event start time - combine date and time fields to Unix timestamp (UTC)
    const eventStartDate = formData.get('event_start_date');
    const eventStartTime = formData.get('event_start_time');

    if (eventStartDate && eventStartTime) {
        // Combine date and time into a single datetime string
        const combinedDateTime = `${eventStartDate}T${eventStartTime}`;
        // Create date object and convert to UTC timestamp
        const localDate = new Date(combinedDateTime);
        updateData.event_start_time = Math.floor(localDate.getTime() / 1000);

        console.log(`Local time: ${localDate.toLocaleString()}`);
        console.log(`UTC timestamp: ${updateData.event_start_time}`);
        console.log(`UTC time: ${new Date(updateData.event_start_time * 1000).toUTCString()}`);
    } else if (eventStartDate) {
        // If only date is provided, use midnight local time
        const combinedDateTime = `${eventStartDate}T00:00`;
        const localDate = new Date(combinedDateTime);
        updateData.event_start_time = Math.floor(localDate.getTime() / 1000);
    } else {
        updateData.event_start_time = null;
    }
    
    // Organization fields
    if (formData.get('roster_type')) updateData.roster_type = formData.get('roster_type');
    if (formData.get('signup_scope')) updateData.signup_scope = formData.get('signup_scope');
    if (formData.get('clan_tag') !== null) updateData.clan_tag = formData.get('clan_tag') || null;
    
    // Requirements
    if (formData.get('min_th')) updateData.min_th = parseInt(formData.get('min_th'));
    else if (formData.get('min_th') === '') updateData.min_th = null;
    
    if (formData.get('max_th')) updateData.max_th = parseInt(formData.get('max_th'));
    else if (formData.get('max_th') === '') updateData.max_th = null;
    
    if (formData.get('max_accounts_per_user')) updateData.max_accounts_per_user = parseInt(formData.get('max_accounts_per_user'));
    else if (formData.get('max_accounts_per_user') === '') updateData.max_accounts_per_user = null;
    
    // Handle allowed categories checkboxes
    const allowedCategories = formData.getAll('allowed_signup_categories');
    updateData.allowed_signup_categories = allowedCategories.length > 0 ? allowedCategories : null;
    
    try {
        const response = await apiCall(`${API_BASE}/roster/${currentRosterId}?server_id=${serverId}`, 'PATCH', updateData);
        
        // Update local roster data
        currentRosterData = response.roster;
        
        showAlert('Settings saved successfully!');
        
        // Update UI elements that depend on roster data
        updateRosterUI(currentRosterData);
        
    } catch (error) {
        console.error('Error saving settings:', error);
        showAlert('Failed to save settings: ' + error.message, 'error');
    }
}

// Update form with roster data
function updateSettingsForm(roster) {
    if (!roster) return;

    console.log('updateSettingsForm called with roster:', roster);
    console.log('event_start_time in roster:', roster.event_start_time);
    console.log('time in roster:', roster.time);

    const form = document.getElementById('roster-form');
    if (!form) return;

    try {
        // Basic information
        if (roster.alias) form.elements['alias'].value = roster.alias;
        if (roster.roster_size) form.elements['roster_size'].value = roster.roster_size;
        if (roster.description) form.elements['description'].value = roster.description;

        // Event start time - convert Unix timestamp to separate date and time fields (local time)
        if (roster.event_start_time) {
            // Convert UTC timestamp to local time
            const date = new Date(roster.event_start_time * 1000);

            console.log(`Stored UTC timestamp: ${roster.event_start_time}`);
            console.log(`Converted to local time: ${date.toLocaleString()}`);
            console.log(`UTC time: ${date.toUTCString()}`);

            // Format date as YYYY-MM-DD (local date)
            const formattedDate = date.getFullYear() + '-' +
                String(date.getMonth() + 1).padStart(2, '0') + '-' +
                String(date.getDate()).padStart(2, '0');

            const dateField = document.getElementById('event_start_date');
            if (dateField) dateField.value = formattedDate;

            // Format time as HH:MM (local time)
            const formattedTime = String(date.getHours()).padStart(2, '0') + ':' +
                String(date.getMinutes()).padStart(2, '0');

            const timeField = document.getElementById('event_start_time');
            if (timeField) timeField.value = formattedTime;
        }
        
        // Organization
        if (roster.roster_type) form.elements['roster_type'].value = roster.roster_type;
        if (roster.signup_scope) form.elements['signup_scope'].value = roster.signup_scope;
        if (roster.clan_tag) form.elements['clan_tag'].value = roster.clan_tag;
        
        // Requirements
        if (roster.min_th) form.elements['min_th'].value = roster.min_th;
        if (roster.max_th) form.elements['max_th'].value = roster.max_th;
        if (roster.max_accounts_per_user) form.elements['max_accounts_per_user'].value = roster.max_accounts_per_user;
        
        // Categories checkboxes
        const categoryCheckboxes = form.querySelectorAll('input[name="allowed_signup_categories"]');
        categoryCheckboxes.forEach(checkbox => {
            checkbox.checked = roster.allowed_signup_categories && 
                               roster.allowed_signup_categories.includes(checkbox.value);
        });
        
        // Update display columns dropdowns
        const displayColumns = roster.columns || ['townhall', 'name', 'tag', 'hitrate'];
        
        // Set column configuration
        for (let i = 1; i <= 4; i++) {
            const element = document.getElementById(`column-${i}`);
            if (element) {
                element.value = displayColumns[i - 1] || '';
            }
        }
        
        // Update sort configuration  
        const sortConfig = roster.sort || ['townhall', 'name'];
        
        // Set sort configuration
        for (let i = 1; i <= 4; i++) {
            const element = document.getElementById(`sort-${i}`);
            if (element) {
                element.value = sortConfig[i - 1] || '';
            }
        }
        
    } catch (error) {
        console.error('Error updating settings form:', error);
    }
}

// Initialize date/time fields with default values if empty (for testing)
function initializeDateTimeFields() {
    const dateField = document.getElementById('event_start_date');
    const timeField = document.getElementById('event_start_time');

    // Set default time to current time for testing
    if (timeField && !timeField.value) {
        const now = new Date();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        timeField.value = `${hours}:${minutes}`;
    }

    // Update timezone info in the UI
    updateTimezoneInfo();

    console.log('Date field:', dateField, dateField?.value);
    console.log('Time field:', timeField, timeField?.value);
}

// Update timezone information in the UI
function updateTimezoneInfo() {
    try {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const offset = new Date().getTimezoneOffset();
        const offsetHours = Math.abs(Math.floor(offset / 60));
        const offsetMinutes = Math.abs(offset % 60);
        const offsetSign = offset <= 0 ? '+' : '-';
        const offsetString = `UTC${offsetSign}${offsetHours.toString().padStart(2, '0')}:${offsetMinutes.toString().padStart(2, '0')}`;

        // Update the help text to include timezone
        const timeHelpText = document.querySelector('input[name="event_start_time"] + p');
        if (timeHelpText) {
            timeHelpText.textContent = `Time of the event/war (${timezone}, ${offsetString})`;
        }

        console.log(`User timezone: ${timezone} (${offsetString})`);
    } catch (error) {
        console.warn('Could not determine timezone:', error);
    }
}

// Call initialization when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(initializeDateTimeFields, 100);

    // If we have current roster data, update the form
    setTimeout(() => {
        if (typeof currentRosterData !== 'undefined' && currentRosterData) {
            console.log('Initializing settings form with current roster data:', currentRosterData);
            updateSettingsForm(currentRosterData);
        }
    }, 200);
});