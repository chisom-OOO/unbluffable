// Accounts (Firebase), loaded on every page after ui.js. With no Firebase config the site
// works exactly as before: no sign-in anywhere, the profile kept in this browser. With it:
// guests can interview, but their profile, rating and history are kept only for the visit;
// signed-in profiles are merged with users/{uid} and synced on every change (account-core.js).
(() => {
  const SDK = "https://www.gstatic.com/firebasejs/10.12.2/";
  const PARTS = ["firebase-app-compat.js", "firebase-auth-compat.js", "firebase-firestore-compat.js"];
  let account = null, enabled = false, resolveReady;
  const whenReady = new Promise((r) => { resolveReady = r; });
  const emit = () => document.dispatchEvent(new CustomEvent("ub-account", { detail: state() }));
  const state = () => (account ? account.state() : { enabled, ready: true, user: null, firstTime: false });

  function load(src) {
    return new Promise((resolve, reject) => {
      const tag = Object.assign(document.createElement("script"), { src, async: false });
      tag.onload = resolve; tag.onerror = () => reject(new Error(`couldn't load ${src}`));
      document.head.appendChild(tag);
    });
  }

  // Guests' changes stay in memory for the visit; signed-in changes go to the account too.
  function guard(store) {
    let guestCopy = null;
    const save = store.save.bind(store), loadProfile = store.load.bind(store);
    store.load = () => (account && account.guest && guestCopy ? guestCopy : loadProfile());
    store.save = (p) => {
      if (account && account.guest) { guestCopy = p; return false; }
      const kept = save(p);
      account?.push(p);
      return kept;
    };
    return store;
  }

  async function start() {
    let config = null;
    try { config = await (await fetch("/api/firebase-config")).json(); } catch { config = null; }
    if (!config || !config.enabled) { resolveReady(state()); emit(); return; }
    enabled = true;
    try {
      for (const part of PARTS) await load(SDK + part);
      let local = null;
      try { local = window.localStorage; } catch { local = null; }
      account = window.UBAccountCore.createAccount({ sdk: window.firebase, config: config.config, store: guard(window.UB.profile()), storage: local,
                                                        popupOnly: window.UB.appleTouch() });
      account.on(() => emit());
      await account.completeEmailLink(location.href, async () => prompt("Which email did you use to sign in?"))
        .then((done) => {
          if (!done) return;
          const url = new URL(location.href);
          ["apiKey", "oobCode", "mode", "lang", "continueUrl"].forEach((k) => url.searchParams.delete(k));
          history.replaceState(null, "", url.pathname + url.search);
        })
        .catch(() => {});
      resolveReady(await account.whenReady);
    } catch {
      enabled = false;  // the SDK didn't load: carry on as a site without accounts
      resolveReady(state());
    }
    emit();
  }

  // ---------- The sign-in dialog: Google first, an email link as the backup ----------
  let dialog = null;
  function openSignIn(reason) {
    if (!account) return;
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.className = "gate-dialog signin-dialog";
      dialog.setAttribute("aria-labelledby", "signin-title");
      dialog.innerHTML = `<div class="dialog-head"><h2 id="signin-title" tabindex="-1">Sign in to save your progress</h2>
        <form method="dialog"><button class="icon-btn" type="submit" aria-label="Close"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button></form></div>
        <p class="muted" id="signin-reason"></p>
        <button class="btn wide" type="button" id="signin-google">Continue with Google</button>
        <p class="signin-or"><span>or</span></p>
        <form class="signin-email" id="signin-email-form">
          <label for="signin-email">Email me a sign-in link</label>
          <div class="name-form"><input class="text-input" type="email" id="signin-email" autocomplete="email" required placeholder="you@example.com">
          <button class="btn secondary" type="submit">Send link</button></div>
        </form>
        <p class="status" id="signin-status" role="status" hidden></p>`;
      document.body.appendChild(dialog);
      const say = (text) => { const el = dialog.querySelector("#signin-status"); el.textContent = text; el.hidden = !text; };
      // The popup opens synchronously in this tap (no await before signInWithGoogle).
      dialog.querySelector("#signin-google").addEventListener("click", async () => {
        say("");
        try { await account.signInWithGoogle(); dialog.close(); } catch (error) {
          if (window.UB.appleTouch()) {  // iPhone and iPad: straight to the email link
            say("Use an email link instead.");
            const field = dialog.querySelector("#signin-email");
            field.scrollIntoView({ block: "nearest" });
            field.focus();
            return;
          }
          say(`Couldn't sign in with Google${error?.code ? ` (${error.code})` : ""}. Try again or use the email link.`);
        }
      });
      dialog.querySelector("#signin-email-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = dialog.querySelector("#signin-email").value.trim();
        try { await account.sendEmailLink(email, location.href); say(`Check ${email} for a sign-in link. Open it in this browser.`); }
        catch (error) { say(`Couldn't send the link${error?.code ? ` (${error.code})` : ""}.`); }
      });
    }
    dialog.querySelector("#signin-reason").textContent = reason || "Your profile, rating and history are kept with your account and synced across your devices.";
    dialog.querySelector("#signin-status").hidden = true;
    dialog.showModal();
    dialog.querySelector("#signin-title").focus();
  }

  window.UBAccount = {
    whenReady,
    get enabled() { return enabled; },
    get guest() { return enabled && (!account || account.guest); },
    get user() { return account ? account.user : null; },
    get firstTime() { return account ? account.firstTime : false; },
    state,
    openSignIn,
    signOut: () => account?.signOut(),
    // With Firebase on: also write the shared roles to "interest" (no uid, no email). Off: nothing.
    shareInterest: async (roles, otherText) => { await whenReady; if (account) await account.shareInterest(roles, otherText); },
    deleteAccount: () => account?.deleteAccount(),
  };
  document.addEventListener("DOMContentLoaded", start);
})();
