/* Turns the long CV form into five steps. Without this script the page stays
   one long form that still works, so nothing here may be needed to submit. */
(function () {
    'use strict';
    var form = document.getElementById('cv_build_form');
    if (!form) { return; }
    var card = form.closest('details');
    var main = form.closest('main');
    var steps = Array.prototype.slice.call(form.querySelectorAll('section.step'));
    var TOTAL = steps.length;
    var byId = function (id) { return document.getElementById(id); };
    var nextBtn = byId('cv_next');
    var backBtn = byId('cv_back');
    var nav = byId('cv_nav');
    var saved = byId('cv_saved');
    var noExp = byId('no_experience');
    var current = Math.min(Math.max(parseInt(form.dataset.startStep, 10) || 1, 1), TOTAL);

    form.noValidate = true;
    main.classList.add('js-on');

    function val(name) {
        var el = form.elements[name];
        return el ? el.value.trim() : '';
    }

    /* ── Saving ─────────────────────────────────────────────────────────── */

    function saveDraft(step) {
        var data = new FormData(form);
        data.append('step', step);
        saved.textContent = 'Saving…';
        return fetch(form.dataset.draftUrl, {method: 'POST', body: data, credentials: 'same-origin'})
            .then(function (res) {
                saved.textContent = res.ok ? 'Saved' : 'Not saved yet';
            })
            .catch(function () {
                // No signal: they can carry on. The next step tries again.
                saved.textContent = 'Not saved yet';
            });
    }

    /* ── Jobs and schools: one at a time ────────────────────────────────── */

    function Row(el) {
        this.el = el;
        this.fields = el.querySelector('.row-fields');
        this.card = el.querySelector('.row-card');
        this.err = el.querySelector('.row-err');
        this.inputs = Array.prototype.slice.call(el.querySelectorAll('input, textarea'));
        this.required = el.dataset.required;
        this.subs = (el.dataset.sub || '').split(',');
        this.snapshot = [];
        var self = this;
        el.querySelector('.row-save').addEventListener('click', function () { self.save(); });
        el.querySelector('.row-cancel').addEventListener('click', function () { self.cancel(); });
        el.querySelector('.row-edit').addEventListener('click', function () { self.open(); });
        el.querySelector('.row-remove').addEventListener('click', function () { self.remove(); });
    }
    Row.prototype.hasContent = function () {
        return this.inputs.some(function (i) { return i.value.trim(); });
    };
    Row.prototype.show = function (mode) {
        this.mode = mode; // hidden | editing | saved
        this.el.hidden = mode === 'hidden';
        this.fields.hidden = mode !== 'editing';
        this.card.hidden = mode !== 'saved';
        this.err.hidden = true;
    };
    Row.prototype.fillCard = function () {
        this.card.querySelector('b').textContent = val(this.required);
        this.card.querySelector('small').textContent = this.subs.map(val).filter(Boolean).join(', ');
    };
    Row.prototype.open = function () {
        this.snapshot = this.inputs.map(function (i) { return i.value; });
        this.previous = this.mode;
        this.show('editing');
        update();
        this.inputs[0].focus();
    };
    Row.prototype.save = function () {
        if (!val(this.required)) {
            this.err.hidden = false;
            this.inputs[0].focus();
            return;
        }
        this.fillCard();
        this.show('saved');
        if (noExp && this.el.dataset.kind === 'job') { noExp.checked = false; }
        update();
        saveDraft(current);
    };
    Row.prototype.cancel = function () {
        var snapshot = this.snapshot;
        this.inputs.forEach(function (input, i) { input.value = snapshot[i] || ''; });
        this.show(this.previous === 'saved' ? 'saved' : 'hidden');
        update();
    };
    Row.prototype.remove = function () {
        this.inputs.forEach(function (i) { i.value = ''; });
        this.show('hidden');
        update();
        saveDraft(current);
    };

    function rowsOf(kind) {
        return Array.prototype.slice.call(form.querySelectorAll('.row[data-kind="' + kind + '"]')).map(function (el) {
            var row = new Row(el);
            if (row.hasContent()) {
                row.fillCard();
                row.show('saved');
            } else {
                row.show('hidden');
            }
            return row;
        });
    }
    var jobs = rowsOf('job');
    var edus = rowsOf('edu');
    var allRows = jobs.concat(edus);

    function count(rows, mode) {
        return rows.filter(function (r) { return r.mode === mode; }).length;
    }
    function firstHidden(rows) {
        return rows.filter(function (r) { return r.mode === 'hidden'; })[0];
    }
    function editing() {
        return allRows.filter(function (r) { return r.mode === 'editing'; })[0];
    }

    byId('job_add_first').addEventListener('click', function () { firstHidden(jobs).open(); });
    byId('job_add').addEventListener('click', function () { firstHidden(jobs).open(); });
    byId('edu_add').addEventListener('click', function () { firstHidden(edus).open(); });
    byId('job_none').addEventListener('click', function () {
        noExp.checked = true;
        update();
        saveDraft(current);
    });
    byId('job_none_undo').addEventListener('click', function () {
        noExp.checked = false;
        firstHidden(jobs).open();
    });

    /* ── Review ─────────────────────────────────────────────────────────── */

    function lines(rows, first, second) {
        return rows.filter(function (r) { return r.mode === 'saved'; }).map(function (r) {
            return r.inputs.slice(first, second).map(function (i) { return i.value.trim(); }).filter(Boolean).join(', ');
        }).join('\n');
    }
    function ticked(name) {
        return Array.prototype.slice.call(form.querySelectorAll('input[name="' + name + '"]:checked'))
            .map(function (i) { return i.value; });
    }
    function buildReview() {
        var skills = ticked('skill_opt');
        if (val('skills')) { skills.push(val('skills')); }
        var langs = ticked('lang_opt');
        if (val('languages')) { langs.push(val('languages')); }
        var nothing = 'Nothing added';
        var rows = [
            ['About you', 1, [val('full_name'), val('town'), val('email')].filter(Boolean).join('\n')],
            ['Work experience', 2, lines(jobs, 0, 2) || (noExp.checked ? 'No work experience yet' : nothing)],
            ['Education', 3, lines(edus, 0, 2) || nothing],
            ['Skills', 4, (skills.join(', ') || nothing) + '\nLicence: ' + form.elements.licence.value],
            ['Languages', 4, langs.join(', ') || nothing],
        ];
        var box = byId('cv_review');
        box.textContent = '';
        rows.forEach(function (row) {
            var item = document.createElement('div');
            item.className = 'row-card';
            var text = document.createElement('div');
            var label = document.createElement('b');
            label.textContent = row[0];
            var value = document.createElement('small');
            value.className = 'pre';
            value.textContent = row[2];
            text.appendChild(label);
            text.appendChild(value);
            var edit = document.createElement('button');
            edit.type = 'button';
            edit.className = 'link';
            edit.textContent = 'Edit';
            edit.setAttribute('aria-label', 'Edit ' + row[0]);
            edit.addEventListener('click', function () { go(row[1]); });
            item.appendChild(text);
            item.appendChild(edit);
            box.appendChild(item);
        });
    }

    /* ── Moving between steps ───────────────────────────────────────────── */

    function update() {
        var isJobs = current === 2;
        var isEdus = current === 3;
        var open = editing();
        var noJobs = count(jobs, 'saved') === 0;
        var asking = isJobs && noJobs && !noExp.checked && !open;
        byId('job_ask').hidden = !asking;
        byId('job_none_note').hidden = !(isJobs && noExp.checked && !open);
        byId('job_add').hidden = !(isJobs && !open && !noJobs && firstHidden(jobs));
        byId('edu_add').hidden = !(isEdus && !open && firstHidden(edus));
        byId('edu_add').textContent = count(edus, 'saved') ? 'Add another' : 'Add your school or course';
        nav.hidden = !!open;
        nextBtn.disabled = asking;
        nextBtn.textContent = current === TOTAL ? 'Create my CV' : isEdus && count(edus, 'saved') === 0 ? 'Skip for now' : 'Next';
    }

    function go(step) {
        current = step;
        steps.forEach(function (el, i) { el.hidden = i + 1 !== step; });
        byId('cv_step_label').textContent = 'Step ' + step + ' of ' + TOTAL;
        Array.prototype.forEach.call(form.querySelectorAll('.progress i'), function (bar, i) {
            bar.className = i < step ? 'on' : '';
        });
        byId('cv_progress').setAttribute('aria-label', 'Step ' + step + ' of ' + TOTAL);
        if (step === TOTAL) { buildReview(); }
        update();
        var heading = steps[step - 1].querySelector('h2');
        if (heading) { heading.focus({preventScroll: true}); }
        window.scrollTo(0, 0);
    }

    function stepValid() {
        if (current !== 1) { return true; }
        var name = form.elements.full_name;
        var email = form.elements.email;
        var nameErr = byId('name_err');
        nameErr.hidden = !!name.value.trim();
        if (!name.value.trim()) {
            name.focus();
            return false;
        }
        return email.reportValidity();
    }

    function next() {
        if (nextBtn.disabled || !stepValid()) { return; }
        saveDraft(current + 1);
        go(current + 1);
    }

    function finish() {
        nextBtn.disabled = true;
        nextBtn.textContent = 'Creating your CV…';
        form.submit();
    }

    // Always a plain button: if it became a submit button during this click,
    // the same click would create the CV and skip the review step.
    nextBtn.addEventListener('click', function () {
        if (current === TOTAL) { finish(); } else { next(); }
    });
    backBtn.addEventListener('click', function () {
        if (current === 1) {
            card.open = false;
        } else {
            go(current - 1);
        }
    });
    // Enter in a text box: finish what's on screen, don't create the CV early.
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var open = editing();
        if (open) {
            open.save();
        } else if (current === TOTAL) {
            finish();
        } else {
            next();
        }
    });
    function building() {
        main.classList.toggle('building', card.open);
    }
    card.addEventListener('toggle', building);
    building();
    go(current);
})();
