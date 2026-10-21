const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
    const elements = new Map();
    const storage = new Map();
    const requests = [];
    const element = id => {
        if (!elements.has(id)) elements.set(id, { hidden: false, classList: {add(){},remove(){},toggle(){}}, value: '', textContent: '', innerHTML: '', disabled: false });
        return elements.get(id);
    };
    const context = vm.createContext({
        window: {addEventListener(){}}, document: {getElementById: element, querySelectorAll(){return [];}},
        localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key,value) => storage.set(key,value)},
        fetch: async (url, options) => { requests.push({url, options}); return {ok: true,json: async () => []}; },
        setTimeout, console
    });
    const html = fs.readFileSync('index.html','utf8');
    const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).sort((a,b)=>b.length-a.length)[0];
    vm.runInContext(script,context);
    vm.runInContext(fs.readFileSync('accounts.js','utf8'),context);
    vm.runInContext(`
        renderAll = () => {};
        showToast = () => {};
        cloudConfig = {supabaseUrl:'https://example.supabase.co',supabaseKey:'public'};
        accountClient = {
            auth: {getSession: async () => ({data: {session: {user: {id:accountUser.id},access_token:'jwt-'+accountUser.id}}})},
            from: () => ({select: () => ({eq: () => ({maybeSingle: async () => ({data:null,error:null})})})})
        };
    `,context);
    return {context, storage, requests, element, run: code => vm.runInContext(code, context)};
}

test('accounts start empty and never inherit another user or legacy browser progress', async () => {
    const h = harness();
    h.storage.set('rooted_built_telemetry_v3', JSON.stringify({'2026-10-21':{manual_logs:{g_devotion:99}}}));
    await h.run("activateAccount({id:'alice'})");
    assert.equal(h.run('Object.keys(telemetryByDate).length'),0);
    h.run("telemetryByDate['2026-10-21']={date:'2026-10-21', manual_logs:{g_devotion:25}}; saveTelemetry();");
    await h.run("activateAccount({id:'bob'})");
    assert.equal(h.run('Object.keys(telemetryByDate).length'),0);
    await h.run("activateAccount({id:'alice'})");
    assert.equal(h.run("telemetryByDate['2026-10-21'].manual_logs.g_devotion"),25);
    await h.run('activateAccount(null)');
    assert.equal(h.element('authenticated-app').hidden,true);
    assert.equal(h.run('Object.keys(telemetryByDate).length'),0);
});

test('manual saves use authenticated account and omit cached Garmin measurements', async () => {
    const h = harness();
    await h.run("activateAccount({id:'alice'})");
    await h.run("pushDayTelemetryToSupabase({date:'2026-10-21',user_id:'bob',steps:0,activities:[],manual_logs:{habit:true}})");
    const request = h.requests.at(-1);
    assert(request.url.endsWith('?on_conflict=user_id,date'));
    assert.equal(request.options.headers.Authorization,'Bearer jwt-alice');
    assert.deepEqual(JSON.parse(request.options.body),{user_id:'alice',date:'2026-10-21',manual_logs:{habit:true}});
});

test('goals restored from cloud replace account cache including empty goal lists', async () => {
    const h = harness();
    h.run("accountClient.from = () => ({select: () => ({eq: () => ({maybeSingle: async () => ({data:{rules:[]},error:null})})})});");
    await h.run("activateAccount({id:'alice'})");
    assert.equal(h.run('rules.length'),0);
    assert.equal(h.storage.get('rooted_built_hybrid_goals_v3:alice'),'[]');
});

test('missing public config leaves account dashboard locked', async () => {
    const h = harness();
    h.element('authenticated-app').hidden = true;
    await h.run('initializeAccounts()');
    assert.equal(h.element('authenticated-app').hidden,true);
    assert.equal(h.element('account-login').disabled,true);
    assert(h.element('account-message').textContent.includes('setup is pending'));
});

test('a response arriving after account switch cannot replace the current account data', async () => {
    const h = harness();
    await h.run("activateAccount({id:'alice'})");
    let release;
    h.context.fetch = () => new Promise(resolve => { release = resolve; });
    const pending = h.run('fetchFromSupabase()');
    await new Promise(resolve => setImmediate(resolve));
    await h.run('activateAccount(null)');
    release({ok:true,json:async () => [{date:'2026-10-21',manual_logs:{secret:10},activities:[]}]});
    assert.equal(await pending,false);
    assert.equal(h.run('Object.keys(telemetryByDate).length'),0);
});

test('a different signed-in SDK user cannot supply the dashboard access token', async () => {
    const h = harness();
    await h.run("activateAccount({id:'alice'})");
    h.run("accountClient.auth.getSession = async () => ({data:{session:{user:{id:'bob'},access_token:'bob-token'}}})");
    await assert.rejects(h.run('accountAccessToken()'), /sign in again/);
});
