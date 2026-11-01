// Accounts (Firebase): sign-in, merge and sync of the profile with users/{uid}. Pure logic
// over an injected SDK (the Firebase compat API in the browser, a fake in the Node test).
// The Firestore document holds { profile, updated_at }: the same profile the browser keeps,
// never any interview answer text.
(() => {
  const P = typeof module !== "undefined" ? require("./profile-core.js") : window.UBProfile;
  const COLLECTION = "users";
  const INTEREST = "interest";
  const INTEREST_ROLES = ["quant", "quant_dev", "ib", "consulting", "software", "other"];  // as firestore.rules

  // `redirect`: sign in with Google by redirect, not a popup (iPhone and iPad Safari block
  // popups opened after the tap; decision log 35).
  function createAccount({ sdk, config, store, now = () => new Date().toISOString(), storage = null, redirect = false }) {
    const app = sdk.initializeApp(config);
    const auth = sdk.auth(app);
    const db = sdk.firestore(app);
    const listeners = new Set();
    let user = null, firstTime = false, ready = false, pushTimer = null;
    let resolveReady;
    const whenReady = new Promise((r) => { resolveReady = r; });
    const doc = () => db.collection(COLLECTION).doc(user.uid);
    const emit = () => listeners.forEach((fn) => fn(state()));
    const state = () => ({ enabled: true, ready, user: user && { uid: user.uid, email: user.email || "", name: user.displayName || "",
                                                                 photoURL: user.photoURL || "" }, firstTime });

    async function write(profile) {
      if (!user) return;
      await doc().set({ profile: JSON.parse(JSON.stringify(profile)), updated_at: now() });
    }

    // Signed in: merge this browser's profile with the account's, keep both the same.
    async function signedIn(next) {
      user = next;
      const snapshot = await doc().get();
      const cloud = snapshot.exists ? (snapshot.data() || {}).profile : null;
      firstTime = !snapshot.exists || !cloud || cloud.onboarded !== "done";
      const merged = P.mergeProfiles(store.load(), cloud);
      store.save(merged);
      await write(merged);
    }

    auth.onAuthStateChanged(async (next) => {
      try {
        if (next) await signedIn(next);
        else { user = null; firstTime = false; }
      } finally {
        ready = true;
        resolveReady(state());
        emit();
      }
    });

    return {
      get user() { return state().user; },
      get firstTime() { return firstTime; },
      get guest() { return ready && !user; },
      whenReady,
      on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
      state,
      // Every change to the profile goes to the account too (debounced).
      push(profile, delay = 400) {
        if (!user) return;
        clearTimeout(pushTimer);
        pushTimer = setTimeout(() => { write(profile).catch(() => {}); }, delay);
      },
      flush(profile) { clearTimeout(pushTimer); return write(profile); },
      async signInWithGoogle() {
        const provider = new sdk.auth.GoogleAuthProvider();
        if (redirect) return auth.signInWithRedirect(provider);
        try {
          await auth.signInWithPopup(provider);
        } catch (error) {
          if (/popup-blocked|operation-not-supported/.test(error?.code || "")) return auth.signInWithRedirect(provider);
          throw error;
        }
      },
      async sendEmailLink(email, url) {
        await auth.sendSignInLinkToEmail(email, { url, handleCodeInApp: true });
        try { storage?.setItem("ub-email-for-link", email); } catch { /* blocked */ }
      },
      // Back from the email: finish signing in with the address saved when the link was sent.
      async completeEmailLink(href, askEmail) {
        if (!auth.isSignInWithEmailLink(href)) return false;
        let email = null;
        try { email = storage?.getItem("ub-email-for-link"); } catch { email = null; }
        email = email || (await askEmail());
        if (!email) return false;
        await auth.signInWithEmailLink(email, href);
        try { storage?.removeItem("ub-email-for-link"); } catch { /* blocked */ }
        return true;
      },
      // Signing out leaves nothing of the account in this browser.
      async signOut() {
        clearTimeout(pushTimer);
        await auth.signOut();
        user = null;
        store.clear();
        emit();
      },
      // Deletes the account's document, then the sign-in itself.
      async deleteAccount() {
        if (!user) return;
        clearTimeout(pushTimer);
        await doc().delete();
        const current = auth.currentUser;
        try {
          await current.delete();
        } catch (error) {
          if (error?.code !== "auth/requires-recent-login") throw error;
          // By redirect on iPhone and iPad: the account is deleted on the next tap, once back.
          if (redirect) return current.reauthenticateWithRedirect(new sdk.auth.GoogleAuthProvider());
          await current.reauthenticateWithPopup(new sdk.auth.GoogleAuthProvider());
          await current.delete();
        }
        user = null;
        store.clear();
        emit();
      },
      // "Share this": one write-only document in "interest", for guests too. No uid, no email,
      // nothing else; firestore.rules allows exactly these fields and nobody may read them.
      async shareInterest(roles, otherText) {
        await db.collection(INTEREST).add(interestDoc(roles, otherText, sdk.firestore.FieldValue.serverTimestamp()));
      },
    };
  }

  function interestDoc(roles, otherText, createdAt) {
    return { roles: [...new Set(roles)].filter((r) => INTEREST_ROLES.includes(r)),
             other_text: String(otherText || "").trim().slice(0, 200), created_at: createdAt };
  }

  const api = { createAccount, COLLECTION, INTEREST, INTEREST_ROLES, interestDoc };
  if (typeof module !== "undefined") module.exports = api;
  else window.UBAccountCore = api;
})();
