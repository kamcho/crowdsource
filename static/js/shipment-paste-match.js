(function () {
    document.querySelectorAll('[data-shipment-paste-row]').forEach(function (row) {
        var select = row.querySelector('[data-shipment-paste-batch]');
        var check = row.querySelector('[data-shipment-paste-check]');
        if (!select || !check) {
            return;
        }
        function syncRow() {
            var hasBatch = Boolean(select.value);
            row.classList.toggle('shipment-paste-row-unmatched', !hasBatch);
            if (hasBatch && !check.checked) {
                check.checked = true;
            }
        }
        select.addEventListener('change', syncRow);
        syncRow();
    });
})();
