// Accounts with the Firebase SDK faked: first sign-in, returning user, merge, sync, sign-out, delete.
const assert = require("node:assert/strict");
const path = require("node:path");
const P = require(path.resolve(__dirname, "../app/static/ui/profile-core.js"));
const { createAccount } = require(path.resolve(__dirname, "../app/static/ui/account-core.js"));

function fakeSdk(docs = new Map()) {
  let listener = null, current = null;
  const calls = [];
  const sdk = {
    calls, docs,
    initializeApp: (config) => { calls.push(["init", config.projectId]); return {}; },
    auth: Object.assign(() => auth, { GoogleAuthProvider: function GoogleAuthProvider() { this.id = "google"; } }),
    firestore: () => ({ collection: (name) => ({ doc: (id) => ({
      async get() { const key = `${name}/${id}`; return { exists: docs.has(key), data: () => docs.get(key) }; },
      async set(value) { calls.push(["set", `${name}/${id}`]); docs.set(`${name}/${id}`, JSON.parse(JSON.stringify(value))); },
      async delete() { calls.push(["delete", `${name}/${id}`]); docs.delete(`${name}/${id}`); },
    }) }) }),
    as(user) { current = user && { ...user, async delete() { calls.push(["deleteUser", user.uid]); if (user.stale && !user.reauthed) throw { code: "auth/requires-recent-login" }; },
                                    async reauthenticateWithPopup() { user.reauthed = true; calls.push(["reauth"]); } };
               return listener(current); },
  };
  const auth = {
    onAuthStateChanged(fn) { listener = fn; },
    get currentUser() { return current; },
    async signInWithPopup(provider) { calls.push(["popup", provider.id]); },
    async signInWithRedirect(provider) { calls.push(["redirect", provider.id]); },
    async sendSignInLinkToEmail(email, settings) { calls.push(["link", email, settings.url, settings.handleCodeInApp]); },
    isSignInWithEmailLink: (href) => href.includes("oobCode="),
    async signInWithEmailLink(email, href) { calls.push(["linkSignIn", email]); },
    async signOut() { calls.push(["signOut"]); current = null; },
  };
  return sdk;
}

function memoryStore() {
  const data = new Map();
  const local = { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k) };
  return { store: P.store(local), local };
}

const CONFIG = { apiKey: "public-id", authDomain: "x.firebaseapp.com", projectId: "unbluffable", storageBucket: "b", messagingSenderId: "1", appId: "a" };

(async () => {
  // --- First sign-in: no document yet; this browser's profile goes up as it is ---
  {
    const sdk = fakeSdk();
    const { store, local } = memoryStore();
    const p = store.load(); p.answers.push({ s: "s1", t: "quant", a: "Probability", v: 0.85, p: false, d: "2026-10-31" });
    p.history.push({ session: "s1", track: "quant", date: "2026-10-31", before: null, after: null });
    store.save(p);
    const account = createAccount({ sdk, config: CONFIG, store, now: () => "T1", storage: local });
    await sdk.as({ uid: "u1", email: "ada@example.com", displayName: "Ada Lovelace", photoURL: "https://photo" });
    const state = await account.whenReady;
    assert.equal(state.user.email, "ada@example.com");
    assert.equal(account.firstTime, true, "no account document: the 'Make it yours' step comes next");
    const doc = sdk.docs.get("users/u1");
    assert.equal(doc.updated_at, "T1");
    assert.deepEqual(doc.profile.history.map((h) => h.session), ["s1"]);
    assert.ok(!JSON.stringify(doc).includes("transcript"), "no answer text is uploaded");
    // Every change is pushed to the account.
    p.name = "Ada"; p.identity_at = "2026-10-31T10:00:00Z";
    store.save(p);
    await account.flush(p);
    assert.equal(sdk.docs.get("users/u1").profile.name, "Ada");
    // Signing out leaves nothing of the account in this browser.
    await account.signOut();
    assert.deepEqual(store.load(), P.empty());
    assert.equal(account.user, null);
  }

  // --- Returning user on a new device: merge, newest name and photo win, history is a union ---
  {
    const cloud = { ...P.empty(), onboarded: "done", roles: ["ib"], roles_at: "2026-10-30T09:00:00Z", default_track: "ib",
                    name: "Grace Hopper", identity_at: "2026-10-31T09:00:00Z",
                    answers: [{ s: "c1", t: "ib", a: "DCF", v: 1, p: true, d: "2026-10-30" }],
                    history: [{ session: "c1", track: "ib", date: "2026-10-30", before: null, after: 100 }],
                    placement: { ib: { date: "2026-10-30", scores: { DCF: 100 } } } };
    const sdk = fakeSdk(new Map([["users/u2", { profile: cloud, updated_at: "T0" }]]));
    const { store } = memoryStore();
    const local = store.load();
    local.name = "Grace"; local.identity_at = "2026-10-29T00:00:00Z";  // older than the account's
    local.answers.push({ s: "l1", t: "quant", a: "Probability", v: 0.6, p: false, d: "2026-10-31" },
                       { s: "c1", t: "ib", a: "DCF", v: 1, p: true, d: "2026-10-30" });  // the same session, already up there
    local.history.push({ session: "l1", track: "quant", date: "2026-10-31", before: null, after: null },
                       { session: "c1", track: "ib", date: "2026-10-30", before: null, after: 100 });
    store.save(local);
    const account = createAccount({ sdk, config: CONFIG, store, now: () => "T2" });
    await sdk.as({ uid: "u2", email: "grace@example.com", displayName: "Grace Hopper" });
    await account.whenReady;
    assert.equal(account.firstTime, false, "returning user: no onboarding");
    const merged = store.load();
    assert.equal(merged.name, "Grace Hopper", "the newer name wins");
    assert.deepEqual(merged.roles, ["ib"]);
    assert.deepEqual(merged.history.map((h) => h.session).sort(), ["c1", "l1"], "union by session");
    assert.equal(merged.answers.filter((x) => x.s === "c1").length, 1, "a session's answers are not doubled");
    assert.equal(P.areaScores(merged, "ib", ["DCF"])[0].score, 100, "area values recomputed from the answers");
    assert.deepEqual(sdk.docs.get("users/u2").profile, merged, "both copies the same");
    // The newer local name wins the other way round.
    const later = P.mergeProfiles({ ...merged, name: "G. Hopper", identity_at: "2026-11-01T00:00:00Z" }, cloud);
    assert.equal(later.name, "G. Hopper");
    assert.equal(P.mergeProfiles(merged, null).name, "Grace Hopper", "nothing in the account: this browser's copy");
  }

  // --- Delete my account: the document first, then the sign-in; a stale sign-in asks again ---
  {
    const sdk = fakeSdk(new Map([["users/u3", { profile: { ...P.empty(), onboarded: "done" } }]]));
    const { store } = memoryStore();
    const account = createAccount({ sdk, config: CONFIG, store });
    await sdk.as({ uid: "u3", email: "x@example.com", stale: true });
    await account.whenReady;
    await account.deleteAccount();
    const order = sdk.calls.map((c) => c[0]).filter((c) => ["delete", "deleteUser", "reauth"].includes(c));
    assert.deepEqual(order, ["delete", "deleteUser", "reauth", "deleteUser"]);
    assert.equal(sdk.docs.has("users/u3"), false);
    assert.deepEqual(store.load(), P.empty());
  }

  // --- Google first (popup, redirect if blocked); the email link remembers the address ---
  {
    const sdk = fakeSdk();
    const { store, local } = memoryStore();
    const account = createAccount({ sdk, config: CONFIG, store, storage: local });
    await account.signInWithGoogle();
    await account.sendEmailLink("ada@example.com", "https://site/ui/end?session=abc");
    assert.deepEqual(sdk.calls.find((c) => c[0] === "link"), ["link", "ada@example.com", "https://site/ui/end?session=abc", true]);
    assert.equal(await account.completeEmailLink("https://site/ui?nothing", async () => null), false);
    assert.equal(await account.completeEmailLink("https://site/ui?oobCode=1", async () => { throw new Error("not asked"); }), true);
    assert.deepEqual(sdk.calls.find((c) => c[0] === "linkSignIn"), ["linkSignIn", "ada@example.com"]);
    assert.equal(local.getItem("ub-email-for-link"), null);
  }
  console.log("account ok");
})().catch((e) => { console.error(e); process.exit(1); });
