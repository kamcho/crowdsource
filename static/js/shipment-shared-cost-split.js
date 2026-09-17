(function () {
    var form = document.getElementById('shared-cost-split-form');
    var table = document.getElementById('shipment-products-table');
    var preview = document.getElementById('shared-cost-split-preview');
    var selectAll = document.getElementById('shared-cost-select-all');
    var modal = document.getElementById('shared-cost-split-modal');
    var openBtn = document.getElementById('open-shared-cost-modal');
    var countEl = document.getElementById('shared-cost-selected-count');
    var modalCountEl = document.getElementById('shared-cost-modal-count');
    if (!form || !table) {
        return;
    }

    var amountInput = form.querySelector('[name="amount"]');

    function selectedRows() {
        return Array.prototype.filter.call(
            table.querySelectorAll('[data-shared-cost-row]'),
            function (row) {
                var cb = row.querySelector('.shared-cost-batch-check');
                return cb && cb.checked;
            },
        );
    }

    function selectedCount() {
        return selectedRows().length;
    }

    function splitByUnits(total, unitCounts) {
        var sum = unitCounts.reduce(function (a, b) {
            return a + b;
        }, 0);
        if (!total || total <= 0 || !sum) {
            return [];
        }
        var shares = [];
        var remainders = [];
        var running = 0;
        for (var i = 0; i < unitCounts.length; i++) {
            var exact = (total * unitCounts[i]) / sum;
            var floored = Math.floor(exact * 100) / 100;
            shares.push(floored);
            remainders.push({ index: i, rem: exact - floored });
            running += floored;
        }
        var centsLeft = Math.round((total - running) * 100);
        remainders.sort(function (a, b) {
            return b.rem - a.rem;
        });
        for (var c = 0; c < centsLeft; c++) {
            shares[remainders[c % remainders.length].index] += 0.01;
        }
        return shares.map(function (s) {
            return Math.round(s * 100) / 100;
        });
    }

    function updatePreview() {
        if (!preview) {
            return;
        }
        var rows = selectedRows();
        var raw = amountInput && amountInput.value ? parseFloat(amountInput.value) : NaN;
        if (!rows.length || !raw || raw <= 0) {
            preview.hidden = true;
            preview.textContent = '';
            return;
        }
        var names = [];
        var units = [];
        rows.forEach(function (row) {
            names.push(row.getAttribute('data-product-name') || 'Product');
            units.push(parseInt(row.getAttribute('data-units') || '0', 10) || 0);
        });
        if (units.reduce(function (a, b) {
            return a + b;
        }, 0) <= 0) {
            preview.hidden = false;
            preview.textContent = 'Selected products have no units — set units imported first.';
            return;
        }
        var shares = splitByUnits(raw, units);
        var parts = names.map(function (name, i) {
            return name + ' $' + shares[i].toFixed(2) + ' (' + units[i] + ' u)';
        });
        preview.hidden = false;
        preview.textContent = 'Preview split: ' + parts.join(' · ');
    }

    function updateSelectionUi() {
        var n = selectedCount();
        if (countEl) {
            countEl.textContent = String(n);
        }
        if (modalCountEl) {
            modalCountEl.textContent = String(n);
        }
        if (openBtn) {
            openBtn.disabled = n === 0;
        }
        updatePreview();
    }

    function openModal() {
        if (!modal || selectedCount() === 0) {
            return;
        }
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        modal.classList.add('is-open');
        document.body.classList.add('shipment-modal-open');
        updatePreview();
        if (amountInput) {
            window.setTimeout(function () {
                amountInput.focus();
            }, 50);
        }
    }

    function closeModal() {
        if (!modal) {
            return;
        }
        modal.classList.remove('is-open');
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('shipment-modal-open');
    }

    function selectOnlyRow(row) {
        table.querySelectorAll('.shared-cost-batch-check').forEach(function (cb) {
            cb.checked = false;
        });
        var cb = row.querySelector('.shared-cost-batch-check');
        if (cb) {
            cb.checked = true;
        }
        if (selectAll) {
            selectAll.checked = false;
        }
        updateSelectionUi();
    }

    if (selectAll) {
        selectAll.addEventListener('change', function () {
            table.querySelectorAll('.shared-cost-batch-check').forEach(function (cb) {
                cb.checked = selectAll.checked;
            });
            updateSelectionUi();
        });
    }

    table.addEventListener('change', function (event) {
        if (event.target.classList.contains('shared-cost-batch-check')) {
            updateSelectionUi();
        }
    });

    if (amountInput) {
        amountInput.addEventListener('input', updatePreview);
    }

    if (openBtn) {
        openBtn.addEventListener('click', openModal);
    }

    document.querySelectorAll('[data-open-shared-cost]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (btn.getAttribute('data-select-only') === '1') {
                var row = btn.closest('[data-shared-cost-row]');
                if (row) {
                    selectOnlyRow(row);
                }
            }
            openModal();
        });
    });

    if (modal) {
        modal.querySelectorAll('[data-shared-cost-dismiss]').forEach(function (el) {
            el.addEventListener('click', closeModal);
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && modal.classList.contains('is-open')) {
                closeModal();
            }
        });
    }

    updateSelectionUi();
})();
