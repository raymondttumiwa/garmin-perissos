/* Passwords and sessions are managed by Supabase Auth, not by our tables. */
let accountTransition = 0;
let goalSaveQueue = Promise.resolve();

function accountStorageKey(key) {
    if (!accountUser) throw new Error('Sign in first');
    return `${key}:${accountUser.id}`;
}

async function accountAccessToken() {
    const { data, error } = await accountClient.auth.getSession();
    if (error || !data.session || data.session.user.id !== accountUser?.id) throw new Error('Please sign in again');
    return data.session.access_token;
}

async function initializeAccounts() {
    document.getElementById('public-landing').hidden = false;
    document.getElementById('account-gate').hidden = true;
    const config = window.PERISSOS_CONFIG || {};
    const message = document.getElementById('account-message');
    if (!config.supabaseUrl || !config.supabaseKey || !window.supabase) {
        message.textContent = 'Account setup is pending. The site owner must configure site-config.js and run the account database migration.';
        document.getElementById('account-login').disabled = true;
        document.getElementById('account-register').disabled = true;
        return;
    }
    accountClient = window.supabase.createClient(config.supabaseUrl, config.supabaseKey);
    cloudConfig = { supabaseUrl: config.supabaseUrl.replace(/\/$/, ''), supabaseKey: config.supabaseKey, userId: '' };
    accountClient.auth.onAuthStateChange((event, session) => {
        if (event === 'SIGNED_OUT' || (event === 'SIGNED_IN' && session?.user.id !== accountUser?.id)) {
            // SDK callbacks must finish before calling other Auth methods.
            setTimeout(() => activateAccount(session?.user || null), 0);
        }
    });
    const { data, error } = await accountClient.auth.getSession();
    if (error) message.textContent = 'Could not restore your session. Please log in again.';
    await activateAccount(data.session?.user || null);
}

function showAccountGate(create = false) {
    document.getElementById('public-landing').hidden = true;
    document.getElementById('account-gate').hidden = false;
    document.getElementById('account-message').textContent = 'Log in or create your personal account.';
    if (create) document.getElementById('account-username').focus();
    window.scrollTo({top: 0, behavior: 'smooth'});
}

function showPublicLanding() {
    document.getElementById('account-gate').hidden = true;
    document.getElementById('public-landing').hidden = false;
    window.scrollTo({top: 0, behavior: 'smooth'});
}

async function submitAccount(event, register = false) {
    event.preventDefault();
    const form = document.getElementById('account-username').form;
    if (!form.reportValidity() || !accountClient) return;
    const username = document.getElementById('account-username').value.trim().toLowerCase();
    const password = document.getElementById('account-password').value;
    const message = document.getElementById('account-message');
    const buttons = ['account-login', 'account-register'].map(id => document.getElementById(id));
    buttons.forEach(button => button.disabled = true);
    message.textContent = register ? 'Creating your account…' : 'Logging in…';
    try {
        // A fixed internal domain gives Supabase a unique identity for each username.
        // This address is not a mailbox; email confirmation must be disabled.
        const credentials = { email: `${username}@accounts.perissos.invalid`, password };
        const result = register
            ? await accountClient.auth.signUp({ ...credentials, options: { data: { username } } })
            : await accountClient.auth.signInWithPassword(credentials);
        if (result.error) throw result.error;
        if (!result.data.session) throw new Error('Account created, but login is unavailable. Ask the site owner to disable email confirmation for username accounts.');
        document.getElementById('account-password').value = '';
        await activateAccount(result.data.user);
    } catch (error) {
        message.textContent = error.message || 'Could not log in. Please try again.';
    } finally { buttons.forEach(button => button.disabled = false); }
}

async function activateAccount(user) {
    const transition = ++accountTransition;
    document.getElementById('authenticated-app').hidden = true;
    document.getElementById('account-gate').hidden = false;
    // Clear every modal and account's in-memory data before loading another account.
    document.querySelectorAll('[id$="-modal"], #account-details').forEach(modal => {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    });
    accountUser = user;
    telemetryByDate = {};
    rules = getDefaultRules();
    cloudConfig.userId = user?.id || '';
    cloudConfig.lastSync = null;
    const message = document.getElementById('account-message');
    if (!user) {
        document.getElementById('public-landing').hidden = false;
        message.textContent = 'Log in or create your personal account.';
        return;
    }
    message.textContent = 'Loading your progress…';
    telemetryByDate = loadTelemetry();
    rules = loadRules();
    try {
        const { data, error } = await accountClient.from('dashboard_goals').select('rules').eq('user_id', user.id).maybeSingle();
        if (transition !== accountTransition) return;
        if (error) throw error;
        if (data && Array.isArray(data.rules)) {
            rules = data.rules;
            localStorage.setItem(accountStorageKey(STORAGE_RULES_KEY), JSON.stringify(rules));
        }
        await fetchFromSupabase();
        if (transition !== accountTransition) return;
        document.getElementById('account-name').textContent = user.user_metadata?.username || 'My account';
        document.getElementById('account-gate').hidden = true;
        document.getElementById('public-landing').hidden = true;
        document.getElementById('authenticated-app').hidden = false;
        renderAll();
    } catch (error) {
        message.textContent = 'Could not load account data. Check your connection and that the account migration has been applied, then log in again.';
    }
}

function saveAccountGoals() {
    const userId = accountUser.id;
    const snapshot = JSON.parse(JSON.stringify(rules));
    goalSaveQueue = goalSaveQueue.catch(() => {}).then(async () => {
        if (accountUser?.id !== userId) return;
        const { error } = await accountClient.from('dashboard_goals').upsert({ user_id: userId, rules: snapshot }, { onConflict: 'user_id' });
        if (error) showToast('Goals saved on this device; cloud save failed. Please retry.', 'amber');
    });
    return goalSaveQueue;
}

async function signOutAccount() {
    const { error } = await accountClient.auth.signOut();
    if (error) { showToast('Could not log out. Please retry.', 'amber'); return; }
    await activateAccount(null);
}
