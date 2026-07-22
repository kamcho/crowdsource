(function (global) {
    function readConfig() {
        var root = document.documentElement;
        return {
            code: root.dataset.currency || 'USD',
            rate: parseFloat(root.dataset.usdKesRate || '135'),
        };
    }

    function format(amountUsd, config) {
        config = config || readConfig();
        var value = parseFloat(amountUsd);
        if (Number.isNaN(value)) {
            return '—';
        }
        if (config.code === 'KES') {
            var kes = Math.round(value * config.rate);
            return 'KES ' + kes.toLocaleString('en-KE');
        }
        return '$' + value.toFixed(2);
    }

    function formatRange(minUsd, maxUsd, config) {
        config = config || readConfig();
        var min = parseFloat(minUsd);
        var max = parseFloat(maxUsd);
        if (Number.isNaN(min)) {
            return '—';
        }
        if (!Number.isNaN(max) && min !== max) {
            return format(min, config) + ' – ' + format(max, config);
        }
        return format(min, config);
    }

    global.CrowdSourceCurrency = {
        readConfig: readConfig,
        format: format,
        formatRange: formatRange,
    };
})(window);
