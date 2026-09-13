/**
 * Add / remove rows for Django inline formsets (management form must be inside root).
 */
(function () {
    function reindexFormsetRow(row, prefix, index) {
        var pattern = new RegExp(prefix + '-\\d+-', 'g');
        var replacement = prefix + '-' + index + '-';
        row.querySelectorAll('input, select, textarea, label').forEach(function (el) {
            ['name', 'id', 'for'].forEach(function (attr) {
                var value = el.getAttribute(attr);
                if (value) {
                    el.setAttribute(attr, value.replace(pattern, replacement));
                }
            });
        });
    }

    function syncFormsetIndices(body, prefix, totalInput) {
        var rows = body.querySelectorAll('[data-formset-row]');
        rows.forEach(function (row, index) {
            reindexFormsetRow(row, prefix, index);
        });
        totalInput.value = String(rows.length);
    }

    function clearFormsetRow(row) {
        row.querySelectorAll('input, select, textarea').forEach(function (el) {
            if (el.type === 'hidden' && el.name.endsWith('-id')) {
                el.value = '';
                return;
            }
            if (el.type === 'checkbox') {
                if (el.name.endsWith('-DELETE')) {
                    el.checked = false;
                }
                return;
            }
            if (el.tagName === 'SELECT') {
                el.selectedIndex = 0;
                return;
            }
            el.value = '';
        });
        row.classList.remove('is-removed');
        row.hidden = false;
    }

    function initInlineFormset(root) {
        var prefix = root.getAttribute('data-formset-prefix');
        if (!prefix) {
            return;
        }
        var totalInput = root.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]');
        var maxInput = root.querySelector('input[name="' + prefix + '-MAX_NUM_FORMS"]');
        var body = root.querySelector('[data-formset-body]');
        var addButton = root.querySelector('[data-formset-add]');
        if (!totalInput || !body || !addButton) {
            return;
        }

        addButton.addEventListener('click', function () {
            var total = parseInt(totalInput.value, 10);
            var maxNum = maxInput ? parseInt(maxInput.value, 10) : 1000;
            if (total >= maxNum) {
                return;
            }
            var templateRow = body.querySelector('[data-formset-row]:last-child');
            if (!templateRow) {
                return;
            }
            var newRow = templateRow.cloneNode(true);
            clearFormsetRow(newRow);
            body.appendChild(newRow);
            syncFormsetIndices(body, prefix, totalInput);
        });

        body.addEventListener('click', function (event) {
            var removeButton = event.target.closest('[data-formset-remove]');
            if (!removeButton) {
                return;
            }
            var row = removeButton.closest('[data-formset-row]');
            if (!row) {
                return;
            }
            var idInput = row.querySelector('input[name$="-id"]');
            var deleteInput = row.querySelector('input[name$="-DELETE"]');
            if (idInput && idInput.value && deleteInput) {
                deleteInput.checked = true;
                row.classList.add('is-removed');
                row.hidden = true;
                return;
            }
            row.remove();
            syncFormsetIndices(body, prefix, totalInput);
        });
    }

    document.querySelectorAll('[data-inline-formset]').forEach(initInlineFormset);
})();
