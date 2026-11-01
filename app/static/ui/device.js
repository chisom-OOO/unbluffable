// Device rules (decision log 35): which screens run the interview, and the iPad specifics.
// Pure functions over plain values, so the Node unit test can check them without a browser.
(() => {
  // Phones get the "open this on a laptop or tablet" screen; tablets (iPad mini and up, in
  // either orientation, touch-only or not) and laptops run. The smaller screen dimension
  // decides, so turning a phone sideways does not let it through; a window under 700 px
  // wide is also too narrow for the room.
  const PHONE_MAX = 700;
  function phoneSized({ screenWidth, screenHeight, innerWidth }) {
    return Math.min(screenWidth, screenHeight) < PHONE_MAX || innerWidth < PHONE_MAX;
  }

  // iPhone, iPod or iPad. iPadOS Safari reports itself as a Mac ("Macintosh", platform
  // "MacIntel"); a Mac has no touch points, an iPad has several.
  function appleTouch({ userAgent = "", platform = "", maxTouchPoints = 0 } = {}) {
    if (/iPad|iPhone|iPod/.test(userAgent) || /^(iPad|iPhone|iPod)/.test(platform)) return true;
    return (/Mac/.test(platform) || /Macintosh/.test(userAgent)) && maxTouchPoints > 1;
  }

  // Touch-only: a coarse pointer and no fine one (no mouse or trackpad). An iPad with a
  // trackpad keyboard is not touch-only.
  const touchOnly = ({ coarse, anyFine }) => !!coarse && !anyFine;

  // The visible area while the on-screen keyboard is open (iPad Safari shrinks the visual
  // viewport, not the layout one). `keyboard` is true when more than 120 px is covered.
  function viewportFrame(vv, innerHeight) {
    if (!vv) return { height: innerHeight, top: 0, keyboard: false };
    const height = Math.round(vv.height), top = Math.max(0, Math.round(vv.offsetTop || 0));
    return { height, top, keyboard: innerHeight - height > 120 };
  }

  const api = { PHONE_MAX, phoneSized, appleTouch, touchOnly, viewportFrame };
  if (typeof module !== "undefined") module.exports = api;
  else window.UBDevice = api;
})();
