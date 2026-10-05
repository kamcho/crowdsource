(function () {
    var root = document.getElementById('shipment-price-player');
    if (!root) {
        return;
    }

    var rows = root.querySelectorAll('[data-price-player-row]');
    var perLineToggle = document.getElementById('price-player-per-line');
    var applyForm = document.getElementById('price-player-apply-form');
    var applyFields = document.getElementById('price-player-apply-fields');
    var totalW = document.getElementById('price-player-total-w');
    var totalR = document.getElementById('price-player-total-r');

    function exchangeRate() {
        var rate = parseFloat(document.documentElement.getAttribute('data-usd-kes-rate'));
        return Number.isFinite(rate) && rate > 0 ? rate : 135;
    }

    function parseNum(value) {
        var n = parseFloat(value);
        return Number.isFinite(n) ? n : 0;
    }

    function roundMoney(n) {
        return Math.round(n * 100) / 100;
    }

    function fmtUsd(amount) {
        return '$' + roundMoney(amount).toFixed(2);
    }

    function fmtKesFromUsd(usd) {
        var kes = roundMoney(usd * exchangeRate());
        return 'KES ' + kes.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    }

    function fmtDual(usd) {
        return fmtKesFromUsd(usd) + ' · ' + fmtUsd(usd);
    }

    function currentMode() {
        var checked = root.querySelector('[data-price-player-mode]:checked');
        return checked ? checked.value : 'margin';
    }

    function syncSliderPair(slider, input) {
        if (!slider || !input) {
            return;
        }
        slider.addEventListener('input', function () {
            input.value = slider.value;
            recalculate();
        });
        input.addEventListener('input', function () {
            slider.value = input.value;
            recalculate();
        });
    }

    function uniformValue(channel, mode) {
        var prefix = channel === 'wholesale' ? 'w' : 'r';
        var suffix = mode === 'margin' ? 'margin' : 'dollar';
        var input = document.getElementById('price-player-' + prefix + '-' + suffix + '-input');
        return parseNum(input && input.value);
    }

    function rowOverride(row, channel) {
        var input = row.querySelector('[data-override="' + channel + '"]');
        if (!input || !perLineToggle || !perLineToggle.checked) {
            return null;
        }
        var raw = (input.value || '').trim();
        if (raw === '') {
            return null;
        }
        return parseNum(raw);
    }

    function sellPrice(landed, mode, value) {
        if (landed <= 0) {
            return 0;
        }
        if (mode === 'margin') {
            return roundMoney(landed * (1 + value / 100));
        }
        return roundMoney(landed + value);
    }

    function setModeVisibility(mode) {
        root.querySelectorAll('.price-player-slider-row').forEach(function (row) {
            var rowMode = row.getAttribute('data-mode');
            row.hidden = rowMode !== mode;
        });
        root.querySelectorAll('.price-player-override-input').forEach(function (input) {
            input.placeholder = mode === 'margin' ? 'Uniform %' : 'Uniform $';
        });
    }

    function recalculate() {
        var mode = currentMode();
        var sumW = 0;
        var sumR = 0;

        rows.forEach(function (row) {
            var units = parseInt(row.getAttribute('data-units') || '0', 10) || 0;
            var landed = parseNum(row.getAttribute('data-landed'));

            var wVal = rowOverride(row, 'wholesale');
            if (wVal === null) {
                wVal = uniformValue('wholesale', mode);
            }
            var rVal = rowOverride(row, 'retail');
            if (rVal === null) {
                rVal = uniformValue('retail', mode);
            }

            var wPrice = sellPrice(landed, mode, wVal);
            var rPrice = sellPrice(landed, mode, rVal);
            var wLine = roundMoney((wPrice - landed) * units);
            var rLine = roundMoney((rPrice - landed) * units);
            sumW += wLine;
            sumR += rLine;

            var landedCell = row.querySelector('[data-role="landed"]');
            var wPriceCell = row.querySelector('[data-role="w-price"]');
            var rPriceCell = row.querySelector('[data-role="r-price"]');
            var wLineCell = row.querySelector('[data-role="w-line"]');
            var rLineCell = row.querySelector('[data-role="r-line"]');

            if (landedCell) {
                landedCell.textContent = landed > 0 ? fmtDual(landed) : '—';
            }
            if (wPriceCell) {
                wPriceCell.innerHTML = landed > 0
                    ? '<span class="price-player-primary">' + fmtKesFromUsd(wPrice) + '</span><span class="price-player-sub">' + fmtUsd(wPrice) + '</span>'
                    : '—';
            }
            if (rPriceCell) {
                rPriceCell.innerHTML = landed > 0
                    ? '<span class="price-player-primary">' + fmtKesFromUsd(rPrice) + '</span><span class="price-player-sub">' + fmtUsd(rPrice) + '</span>'
                    : '—';
            }
            if (wLineCell) {
                wLineCell.textContent = units ? fmtDual(wLine) : '—';
            }
            if (rLineCell) {
                rLineCell.textContent = units ? fmtDual(rLine) : '—';
            }

            row.setAttribute('data-w-price', String(wPrice));
        });

        if (totalW) {
            totalW.innerHTML = '<strong>' + fmtDual(sumW) + '</strong>';
        }
        if (totalR) {
            totalR.innerHTML = '<strong>' + fmtDual(sumR) + '</strong>';
        }

        if (applyFields) {
            applyFields.innerHTML = '';
            rows.forEach(function (row) {
                var batchId = row.getAttribute('data-batch-id');
                var wPrice = row.getAttribute('data-w-price');
                if (!batchId || !wPrice || parseNum(wPrice) <= 0) {
                    return;
                }
                var idInput = document.createElement('input');
                idInput.type = 'hidden';
                idInput.name = 'price_batch_id';
                idInput.value = batchId;
                var priceInput = document.createElement('input');
                priceInput.type = 'hidden';
                priceInput.name = 'price_unit_usd';
                priceInput.value = wPrice;
                applyFields.appendChild(idInput);
                applyFields.appendChild(priceInput);
            });
        }
    }

    syncSliderPair(
        document.getElementById('price-player-w-margin-slider'),
        document.getElementById('price-player-w-margin-input'),
    );
    syncSliderPair(
        document.getElementById('price-player-r-margin-slider'),
        document.getElementById('price-player-r-margin-input'),
    );
    syncSliderPair(
        document.getElementById('price-player-w-dollar-slider'),
        document.getElementById('price-player-w-dollar-input'),
    );
    syncSliderPair(
        document.getElementById('price-player-r-dollar-slider'),
        document.getElementById('price-player-r-dollar-input'),
    );

    root.querySelectorAll('[data-price-player-mode]').forEach(function (radio) {
        radio.addEventListener('change', function () {
            setModeVisibility(currentMode());
            recalculate();
        });
    });

    if (perLineToggle) {
        perLineToggle.addEventListener('change', function () {
            var show = perLineToggle.checked;
            root.querySelectorAll('.price-player-override-col').forEach(function (cell) {
                cell.hidden = !show;
            });
            recalculate();
        });
    }

    root.querySelectorAll('.price-player-override-input').forEach(function (input) {
        input.addEventListener('input', recalculate);
    });

    if (rows.length) {
        var firstMargin = parseNum(rows[0].getAttribute('data-default-w-margin'));
        if (firstMargin > 0) {
            var wSlider = document.getElementById('price-player-w-margin-slider');
            var wInput = document.getElementById('price-player-w-margin-input');
            if (wSlider && wInput) {
                wSlider.value = String(firstMargin);
                wInput.value = String(firstMargin);
            }
        }
    }

    setModeVisibility('margin');
    recalculate();
})();
