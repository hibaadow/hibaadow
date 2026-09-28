(function () {
  var form = document.getElementById('waitlist-form');
  var formWrap = document.getElementById('form-wrap');
  var thanks = document.getElementById('thanks');
  var submitBtn = document.getElementById('submit-btn');
  var formError = document.getElementById('form-error');
  var shareBtn = document.getElementById('share-btn');
  var shareMsg = document.getElementById('share-msg');

  var DRAFT_KEY = 'sway-waitlist-draft';
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  var loadedAt = Date.now();

  // ---------- Keep what people typed (even if they close the tab) ----------
  function readForm() {
    return {
      firstName: form.firstName.value.trim(),
      email: form.email.value.trim(),
      city: form.city.value.trim(),
      ageRange: (form.querySelector('input[name="ageRange"]:checked') || {}).value || '',
      activities: Array.prototype.map.call(
        form.querySelectorAll('input[name="activities"]:checked'),
        function (el) { return el.value; }
      ),
      handle: form.handle.value.trim(),
      consent: form.consent.checked,
      website: form.website.value
    };
  }

  function saveDraft() {
    try {
      var d = readForm();
      delete d.website;
      localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
    } catch (e) { /* storage unavailable: fine */ }
  }

  function restoreDraft() {
    var d;
    try { d = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch (e) { d = null; }
    if (!d) return;
    form.firstName.value = d.firstName || '';
    form.email.value = d.email || '';
    form.city.value = d.city || '';
    form.handle.value = d.handle || '';
    form.consent.checked = !!d.consent;
    form.querySelectorAll('input[name="ageRange"]').forEach(function (el) {
      el.checked = el.value === d.ageRange;
    });
    form.querySelectorAll('input[name="activities"]').forEach(function (el) {
      el.checked = (d.activities || []).indexOf(el.value) !== -1;
    });
  }

  function clearDraft() {
    try { localStorage.removeItem(DRAFT_KEY); } catch (e) {}
  }

  restoreDraft();
  form.addEventListener('input', saveDraft);
  form.addEventListener('change', saveDraft);

  // ---------- Validation ----------
  function setError(id, msg) {
    var input = document.getElementById(id);
    var err = document.getElementById(id + '-err');
    if (err) err.textContent = msg || '';
    if (input) input.setAttribute('aria-invalid', msg ? 'true' : 'false');
  }

  function validate(d) {
    var errors = {};
    if (!d.firstName) errors.firstName = 'Please add your first name.';
    if (!d.email) errors.email = 'Please add your email.';
    else if (!EMAIL_RE.test(d.email)) errors.email = "That email doesn't look quite right. Can you check it?";
    if (!d.city) errors.city = 'Which city are you in?';
    if (!d.consent) errors.consent = 'Please tick this so we can email you when Sway launches.';

    ['firstName', 'email', 'city', 'consent'].forEach(function (k) { setError(k, errors[k]); });
    return errors;
  }

  // Clear a field's error as soon as they fix it
  ['firstName', 'email', 'city', 'consent'].forEach(function (id) {
    document.getElementById(id).addEventListener('input', function () { setError(id, ''); });
    document.getElementById(id).addEventListener('change', function () { setError(id, ''); });
  });

  // ---------- Submit ----------
  function showThanks() {
    clearDraft();
    formWrap.hidden = true;
    thanks.hidden = false;
    thanks.focus({ preventScroll: true });
    document.getElementById('join').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function showFormError(msg) {
    formError.textContent = msg;
    formError.hidden = false;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    formError.hidden = true;

    var d = readForm();
    var errors = validate(d);
    var firstBad = Object.keys(errors)[0];
    if (firstBad) {
      document.getElementById(firstBad).focus();
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Adding you to the list…';

    d.elapsedMs = Date.now() - loadedAt;

    fetch('/api/join', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(d)
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (r) {
        if (r.ok && r.body.ok) {
          showThanks();
        } else {
          if (r.body.field) setError(r.body.field, r.body.error);
          showFormError(r.body.error ||
            "Oops, something went wrong on our side. Your answers are still here, so just tap the button again.");
        }
      })
      .catch(function () {
        showFormError("Hmm, we couldn't connect. Check your internet and tap the button again. Your answers are saved.");
      })
      .then(function () {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Join the waitlist';
      });
  });

  // ---------- Share ----------
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) {}
      document.body.removeChild(ta);
      ok ? resolve() : reject();
    });
  }

  shareBtn.addEventListener('click', function () {
    var link = window.location.origin + '/';
    copyText(link).then(function () {
      shareMsg.textContent = 'Link copied! Send it to your group chat 💕';
    }, function () {
      shareMsg.textContent = 'Copy this link: ' + link;
    });
  });
})();
