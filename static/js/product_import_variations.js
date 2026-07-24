(function () {
    var dataNode = document.getElementById('variations-data');
    var optionsEditor = document.getElementById('options-editor');
    var variationsBody = document.getElementById('variations-body');
    var headerRow = document.getElementById('variations-header-row');
    var mergeNote = document.getElementById('options-merge-note');
    var hiddenInput = document.getElementById('variations-json');
    var form = document.getElementById('variations-form');
    if (!dataNode || !optionsEditor || !variationsBody || !headerRow || !hiddenInput || !form) return;

    var state = JSON.parse(dataNode.textContent || '{"options":[],"variations":[]}');
    if (!state.options) state.options = [];
    if (!state.variations) state.variations = [];
    var skuPrefix = (state.sku_prefix || 'IMPORT').toUpperCase();
    var defaultPrice = state.default_price || '0.00';

    var mergingOptions = false;
    var syncTimer = null;

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/"/g, '&quot;');
    }

    function parseOptionValues(raw) {
        return String(raw || '')
            .split(/[,;\n|]+/)
            .map(function (v) { return v.trim(); })
            .filter(Boolean);
    }

    function abbrevForSku(value) {
        var cleaned = String(value || '').replace(/[^a-zA-Z0-9]+/g, '');
        if (!cleaned) return 'X';
        if (cleaned.length <= 4) return cleaned.toUpperCase();
        var upper = cleaned.toUpperCase();
        var skeleton = upper.replace(/[AEIOU]/g, '');
        if (skeleton.length >= 3) return skeleton.slice(0, 4);
        return upper.slice(0, 4);
    }

    function selectionKey(selections, optionNames) {
        return optionNames.map(function (name) {
            return name + ':' + String((selections || {})[name] || '').trim();
        }).join('|');
    }

    function averagePrice(variations) {
        var prices = (variations || []).map(function (variation) {
            var price = parseFloat(variation.price);
            return isNaN(price) ? null : price;
        }).filter(function (price) { return price !== null; });
        if (!prices.length) return defaultPrice;
        var total = prices.reduce(function (sum, price) { return sum + price; }, 0);
        return (total / prices.length).toFixed(2);
    }

    function generateSku(prefix, selections, optionNames, index, usedSkus) {
        var parts = [prefix];
        optionNames.forEach(function (name) {
            parts.push(abbrevForSku(selections[name]));
        });
        var baseSku = parts.filter(Boolean).join('-').slice(0, 80) || (prefix + '-' + (index + 1));
        var sku = baseSku;
        var counter = 1;
        while (usedSkus[sku]) {
            var suffix = '-' + counter;
            sku = baseSku.slice(0, Math.max(1, 80 - suffix.length)) + suffix;
            counter += 1;
        }
        usedSkus[sku] = true;
        return sku;
    }

    function syncVariationsFromOptions(options, variations) {
        var validOptions = options.filter(function (opt) {
            return opt.name && opt.name.trim() && opt.values && opt.values.length;
        });
        if (!validOptions.length) {
            return [];
        }

        var optionNames = validOptions.map(function (opt) { return opt.name.trim(); });
        var combos = [];

        function buildCombo(index, current) {
            if (index >= validOptions.length) {
                combos.push(Object.assign({}, current));
                return;
            }
            var option = validOptions[index];
            var optionName = option.name.trim();
            option.values.forEach(function (valueItem) {
                var label = String(valueItem.value || '').trim();
                if (!label) return;
                var next = Object.assign({}, current);
                next[optionName] = label;
                buildCombo(index + 1, next);
            });
        }
        buildCombo(0, {});

        var fallbackPrice = averagePrice(variations);
        var existingByKey = {};
        (variations || []).forEach(function (variation) {
            var selections = variation.option_selections || {};
            if (!optionNames.every(function (name) { return String(selections[name] || '').trim(); })) {
                return;
            }
            existingByKey[selectionKey(selections, optionNames)] = variation;
        });

        var synced = [];
        var usedSkus = {};
        combos.forEach(function (combo, index) {
            var key = selectionKey(combo, optionNames);
            var row;
            if (existingByKey[key]) {
                row = Object.assign({}, existingByKey[key], { option_selections: combo });
                var sku = String(row.sku || '').trim();
                if (!sku) {
                    row.sku = generateSku(skuPrefix, combo, optionNames, index, usedSkus);
                } else {
                    var baseSku = sku.slice(0, 80);
                    var counter = 1;
                    while (usedSkus[sku]) {
                        var suffix = '-' + counter;
                        sku = baseSku.slice(0, Math.max(1, 80 - suffix.length)) + suffix;
                        counter += 1;
                    }
                    usedSkus[sku] = true;
                    row.sku = sku;
                }
                if (!row.price) row.price = fallbackPrice;
                if (row.is_active === undefined) row.is_active = true;
            } else {
                row = {
                    sku: generateSku(skuPrefix, combo, optionNames, index, usedSkus),
                    price: fallbackPrice,
                    is_active: true,
                    option_selections: combo,
                };
            }
            synced.push(row);
        });

        return synced;
    }

    function mergeOptionsByName(options) {
        var merged = [];
        var indexByName = {};

        options.forEach(function (opt) {
            var key = opt.name.trim().toLowerCase();
            if (!key) {
                return;
            }
            if (indexByName[key] === undefined) {
                indexByName[key] = merged.length;
                merged.push({
                    name: opt.name.trim(),
                    sort_order: merged.length,
                    values: (opt.values || []).slice(),
                });
                return;
            }

            var target = merged[indexByName[key]];
            var seen = {};
            target.values.forEach(function (valueItem) {
                seen[valueItem.value.toLowerCase()] = true;
            });
            (opt.values || []).forEach(function (valueItem) {
                var valueKey = valueItem.value.toLowerCase();
                if (!seen[valueKey]) {
                    target.values.push({
                        value: valueItem.value,
                        sort_order: target.values.length,
                    });
                    seen[valueKey] = true;
                }
            });
        });

        return merged;
    }

    function collectOptionsFromDom() {
        var blocks = optionsEditor.querySelectorAll('.import-option-block');
        var options = [];
        blocks.forEach(function (block, index) {
            var name = block.querySelector('.option-name').value.trim();
            if (!name) {
                return;
            }
            var values = parseOptionValues(block.querySelector('.option-values').value)
                .map(function (value, valIndex) {
                    return { value: value, sort_order: valIndex };
                });
            if (!values.length) {
                return;
            }
            options.push({ name: name, sort_order: index, values: values });
        });
        return options;
    }

    function showMergeNote(rawCount, mergedCount) {
        if (!mergeNote) {
            return;
        }
        if (mergedCount < rawCount) {
            mergeNote.hidden = false;
            mergeNote.textContent = 'Duplicate option names were combined into one column. Use a single Color row with comma-separated values instead of multiple Color rows.';
            return;
        }
        mergeNote.hidden = true;
        mergeNote.textContent = '';
    }

    function renderOptionsEditor() {
        optionsEditor.innerHTML = '';
        state.options.forEach(function (option, optionIndex) {
            var block = document.createElement('div');
            block.className = 'import-option-block';
            var valuesText = (option.values || []).map(function (v) { return v.value; }).join(', ');
            block.innerHTML =
                '<div class="import-option-head">' +
                    '<div class="import-option-field">' +
                        '<label class="import-option-label">Option name</label>' +
                        '<input type="text" class="form-input option-name" value="' + escapeHtml(option.name) + '" placeholder="e.g. Color">' +
                    '</div>' +
                    '<button type="button" class="btn btn-outline btn-sm remove-option" data-index="' + optionIndex + '">Remove</button>' +
                '</div>' +
                '<div class="import-option-field">' +
                    '<label class="import-option-label">Values (comma-separated)</label>' +
                    '<input type="text" class="form-input option-values" value="' + escapeHtml(valuesText) + '" placeholder="Black, White, Pink">' +
                '</div>';
            optionsEditor.appendChild(block);
        });
        bindOptionEvents();
    }

    function bindOptionEvents() {
        optionsEditor.querySelectorAll('.remove-option').forEach(function (button) {
            button.addEventListener('click', function () {
                state.options.splice(parseInt(button.getAttribute('data-index'), 10), 1);
                renderAll();
            });
        });
    }

    function renderTableHeader(options) {
        var cells = [
            '<th>SKU</th>',
            '<th>Price (USD)</th>',
        ];
        options.forEach(function (opt) {
            cells.push('<th>' + escapeHtml(opt.name) + '</th>');
        });
        cells.push('<th>Active</th>', '<th></th>');
        headerRow.innerHTML = cells.join('');
    }

    function captureVariationsFromDom() {
        var rows = variationsBody.querySelectorAll('tr');
        if (!rows.length || rows[0].querySelector('.import-variations-empty')) {
            return state.variations;
        }

        var optionNames = state.options.map(function (opt) { return opt.name.trim(); });
        var captured = [];
        rows.forEach(function (row) {
            var skuInput = row.querySelector('.variation-sku');
            var priceInput = row.querySelector('.variation-price');
            var activeInput = row.querySelector('.variation-active');
            if (!skuInput || !priceInput || !activeInput) {
                return;
            }
            var sku = skuInput.value.trim();
            var price = priceInput.value.trim();
            var isActive = activeInput.checked;
            var selections = {};
            row.querySelectorAll('.variation-option').forEach(function (select) {
                var optionName = select.getAttribute('data-option');
                if (select.value) {
                    selections[optionName] = select.value;
                }
            });
            if (!sku && !optionNames.every(function (name) { return selections[name]; })) {
                return;
            }
            captured.push({
                sku: sku,
                price: price || defaultPrice,
                is_active: isActive,
                option_selections: selections,
            });
        });
        return captured;
    }

    function bindVariationRowEvents() {
        variationsBody.querySelectorAll('.remove-variation').forEach(function (button) {
            button.addEventListener('click', function () {
                state.variations = captureVariationsFromDom();
                state.variations.splice(parseInt(button.getAttribute('data-index'), 10), 1);
                renderVariationRows(state.options);
            });
        });

        variationsBody.querySelectorAll('.variation-sku, .variation-price, .variation-active, .variation-option').forEach(function (input) {
            input.addEventListener('change', function () {
                state.variations = captureVariationsFromDom();
            });
        });
    }

    function renderVariationRows(options) {
        variationsBody.innerHTML = '';

        if (!options.length) {
            var emptyRow = document.createElement('tr');
            emptyRow.innerHTML =
                '<td colspan="4" class="import-variations-empty">' +
                'Add at least one option above. SKU rows will be generated automatically.' +
                '</td>';
            variationsBody.appendChild(emptyRow);
            return;
        }

        if (!state.variations.length) {
            var waitingRow = document.createElement('tr');
            waitingRow.innerHTML =
                '<td colspan="' + (options.length + 4) + '" class="import-variations-empty">' +
                'Enter option values to generate SKU rows automatically.' +
                '</td>';
            variationsBody.appendChild(waitingRow);
            return;
        }

        state.variations.forEach(function (variation, index) {
            var row = document.createElement('tr');
            var optionCells = options.map(function (opt) {
                var selected = (variation.option_selections || {})[opt.name] || '';
                var choices = opt.values.map(function (val) {
                    var label = val.value;
                    return '<option value="' + escapeHtml(label) + '"' + (label === selected ? ' selected' : '') + '>' +
                        escapeHtml(label) + '</option>';
                }).join('');
                return '<td><select class="form-input form-select variation-option" data-option="' + escapeHtml(opt.name) + '">' +
                    '<option value="">Choose ' + escapeHtml(opt.name) + '</option>' + choices + '</select></td>';
            }).join('');

            row.innerHTML =
                '<td><input type="text" class="form-input variation-sku" value="' + escapeHtml(variation.sku) + '" placeholder="SKU-001"></td>' +
                '<td><input type="text" class="form-input variation-price" value="' + escapeHtml(variation.price) + '" placeholder="0.00"></td>' +
                optionCells +
                '<td><input type="checkbox" class="variation-active"' + (variation.is_active !== false ? ' checked' : '') + '></td>' +
                '<td><button type="button" class="btn btn-outline btn-sm remove-variation" data-index="' + index + '">Remove</button></td>';
            variationsBody.appendChild(row);
        });

        bindVariationRowEvents();
    }

    function syncOptionsFromDom() {
        if (mergingOptions) {
            return state.options;
        }

        var rawOptions = collectOptionsFromDom();
        var mergedOptions = mergeOptionsByName(rawOptions);
        showMergeNote(rawOptions.length, mergedOptions.length);

        if (mergedOptions.length < rawOptions.length) {
            mergingOptions = true;
            state.options = mergedOptions;
            renderOptionsEditor();
            mergingOptions = false;
        } else {
            state.options = mergedOptions;
        }

        return state.options;
    }

    function renderAll() {
        syncOptionsFromDom();
        state.variations = syncVariationsFromOptions(state.options, state.variations);
        renderTableHeader(state.options);
        renderVariationRows(state.options);
    }

    function scheduleOptionSync() {
        if (syncTimer) {
            clearTimeout(syncTimer);
        }
        syncTimer = setTimeout(function () {
            syncTimer = null;
            renderAll();
        }, 250);
    }

    function collectVariationsFromDom() {
        var options = syncOptionsFromDom();
        var edited = captureVariationsFromDom();
        return {
            options: options,
            variations: syncVariationsFromOptions(options, edited),
        };
    }

    document.getElementById('add-option').addEventListener('click', function () {
        state.options.push({
            name: '',
            sort_order: state.options.length,
            values: [{ value: '', sort_order: 0 }],
        });
        renderOptionsEditor();
        renderAll();
    });

    document.getElementById('add-variation-row').addEventListener('click', function () {
        if (!state.options.length) {
            if (mergeNote) {
                mergeNote.hidden = false;
                mergeNote.textContent = 'Add an option (e.g. Color with Black, White, Pink) first.';
            }
            return;
        }
        state.variations = syncVariationsFromOptions(state.options, captureVariationsFromDom());
        renderVariationRows(state.options);
    });

    optionsEditor.addEventListener('input', function (event) {
        if (event.target.classList.contains('option-name') || event.target.classList.contains('option-values')) {
            scheduleOptionSync();
        }
    });

    optionsEditor.addEventListener('change', function (event) {
        if (event.target.classList.contains('option-name') || event.target.classList.contains('option-values')) {
            if (syncTimer) {
                clearTimeout(syncTimer);
                syncTimer = null;
            }
            renderAll();
        }
    });

    form.addEventListener('submit', function () {
        hiddenInput.value = JSON.stringify(collectVariationsFromDom());
    });

    renderOptionsEditor();
    state.variations = syncVariationsFromOptions(state.options, state.variations);
    renderAll();
})();
