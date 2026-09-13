(function () {
    var HOLD_MS = 5000;
    var modal = document.getElementById('shipment-remove-modal');
    var messageEl = document.getElementById('shipment-remove-message');
    var batchInput = document.getElementById('shipment-remove-batch-id');
    var form = document.getElementById('shipment-remove-form');
    var holdBtn = document.getElementById('shipment-remove-hold-btn');
    var progressEl = document.getElementById('shipment-remove-progress');
    var labelEl = document.getElementById('shipment-remove-hold-label');

    if (!modal || !messageEl || !batchInput || !form || !holdBtn || !progressEl || !labelEl) {
        return;
    }

    var holdStart = null;
    var rafId = null;
    var submitted = false;

    function resetHold() {
        if (submitted) {
            return;
        }
        holdStart = null;
        if (rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
        progressEl.style.width = '0%';
        labelEl.textContent = 'Hold to remove · 5s';
        holdBtn.classList.remove('is-holding', 'is-complete');
        holdBtn.disabled = false;
    }

    function tick() {
        if (!holdStart || submitted) {
            return;
        }
        var elapsed = Date.now() - holdStart;
        var percent = Math.min(100, (elapsed / HOLD_MS) * 100);
        progressEl.style.width = percent + '%';

        var secondsLeft = Math.ceil((HOLD_MS - elapsed) / 1000);
        if (secondsLeft > 0) {
            labelEl.textContent = 'Keep holding… ' + secondsLeft + 's';
        } else {
            submitted = true;
            holdBtn.classList.add('is-complete');
            holdBtn.disabled = true;
            labelEl.textContent = 'Removing…';
            progressEl.style.width = '100%';
            form.submit();
            return;
        }
        rafId = requestAnimationFrame(tick);
    }

    function startHold(event) {
        if (submitted || holdBtn.disabled) {
            return;
        }
        event.preventDefault();
        resetHold();
        holdStart = Date.now();
        holdBtn.classList.add('is-holding');
        rafId = requestAnimationFrame(tick);
    }

    function endHold() {
        if (submitted) {
            return;
        }
        resetHold();
    }

    function openModal(batchId, productName) {
        submitted = false;
        resetHold();
        batchInput.value = batchId;
        messageEl.textContent = 'Remove “' + productName + '” from this shipment?';
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        modal.classList.add('is-open');
        var cancelBtn = modal.querySelector('[data-shipment-confirm-dismiss].btn');
        if (cancelBtn) {
            cancelBtn.focus();
        }
    }

    function closeModal() {
        endHold();
        submitted = false;
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
        modal.classList.remove('is-open');
        batchInput.value = '';
    }

    document.querySelectorAll('[data-shipment-remove]').forEach(function (button) {
        button.addEventListener('click', function () {
            openModal(button.dataset.importBatchId, button.dataset.productName || 'this product');
        });
    });

    modal.querySelectorAll('[data-shipment-confirm-dismiss]').forEach(function (el) {
        el.addEventListener('click', closeModal);
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal.classList.contains('is-open')) {
            closeModal();
        }
    });

    holdBtn.addEventListener('mousedown', startHold);
    holdBtn.addEventListener('touchstart', startHold, { passive: false });
    holdBtn.addEventListener('mouseup', endHold);
    holdBtn.addEventListener('mouseleave', endHold);
    holdBtn.addEventListener('touchend', endHold);
    holdBtn.addEventListener('touchcancel', endHold);
    holdBtn.addEventListener('contextmenu', function (event) {
        event.preventDefault();
    });

    form.addEventListener('submit', function (event) {
        if (!submitted) {
            event.preventDefault();
        }
    });
})();
